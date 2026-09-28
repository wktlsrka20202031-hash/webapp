"""
레퍼런스 라이트테이블 — 독립 실행형 웹앱

Claude 채팅이 필요 없다. 광고 레퍼런스 이미지를 올리면 Google Gemini(무료 API)가
직접 분석해서 업종/색감/레이아웃/무드/카피 톤을 뽑고, 핀터레스트·메타 라이브러리
검색 키워드를 링크와 함께 보여준다.

로컬 실행:
    pip install -r requirements.txt
    export GEMINI_API_KEY=발급받은_키
    streamlit run app.py

배포 (Streamlit Community Cloud, 무료):
    1) 이 webapp 폴더를 GitHub 저장소에 올린다
    2) share.streamlit.io 에서 GitHub으로 로그인 → New app → 저장소 선택 → Main file: app.py
    3) App settings → Secrets 에 아래처럼 입력:
       GEMINI_API_KEY = "발급받은_키"
    4) Deploy 누르면 https://xxxx.streamlit.app 링크가 생기고, 그 링크를 아무나 열어 쓸 수 있다.
"""

import html
import json
import time
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import types

MODEL_FALLBACKS = ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash"]

SYSTEM_PROMPT = """당신은 광고/디자인 크리에이티브 디렉터입니다. 마케터가 올린 레퍼런스(이미지 또는 텍스트 설명)를 분석해서, (1) 핀터레스트에서 비슷한 스타일의 레퍼런스를 찾을 검색 키워드와 (2) 메타 광고 라이브러리(Meta Ad Library)에서 비슷한 업종/형태의 실제 집행 광고 소재를 찾을 검색 키워드를 각각 만들어야 합니다.

핀터레스트 키워드는 색감·레이아웃·무드 같은 "시각 스타일" 기준으로 만들고, 메타 라이브러리 키워드는 다릅니다. 메타 라이브러리는 광고 카피 텍스트/광고주명/페이지명 기준으로 검색되는 서비스이므로, 시각적 키워드(색감, 무드 등)가 아니라 업종명, 제품/서비스 카테고리, 프로모션 유형(예: 할인, 신규 출시, 이벤트), 브랜드 톤에 맞는 짧은 문구 등 "텍스트로 검색했을 때 실제로 걸릴 법한" 키워드로 만드세요.

다음 JSON 형식으로만 응답하세요:

{
  "summary": "레퍼런스에 대한 한 문장 요약 (한국어, 30자 내외)",
  "attributes": {
    "industry": "업종/카테고리",
    "colorPalette": "주요 색감 설명",
    "layout": "레이아웃 구조 설명",
    "mood": "무드/톤 설명",
    "copyStyle": "카피/타이포그래피 스타일 설명 (텍스트가 있는 경우, 없으면 빈 문자열)"
  },
  "keywords": [
    {"label": "한국어 검색 키워드 (2~5단어)", "angle": "색감"}
  ],
  "metaKeywords": [
    {"label": "한국어 검색 키워드 (2~5단어)", "angle": "업종"}
  ]
}

keywords의 angle 값은 반드시 다음 6개 중 하나만 사용하세요: "색감", "레이아웃", "업종", "무드", "카피 스타일", "구체적 키워드". 각 관점마다 최소 1개씩, 총 6~8개를 만드세요.

keywords는 반드시 "광고 소재" 레퍼런스가 검색되도록, 모든 키워드 끝에 "배너", "광고", "포스터", "상세페이지", "카드뉴스", "SNS 광고" 같은 광고 형식 단어를 하나 붙이세요. "네이비 골드 색감", "미니멀 무드"처럼 형식 단어가 없으면 핀터레스트가 컬러 팔레트·무드보드 같은 추상적인 이미지만 보여줍니다. 좋은 예: "네이비 골드 배너", "미니멀 화장품 광고", "좌측 인물 배치 배너", "명조체 헤드라인 포스터".

metaKeywords의 angle 값은 반드시 다음 3개 중 하나만 사용하세요: "업종", "프로모션 유형", "브랜드 톤". 각 관점마다 최소 1개씩, 총 4~6개를 만드세요. 시각 키워드(색감, 무드 등)는 넣지 마세요.

metaKeywords는 반드시 1~2단어의 명사로만 만드세요. 메타 라이브러리는 검색어의 모든 단어가 광고 문구에 들어 있어야 결과가 나오기 때문에, "신뢰감 있는", "프리미엄", "고급스러운", "감성적인" 같은 꾸밈말이 하나라도 붙으면 결과가 0개가 됩니다. "법률 상담", "수분 세럼", "신제품 할인", "무료배송", "이혼 전문"처럼 실제 광고 카피에 그대로 쓰이는 업종명·제품명·프로모션 문구만 쓰세요. 브랜드 톤 관점도 형용사 대신 그 톤의 광고에 실제로 자주 나오는 단어(예: 신뢰 → "무료 상담", "전문 변호사")로 표현하세요.

모든 키워드(label)는 반드시 한국어로만 작성하세요. 영어 단어를 섞지 마세요. keywords(핀터레스트)는 광고 형식 단어를 포함해 검색창에 넣었을 때 자연스러운 길이(3~5단어)로 만드세요.

이미지가 없고 텍스트 설명만 주어진 경우에도, 그 텍스트를 근거로 같은 방식으로 추론해서 동일한 JSON 형식으로 응답하세요."""


AD_FORMAT_WORDS = ("광고", "배너", "포스터", "상세페이지", "카드뉴스", "전단", "브로슈어", "썸네일", "리플렛", "현수막")
ABSTRACT_WORDS = {"색감", "무드", "느낌", "분위기", "감성", "스타일", "컬러", "팔레트", "톤", "톤앤매너", "디자인", "레이아웃", "구도"}


def ensure_ad_format(label: str) -> str:
    """핀터레스트는 형식 단어가 없으면 팔레트·무드보드 같은 추상 이미지를 보여준다.
    모델이 빠뜨린 경우 "배너 광고"를 붙여 광고 소재가 검색되게 한다."""
    if any(w in label for w in AD_FORMAT_WORDS):
        return label
    # "색감", "무드" 같은 추상어는 팔레트·무드보드를 끌어오므로 빼고 붙인다
    words = [w for w in label.split() if w not in ABSTRACT_WORDS] or label.split()
    return " ".join(words) + " 배너 광고"


def pin_url(label: str) -> str:
    return f"https://www.pinterest.com/search/pins/?q={quote(label)}"


def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "API_KEY_INVALID" in msg or "API key not valid" in msg:
        return "API 키가 올바르지 않아요. Streamlit Secrets에 등록한 GEMINI_API_KEY 값을 다시 확인해주세요."
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        return "요청이 너무 많아요 (무료 한도 초과). 잠시 후 다시 시도해주세요."
    if "UNAVAILABLE" in msg or "503" in msg:
        return "Gemini 서버가 많이 붐벼서 자동으로 3번 다시 시도했지만 응답을 못 받았어요. 1~2분 뒤 다시 눌러주세요."
    if "JSONDecodeError" in e.__class__.__name__:
        return "결과를 제대로 받지 못했어요. 다시 시도해주세요."
    return f"분석 중 문제가 발생했어요: {msg}"


def shorten_meta_label(label: str) -> str:
    """메타 라이브러리는 모든 단어가 광고 문구에 있어야 검색된다.
    모델이 3단어 이상으로 길게 만들면 꾸밈말은 버리고 뒤쪽 2단어(한국어에서
    핵심 명사가 오는 자리)만 남긴다. 예: "신뢰감 있는 법률 상담" → "법률 상담"."""
    words = label.split()
    return " ".join(words[-2:]) if len(words) > 2 else label


def meta_url(label: str) -> str:
    return (
        "https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
        f"&country=KR&media_type=all&search_type=keyword_unordered&q={quote(label)}"
    )


@st.cache_resource
def get_client() -> genai.Client:
    try:
        api_key = st.secrets.get("GEMINI_API_KEY") or ""
    except Exception:
        api_key = ""
    if not api_key:
        st.error(
            "GEMINI_API_KEY가 설정되지 않았어요.\n\n"
            "로컬 실행: `.streamlit/secrets.toml`에 `GEMINI_API_KEY = \"발급받은_키\"`를 추가하세요.\n\n"
            "Streamlit Cloud 배포: App settings → Secrets에 같은 내용을 등록하세요."
        )
        st.stop()
    return genai.Client(api_key=api_key)


_ANGLE_STOPWORDS = {
    "색감", "팔레트", "레이아웃", "구도", "업종", "카테고리", "무드", "감성",
    "카피", "타이포", "카피톤", "카피 스타일", "프로모션", "유형", "브랜드",
    "브랜드 톤", "제품군", "넓은 카테고리", "구체적", "구체적 키워드",
}

PIN_ANGLE_ORDER = ["색감", "레이아웃", "업종", "무드", "카피 스타일", "구체적 키워드"]
META_ANGLE_ORDER = ["업종", "프로모션 유형", "브랜드 톤"]


def group_by_angle(items: list, angle_order: list) -> dict:
    groups: dict[str, list] = {angle: [] for angle in angle_order}
    for kw in items:
        groups.setdefault(kw["angle"], []).append(kw)
    return {angle: kws for angle, kws in groups.items() if kws}


def clean_keyword_list(items: list) -> list:
    """모델이 가끔 하나의 키워드를 label/angle이 따로따로인 조각난 항목(빈 문자열,
    "색감"처럼 관점 단어 자체가 label로 들어온 항목, 한 글자짜리 자모 등)으로
    쪼개서 보낼 때 걸러낸다. label과 angle이 둘 다 정상적으로 채워진 것만 남긴다."""
    cleaned = []
    for kw in items or []:
        if not isinstance(kw, dict):
            continue
        label = (kw.get("label") or "").strip()
        angle = (kw.get("angle") or "").strip()
        if len(label) < 2 or not angle or label in _ANGLE_STOPWORDS:
            continue
        cleaned.append({"label": label, "angle": angle})
    return cleaned


RETRY_WAITS = [3, 6]  # 모든 모델이 붐빔(503)이면 이만큼(초) 쉬었다가 한 바퀴 더 시도


def is_retryable(e: Exception) -> bool:
    msg = str(e)
    return "UNAVAILABLE" in msg or "503" in msg or isinstance(e, json.JSONDecodeError)


def analyze(image_bytes: bytes | None, mime_type: str | None, text_desc: str | None, on_retry=None) -> dict:
    client = get_client()

    parts = []
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"))
        prompt = "이 이미지를 분석해서 지정된 JSON 형식으로 응답해주세요."
        if text_desc:
            prompt += f"\n\n광고주 요청 문구도 함께 참고해서, 이미지와 요청이 겹치는 방향으로 키워드를 만들어주세요:\n{text_desc}"
        parts.append(types.Part.from_text(text=prompt))
    else:
        parts.append(types.Part.from_text(text=f"다음 텍스트 설명을 분석해서 지정된 JSON 형식으로 응답해주세요:\n\n{text_desc}"))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    last_error: Exception | None = None
    for round_no in range(len(RETRY_WAITS) + 1):
        if round_no:
            wait = RETRY_WAITS[round_no - 1]
            if on_retry:
                on_retry(round_no, wait)
            time.sleep(wait)
        for model in MODEL_FALLBACKS:
            try:
                response = client.models.generate_content(model=model, contents=parts, config=config)
                data = json.loads(response.text)
                data["keywords"] = [
                    {**kw, "label": ensure_ad_format(kw["label"])} for kw in clean_keyword_list(data.get("keywords"))
                ]
                meta = clean_keyword_list(data.get("metaKeywords"))
                seen = set()
                data["metaKeywords"] = []
                for kw in meta:
                    kw["label"] = shorten_meta_label(kw["label"])
                    if kw["label"] not in seen:
                        seen.add(kw["label"])
                        data["metaKeywords"].append(kw)
                return data
            except Exception as e:
                last_error = e
                if not is_retryable(e):
                    raise
    raise last_error


# ---------------------------------------------------------------- UI ----

st.set_page_config(page_title="Light Table · 광고 레퍼런스 분석", page_icon="🎞️", layout="wide")

# 디자인 토큰 (spacing: 8 12 16 24 32 48 64 96)
DESIGN_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
:root{
  --bg:#F7F7F3; --card:#FFFFFF; --ink:#111111; --ink-2:#444444; --ink-3:#777777; --line:#E8E7E1;
  --accent:#12997C; --accent-hover:#0E8069; --accent-soft:#E9F6F2;
  --radius-lg:20px; --radius-md:14px; --radius-pill:999px;
  --shadow:0 1px 2px rgba(17,17,17,.04), 0 8px 24px rgba(17,17,17,.04);
  --font:'Pretendard Variable', Pretendard, -apple-system, 'Noto Sans KR', sans-serif;
}

/* ── Streamlit 기본 UI 정리 ─────────────────────── */
.stApp{ background:var(--bg); }
.stApp, .stApp p, .stApp label, .stApp textarea, .stApp input, .stApp button,
.stApp span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded){
  font-family:var(--font) !important;
}
.stApp p{ color:var(--ink-2); }
.stApp p, .stApp h1, .stApp h2, .stApp h3, .lt-card .v, .lt-summary .v{ word-break:keep-all; }
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"]{ display:none !important; }
.block-container{ max-width:1160px !important; padding:120px 40px 96px !important; }
[data-testid="stVerticalBlock"]{ gap:0; }
.stElementContainer{ margin-bottom:0; }
.stApp [data-testid="stMarkdownContainer"]{ margin-bottom:0 !important; }   /* 기본 -1rem 여백 제거 → spacing 토큰대로 */

/* ── Header ─────────────────────────────────────── */
.lt-header{
  position:fixed; top:0; left:0; right:0; height:72px; z-index:999990;
  background:rgba(255,255,255,.92); backdrop-filter:saturate(180%) blur(8px);
  box-shadow:0 1px 0 var(--line);
}
.lt-header .inner{
  max-width:1160px; height:100%; margin:0 auto; padding:0 40px;
  display:flex; align-items:center; justify-content:space-between;
}
.lt-logo{ display:flex; align-items:center; gap:10px; font-size:21px; font-weight:700; color:var(--ink); letter-spacing:-.02em; text-decoration:none !important; }
.lt-logo, .lt-logo:hover{ color:var(--ink) !important; }
.lt-logo .mark{ width:22px; height:22px; border-radius:6px; background:var(--accent); position:relative; }
.lt-logo .mark::after{ content:""; position:absolute; inset:6px; border-radius:2px; background:#fff; opacity:.9; }
.lt-nav{ display:flex; gap:40px; }
.lt-nav a{ font-size:15px; font-weight:500; color:var(--ink-2) !important; text-decoration:none !important; padding:24px 0; border-bottom:2px solid transparent; }
.lt-nav a:hover{ color:var(--ink) !important; }
.lt-nav a.active{ color:var(--ink) !important; font-weight:600; border-bottom-color:var(--accent); }
.lt-cta{
  background:var(--accent); color:#fff !important; text-decoration:none !important;
  font-size:15px; font-weight:600; padding:12px 24px; border-radius:var(--radius-pill); transition:background .2s;
}
.lt-cta:hover{ background:var(--accent-hover); }

/* ── Page header ────────────────────────────────── */
.lt-eyebrow{ font-size:13px; font-weight:700; letter-spacing:.14em; color:var(--accent); text-transform:uppercase; margin-bottom:16px; }
.stApp h1.lt-title{ font-size:42px !important; line-height:1.3; font-weight:700; letter-spacing:-.03em; color:var(--ink); margin:0 0 16px; }
.stApp p.lt-lead{ font-size:17px; line-height:1.7; color:var(--ink-3); margin:0; }

/* ── Stepper ────────────────────────────────────── */
.lt-steps{ display:flex; gap:8px; margin:48px 0 32px; padding:0; list-style:none; }
.lt-steps li{
  flex:1; word-break:keep-all; display:flex; align-items:center; gap:12px; padding:14px 16px;
  border-radius:var(--radius-md); background:transparent; color:var(--ink-3); font-size:15px; font-weight:500;
}
.lt-steps .n{
  width:28px; height:28px; border-radius:50%; flex:none; display:grid; place-items:center;
  font-size:13px; font-weight:700; border:1.5px solid #D4D3CC; color:var(--ink-3);
}
.lt-steps li.done .n{ background:var(--ink); border-color:var(--ink); color:#fff; }
.lt-steps li.done{ color:var(--ink-2); }
.lt-steps li.current{ background:var(--card); color:var(--ink); font-weight:600; box-shadow:var(--shadow); }
.lt-steps li.current .n{ background:var(--accent); border-color:var(--accent); color:#fff; }

/* ── Section title ──────────────────────────────── */
.lt-section{ display:flex; align-items:flex-end; justify-content:space-between; margin:0 0 24px; }
.stApp .lt-section h2{ font-size:28px !important; font-weight:700; letter-spacing:-.02em; color:var(--ink); margin:0; padding:0; }
.lt-section .cap{ font-size:14px; color:var(--ink-3); }
.lt-label{ font-size:13px; font-weight:700; letter-spacing:.1em; color:var(--ink-3); text-transform:uppercase; margin:0 0 12px; }

/* ── Input card (st.container(border=True, key="input_card")) ── */
.st-key-input_card, .st-key-history_card{
  background:var(--card); border:none !important; border-radius:var(--radius-lg) !important;
  box-shadow:var(--shadow); padding:40px !important;
}
.st-key-input_card [data-testid="stVerticalBlock"]{ gap:0; }

/* Analysis mode: radio → 기능 카드 */
.st-key-mode{ width:100% !important; }
.st-key-mode [role="radiogroup"]{ display:grid !important; grid-template-columns:1fr 1fr; gap:16px; }
.st-key-mode [role="radiogroup"] > div{
  position:relative; padding:24px 28px; border:1.5px solid var(--line); border-radius:var(--radius-md);
  background:var(--card); cursor:pointer; transition:all .2s;
}
.st-key-mode [role="radiogroup"] > div:hover{ border-color:#CFCEC6; }
.st-key-mode [role="radiogroup"] > div[data-selected="true"]{ border-color:var(--accent); background:var(--accent-soft); }
.st-key-mode [role="radiogroup"] > div[data-selected="true"]::after{
  content:"✓"; position:absolute; top:22px; right:24px; width:24px; height:24px; border-radius:50%;
  background:var(--accent); color:#fff; font-size:13px; font-weight:700; display:grid; place-items:center;
}
.st-key-mode [data-testid="stRadioOption"]{ cursor:pointer; }
.st-key-mode [data-testid="stRadioOption"]::after{ content:""; position:absolute; inset:0; }   /* 카드 전체를 클릭 영역으로 */
.st-key-mode [data-testid="stRadioOption"] > div > div:first-child{ display:none; }            /* 기본 라디오 동그라미 숨김 */
.st-key-mode [data-testid="stRadioOption"] p{ font-size:19px !important; font-weight:700; color:var(--ink) !important; margin:0; }
.st-key-mode [data-selected="true"] [data-testid="stRadioOption"] p{ color:var(--accent-hover) !important; }
.st-key-mode [data-testid="stRadioCaption"]{ padding:0 !important; margin-top:8px; }
.st-key-mode [data-testid="stRadioCaption"] p{ font-size:15px !important; color:var(--ink-3) !important; line-height:1.6; margin:0; }

/* 입력 라벨 */
.st-key-input_card [data-testid="stWidgetLabel"] p{ font-size:15px !important; font-weight:600; color:var(--ink) !important; }

/* Upload card */
[data-testid="stFileUploader"] section,
[data-testid="stFileUploaderDropzone"]{
  min-height:260px; display:flex !important; flex-direction:column !important; align-items:center !important; justify-content:center !important;
  gap:16px; padding:40px 24px !important; background:#FBFBF9 !important;
  border:1.5px dashed #D4D3CC !important; border-radius:var(--radius-md) !important; transition:all .2s; text-align:center;
}
[data-testid="stFileUploaderDropzone"]:hover{ border-color:var(--accent) !important; background:var(--accent-soft) !important; }
[data-testid="stFileUploaderDropzone"]::before{
  content:"↑"; width:56px; height:56px; border-radius:50%; display:grid; place-items:center;
  background:var(--card); box-shadow:var(--shadow); color:var(--accent); font-size:24px; font-weight:700;
}
[data-testid="stFileUploaderDropzoneInstructions"]{ display:flex; flex-direction:column; align-items:center; gap:4px; order:1; }
[data-testid="stFileUploaderDropzone"] > span{ order:2; }   /* 안내 문구 → 파일 선택 버튼 순서 */
[data-testid="stFileUploaderDropzoneInstructions"]::before{
  content:"광고 레퍼런스를 여기로 끌어다 놓으세요"; font-size:18px; font-weight:700; color:var(--ink);
}
[data-testid="stFileUploaderDropzoneInstructions"] span, [data-testid="stFileUploaderDropzoneInstructions"] small{
  font-size:14px !important; color:var(--ink-3) !important;
}
[data-testid="stFileUploaderDropzone"] > span > svg, [data-testid="stFileUploaderDropzoneInstructions"] svg{ display:none; }
[data-testid="stFileUploaderDropzone"] > span button{
  background:var(--card) !important; color:var(--ink) !important; border:1px solid #D4D3CC !important;
  border-radius:var(--radius-pill) !important; padding:10px 22px !important; font-weight:600;
}
[data-testid="stImage"] img{ border-radius:var(--radius-md); max-height:420px; object-fit:contain; background:#F1F1EC; }

/* Text area */
[data-testid="stTextAreaRootElement"]{ border:1.5px solid var(--line) !important; border-radius:var(--radius-md) !important; background:#FBFBF9 !important; transition:all .2s; }
[data-testid="stTextAreaRootElement"]:hover{ border-color:#CFCEC6 !important; }
[data-testid="stTextAreaRootElement"]:focus-within{ border-color:var(--accent) !important; background:#fff !important; box-shadow:0 0 0 4px var(--accent-soft); }
.stTextArea textarea{ font-size:16px !important; line-height:1.7 !important; padding:16px !important; color:var(--ink) !important; background:transparent !important; }
.stTextArea textarea::placeholder{ color:#A5A49D; }

/* Upload 완료 상태: 드롭존을 한 줄로 줄이고 파일 정보만 강조 */
[data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChip"]){
  min-height:0; flex-direction:row !important; padding:16px 20px !important; border-style:solid !important;
  border-color:var(--accent) !important; background:var(--accent-soft) !important; justify-content:flex-start !important;
}
[data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChip"])::before{ content:"✓"; width:36px; height:36px; font-size:16px; background:var(--accent); color:#fff; box-shadow:none; }
[data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChip"]) [data-testid="stFileUploaderDropzoneInstructions"]{ display:none; }
[data-testid="stFileUploaderDropzone"] button[aria-label="Add files"]{ display:none; }   /* 1장만 받으므로 + 버튼 숨김 */
[data-testid="stFileChip"]{ background:transparent !important; border:none !important; }
[data-testid="stFileChipName"]{ font-size:15px !important; font-weight:600; color:var(--ink) !important; }

/* Primary CTA */
.st-key-analyze, .st-key-analyze_text{ width:100% !important; }
.st-key-analyze .stButton, .st-key-analyze_text .stButton{ width:100%; }
.st-key-analyze button, .st-key-analyze_text button{
  width:100%; height:60px; border-radius:var(--radius-md) !important; border:none !important;
  background:var(--accent) !important; transition:all .2s; box-shadow:0 6px 16px rgba(18,153,124,.22);
}
.st-key-analyze button p, .st-key-analyze_text button p{ color:#fff !important; font-size:17px !important; font-weight:700; letter-spacing:-.01em; }
.st-key-analyze button:hover, .st-key-analyze_text button:hover{ background:var(--accent-hover) !important; transform:translateY(-1px); }
.st-key-analyze button:active, .st-key-analyze_text button:active{ transform:translateY(0); box-shadow:none; }
.st-key-analyze button:disabled{ background:#E3E2DC !important; box-shadow:none; transform:none; cursor:not-allowed; }
.st-key-analyze button:disabled p{ color:#9A9992 !important; }

/* Alerts */
[data-testid="stAlert"] > div{ border-radius:var(--radius-md) !important; border:none !important; }
[data-testid="stAlertContentError"], [data-testid="stAlertContentWarning"]{ font-size:15px; }

/* Loading */
.lt-loading{ background:var(--card); border-radius:var(--radius-lg); box-shadow:var(--shadow); padding:32px 40px; }
.stApp .lt-loading h3{ font-size:20px !important; font-weight:700; color:var(--ink); margin:0 0 20px; padding:0; }
.lt-loading ul{ list-style:none; padding:0; margin:0; display:grid; gap:14px; }
.lt-loading li{ display:flex; align-items:center; gap:12px; font-size:16px; color:var(--ink-3); }
.lt-loading li .dot{ width:22px; height:22px; border-radius:50%; border:1.5px solid #D4D3CC; flex:none; display:grid; place-items:center; font-size:12px; }
.lt-loading li.done{ color:var(--ink-2); }
.lt-loading li.done .dot{ background:var(--ink); border-color:var(--ink); color:#fff; }
.lt-loading li.active{ color:var(--ink); font-weight:600; }
.lt-loading li.active .dot{ border-color:var(--accent); border-top-color:transparent; animation:lt-spin .9s linear infinite; }
@keyframes lt-spin{ to{ transform:rotate(360deg); } }

/* ── Result ─────────────────────────────────────── */
.lt-summary{
  background:var(--ink); color:#fff; border-radius:var(--radius-lg); padding:40px; margin-bottom:16px;
  display:flex; flex-direction:column; gap:12px;
}
.lt-summary .k{ font-size:13px; font-weight:700; letter-spacing:.14em; color:#7FD4BF; text-transform:uppercase; }
.lt-summary .v{ font-size:30px; line-height:1.4; font-weight:700; letter-spacing:-.02em; color:#fff; }
.lt-grid{ display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; }
.lt-card{ background:var(--card); border-radius:var(--radius-md); box-shadow:var(--shadow); padding:24px; }
.lt-card.wide{ grid-column:1 / -1; }
.lt-card .k{ font-size:13px; font-weight:700; letter-spacing:.08em; color:var(--ink-3); text-transform:uppercase; margin-bottom:10px; }
.lt-card .v{ font-size:17px; line-height:1.6; font-weight:600; color:var(--ink); }

.lt-kw-grid{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.lt-kw-card{ background:var(--card); border-radius:var(--radius-lg); box-shadow:var(--shadow); padding:32px; display:flex; flex-direction:column; }
.lt-kw-head{ display:flex; align-items:center; gap:12px; margin-bottom:8px; }
.lt-kw-head .badge{ width:36px; height:36px; border-radius:10px; display:grid; place-items:center; font-weight:800; font-size:16px; color:#fff; }
.lt-kw-head .badge.pin{ background:#E60023; } .lt-kw-head .badge.meta{ background:#0866FF; }
.stApp .lt-kw-head h3{ font-size:20px !important; font-weight:700; color:var(--ink); margin:0; padding:0; }
.stApp p.lt-kw-desc{ font-size:14px; line-height:1.6; color:var(--ink-3); margin:0 0 20px; }
.lt-group{ margin-bottom:16px; }
.lt-group .g{ font-size:13px; font-weight:600; color:var(--ink-3); margin-bottom:8px; }
.lt-chips{ display:flex; flex-wrap:wrap; gap:10px; }
a.lt-chip .ang{ font-size:12px; font-weight:600; color:var(--ink-3); padding-right:8px; border-right:1px solid #DAD9D2; }
a.lt-chip:hover .ang{ color:var(--accent-hover); border-color:#B9E2D7; }
a.lt-chip{
  display:inline-flex; align-items:center; gap:8px; padding:10px 16px; border-radius:var(--radius-pill);
  background:#F3F3EF; color:var(--ink) !important; text-decoration:none !important;
  font-size:15px; font-weight:500; transition:all .15s; border:1px solid transparent;
}
a.lt-chip .arr{ color:var(--ink-3); font-size:13px; }
a.lt-chip:hover{ background:var(--accent-soft); border-color:var(--accent); color:var(--accent-hover) !important; }
a.lt-chip:hover .arr{ color:var(--accent); }
.lt-chip-pair{ display:inline-flex; align-items:center; gap:4px; }
a.lt-chip-broad{
  padding:10px 12px; border-radius:var(--radius-pill); font-size:13px; font-weight:500;
  color:var(--ink-3) !important; text-decoration:none !important; border:1px dashed #D4D3CC; transition:all .15s;
}
a.lt-chip-broad:hover{ color:var(--accent-hover) !important; border-color:var(--accent); border-style:solid; }

/* 전체 복사 (st.code) */
.st-key-copy_all [data-testid="stCode"] pre{ background:var(--card) !important; border-radius:var(--radius-md); box-shadow:var(--shadow); padding:20px 24px !important; }
.st-key-copy_all code{ font-family:var(--font) !important; font-size:15px !important; color:var(--ink-2) !important; white-space:pre-wrap !important; }

/* History */
.st-key-history_card .stButton button{
  width:100%; justify-content:flex-start; text-align:left; background:#FBFBF9; border:1px solid var(--line);
  border-radius:var(--radius-md); padding:14px 18px; min-height:0;
}
.st-key-history_card .stButton button p{ font-size:15px !important; color:var(--ink) !important; }
.st-key-history_card .stButton button:hover{ border-color:var(--accent); background:var(--accent-soft); }
.stApp p.lt-empty{ font-size:15px; color:var(--ink-3); margin:0; }

/* Footer */
.lt-footer{ margin-top:96px; padding-top:32px; border-top:1px solid var(--line); display:flex; justify-content:space-between; gap:24px; }
.lt-footer p{ font-size:13px !important; color:var(--ink-3) !important; line-height:1.7; margin:0; }

.lt-gap-64{ height:64px; } .lt-gap-32{ height:32px; } .lt-gap-24{ height:24px; } .lt-gap-16{ height:16px; }
.lt-anchor{ position:relative; top:-96px; }

/* ── Responsive ─────────────────────────────────── */
@media (max-width:1024px){
  .lt-grid{ grid-template-columns:1fr 1fr; }
  .lt-kw-grid{ grid-template-columns:1fr; }
  .lt-nav{ gap:24px; }
}
@media (max-width:720px){
  .block-container{ padding:96px 16px 64px !important; }
  .lt-header .inner{ padding:0 16px; }
  .lt-header{ height:60px; }
  .lt-nav{ display:none; }
  .lt-cta{ padding:10px 18px; font-size:14px; }
  .stApp h1.lt-title{ font-size:30px !important; }
  .stApp p.lt-lead{ font-size:16px; }
  .lt-steps{ margin:32px 0 24px; gap:4px; }
  .lt-steps li{ flex-direction:column; gap:6px; padding:10px 4px; font-size:12px; text-align:center; }
  .st-key-input_card, .st-key-history_card{ padding:24px !important; }
  .st-key-mode [role="radiogroup"]{ grid-template-columns:1fr; }
  .lt-grid{ grid-template-columns:1fr; }
  .lt-summary{ padding:28px; } .lt-summary .v{ font-size:24px; }
  .lt-kw-card{ padding:24px; }
  .lt-footer{ flex-direction:column; }
}
</style>
"""

MODE_IMAGE = "이미지 분석"
MODE_TEXT = "텍스트 분석"
STEPS = ["레퍼런스 입력", "AI 분석", "결과 확인", "레퍼런스 검색"]


# ── Components ───────────────────────────────────────────────────────────

def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def gap(size: int) -> None:
    html_block(f'<div class="lt-gap-{size}"></div>')


def Header(active: str) -> None:
    items = [("analyze", "레퍼런스 분석"), ("result", "분석 결과"), ("history", "분석 기록")]
    nav = "".join(
        f'<a href="#{anchor}" class="{"active" if anchor == active else ""}">{label}</a>'
        for anchor, label in items
    )
    html_block(
        '<div class="lt-header"><div class="inner">'
        '<a class="lt-logo" href="#analyze"><span class="mark"></span>Light Table</a>'
        f'<nav class="lt-nav">{nav}</nav>'
        '<a class="lt-cta" href="#analyze">분석 시작하기</a>'
        "</div></div>"
    )


def PageHeader() -> None:
    html_block(
        '<div class="lt-anchor" id="analyze"></div>'
        '<div class="lt-eyebrow">Ad Reference Light Table</div>'
        '<h1 class="lt-title">레퍼런스 광고를 분석하고<br>다음 소재의 방향을 찾아보세요</h1>'
        '<p class="lt-lead">이미지나 광고주 요청 문구에서 업종·색감·레이아웃·무드·카피 톤을 읽어내고, '
        "핀터레스트와 메타 광고 라이브러리에서 바로 쓸 수 있는 검색어로 정리합니다.</p>"
    )


def Stepper(current: int) -> None:
    """current: 0부터 시작하는 현재 단계 번호"""
    items = []
    for i, label in enumerate(STEPS):
        state = "done" if i < current else "current" if i == current else ""
        mark = "✓" if i < current else str(i + 1)
        items.append(f'<li class="{state}"><span class="n">{mark}</span>{label}</li>')
    html_block(f'<ol class="lt-steps">{"".join(items)}</ol>')


def LoadingState(slot, retry_note: str = "") -> None:
    note = f'<li class="active"><span class="dot"></span>{retry_note}</li>' if retry_note else ""
    slot.markdown(
        '<div class="lt-loading"><h3>레퍼런스를 분석하고 있어요</h3><ul>'
        '<li class="done"><span class="dot">✓</span>레퍼런스 확인</li>'
        f'{note}'
        '<li class="active"><span class="dot"></span>디자인 요소 분석 · 검색 키워드 생성 중</li>'
        '<li><span class="dot"></span>결과 정리</li>'
        "</ul></div>",
        unsafe_allow_html=True,
    )


def SectionTitle(title: str, caption: str = "", anchor: str = "") -> None:
    anchor_html = f'<div class="lt-anchor" id="{anchor}"></div>' if anchor else ""
    html_block(f'{anchor_html}<div class="lt-section"><h2>{title}</h2><span class="cap">{caption}</span></div>')


def ResultCard(label: str, value: str, wide: bool = False) -> str:
    return (
        f'<div class="lt-card{" wide" if wide else ""}"><div class="k">{label}</div>'
        f'<div class="v">{html.escape(value)}</div></div>'
    )


def AnalysisResult(result: dict) -> None:
    attrs = result.get("attributes", {})
    cards = [
        ResultCard("업종", attrs.get("industry", "")),
        ResultCard("무드", attrs.get("mood", "")),
        ResultCard("컬러", attrs.get("colorPalette", "")),
        ResultCard("레이아웃", attrs.get("layout", "")),
    ]
    if attrs.get("copyStyle"):
        cards.append(ResultCard("카피 · 타이포", attrs["copyStyle"], wide=True))
    html_block(
        '<div class="lt-summary"><span class="k">Analysis Summary</span>'
        f'<span class="v">{html.escape(result.get("summary", ""))}</span></div>'
        f'<div class="lt-grid">{"".join(cards)}</div>'
    )


def KeywordChip(label: str, url: str, angle: str, broad: tuple[str, str] | None = None) -> str:
    chip = (
        f'<a class="lt-chip" href="{html.escape(url)}" target="_blank" rel="noopener">'
        f'<span class="ang">{html.escape(angle)}</span>{html.escape(label)}<span class="arr">↗</span></a>'
    )
    if not broad:
        return chip
    word, broad_url = broad
    return (
        f'<span class="lt-chip-pair">{chip}'
        f'<a class="lt-chip-broad" href="{html.escape(broad_url)}" target="_blank" rel="noopener" '
        f'title="결과가 없으면 \'{html.escape(word)}\' 한 단어로 넓게 검색">넓게 · {html.escape(word)}</a></span>'
    )


def SearchCTA(kind: str, title: str, desc: str, groups: dict, url_fn) -> str:
    def broad_for(label: str):
        # 메타는 모든 단어가 광고 문구에 있어야 검색되므로, 2단어 이상이면
        # 핵심 명사(마지막 단어) 하나로 넓게 찾는 링크를 함께 제공
        words = label.split()
        return (words[-1], url_fn(words[-1])) if kind == "meta" and len(words) > 1 else None

    chips = "".join(
        KeywordChip(kw["label"], url_fn(kw["label"]), angle, broad_for(kw["label"]))
        for angle, kws in groups.items() for kw in kws
    )
    badge = "P" if kind == "pin" else "M"
    return (
        f'<div class="lt-kw-card"><div class="lt-kw-head"><span class="badge {kind}">{badge}</span><h3>{title}</h3></div>'
        f'<p class="lt-kw-desc">{desc}</p><div class="lt-chips">{chips}</div></div>'
    )


def SearchKeywords(result: dict) -> None:
    pin_groups = group_by_angle(result.get("keywords", []), PIN_ANGLE_ORDER)
    meta_groups = group_by_angle(result.get("metaKeywords", []), META_ANGLE_ORDER)
    html_block(
        '<div class="lt-kw-grid">'
        + SearchCTA("pin", "Pinterest에서 검색", "색감·레이아웃·무드 같은 시각 스타일 기준 검색어입니다. 누르면 새 탭에서 검색 결과가 열립니다.", pin_groups, pin_url)
        + SearchCTA("meta", "Meta 광고 라이브러리에서 검색", "실제 광고 문구에 쓰이는 업종·프로모션 단어입니다. 국내 집행 광고 기준이며, 결과가 없으면 옆의 '넓게' 버튼으로 핵심 단어만 검색하세요.", meta_groups, meta_url)
        + "</div>"
    )
    all_labels = [kw["label"] for kw in result.get("keywords", [])] + [kw["label"] for kw in result.get("metaKeywords", [])]
    if all_labels:
        gap(24)
        html_block('<div class="lt-label">키워드 전체 복사 — 오른쪽 위 아이콘을 누르세요</div>')
        with st.container(key="copy_all"):
            st.code(", ".join(all_labels), language=None)


def Footer() -> None:
    html_block(
        '<div class="lt-footer">'
        "<p><strong>Light Table</strong> · 광고 레퍼런스 분석</p>"
        "<p>핀터레스트·메타 광고 라이브러리의 자동 크롤링과 이미지 자동 수집은 이용약관상 금지되어 있습니다.<br>"
        "검색 결과의 이미지 확인과 저장은 직접 진행해 주세요. 분석에는 Google Gemini가 사용됩니다.</p>"
        "</div>"
    )


# ── State ────────────────────────────────────────────────────────────────

st.session_state.setdefault("history", [])


def run_analysis(image_bytes, mime_type, text_desc) -> None:
    gap(16)
    slot = st.empty()
    LoadingState(slot)

    def on_retry(round_no: int, wait: int) -> None:
        LoadingState(slot, f"Gemini 서버가 붐벼서 {wait}초 뒤 다시 시도하는 중 ({round_no}/{len(RETRY_WAITS)})")

    try:
        data = analyze(image_bytes, mime_type, text_desc, on_retry=on_retry)
    except Exception as e:
        slot.empty()
        st.session_state["error"] = friendly_error(e)
        return
    slot.empty()
    st.session_state.pop("error", None)
    st.session_state["result"] = data
    st.session_state["history"] = ([data] + st.session_state["history"])[:5]
    st.rerun()


# ── Page ─────────────────────────────────────────────────────────────────

html_block(DESIGN_CSS)

result = st.session_state.get("result")
Header("analyze")
PageHeader()

mode = st.session_state.get("mode", MODE_IMAGE)
file = st.session_state.get("upload")
has_input = bool(file) if mode == MODE_IMAGE else bool((st.session_state.get("brief_text") or "").strip())
Stepper(3 if result else 1 if has_input else 0)

with st.container(border=True, key="input_card"):
    html_block('<div class="lt-label">분석 방식</div>')
    mode = st.radio(
        "분석 방식",
        [MODE_IMAGE, MODE_TEXT],
        captions=["광고 이미지에서 색감·레이아웃·무드 등 디자인 요소를 분석합니다", "광고주 요청 문구만으로 톤앤매너와 검색 키워드를 뽑습니다"],
        key="mode",
        label_visibility="collapsed",
    )
    gap(32)

    if mode == MODE_IMAGE:
        file = st.file_uploader(
            "레퍼런스 이미지", type=["jpg", "jpeg", "png", "webp"], key="upload", label_visibility="collapsed"
        )
        if file:
            gap(16)
            st.image(file.getvalue(), width="stretch")
        gap(24)
        extra = st.text_area(
            "광고주 요청 문구 (선택)",
            placeholder="예: 고급스럽고 신뢰감 있게, 20대 여성 타겟 — 함께 적으면 이미지와 요청이 겹치는 방향으로 키워드를 만듭니다",
            key="image_extra",
            height=100,
        )
        gap(24)
        if st.button("레퍼런스 분석하기  →", key="analyze", disabled=not file):
            run_analysis(file.getvalue(), file.type, extra.strip() or None)
    else:
        desc = st.text_area(
            "광고주 요청 문구",
            placeholder="예: 법무법인 광고, 신뢰감 있고 깔끔하게",
            key="brief_text",
            height=160,
        )
        gap(24)
        if st.button("레퍼런스 분석하기  →", key="analyze_text"):
            if not desc.strip():
                st.session_state["error"] = "광고주 요청 문구를 입력해 주세요."
            else:
                run_analysis(None, None, desc)

    if st.session_state.get("error"):
        gap(16)
        st.error(st.session_state["error"])

if result:
    gap(64)
    SectionTitle("분석 결과", "레퍼런스에서 읽어낸 디자인 요소", anchor="result")
    AnalysisResult(result)
    gap(64)
    SectionTitle("검색 키워드", "키워드를 누르면 새 탭에서 검색 결과가 열립니다")
    SearchKeywords(result)

gap(64)
SectionTitle("분석 기록", "이번 접속에서 분석한 최근 5건", anchor="history")
with st.container(border=True, key="history_card"):
    history = st.session_state["history"]
    if not history:
        html_block('<p class="lt-empty">아직 분석 기록이 없어요. 첫 레퍼런스를 분석하면 여기에 쌓입니다.</p>')
    for i, item in enumerate(history):
        label = item.get("summary") or f"분석 {i + 1}"
        current = " · 현재 보는 결과" if item is result else ""
        if st.button(f"{label}{current}", key=f"history_{i}"):
            st.session_state["result"] = item
            st.rerun()

Footer()
