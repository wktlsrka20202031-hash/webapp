"""카피 기획 엔진 — AI 호출(무료 한도 순환), 상세페이지 읽기, 규칙 검사.

Streamlit에 의존하지 않아서 따로 테스트할 수 있다.
화면은 pages/2_카피_기획.py 가 맡는다.
"""
from __future__ import annotations

import base64
import csv
import difflib
import io
import ipaddress
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
from google import genai
from google.genai import types

# ------------------------------------------------------------------ 모델 ----
# 무료 하루 한도 (AI Studio 사용량 화면, 2026-11-03 확인)
#   Flash-Lite 3.5 / 3.1 : 500회   Gemma 4 : 14,400회(분당 토큰 16K)   Flash 계열 : 각 20회
LITE_CHAIN = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it", "gemma-4-26b-a4b-it"]
WRITE_CHAIN = ["gemini-3-flash-preview", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# gemini-3.8-flash는 출시 직후라 응답 없이 150초 넘게 멈추는 일이 있어 뺐다 (2026-11-03 시험)
REQUEST_TIMEOUT_MS = 60_000  # 이보다 오래 답이 없으면 기다리지 않고 다음 모델로 넘어간다
OLLAMA_MODEL = "qwen3-vl:8b"
HOOKS = ["문제 직격", "구매 실패 회피", "공감", "선택 기준 전환", "구매 타이밍"]


@dataclass(frozen=True)
class Cfg:
    api_key: str
    local_only: bool = False
    ollama_host: str = "http://127.0.0.1:11434"


class AllModelsFailed(Exception):
    def __init__(self, tries, last_error: str = ""):
        self.tries = tries
        self.last_error = last_error
        super().__init__("ALL_MODELS_FAILED: " + ", ".join(f"{m}:{k}" for m, k in tries)
                         + (f" | 마지막 오류: {last_error}" if last_error else ""))


# 한도에 걸린 모델은 잠시 건너뛴다 (프로세스 안에서 공유)
_EXHAUSTED: dict[str, float] = {}
_COOLDOWN: dict[str, float] = {}


def _blocked(model: str) -> bool:
    now = time.time()
    return _EXHAUSTED.get(model, 0) > now or _COOLDOWN.get(model, 0) > now


def _classify(e: Exception) -> str:
    s = str(e)
    if "API_KEY_INVALID" in s or "API key not valid" in s:
        return "fatal"
    if "PerDay" in s:
        return "day"
    if "RESOURCE_EXHAUSTED" in s or "429" in s:
        return "minute"
    if any(k in s for k in ("UNAVAILABLE", "503", "500", "INTERNAL", "DEADLINE", "timed out", "Timeout")):
        return "busy"
    return "skip"


def parse_json_loose(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a : b + 1])
        raise


def _coerce(data, expect: str | None):
    """모델이 {"키": [...]} 대신 목록만 주거나 키를 빠뜨리면 보정하고, 그래도 안 맞으면 다음 모델로 넘어가게 한다."""
    if isinstance(data, list):
        data = {expect: data} if expect else {"_list": data}
    if not isinstance(data, dict):
        raise ValueError("BAD_SHAPE")
    if expect and expect not in data:
        raise ValueError("MISSING_KEY:" + expect)
    return data


def ollama_available(host: str = "http://127.0.0.1:11434") -> bool:
    try:
        return requests.get(f"{host}/api/tags", timeout=1.5).ok
    except Exception:
        return False


def _ollama_once(cfg: Cfg, instruction: str, parts: list) -> tuple[dict, dict]:
    text = "\n\n".join(p[1] for p in parts if p[0] == "text")
    images = [base64.b64encode(p[1]).decode() for p in parts if p[0] == "image"]
    msg = {"role": "user", "content": text}
    if images:
        msg["images"] = images
    body = {
        "model": OLLAMA_MODEL, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": instruction}, msg],
        "options": {"num_ctx": 16384, "temperature": 0.4},
    }
    t0 = time.time()
    r = requests.post(f"{cfg.ollama_host}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    d = r.json()
    data = parse_json_loose(d["message"]["content"])
    return data, {"model": f"{OLLAMA_MODEL} (이 컴퓨터)", "prompt_tokens": d.get("prompt_eval_count"),
                  "output_tokens": d.get("eval_count"), "seconds": round(time.time() - t0, 1)}


def _grounding(r) -> tuple[list[dict], list[str]]:
    """검색으로 참고한 사이트 목록과, 링크 읽기에 실패한 주소 목록."""
    sources, failed = [], []
    try:
        cand = r.candidates[0]
    except (AttributeError, IndexError, TypeError):
        return sources, failed
    gm = getattr(cand, "grounding_metadata", None)
    for ch in (getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        if web and getattr(web, "uri", None):
            sources.append({"title": str(getattr(web, "title", "") or ""), "uri": str(web.uri)})
    um = getattr(cand, "url_context_metadata", None)
    for m in (getattr(um, "url_metadata", None) or []):
        if "SUCCESS" not in str(getattr(m, "url_retrieval_status", "")):
            failed.append(str(getattr(m, "retrieved_url", "") or ""))
    uniq = list({s["uri"]: s for s in sources}.values())
    return uniq, failed


def _gemini_once(cfg: Cfg, model: str, instruction: str, parts: list, tools: list | None = None) -> tuple[dict, dict]:
    client = genai.Client(api_key=cfg.api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    gparts = []
    gemma = model.startswith("gemma")
    if tools:  # 웹 검색·링크 읽기: 일반 텍스트로 받고 참고한 사이트를 함께 돌려준다
        for p in parts:
            gparts.append(types.Part.from_text(text=p[1]) if p[0] == "text"
                          else types.Part.from_bytes(data=p[1], mime_type=p[2]))
        t0 = time.time()
        r = client.models.generate_content(model=model, contents=gparts,
                                           config=types.GenerateContentConfig(system_instruction=instruction, tools=tools))
        if not (r.text or "").strip():
            raise ValueError("EMPTY_RESPONSE")
        sources, failed = _grounding(r)
        u = r.usage_metadata
        return {"text": r.text.strip(), "sources": sources, "url_failed": failed}, {
            "model": model, "prompt_tokens": getattr(u, "prompt_token_count", None),
            "output_tokens": getattr(u, "candidates_token_count", None), "seconds": round(time.time() - t0, 1)}
    if gemma:  # Gemma는 시스템 지시문·JSON 모드가 없어서 본문 앞에 붙인다
        gparts.append(types.Part.from_text(text=instruction))
    for p in parts:
        if p[0] == "text":
            gparts.append(types.Part.from_text(text=p[1]))
        else:
            gparts.append(types.Part.from_bytes(data=p[1], mime_type=p[2]))
    config = None if gemma else types.GenerateContentConfig(
        system_instruction=instruction, response_mime_type="application/json")
    t0 = time.time()
    r = client.models.generate_content(model=model, contents=gparts, config=config)
    if not r.text:
        raise ValueError("EMPTY_RESPONSE")
    data = parse_json_loose(r.text)
    u = r.usage_metadata
    return data, {"model": model, "prompt_tokens": getattr(u, "prompt_token_count", None),
                  "output_tokens": getattr(u, "candidates_token_count", None),
                  "seconds": round(time.time() - t0, 1)}


def call_json(cfg: Cfg, chain: list[str], instruction: str, parts: list, expect: str | None = None,
              tools: list | None = None) -> tuple[dict, dict]:
    """모델을 차례로 시도한다. 한도(하루)·붐빔·분당 한도에 걸리면 다음 모델로 넘어간다.
    parts: ("text", str) 또는 ("image", bytes, mime) 목록.
    tools를 주면(웹 검색 등) Gemini만 쓰고, 결과는 {"text", "sources", "url_failed"}."""
    if tools:
        chain = [m for m in chain if not m.startswith("gemma")]
    n_img = sum(1 for p in parts if p[0] == "image")
    est_tokens = sum(len(p[1]) for p in parts if p[0] == "text") // 1.5 + n_img * 1100
    tries: list[tuple[str, str]] = []
    last_error = ""
    errors: dict[str, str] = {}

    if not cfg.local_only:
        for _round in range(3):
            attempted = False
            for m in chain:
                slot = f"{m}+tools" if tools else m  # 웹 검색 한도는 일반 호출과 따로 센다
                if _blocked(slot):
                    continue
                if m.startswith("gemma") and est_tokens > 11000:  # Gemma는 분당 토큰 한도가 16K
                    tries.append((m, "too_big"))
                    continue
                attempted = True
                try:
                    data, meta = _gemini_once(cfg, m, instruction, parts, tools)
                    data = _coerce(data, expect)
                    meta["tries"] = tries
                    return data, meta
                except Exception as e:  # noqa: BLE001
                    kind = _classify(e)
                    tries.append((m, kind))
                    errors[m] = str(e)[:1200]
                    last_error = " || ".join(f"{k}: {v}" for k, v in errors.items())
                    if kind == "minute" and (tools or "limit: 0" in str(e)):
                        kind = "day"  # 웹 검색 한도·무료 등급에 없는 기능은 기다려도 소용없다
                    if kind == "fatal":
                        raise
                    if kind == "day":
                        _EXHAUSTED[slot] = time.time() + 4 * 3600
                    elif kind == "minute":
                        _COOLDOWN[slot] = time.time() + 25
                    elif kind == "busy":
                        _COOLDOWN[slot] = time.time() + 8
            slots = [f"{m}+tools" if tools else m for m in chain]
            waits = [_COOLDOWN[x] - time.time() for x in slots
                     if x in _COOLDOWN and _EXHAUSTED.get(x, 0) <= time.time() and _COOLDOWN[x] > time.time()]
            if not waits and not attempted:
                break
            if waits:
                time.sleep(min(max(min(waits), 1), 25))

    if tools:  # 이 컴퓨터의 AI는 웹 검색을 못 한다
        raise AllModelsFailed(tries, last_error)
    if cfg.local_only or ollama_available(cfg.ollama_host):
        try:
            data, meta = _ollama_once(cfg, instruction, parts)
            data = _coerce(data, expect)
            meta["tries"] = tries
            return data, meta
        except Exception as e:  # noqa: BLE001
            tries.append((OLLAMA_MODEL, "local_fail:" + str(e)[:60]))
    raise AllModelsFailed(tries, last_error)


# ------------------------------------------------------------ 글자 정리 ----
def norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def quote_found(quote: str, material_norm: str) -> bool:
    q = norm(quote)
    return len(q) >= 6 and q in material_norm


# ------------------------------------------------------------ 상세페이지 ----
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
_SKIP_IMG = re.compile(r"(icon|logo|sprite|loading|blank|pixel|spacer|btn_|button|arrow|gnb|footer|header|\.svg|\.gif)", re.I)


@dataclass
class Page:
    ok: bool
    text: str = ""
    images: list = field(default_factory=list)  # [(bytes, mime)]
    notes: list = field(default_factory=list)


def _assert_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("http(s) 주소만 읽을 수 있어요")
    for info in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("공개된 웹 주소만 읽을 수 있어요")


def _get(url: str, referer: str | None = None, max_bytes: int = 6_000_000):
    headers = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
               "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    for _ in range(5):
        _assert_public(url)
        r = requests.get(url, headers=headers, timeout=15, stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("location", ""))
            r.close()
            continue
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                break
        r.close()
        return r, bytes(buf), url
    raise ValueError("주소가 너무 여러 번 다른 곳으로 넘어가요")


def tiles_from_image(img_bytes: bytes, max_w: int = 1000, tile_h: int = 1500, overlap: int = 60) -> list[tuple[bytes, str]]:
    """긴 상세페이지 이미지를 글자가 읽히는 크기의 조각으로 자른다."""
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im.load()
    except Exception:  # noqa: BLE001
        return []
    im = im.convert("RGB")
    if im.width < 300 or im.height < 150:
        return []
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    out, y = [], 0
    while y < im.height:
        crop = im.crop((0, y, im.width, min(y + tile_h, im.height)))
        if crop.height >= 120:
            buf = io.BytesIO()
            crop.save(buf, "JPEG", quality=82)
            out.append((buf.getvalue(), "image/jpeg"))
        if y + tile_h >= im.height:
            break
        y += tile_h - overlap
    return out


MAX_TILES = 16  # AI에 넘기는 이미지 조각 수 (조각 하나 ≈ 1,100토큰)

# 상세 설명이 들어 있는 영역 / 상세가 아닌 영역 (id·class·JSON 키 이름으로 판단)
_DETAIL = re.compile(r"(detail|desc|goods_?info|prd_?info|product_?info|상세)", re.I)
_NOT_DETAIL = re.compile(r"(review|related|recommend|banner|swiper|slide|event|coupon|popup|login|insta|sticker|thumb|"
                         r"best|ranking|footer|header|gnb|lnb|nav|menu|cart|basket|quick|share)", re.I)
_IMG_ATTRS = ("ec-data-src", "data-src", "data-original", "data-lazy-src", "data-lazy", "data-url", "data-echo", "src")
_IMG_URL = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
# 자동 읽기를 막아 두는 큰 쇼핑몰 — 막히면 캡처를 넣으라고 바로 안내한다
_BLOCKING_SITES = {"coupang.com": "쿠팡", "oliveyoung.co.kr": "올리브영", "musinsa.com": "무신사", "29cm.co.kr": "29CM",
                   "smartstore.naver.com": "네이버 스마트스토어", "brand.naver.com": "네이버 브랜드스토어",
                   "11st.co.kr": "11번가", "gmarket.co.kr": "G마켓", "auction.co.kr": "옥션"}


def _site_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return next((v for k, v in _BLOCKING_SITES.items() if host == k or host.endswith("." + k)), "")


def _img_src(img) -> str:
    for a in _IMG_ATTRS:
        v = (img.get(a) or "").strip()
        if v and not v.startswith("data:"):
            return v
    return (img.get("srcset") or img.get("data-srcset") or "").strip().split(" ")[0]


def _area_score(el) -> int:
    """상세 영역 안에 깊이 들어 있을수록 높은 점수, 리뷰·배너·추천 영역 안이면 -1."""
    score = 0
    for p in el.parents:
        if p.name in ("html", "body", "[document]"):
            continue
        name = " ".join([p.get("id") or ""] + list(p.get("class") or [])) if hasattr(p, "get") else ""
        if not name:
            continue
        if _NOT_DETAIL.search(name):
            return -1
        if _DETAIL.search(name):
            score += 1
    return score


def _html_images(soup, base: str, bonus: int = 0) -> list[tuple[int, str]]:
    out = []
    for img in soup.find_all("img"):
        w = re.sub(r"\D", "", str(img.get("width") or ""))
        if w and int(w) < 200:
            continue
        src = _img_src(img)
        if not src or _SKIP_IMG.search(src):
            continue
        score = _area_score(img)
        if score >= 0:
            out.append((score + bonus, urljoin(base, src)))
    return out


def _walk_json(o, path: str, base: str, texts: list, imgs: list) -> None:
    """페이지에 숨어 있는 데이터(JSON)에서 상세 설명 글과 이미지를 찾는다. (컬리·Next.js 쇼핑몰 등)"""
    if isinstance(o, dict):
        for k, v in o.items():
            _walk_json(v, f"{path}.{k}", base, texts, imgs)
    elif isinstance(o, list):
        for v in o:
            _walk_json(v, path, base, texts, imgs)
    elif isinstance(o, str):
        if _NOT_DETAIL.search(path) or not _DETAIL.search(path):
            return
        s = o.strip()
        if s[:1] in "{[":
            try:
                _walk_json(json.loads(s), path, base, texts, imgs)
                return
            except ValueError:
                pass
        if "<img" in s or "</p>" in s or "<br" in s:
            sub = BeautifulSoup(s, "html.parser")
            imgs.extend(_html_images(sub, base, bonus=3))
            texts.extend(ln.strip() for ln in sub.get_text("\n").splitlines() if ln.strip())
        elif s.startswith(("http", "//")) and _IMG_URL.search(s):
            imgs.append((3, urljoin(base, s)))
        elif len(s) >= 10 and not s.startswith(("http", "//")):
            texts.append(s)


def _embedded_json(soup) -> list:
    out = []
    for sc in soup.find_all("script"):
        body = (sc.string or "").strip()
        if not body:
            continue
        kind = (sc.get("type") or "").lower()
        try:
            if "json" in kind:
                out.append(json.loads(body))
            elif m := re.search(r"window\.__[A-Z_]+__\s*=\s*", body):  # window.__PRELOADED_STATE__ = {...}
                out.append(json.JSONDecoder().raw_decode(body[m.end():])[0])
        except ValueError:
            continue
    return out


def _ld_product(data) -> list[str]:
    """schema.org Product 정보(제품명·브랜드·가격·설명)를 한 줄씩."""
    items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
    lines = []
    for it in items:
        if not isinstance(it, dict) or "Product" not in str(it.get("@type", "")):
            continue
        brand = it.get("brand")
        brand = brand.get("name") if isinstance(brand, dict) else brand
        offers = it.get("offers")
        offers = offers[0] if isinstance(offers, list) and offers else offers
        price = offers.get("price") if isinstance(offers, dict) else None
        lines += [f"제품명: {it.get('name')}" if it.get("name") else "", f"브랜드: {brand}" if brand else "",
                  f"가격: {price}원" if price else "", str(it.get("description") or "")]
    return [ln for ln in lines if ln]


def download_tiles(urls: list[str], referer: str, max_tiles: int) -> tuple[list, bool]:
    """이미지를 6장씩 동시에 받아 순서대로 조각낸다. 조각이 충분히 모이면 멈춘다."""
    def one(u):
        try:
            ir, ibytes, _ = _get(u, referer=referer, max_bytes=4_000_000)
            return tiles_from_image(ibytes) if ir.status_code < 400 else []
        except Exception:  # noqa: BLE001
            return []

    tiles: list[tuple[bytes, str]] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i in range(0, len(urls), 6):
            for t in ex.map(one, urls[i:i + 6]):
                tiles.extend(t)
            if len(tiles) >= max_tiles:
                return tiles[:max_tiles], i + 6 < len(urls) or len(tiles) > max_tiles
    return tiles, False


CLIP_MARK = "[상세페이지 가져오기]"  # clipper.py 북마크가 복사한 내용의 첫 줄


def parse_clip(text: str) -> tuple[str, str, list[str]] | None:
    """북마크로 복사한 내용이면 (페이지 주소, 본문 글, 이미지 주소 목록), 아니면 None."""
    t = (text or "").strip()
    if not t.startswith(CLIP_MARK):
        return None
    first, _, rest = t.partition("\n")
    page_url = first[len(CLIP_MARK):].strip()
    body, _, imgs = rest.partition("---이미지---")
    body = body.replace("---본문---", "", 1).strip()
    urls = [u.strip() for u in imgs.splitlines() if u.strip().startswith(("http://", "https://"))]
    return page_url, body, list(dict.fromkeys(urls))


def fetch_page(url: str, max_tiles: int = MAX_TILES) -> Page:
    notes: list[str] = []
    site = _site_name(url)
    if site:  # 막아 둔 사이트는 두드리지 않고, 웹 검색·구글의 링크 읽기로 자료를 모은다
        return Page(False, notes=[f"{site}은(는) 직접 읽기를 막아 둔 사이트라 웹 검색으로 자료를 모았어요"])
    blocked_msg = ""
    try:
        r, body, final = _get(url)
    except Exception as e:  # noqa: BLE001
        return Page(False, notes=[f"링크를 열지 못했어요: {str(e)[:80]}"])
    if r.status_code >= 400:
        return Page(False, notes=[blocked_msg or f"링크가 막혀 있어요 (응답 코드 {r.status_code})"])
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError:
        html = body.decode("cp949", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    head = []
    for sel in ("meta[property='og:title']", "meta[property='og:description']", "meta[name='description']"):
        el = soup.select_one(sel)
        if el and el.get("content"):
            head.append(el["content"].strip())

    # 1) 숨은 데이터(JSON)에서 제품 정보·상세 설명
    json_texts: list[str] = []
    cands: list[tuple[int, str]] = []
    for data in _embedded_json(soup):
        head += _ld_product(data)
        _walk_json(data, "", final, json_texts, cands)

    # 2) <noscript> 안의 이미지 (지연 로딩 페이지는 진짜 주소가 여기 있다)
    for ns in soup.find_all("noscript"):
        if (s := _area_score(ns)) >= 0:
            cands += _html_images(BeautifulSoup(ns.decode_contents(), "html.parser"), final, bonus=s)

    # 3) 상세 설명을 따로 띄우는 iframe (같은 사이트 안, 최대 2개)
    for fr in [f for f in soup.find_all("iframe") if _DETAIL.search(" ".join([f.get("id") or "", f.get("src") or ""]))][:2]:
        try:
            fu = urljoin(final, fr.get("src"))
            if urlparse(fu).hostname != urlparse(final).hostname:
                continue
            fr_r, fr_body, fr_final = _get(fu, referer=final)
            if fr_r.status_code < 400:
                fsoup = BeautifulSoup(fr_body.decode("utf-8", errors="replace"), "html.parser")
                cands += _html_images(fsoup, fr_final, bonus=3)
                json_texts += [ln.strip() for ln in fsoup.get_text("\n").splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            continue

    # 4) 본문 이미지 — 상세 영역 점수 순 (같은 점수면 페이지 순서)
    for t in soup(["script", "style", "noscript", "svg", "iframe", "form", "header", "footer", "nav"]):
        t.decompose()
    cands += _html_images(soup, final)
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    text = "\n".join(dict.fromkeys(head + json_texts + lines))[:20000]

    order = sorted(range(len(cands)), key=lambda i: -cands[i][0])
    urls = list(dict.fromkeys(cands[i][1] for i in order))[:40]
    tiles, more = download_tiles(urls, final, max_tiles)
    if more:
        notes.append(f"상세 이미지가 길어서 앞부분 {max_tiles}조각만 읽었어요")

    if len(text) < 200 and not tiles:
        return Page(False, text, [], notes + [blocked_msg or "페이지에서 읽을 내용이 거의 없어요 (막혀 있거나 화면을 JS로 그리는 페이지일 수 있어요)"])
    if len(text) < 200:
        notes.append("글자는 거의 없고 이미지 위주 페이지예요 — 이미지 속 글자를 AI가 읽어요")
    return Page(True, text, tiles, notes)


# ------------------------------------------------------------------ 프롬프트 ----
MATERIAL_SYSTEM = """당신은 광고 대행사의 카피 기획자입니다. 아래 [자료]에 실제로 적힌 내용만 근거로 제품 사실을 정리하고 소구점 후보 3개를 뽑습니다.

[절대 규칙]
- 자료에 없는 효능, 수치, 인증, 순위, 최상급(1위, 최고 등)은 사실로 적지 마세요. 상식이나 추측으로 채우지 마세요.
- facts와 appeals마다 quote를 반드시 붙이세요. quote는 자료에서 한 글자도 바꾸지 않고 그대로 복사한 20~80자 구절입니다.
- 이미지가 있으면 이미지 속 글자를 위에서 아래 순서로 빠짐없이 그대로 읽어서 image_text에 적으세요. 읽을 수 없는 부분은 건너뛰고 지어내지 마세요. 이미지가 없으면 image_text는 빈 문자열입니다.
- 소구점 3개는 서로 다른 구매 이유여야 합니다 (예: 문제 해결 / 불안 제거 / 취향·가치 / 가격·혜택 중 서로 다른 것).
- 근거가 자료에 충분하면 strength는 "강함", 한두 줄뿐이거나 간접적이면 "약함".

JSON으로만 답하세요:
{"image_text":"...","facts":[{"fact":"제품 사실 한 줄","quote":"자료 원문 그대로"}],"appeals":[{"name":"소구점 이름(10자 내외)","buying_reason":"이 소구가 겨냥하는 구매 이유 한 문장","quote":"자료 원문 그대로","strength":"강함 또는 약함"}],"gaps":["자료에 없어서 확인하지 못한, 카피에 중요한 정보"]}
facts는 6~12개, appeals는 정확히 3개."""

REF_SYSTEM = """당신은 광고 카피 구조 분석가입니다. 레퍼런스에서 문구 자체가 아니라 '구조'만 뽑습니다.
- structure 안에는 레퍼런스에 쓰인 단어나 문구를 절대 옮겨 적지 말고, 일반적인 설명으로만 쓰세요. (예: "메인 문구는 문제를 묻는 짧은 질문형이고 핵심 단어 하나만 색으로 강조")
- reference_text에는 레퍼런스에 보이는 글자를 그대로 적으세요. 이건 겹침 검사에만 쓰이고 다른 곳에는 전달되지 않습니다. 글자가 없으면 빈 문자열.
- visible_brand, visible_product에는 이미지에 글자로 실제 보이는 브랜드명·제품명만 적으세요. 보이지 않으면 빈 문자열이고, 추측하지 마세요.
JSON으로만: {"structure":{"composition":"구성(제목·서브·라벨·CTA 배치)","number_emphasis":"숫자를 강조하는 방식, 없으면 '없음'","hook_types":["쓰인 후킹 유형"],"tone":"톤"},"reference_text":"...","visible_brand":"","visible_product":""}"""

COPY_SYSTEM = """당신은 퍼포먼스 광고 카피라이터입니다. 아래 [제품 사실]에 적힌 내용만으로 광고 카피를 씁니다.

[절대 규칙]
- 사실 목록에 없는 효능, 수치, 인증, 순위, 최상급(1위, 최고, 최초, 유일, 가장 등)은 카피에 쓰지 마세요. 숫자는 사실 목록에 있는 것만 그대로 쓰세요. 사실에 없는 혜택·기한·한정 수량을 만들지 마세요.
- [레퍼런스 구조]는 구성과 강조 방식만 참고하세요. 레퍼런스의 문구는 주어지지 않았고, 비슷하게 쓰지도 마세요.
- 선택된 소구점마다 카피를 정확히 5개 쓰고, 5개는 후킹 유형을 하나씩 다르게: 문제 직격, 구매 실패 회피, 공감, 선택 기준 전환, 구매 타이밍.
- 카피 하나 = 메인 타이틀(20자 안팎), 서브 카피(40자 안팎), CTA(10자 안팎), 라벨 문구(짧은 배지 문구, 12자 이내, 사실에 근거).
- evidence에는 그 카피가 근거한 사실의 quote를 그대로 복사해 적으세요.

JSON으로만: {"copies":[{"appeal":"소구점 이름","hook":"후킹 유형","main_title":"","sub_copy":"","cta":"","label":"","evidence":""}]}"""


RESEARCH_SYSTEM = """당신은 광고 카피 기획을 위한 제품 리서처입니다. Google 검색과(링크가 주어지면) 그 링크를 읽어서 제품 정보를 모읍니다.
찾을 곳: 공식몰·브랜드 사이트, 네이버쇼핑·쿠팡·올리브영 등 판매 페이지의 상품 설명, 구매 후기, 블로그·카페 사용기.

[규칙]
- 검색 결과와 링크에 실제로 적힌 내용만 쓰세요. 추측이나 상식으로 채우지 말고, 찾지 못한 정보는 쓰지 마세요.
- 다른 제품(같은 브랜드의 다른 제품 포함) 정보를 섞지 마세요. 어떤 제품인지 확실하지 않으면 맨 위에 그렇게 적으세요.
- 문장은 출처에 적힌 표현을 최대한 그대로 옮기세요. 각 줄 끝에 (출처: 사이트 이름)을 붙이세요.
- 효능·수치·인증·순위는 출처에 적힌 그대로만 옮기고, 부풀리지 마세요.

아래 형식의 일반 텍스트로만 답하세요(머리말·맺음말 없이).
[제품 기본 정보] 정확한 제품명, 용량·구성, 가격, 주요 성분·소재·스펙
[판매 페이지가 강조하는 내용]
[구매 후기에서 반복되는 말] 좋다는 점 / 아쉽다는 점
[구매 전 고민·비교 포인트]"""

SEARCH_CHAIN = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.6-flash"]


def web_research(cfg: Cfg, brand: str, product: str, url: str = "") -> tuple[dict, dict]:
    """브랜드·제품명(과 링크)으로 웹을 조사해 자료 글을 만든다. 막힌 쇼핑몰은 검색 결과·구글의 링크 읽기로 대신한다.
    결과: {"text", "sources":[{"title","uri"}], "url_failed":[...]}"""
    tools = [types.Tool(google_search=types.GoogleSearch())]
    ask = f"브랜드: {brand}\n제품: {product}\n"
    if url:
        tools.append(types.Tool(url_context=types.UrlContext()))
        ask += f"상세페이지 링크: {url}\n이 링크를 먼저 읽고, 부족한 내용은 검색으로 보충하세요.\n"
    else:
        ask += "이 제품을 검색해서 조사하세요.\n"
    return call_json(cfg, SEARCH_CHAIN, RESEARCH_SYSTEM, [("text", ask)], tools=tools)


_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    import html as _html
    return _html.unescape(_TAG.sub("", s or "")).strip()


NAVER_HUB = "https://naverapihub.apigw.ntruss.com/search/v1"
NAVER_OLD = "https://openapi.naver.com/v1/search"
# 검색 결과에서 상품 페이지로 읽지 않을 곳 (후기·뉴스·포털·막아 둔 쇼핑몰은 따로 다룬다)
_NOT_SHOP = re.compile(r"(blog\.|cafe\.|news\.|post\.naver|kin\.naver|tistory\.com|youtube\.|instagram\.|facebook\.|"
                       r"namu\.wiki|wikipedia|dcinside|fmkorea|theqoo|clien|ppomppu|danawa|enuri)", re.I)


def naver_search(client_id: str, client_secret: str, kind: str, query: str, display: int) -> list[dict]:
    """NAVER API HUB(네이버클라우드) 검색. 예전 개발자센터 키도 받아 준다.
    kind: blog / cafearticle / webkr / news / shop"""
    params = {"query": query, "display": display, "start": 1, "sort": "sim"}
    tries = [(f"{NAVER_HUB}/{kind}", {"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": client_secret},
              dict(params, format="json")),
             (f"{NAVER_OLD}/{kind}.json", {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}, params)]
    auth_failed = False
    for url, headers, p in tries:
        try:
            r = requests.get(url, headers=headers, params=p, timeout=10)
        except requests.RequestException:
            continue
        if r.status_code in (401, 403):
            auth_failed = True
            continue
        if r.status_code == 404:  # 이 검색 종류가 없거나 종료됨
            continue
        r.raise_for_status()
        return r.json().get("items") or []
    if auth_failed:
        raise ValueError("NAVER_AUTH: 네이버 API 키가 올바르지 않거나, API HUB에서 검색 API 사용 신청이 안 되어 있어요")
    return []


def _pick_shop_pages(items: list[dict], limit: int = 2) -> list[str]:
    out = []
    for it in items:
        link = str(it.get("link") or "")
        if not link.startswith("http") or _NOT_SHOP.search(link) or _site_name(link):
            continue
        if link not in out:
            out.append(link)
        if len(out) >= limit:
            break
    return out


def naver_research(client_id: str, client_secret: str, brand: str, product: str) -> dict:
    """브랜드·제품명만으로 자료를 모은다.
    1) 네이버 웹문서 검색으로 공식몰·브랜드몰 상품 페이지를 찾아 직접 읽는다 (막아 둔 쇼핑몰은 건너뜀)
    2) 블로그·카페 검색으로 후기 요약을 모은다
    결과: {"text", "sources":[{"title","uri"}], "url_failed":[], "page_text", "images", "pages"}"""
    query = f"{brand} {product}".strip()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {k: ex.submit(naver_search, client_id, client_secret, k, query, n)
                for k, n in (("webkr", 15), ("blog", 30), ("cafearticle", 15), ("shop", 10))}
        res = {}
        for k, f in futs.items():
            try:
                res[k] = f.result()
            except ValueError:
                raise
            except Exception:  # noqa: BLE001
                res[k] = []

    lines, sources = [], []
    # 상품 페이지 자동으로 찾아 읽기 (웹문서 → 쇼핑 결과 순)
    page_text, images, pages = "", [], []
    for link in _pick_shop_pages(res["webkr"] + res["shop"]):
        pg = fetch_page(link, max_tiles=MAX_TILES // 2)
        if pg.ok and (len(pg.text) > 300 or pg.images):
            pages.append(link)
            page_text += f"\n\n[자동으로 찾은 상품 페이지: {link}]\n{pg.text[:9000]}"
            images += list(pg.images)
            sources.append({"title": "상품 페이지 (자동으로 찾음)", "uri": link})
        if len(images) >= MAX_TILES:
            break

    if res["shop"]:
        lines.append("[쇼핑 검색 상품 정보]")
        for it in res["shop"]:
            parts = [_clean(it.get("title"))]
            for k, label in (("brand", "브랜드"), ("maker", "제조사")):
                if it.get(k):
                    parts.append(f"{label} {_clean(it[k])}")
            if str(it.get("lprice") or "").isdigit():
                parts.append(f"최저가 {int(it['lprice']):,}원")
            lines.append("- " + " | ".join(parts) + f" (출처: {_clean(it.get('mallName')) or '네이버쇼핑'})")
    for key, head, who in (("webkr", "[웹문서 검색 요약]", None), ("blog", "[블로그 사용기·후기 요약]", "bloggername"),
                           ("cafearticle", "[카페 글 요약]", "cafename")):
        good = [it for it in res[key] if _clean(it.get("description"))]
        if not good:
            continue
        lines.append("\n" + head)
        for it in good:
            src = _clean(it.get(who)) if who else (urlparse(str(it.get("link") or "")).hostname or "웹문서")
            lines.append(f"- {_clean(it.get('title'))}: {_clean(it.get('description'))} (출처: {src or '네이버'})")
            if it.get("link"):
                sources.append({"title": _clean(it.get("title"))[:50], "uri": it["link"]})
    return {"text": "\n".join(lines).strip(), "sources": sources[:45], "url_failed": [],
            "page_text": page_text.strip(), "images": images[:MAX_TILES], "pages": pages}


# ------------------------------------------------------------------ 단계 ----
def analyze_material(cfg: Cfg, brand: str, product: str, page_text: str, manual_text: str,
                     images: list[tuple[bytes, str]], web_text: str = "") -> tuple[dict, dict]:
    parts: list = [("text", f"[브랜드] {brand}\n[제품] {product}\n\n[자료 — 상세페이지 글자]\n{page_text[:15000] or '(없음)'}\n\n"
                            f"[자료 — 직접 붙여넣은 텍스트]\n{manual_text[:15000] or '(없음)'}\n\n"
                            f"[자료 — 웹 검색으로 모은 내용 (공식몰·판매처·후기)]\n{web_text[:12000] or '(없음)'}")]
    if images:
        parts.append(("text", f"[자료 — 이미지 {len(images)}장] 아래 이미지는 상세페이지(또는 캡처)를 위에서 아래로 자른 조각입니다. "
                              "이미지 속 글자를 순서대로 빠짐없이 읽어 image_text에 적으세요."))
        parts += [("image", b, m) for b, m in images]
    data, meta = call_json(cfg, LITE_CHAIN, MATERIAL_SYSTEM, parts, expect="facts")

    image_text = str(data.get("image_text") or "")
    material_text = "\n".join([page_text, manual_text, image_text, web_text])

    def source_of(q: str) -> str:
        if quote_found(q, norm(page_text) + norm(manual_text)):
            return "글자"
        if quote_found(q, norm(image_text)):
            return "이미지(AI가 읽음)"
        if quote_found(q, norm(web_text)):
            return "웹 검색"
        return ""

    facts = []
    for f in data.get("facts") or []:
        if isinstance(f, dict) and f.get("fact"):
            q = str(f.get("quote") or "")
            src = source_of(q)
            facts.append({"fact": str(f["fact"]).strip(), "quote": q.strip(), "verified": bool(src), "source": src})
    appeals = []
    for i, a in enumerate((data.get("appeals") or [])[:3]):
        if not isinstance(a, dict) or not a.get("name"):
            continue
        q = str(a.get("quote") or "")
        src = source_of(q)
        strong = str(a.get("strength") or "").startswith("강")
        reasons = []
        if not src:
            reasons.append("근거 인용을 자료에서 찾지 못했어요")
        if not strong:
            reasons.append("근거가 약해요")
        appeals.append({"id": i, "name": str(a["name"]).strip(), "buying_reason": str(a.get("buying_reason") or "").strip(),
                        "quote": q.strip(), "source": src,
                        "status": "확인됨" if not reasons else "검증 필요", "reasons": reasons})
    return {"material_text": material_text, "image_text": image_text, "facts": facts, "appeals": appeals,
            "gaps": [str(g) for g in (data.get("gaps") or [])][:6]}, meta


def reference_structure(cfg: Cfg, image: tuple[bytes, str] | None, attrs_text: str) -> tuple[dict, dict]:
    parts: list = [("text", f"[Part 1 분석 요약]\n{attrs_text}" if attrs_text else "[레퍼런스 이미지]")]
    if image:
        parts.append(("image", image[0], image[1]))
    data, meta = call_json(cfg, LITE_CHAIN, REF_SYSTEM, parts, expect="structure")
    ref_text = str(data.get("reference_text") or "")
    s = data.get("structure") or {}
    structure = {k: s.get(k) for k in ("composition", "number_emphasis", "hook_types", "tone")}
    # 구조 설명에 레퍼런스 문구가 그대로 새어 들어갔으면 그 항목은 버린다
    rn = norm(ref_text)
    if len(rn) >= 8:
        grams = {rn[i:i + 8] for i in range(len(rn) - 7)}
        for k, v in list(structure.items()):
            vn = norm(json.dumps(v, ensure_ascii=False))
            if any(vn[i:i + 8] in grams for i in range(max(0, len(vn) - 7))):
                structure[k] = "(문구가 섞여 있어 제외)"
    return {"structure": structure, "reference_text": ref_text,
            "visible_brand": str(data.get("visible_brand") or "").strip(),
            "visible_product": str(data.get("visible_product") or "").strip()}, meta


# ------------------------------------------------------------------ 규칙 검사 ----
SUPERLATIVES = ["1위", "일등", "최고", "최초", "최대", "최상", "최저", "최강", "유일", "No.1", "넘버원", "가장",
                "세계 최", "국내 최", "업계 최", "압도적", "독보적", "완벽"]
CERT_TERMS = ["인증", "특허", "임상", "FDA", "식약처", "KC", "ISO", "GMP", "HACCP", "수상", "어워드", "테스트 완료",
              "검증", "입증", "피부과", "전문의", "논문"]
EFFICACY_TERMS = ["치료", "완치", "예방", "개선", "효과", "효능", "증가", "감소", "제거", "방지", "회복", "재생",
                  "강화", "향상", "해결", "즉시"]
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def check_copy(c: dict, material_text: str, ref_text: str = "") -> dict:
    """카피 한 개를 검사한다. 자료에 없는 숫자·최상급·인증·효능 단어, 근거 인용, 레퍼런스 겹침."""
    body = " ".join(str(c.get(k) or "") for k in ("main_title", "sub_copy", "cta", "label"))
    mat = material_text or ""
    mat_digits = re.sub(r"(?<=\d),(?=\d)", "", mat)
    mat_lower = mat.lower()
    reasons, flagged = [], []

    for n in dict.fromkeys(_NUM.findall(re.sub(r"(?<=\d),(?=\d)", "", body))):
        if not re.search(rf"(?<![\d.]){re.escape(n)}(?!\d)", mat_digits):
            reasons.append(f"숫자 '{n}'이(가) 자료에 없어요")
            flagged.append(n)
    for group, label in ((SUPERLATIVES, "최상급·순위 표현"), (CERT_TERMS, "인증·검증 표현"), (EFFICACY_TERMS, "효능 표현")):
        for t in group:
            if t.lower() in body.lower() and t.lower() not in mat_lower:
                reasons.append(f"{label} '{t}'이(가) 자료에 없어요")
                flagged.append(t)
    if not quote_found(str(c.get("evidence") or ""), norm(mat)):
        reasons.append("근거 인용을 자료에서 찾지 못했어요")

    similar = False
    if ref_text:
        rlines = [norm(x) for x in re.split(r"[\n。.!?]+", ref_text) if len(norm(x)) >= 6]
        for k in ("main_title", "sub_copy", "cta"):
            cn = norm(str(c.get(k) or ""))
            if len(cn) < 6:
                continue
            for rl in rlines:
                if rl in cn or cn in rl or difflib.SequenceMatcher(None, cn, rl).ratio() >= 0.65:
                    similar = True
    return {"status": "확인됨" if not reasons else "검증 필요", "reasons": reasons, "flagged": flagged, "similar": similar}


def generate_copies(cfg: Cfg, brand: str, product: str, facts: list[dict], appeals: list[dict],
                    ref_structure: dict, material_text: str, ref_text: str,
                    tone_note: str = "") -> tuple[list[dict], dict, int]:
    fact_lines = "\n".join(f"- {f['fact']} (근거: {f['quote']})" for f in facts)
    appeal_lines = "\n".join(f"- {a['name']}: {a['buying_reason']} (근거: {a['quote']})" for a in appeals)
    struct = json.dumps(ref_structure or {}, ensure_ascii=False) if ref_structure else "(레퍼런스 없음)"
    parts = [("text", f"[브랜드] {brand}\n[제품] {product}\n\n[제품 사실]\n{fact_lines}\n\n[선택된 소구점]\n{appeal_lines}\n\n"
                      f"[레퍼런스 구조]\n{struct}"
                      + (f"\n\n[광고주 요청 — 톤 참고용일 뿐 사실이 아닙니다]\n{tone_note}" if tone_note else ""))]
    data, meta = call_json(cfg, WRITE_CHAIN, COPY_SYSTEM, parts, expect="copies")
    names = {a["name"] for a in appeals}
    copies, dropped = [], 0
    meta["audit"] = None
    for c in data.get("copies") or []:
        if not isinstance(c, dict) or not c.get("main_title"):
            continue
        c = {k: str(c.get(k) or "").strip() for k in ("appeal", "hook", "main_title", "sub_copy", "cta", "label", "evidence")}
        if c["appeal"] not in names and appeals:
            best = difflib.get_close_matches(c["appeal"], list(names), n=1, cutoff=0.3)
            c["appeal"] = best[0] if best else appeals[0]["name"]
        chk = check_copy(c, material_text, ref_text)
        if chk["similar"]:
            dropped += 1  # 레퍼런스 문구와 겹치면 아예 제외
            continue
        c.update(status=chk["status"], reasons=chk["reasons"], flagged=chk["flagged"])
        copies.append(c)
    meta["audit"] = audit_copies(cfg, fact_lines, copies, brand, product)
    return copies, meta, dropped


AUDIT_SYSTEM = """당신은 광고 심의 담당자입니다. [제품 사실]만이 근거입니다. 각 카피에서 제품 사실로 뒷받침되지 않는 주장을 찾으세요.
찾을 것: 효능·효과, 건강이나 위험을 암시하는 표현, 사실에 없는 수치, 보장·확약("확실히", "보장"), 다른 제품과의 비교, 최상급·순위, 인증·검증, 사실에 없는 혜택·기한·한정.
다음은 문제가 아닙니다: 브랜드명·제품명, 사실을 다른 말로 풀어 쓴 것(예: "배터리 최대 6개월" → "반년 동안 쓰는 배터리"), 질문형·권유형 문장, CTA 문구. 사실에 없는 새로운 주장(효능, 건강·위험 암시, 수치, 보장, 비교, 순위, 인증, 혜택)만 찾으세요. 문제 구절은 카피에 적힌 그대로, 최소 한 단어 이상으로 적으세요.
JSON으로만: {"results":[{"no":카피 번호,"unsupported":["문제 구절 그대로"]}]} — 문제가 없는 카피는 unsupported를 빈 배열로 두세요."""


def audit_copies(cfg: Cfg, fact_lines: str, copies: list[dict], brand: str = "", product: str = "") -> dict | None:
    """AI가 카피 전체를 한 번 더 검수해 근거 없는 주장을 찾는다 (실패해도 규칙 검사 결과는 그대로 유지)."""
    if not copies:
        return None
    listing = "\n".join(f"{i}. {c['main_title']} / {c['sub_copy']} / CTA: {c['cta']} / 라벨: {c['label']}" for i, c in enumerate(copies))
    try:
        data, meta = call_json(cfg, LITE_CHAIN, AUDIT_SYSTEM,
                               [("text", f"[브랜드] {brand}\n[제품] {product}\n\n[제품 사실]\n{fact_lines}\n\n[카피]\n{listing}")], expect="results")
    except Exception:  # noqa: BLE001
        return None
    skip = {norm(brand), norm(product)} - {""}
    for r in data.get("results") or []:
        try:
            c = copies[int(r.get("no"))]
        except (TypeError, ValueError, IndexError):
            continue
        for phrase in r.get("unsupported") or []:
            phrase = str(phrase).strip()
            if phrase and len(norm(phrase)) >= 3 and norm(phrase) not in skip:
                c["reasons"].append(f"AI 검수: '{phrase}'은(는) 제품 사실에 근거가 없어요")
                c["flagged"].append(phrase)
                c["status"] = "검증 필요"
    return meta


def format_copy(c: dict) -> str:
    return (f"[{c['appeal']} · {c['hook']}]\n메인 타이틀: {c['main_title']}\n서브 카피: {c['sub_copy']}\n"
            f"CTA: {c['cta']}\n라벨: {c['label']}")


def copies_to_csv(copies: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["소구점", "후킹 유형", "메인 타이틀", "서브 카피", "CTA", "라벨 문구", "근거(자료 원문)", "상태", "검증 사유"])
    for c in copies:
        w.writerow([c["appeal"], c["hook"], c["main_title"], c["sub_copy"], c["cta"], c["label"], c["evidence"],
                    c["status"], " / ".join(c.get("reasons") or [])])
    return buf.getvalue().encode("utf-8-sig")  # 엑셀에서 한글이 안 깨지게
