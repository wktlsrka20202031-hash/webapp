"""파트 2 — 카피 기획.

브랜드·제품명(+ 선택: 링크·캡처·텍스트) → 웹 검색으로 자료 자동 수집 → 제품 사실 + 소구점 3개 → 소구마다 카피 5개를 한 번에.
자료에 없는 수치·효능·인증·최상급은 자동으로 "검증 필요"로 표시한다.
디자인 토큰은 파트 1(app.py)과 같다.
"""
import hmac
import html
import json
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

import copy_engine as ce
from clipper import receive_clip, render_installer, title_from_clip
from nav import tool_nav

st.set_page_config(page_title="카피 기획 · 레퍼런스 키워드 추출기", page_icon="🎞️", layout="wide")

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
:root{
  --bg:#F7F7F3; --card:#FFFFFF; --ink:#111111; --ink-2:#444444; --ink-3:#777777; --line:#E8E7E1;
  --accent:#12997C; --accent-hover:#0E8069; --accent-soft:#E9F6F2;
  --warn-bg:#FFF1D1; --warn:#8A5A00;
  --radius-lg:20px; --radius-md:14px; --radius-pill:999px;
  --shadow:0 1px 2px rgba(17,17,17,.04), 0 8px 24px rgba(17,17,17,.04);
  --font:'Pretendard Variable', Pretendard, -apple-system, 'Noto Sans KR', sans-serif;
}
.stApp{ background:var(--bg); }
.stApp, .stApp p, .stApp label, .stApp textarea, .stApp input, .stApp button,
.stApp span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded){ font-family:var(--font) !important; }
.stApp p{ color:var(--ink-2); word-break:keep-all; }
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"]{ display:none !important; }
.block-container{ max-width:960px !important; padding:120px 40px 96px !important; }
[data-testid="stVerticalBlock"]{ gap:0; }
.stApp [data-testid="stMarkdownContainer"]{ margin-bottom:0 !important; }

.lt-header{ position:fixed; top:0; left:0; right:0; height:72px; z-index:999990; background:rgba(255,255,255,.92);
  backdrop-filter:saturate(180%) blur(8px); box-shadow:0 1px 0 var(--line); }
.lt-header .inner{ max-width:960px; height:100%; margin:0 auto; padding:0 40px; display:flex; align-items:center; justify-content:space-between; }
.lt-logo{ display:flex; align-items:center; gap:10px; font-size:21px; font-weight:700; color:var(--ink); letter-spacing:-.02em; }
.lt-logo .mark{ width:22px; height:22px; border-radius:6px; background:var(--accent); position:relative; }
.lt-logo .mark::after{ content:""; position:absolute; inset:6px; border-radius:2px; background:#fff; opacity:.9; }
.lt-tag{ font-size:14px; font-weight:600; color:var(--accent-hover); background:var(--accent-soft); padding:8px 16px; border-radius:var(--radius-pill); }

.lt-eyebrow{ font-size:13px; font-weight:700; letter-spacing:.14em; color:var(--accent); text-transform:uppercase; margin:16px 0; }
.stApp h1.lt-title{ font-size:40px !important; line-height:1.3; font-weight:700; letter-spacing:-.03em; color:var(--ink); margin:0 0 16px; }
.stApp p.lt-lead{ font-size:17px; line-height:1.7; color:var(--ink-3); margin:0; }
.lt-steps{ display:flex; gap:8px; margin:40px 0 32px; padding:0; list-style:none; }
.lt-steps li{ flex:1; display:flex; align-items:center; gap:12px; padding:14px 16px; border-radius:var(--radius-md); color:var(--ink-3); font-size:15px; font-weight:500; word-break:keep-all; }
.lt-steps .n{ width:28px; height:28px; border-radius:50%; flex:none; display:grid; place-items:center; font-size:13px; font-weight:700; border:1.5px solid #D4D3CC; color:var(--ink-3); }
.lt-steps li.done .n{ background:var(--ink); border-color:var(--ink); color:#fff; } .lt-steps li.done{ color:var(--ink-2); }
.lt-steps li.current{ background:var(--card); color:var(--ink); font-weight:600; box-shadow:var(--shadow); }
.lt-steps li.current .n{ background:var(--accent); border-color:var(--accent); color:#fff; }
.lt-section{ display:flex; align-items:flex-end; justify-content:space-between; margin:0 0 24px; }
.stApp .lt-section h2{ font-size:26px !important; font-weight:700; letter-spacing:-.02em; color:var(--ink); margin:0; padding:0; }
.lt-section .cap{ font-size:14px; color:var(--ink-3); }
.lt-label{ font-size:13px; font-weight:700; letter-spacing:.1em; color:var(--ink-3); text-transform:uppercase; margin:0 0 12px; }

/* 카드 */
.st-key-p2_input_card, [class*="st-key-p2_ap_card"], [class*="st-key-p2_copy_card"]{
  background:var(--card); border:none !important; border-radius:var(--radius-lg) !important; box-shadow:var(--shadow); padding:32px !important; margin-bottom:16px; }
[class*="st-key-p2_ap_card"], [class*="st-key-p2_copy_card"]{ padding:24px 28px !important; }
.st-key-p2_input_card [data-testid="stWidgetLabel"] p{ font-size:15px !important; font-weight:600; color:var(--ink) !important; }
.stTextInput [data-baseweb="input"], [data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"]{
  border:1.5px solid var(--line) !important; border-radius:var(--radius-md) !important; background:#FBFBF9 !important; transition:all .2s; }
.stTextInput [data-baseweb="input"]:focus-within, [data-testid="stTextInputRootElement"]:focus-within, [data-testid="stTextAreaRootElement"]:focus-within{
  border-color:var(--accent) !important; background:#fff !important; box-shadow:0 0 0 4px var(--accent-soft); }
.stTextInput input{ font-size:16px !important; padding:14px 16px !important; color:var(--ink) !important; background:transparent !important; }
.stTextArea textarea{ font-size:15px !important; line-height:1.7 !important; padding:14px 16px !important; color:var(--ink) !important; background:transparent !important; }
[data-testid="stFileUploaderDropzone"]{ background:#FBFBF9 !important; border:1.5px dashed #D4D3CC !important; border-radius:var(--radius-md) !important; }
[data-testid="stFileUploaderDropzone"]:hover{ border-color:var(--accent) !important; background:var(--accent-soft) !important; }
[data-testid="stExpander"]{ border:1.5px solid var(--line) !important; border-radius:var(--radius-md) !important; background:#FBFBF9; }
[data-testid="stAlert"] > div{ border-radius:var(--radius-md) !important; border:none !important; }

/* 주 버튼 */
.st-key-p2_run1, .st-key-p2_run2{ width:100% !important; }
.st-key-p2_run1 .stButton, .st-key-p2_run2 .stButton{ width:100%; }
.st-key-p2_run1 button, .st-key-p2_run2 button{ width:100%; height:60px; border-radius:var(--radius-md) !important; border:none !important;
  background:var(--accent) !important; transition:all .2s; box-shadow:0 6px 16px rgba(18,153,124,.22); }
.st-key-p2_run1 button p, .st-key-p2_run2 button p{ color:#fff !important; font-size:17px !important; font-weight:700; letter-spacing:-.01em; }
.st-key-p2_run1 button:hover, .st-key-p2_run2 button:hover{ background:var(--accent-hover) !important; transform:translateY(-1px); }
.st-key-p2_run2 button:disabled{ background:#E3E2DC !important; box-shadow:none; transform:none; }
.st-key-p2_run2 button:disabled p{ color:#9A9992 !important; }

/* 상태·후킹 표시 */
.pill{ display:inline-block; font-size:12.5px; font-weight:700; border-radius:var(--radius-pill); padding:4px 12px; margin:0 8px 8px 0; }
.pill.ok{ background:var(--accent-soft); color:var(--accent-hover); }
.pill.warn{ background:var(--warn-bg); color:var(--warn); }
.pill.hook{ background:#F3F3EF; color:var(--ink-2); }
.pill.badge{ background:var(--ink); color:#fff; }
.copy-title{ font-size:22px; font-weight:700; line-height:1.4; letter-spacing:-.02em; color:var(--ink); margin:4px 0 6px; word-break:keep-all; }
.copy-sub{ font-size:16px; line-height:1.6; color:var(--ink-2); margin-bottom:14px; word-break:keep-all; }
.chip{ display:inline-block; font-size:13px; font-weight:600; background:#F3F3EF; border-radius:var(--radius-pill); padding:6px 14px; margin:0 8px 8px 0; color:var(--ink); }
.chip b{ color:var(--ink-3); font-weight:600; margin-right:6px; }
.warn-line{ font-size:14px; color:var(--warn); margin:4px 0; }
.angle-heading{ font-size:20px; font-weight:700; letter-spacing:-.02em; color:var(--ink); margin:40px 0 16px; }
.lt-gap-16{ height:16px; } .lt-gap-24{ height:24px; } .lt-gap-32{ height:32px; } .lt-gap-48{ height:48px; }
.lt-footer{ margin-top:80px; padding-top:32px; border-top:1px solid var(--line); }
.lt-footer p{ font-size:13px !important; color:var(--ink-3) !important; line-height:1.7; margin:0; }
@media (max-width:720px){
  .block-container{ padding:96px 16px 64px !important; } .lt-header .inner{ padding:0 16px; } .lt-header{ height:60px; }
  .stApp h1.lt-title{ font-size:28px !important; } .lt-steps li{ flex-direction:column; gap:6px; padding:10px 4px; font-size:12px; text-align:center; }
  .st-key-p2_input_card{ padding:20px !important; }
}
</style>
"""

esc = html.escape


def block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def gap(n: int) -> None:
    block(f'<div class="lt-gap-{n}"></div>')


def section(title: str, caption: str = "") -> None:
    block(f'<div class="lt-section"><h2>{esc(title)}</h2><span class="cap">{esc(caption)}</span></div>')


block(CSS)
block('<div class="lt-header"><div class="inner"><span class="lt-logo"><span class="mark"></span>레퍼런스 키워드 추출기</span>'
      '<span class="lt-tag">카피 기획</span></div></div>')

# 📋 북마크가 보낸 상세페이지 — 비밀번호 화면에서 도착해도 잃지 않게 먼저 받아 둔다
_clip_in = receive_clip()
if _clip_in and ce.parse_clip(_clip_in):
    st.session_state["p2_pending_clip"] = _clip_in

# 파트 1과 같은 비밀번호 잠금 (북마크로 새 탭이 열려도 여기서 바로 입력할 수 있게)
try:
    _password = st.secrets.get("APP_PASSWORD") or ""
except Exception:
    _password = ""
if _password and not st.session_state.get("authed"):
    block('<h1 class="lt-title">팀 전용 도구입니다</h1><p class="lt-lead">공유받은 비밀번호를 입력해 주세요.'
          + (' 비밀번호를 넣으면 보내온 상세페이지로 바로 시작해요.' if st.session_state.get("p2_pending_clip") else '') + '</p>')
    gap(24)
    with st.form("p2_gate", border=False):
        _entered = st.text_input("비밀번호", type="password", key="p2_gate_pw")
        _ok = st.form_submit_button("들어가기  →")
    if _ok:
        if hmac.compare_digest(_entered.encode(), _password.encode()):
            st.session_state["authed"] = True
            st.rerun()
        st.error("비밀번호가 맞지 않아요.")
    st.stop()


def get_key() -> str:
    try:
        key = st.secrets.get("GEMINI_API_KEY") or ""
    except Exception:
        key = ""
    if not key:
        st.error("GEMINI_API_KEY가 설정되지 않았어요. Streamlit Secrets에 등록해주세요.")
        st.stop()
    return key


def friendly(e: Exception) -> str:
    if isinstance(e, ce.AllModelsFailed):
        kinds = {k for _, k in e.tries}
        if "day" in kinds and not ({"busy", "minute"} & kinds):
            return "오늘 쓸 수 있는 무료 AI 한도를 다 썼어요. 매일 오후 4시(한국 시간, 11월 초~3월 초에는 오후 5시)에 다시 채워져요."
        return "지금 쓸 수 있는 무료 AI가 모두 붐비거나 한도에 걸렸어요. 1~2분 뒤에 다시 눌러주세요."
    s = str(e)
    if "API_KEY_INVALID" in s or "API key not valid" in s:
        return "API 키가 올바르지 않아요. Streamlit Secrets의 GEMINI_API_KEY를 확인해주세요."
    return f"문제가 생겼어요: {s[:160]}"


# ---- 같은 자료를 두 번 분석하지 않도록 결과를 저장 ----
@st.cache_data(show_spinner=False, ttl=3600, max_entries=30)
def c_fetch(url: str):
    return ce.fetch_page(url)


@st.cache_data(show_spinner=False, ttl=86400, max_entries=60)
def c_research(_cfg, brand, product, url):
    return ce.web_research(_cfg, brand, product, url)


@st.cache_data(show_spinner=False, ttl=86400, max_entries=60)
def c_material(_cfg, local_only, brand, product, page_text, manual_text, images, web_text=""):
    return ce.analyze_material(_cfg, brand, product, page_text, manual_text, list(images), web_text)


@st.cache_data(show_spinner=False, ttl=86400, max_entries=60)
def c_ref(_cfg, local_only, image, attrs_text):
    return ce.reference_structure(_cfg, image, attrs_text)


@st.cache_data(show_spinner=False, ttl=86400, max_entries=60)
def c_copies(_cfg, local_only, brand, product, facts_json, appeals_json, struct_json, material_text, ref_text, tone_note):
    return ce.generate_copies(_cfg, brand, product, json.loads(facts_json), json.loads(appeals_json),
                              json.loads(struct_json), material_text, ref_text, tone_note)


# ------------------------------------------------------------------ 화면 ----
key = get_key()
local_ok = ce.ollama_available()
ref_in = st.session_state.get("copy_ref")  # 파트 1에서 넘어온 레퍼런스
p2 = st.session_state.setdefault("p2", {})

# 북마크로 받은 상세페이지가 있으면 입력칸을 채우고 바로 실행한다
_pending = st.session_state.pop("p2_pending_clip", None)
if _pending:
    _, _body, _ = ce.parse_clip(_pending)
    st.session_state["p2_manual"] = _pending
    st.session_state["p2_link"] = ""
    if not (st.session_state.get("p2_product") or "").strip():
        st.session_state["p2_product"] = title_from_clip(_body)
    p2.update(material=None, copies=None, auto_run=True, from_clip=True)

tool_nav("copy")
block('<div class="lt-eyebrow">Copy Planner</div>'
      '<h1 class="lt-title">브랜드명·제품명만 넣으면<br>소구점부터 카피까지 한 번에</h1>'
      '<p class="lt-lead">자료에 실제로 적힌 내용만 근거로 삼고, 근거 없는 수치·효능·인증·최상급은<br>자동으로 "검증 필요"로 표시합니다.</p>')

step = 3 if p2.get("copies") else 2 if p2.get("material") else 0
block('<ol class="lt-steps">' + "".join(
    f'<li class="{"done" if i < step else "current" if i == step else ""}"><span class="n">{"✓" if i < step else i + 1}</span>{lbl}</li>'
    for i, lbl in enumerate(["자료 입력", "자료 조사·소구점", "카피 완성"])) + "</ol>")

# 파트 1에서 넘어오면 레퍼런스 구조를 읽고, 비어 있는 칸에 제품명(없으면 이미지에 보이는 이름)을 채워 둔다
if ref_in and not p2.get("handoff_done"):
    attrs = ref_in.get("attributes") or {}
    attrs_text = "\n".join([ref_in.get("summary", "")] + [f"{k}: {v}" for k, v in attrs.items() if v])
    if ref_in.get("product") and not st.session_state.get("p2_product"):
        st.session_state["p2_product"] = ref_in["product"]
    with st.spinner("파트 1에서 가져온 레퍼런스를 읽는 중…"):
        try:
            ref_res, ref_meta = c_ref(ce.Cfg(api_key=key), False, ref_in.get("image"), attrs_text)
            p2["ref"] = ref_res
            p2.setdefault("usage", []).append(("레퍼런스 구조", ref_meta))
            if ref_res.get("visible_brand") and not st.session_state.get("p2_brand"):
                st.session_state["p2_brand"] = ref_res["visible_brand"]
                p2["prefilled"] = True
            if ref_res.get("visible_product") and not st.session_state.get("p2_product"):
                st.session_state["p2_product"] = ref_res["visible_product"]
                p2["prefilled"] = True
        except Exception as e:  # noqa: BLE001
            st.warning("레퍼런스를 읽지 못했어요. 레퍼런스 없이 진행하거나, 아래에서 이미지를 올려주세요. (" + friendly(e) + ")")
    p2["handoff_done"] = True

with st.container(border=True, key="p2_input_card"):
    block('<div class="lt-label">입력</div>')
    c1, c2 = st.columns(2)
    brand = c1.text_input("브랜드명", key="p2_brand", placeholder="예: 바이브랩")
    product = c2.text_input("제품명", key="p2_product", placeholder="예: 브로우 래시 세럼")
    if p2.get("prefilled"):
        st.caption("브랜드명은 레퍼런스 이미지에서 읽은 이름이에요. 우리 제품과 다르면 바꿔주세요.")
    gap(16)

    ref_upload = None
    if ref_in:
        block(f'<span class="pill ok">레퍼런스 가져옴</span><span style="font-size:15px;color:#444">{esc(ref_in.get("summary", ""))}</span>')
        gap(16)
    else:
        ref_upload = st.file_uploader("레퍼런스 이미지 (선택 — 구성·숫자 강조·후킹 방식만 참고해요)",
                                      type=["jpg", "jpeg", "png", "webp"], key="p2_refup")
        gap(16)

    link = st.text_input("상세페이지 링크 (선택)", key="p2_link", placeholder="https://...")
    st.caption("링크가 없어도 돼요. 브랜드명·제품명으로 공식몰·판매처·구매 후기를 자동으로 검색해서 자료를 모아요.")
    gap(8)
    use_web = st.checkbox("웹 검색으로 자료 자동 보강 (공식몰·쇼핑몰·후기·블로그)", value=True, key="p2_web")
    gap(8)
    with st.expander("자료를 직접 더 넣고 싶을 때 (선택) — 캡처 / 텍스트 / 📋 상세페이지 가져오기 버튼",
                     expanded=bool(p2.get("link_failed"))):
        st.caption("자동 조사로는 상세페이지 이미지 속 글자까지는 못 읽을 때가 있어요. 그 내용까지 꼭 반영하고 싶을 때만 쓰세요.")
        render_installer()
        manual = st.text_area("복사한 텍스트 — 📋 가져오기 버튼으로 복사한 내용도 여기에 붙여넣어요", key="p2_manual", height=140)
        if ce.parse_clip(manual):
            st.caption(f"✓ 가져오기 버튼으로 복사한 상세페이지예요 (이미지 {len(ce.parse_clip(manual)[2])}장). 위 링크 칸은 비워 둬도 돼요.")
        gap(8)
        up_files = st.file_uploader("상세페이지 캡처 이미지 (여러 장 가능)", type=["jpg", "jpeg", "png", "webp"],
                                    accept_multiple_files=True, key="p2_up")
    local_only = False
    if local_ok:
        gap(8)
        local_only = st.checkbox("기밀 모드 — 구글로 보내지 않고 이 컴퓨터의 AI만 사용 (느려요)", key="p2_local")
    gap(8)
    st.caption("무료 구글 AI를 쓰기 때문에 입력한 내용이 구글 서비스 개선에 쓰일 수 있어요. 공개된 상세페이지는 괜찮지만, 출시 전 자료나 계약 내용은 넣지 마세요.")
    gap(16)
    run1 = st.button("자료 조사부터 카피까지 한 번에 만들기  →", type="primary", key="p2_run1") or p2.pop("auto_run", False)
    if p2.get("from_clip") and ce.parse_clip(manual):
        st.caption("✓ 📋 북마크로 보내온 상세페이지로 진행해요. 브랜드명이 비어 있으면 자료에서 찾아요.")

def make_copies(cfg, material, local_only) -> None:
    """정리된 자료의 소구점 전부로 카피를 쓰고 검수한다. 결과는 p2에 저장."""
    usage = list(p2.get("usage", []))
    ref_struct, ref_text = (p2.get("ref") or {}).get("structure"), (p2.get("ref") or {}).get("reference_text", "")
    if p2.get("ref_upload"):
        st.write("레퍼런스의 구성만 읽는 중…")
        rr, rm = c_ref(cfg, local_only, p2["ref_upload"], "")
        ref_struct, ref_text = rr["structure"], rr["reference_text"]
        usage.append(("레퍼런스 구조", rm))
    appeals = material["appeals"]
    st.write(f"소구점 {len(appeals)}개 × 카피 5개를 쓰고 검수하는 중…")
    copies, meta, dropped = c_copies(cfg, local_only, p2["brand"], p2["product"],
                                     json.dumps(material["facts"], ensure_ascii=False),
                                     json.dumps(appeals, ensure_ascii=False),
                                     json.dumps(ref_struct or {}, ensure_ascii=False),
                                     material["material_text"], ref_text,
                                     (ref_in or {}).get("brief", ""))
    usage.append(("카피 작성", meta))
    if meta.get("audit"):
        usage.append(("AI 검수", meta["audit"]))
    p2.update(copies=copies, dropped=dropped, usage=usage, copy_error=None)


def collect_direct(link_url: str, clip, up_files) -> tuple[str, list, list]:
    """링크·북마크 복사본·캡처에서 글자와 이미지 조각을 모은다 (AI를 쓰지 않아서 따로 돌려도 된다)."""
    page_text, tiles, notes = "", [], []
    if clip:  # 📋 가져오기 버튼으로 복사한 내용 — 사용자 브라우저에서 읽은 것이라 링크보다 우선
        clip_url, page_text, clip_imgs = clip
        tiles, more = ce.download_tiles(clip_imgs, clip_url, ce.MAX_TILES)
        if more:
            notes.append(f"상세 이미지가 길어서 앞부분 {ce.MAX_TILES}조각만 읽었어요")
        if clip_imgs and not tiles:
            notes.append("붙여넣은 상세페이지의 이미지는 사이트가 막아서 받지 못했어요")
    elif link_url:
        pg = ce.fetch_page(link_url)
        notes += pg.notes
        if pg.ok:
            page_text, tiles = pg.text, list(pg.images)
    for f in up_files:
        tiles += ce.tiles_from_image(f)
    return page_text, tiles[:ce.MAX_TILES], notes


if run1:
    if not product.strip() or not (brand.strip() or ce.parse_clip(manual)):
        st.warning("브랜드명과 제품명을 입력해주세요.")
    elif not (use_web and not local_only) and not (link.strip() or up_files or manual.strip()):
        st.warning("웹 검색을 끄면 자료가 필요해요. 상세페이지 링크, 캡처 이미지, 복사한 텍스트 중 하나를 넣어주세요.")
    else:
        cfg = ce.Cfg(api_key=key, local_only=local_only)
        usage = [u for u in p2.get("usage", []) if u[0] == "레퍼런스 구조"]
        notes, web = [], None
        b, pr, url = brand.strip(), product.strip(), link.strip()
        clip = ce.parse_clip(manual)
        manual_text = "" if clip else manual.strip()
        p2.update(material=None, copies=None, copy_error=None, web=None, web_error=None, brand=b, product=pr,
                  ref_upload=(ref_upload.getvalue(), ref_upload.type) if ref_upload is not None else None)
        try:
            with st.status("자료를 모으는 중…", expanded=True) as status:
                # 링크 읽기(이 서버)와 웹 검색(구글)을 동시에 진행한다
                with ThreadPoolExecutor(max_workers=1) as ex:
                    direct = ex.submit(collect_direct, url, clip, [f.getvalue() for f in up_files or []])
                    if use_web and not local_only:
                        st.write("공식몰·쇼핑몰·후기를 웹에서 검색하는 중…")
                        try:
                            web, wmeta = c_research(cfg, b, pr, url or (clip[0] if clip else ""))
                            usage.append(("웹 검색", wmeta))
                            st.write(f"웹 검색 완료 — 참고한 사이트 {len(web.get('sources') or [])}곳")
                            if url and url in (web.get("url_failed") or []):
                                notes.append("구글도 링크 본문은 열지 못해서, 검색 결과로 자료를 채웠어요")
                        except Exception as e:  # noqa: BLE001
                            if "API_KEY_INVALID" in str(e) or "API key not valid" in str(e):
                                raise
                            detail = getattr(e, "last_error", "") or str(e)[:300]
                            notes.append("웹 검색을 하지 못했어요 — 링크·첨부 자료만 썼어요. (" + friendly(e)[:80] + ")")
                            p2["web_error"] = detail
                    if url or clip or up_files:
                        st.write("상세페이지를 읽는 중…")
                    page_text, tiles, dnotes = direct.result()
                    notes += dnotes
                web_text = (web or {}).get("text", "")
                if not page_text and not tiles and not manual_text and not web_text:
                    status.update(label="자료를 모으지 못했어요", state="error", expanded=True)
                    p2["link_failed"] = True
                    for n in notes:
                        st.write("ℹ️ " + n)
                    if p2.get("web_error"):
                        st.code("웹 검색 오류: " + p2["web_error"], language=None)
                    st.error("자료를 찾지 못했어요. 브랜드명·제품명을 정확히 적었는지 확인하거나, 아래 '자료를 직접 더 넣고 싶을 때'에 캡처를 올려주세요.")
                    st.stop()
                st.write(f"글자 {len(page_text) + len(manual_text) + len(web_text):,}자, 이미지 조각 {len(tiles)}개 — 제품 사실과 소구점을 정리하는 중…")
                material, meta = c_material(cfg, local_only, b, pr, page_text, manual_text, tuple(tiles), web_text)
                usage.append(("자료 정리·소구점", meta))
                p2.update(material=material, notes=notes, web=web, usage=usage)
                if not material["appeals"]:
                    status.update(label="소구점을 뽑지 못했어요", state="error")
                else:
                    status.update(label="소구점 정리 완료 — 카피를 쓰는 중…")
                    try:
                        make_copies(cfg, material, local_only)
                        status.update(label="카피 완성", state="complete", expanded=False)
                    except Exception as e:  # noqa: BLE001
                        p2["copy_error"] = friendly(e)
                        status.update(label="소구점까지 완료 — 카피는 다시 시도해주세요", state="error")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(friendly(e))

material = p2.get("material")
if material:
    gap(48)
    section("정리된 제품 사실과 소구점", "모은 자료에 적힌 내용만 근거로 삼았어요")
    for n in p2.get("notes", []):
        st.caption("ℹ️ " + n)
    web = p2.get("web") or {}
    if web.get("text"):
        with st.expander(f"웹 검색으로 모은 자료 보기 (참고한 사이트 {len(web.get('sources') or [])}곳)"):
            st.caption("AI가 검색 결과를 정리한 내용이에요. 중요한 수치·성분은 출처 사이트에서 한 번 더 확인하세요.")
            st.text(web["text"])
            for s in web.get("sources") or []:
                st.markdown(f"- [{esc(s['title'] or s['uri'])}]({s['uri']})")
    with st.expander(f"제품 사실 {len(material['facts'])}개 보기"):
        for f in material["facts"]:
            mark = "✓ 인용 확인" if f["verified"] else "⚠ 인용 미확인"
            st.markdown(f"- {esc(f['fact'])}  \n  <span style='font-size:13px;color:#777'>{mark} · {esc(f['source'] or '출처 미확인')} · “{esc(f['quote'])}”</span>",
                        unsafe_allow_html=True)
    if material["gaps"]:
        st.caption("자료에 없어서 카피에 못 쓰는 정보: " + " · ".join(material["gaps"]))
    gap(16)
    if not material["appeals"]:
        st.warning("소구점을 뽑지 못했어요. 자료를 더 넣고 다시 시도해주세요.")
    for a in material["appeals"]:
        with st.container(border=True, key=f"p2_ap_card_{a['id']}"):
            cls = "ok" if a["status"] == "확인됨" else "warn"
            block(f'<div class="copy-title" style="font-size:19px">{esc(a["name"])}</div>'
                  f'<span class="pill {cls}">{a["status"]}</span><span style="font-size:15px;color:#444">{esc(a["buying_reason"])}</span>')
            st.caption(f"근거: “{a['quote']}” ({a['source'] or '출처 미확인'})")
            for r in a["reasons"]:
                block(f'<div class="warn-line">⚠ {esc(r)}</div>')
    if p2.get("copy_error") and material["appeals"]:
        gap(8)
        st.error("카피를 쓰지 못했어요: " + p2["copy_error"])
        if st.button("카피만 다시 만들기  →", type="primary", key="p2_run2"):
            try:
                with st.status("카피를 쓰는 중…", expanded=True) as status:
                    lo = bool(st.session_state.get("p2_local"))
                    make_copies(ce.Cfg(api_key=key, local_only=lo), material, lo)
                    status.update(label="카피 완성", state="complete", expanded=False)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                p2["copy_error"] = friendly(e)
                st.error(friendly(e))

copies = p2.get("copies")
if copies:
    gap(48)
    n_warn = sum(1 for c in copies if c["status"] != "확인됨")
    section("카피", f"{len(copies)}개 중 검증 필요 {n_warn}개")
    if p2.get("dropped"):
        st.caption(f"레퍼런스 문구와 너무 비슷해서 {p2['dropped']}개는 자동으로 뺐어요.")
    st.caption("'검증 필요' 카피는 이유를 확인한 뒤 쓰세요. 이 표시는 걸러내는 보조 장치이니 최종 확인은 사람이 해주세요.")
    seen = []
    for c in copies:
        if c["appeal"] not in seen:
            seen.append(c["appeal"])
    n = 0
    for ap in seen:
        block(f'<div class="angle-heading">{esc(ap)}</div>')
        for c in [x for x in copies if x["appeal"] == ap]:
            n += 1
            with st.container(border=True, key=f"p2_copy_card_{n}"):
                cls = "ok" if c["status"] == "확인됨" else "warn"
                block(f'<span class="pill hook">{esc(c["hook"])}</span><span class="pill {cls}">{c["status"]}</span>')
                block(f'<div class="copy-title">{esc(c["main_title"])}</div><div class="copy-sub">{esc(c["sub_copy"])}</div>'
                      f'<span class="chip"><b>CTA</b>{esc(c["cta"])}</span><span class="chip"><b>라벨</b>{esc(c["label"])}</span>')
                st.caption(f"근거: “{c['evidence']}”")
                for r in c["reasons"]:
                    block(f'<div class="warn-line">⚠ {esc(r)}</div>')
                with st.expander("복사하기"):
                    st.code(ce.format_copy(c), language=None)
    gap(16)
    st.download_button("엑셀(CSV)로 받기", data=ce.copies_to_csv(copies), file_name="카피_기획.csv", mime="text/csv", key="p2_csv")

if p2.get("usage"):
    gap(24)
    with st.expander("사용한 AI와 시간"):
        for label, m in p2["usage"]:
            skipped = ", ".join(f"{mm}({k})" for mm, k in (m.get("tries") or []))
            st.write(f"{label}: **{m['model']}** · {m.get('seconds', '?')}초 · 토큰 {m.get('prompt_tokens', '?')}→{m.get('output_tokens', '?')}"
                     + (f" · 건너뜀: {skipped}" if skipped else ""))

if p2.get("material"):
    gap(16)
    if st.button("처음부터 다시", key="p2_reset"):
        for k in list(st.session_state.keys()):
            if k.startswith("p2"):
                del st.session_state[k]
        st.rerun()

block('<div class="lt-footer"><p>핀터레스트·메타 라이브러리의 이미지 자동 수집 기능은 없습니다 (이용약관). '
      '분석과 카피 작성에는 Google Gemini가 사용됩니다.</p></div>')
