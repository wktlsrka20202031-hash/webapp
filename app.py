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

import json
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import types

MODEL = "gemini-3.6-flash"

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
    {"label": "키워드(한국어 또는 영어, 검색에 최적화된 형태)", "angle": "이 키워드가 어떤 관점을 겨냥하는지 5-10자 라벨 (예: 색감, 레이아웃, 업종, 무드, 카피톤)"}
  ],
  "metaKeywords": [
    {"label": "메타 라이브러리 검색에 적합한 텍스트 키워드", "angle": "이 키워드가 겨냥하는 관점 5-10자 라벨 (예: 업종, 제품군, 프로모션 유형, 브랜드 톤)"}
  ]
}

keywords는 반드시 6~8개를 만들고, 다음 관점을 최소 하나씩 포함하세요: (1) 색감/팔레트, (2) 레이아웃/구도, (3) 업종/카테고리, (4) 무드/감성, (5) 카피/타이포 스타일, (6) 더 넓은 카테고리 키워드 1개, (7) 더 좁고 구체적인 키워드 1개. 한국어와 영어 키워드를 섞어서 만드세요. 검색창에 넣었을 때 자연스러운 길이(2~5단어)로 만드세요.

metaKeywords는 4~6개를 만들고, 업종/제품군, 프로모션 유형, 브랜드 톤 관점을 최소 하나씩 포함하세요. 시각 키워드(색감, 무드 등)는 넣지 마세요.

이미지가 없고 텍스트 설명만 주어진 경우에도, 그 텍스트를 근거로 같은 방식으로 추론해서 동일한 JSON 형식으로 응답하세요."""


def pin_url(label: str) -> str:
    return f"https://www.pinterest.com/search/pins/?q={quote(label)}"


def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "API_KEY_INVALID" in msg or "API key not valid" in msg:
        return "API 키가 올바르지 않아요. Streamlit Secrets에 등록한 GEMINI_API_KEY 값을 다시 확인해주세요."
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        return "요청이 너무 많아요 (무료 한도 초과). 잠시 후 다시 시도해주세요."
    if "UNAVAILABLE" in msg or "503" in msg:
        return "지금 Gemini 서버에 요청이 몰려서 잠깐 응답을 못 받았어요. 30초~1분 후 다시 시도해주세요."
    if "JSONDecodeError" in e.__class__.__name__:
        return "결과를 제대로 받지 못했어요. 다시 시도해주세요."
    return f"분석 중 문제가 발생했어요: {msg}"


def meta_url(label: str) -> str:
    return (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
        f"&country=ALL&media_type=all&search_type=keyword_unordered&q={quote(label)}"
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


def analyze(image_bytes: bytes | None, mime_type: str | None, text_desc: str | None) -> dict:
    client = get_client()

    parts = []
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"))
        parts.append(types.Part.from_text(text="이 이미지를 분석해서 지정된 JSON 형식으로 응답해주세요."))
    else:
        parts.append(types.Part.from_text(text=f"다음 텍스트 설명을 분석해서 지정된 JSON 형식으로 응답해주세요:\n\n{text_desc}"))

    response = client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return json.loads(response.text)


# ---------------------------------------------------------------- UI ----

st.set_page_config(page_title="레퍼런스 라이트테이블", page_icon="🎞️", layout="centered")

PALETTE_CSS = """
<style>
:root{
  --paper:#F1F0E9; --ink:#191C1A; --ink-dim:#5B6058; --line:#DBD7C8;
  --brand:#1F5D4C; --pin:#C6501C; --meta:#2F4FA0;
}
.stApp{ background:var(--paper); }
h1, h2, h3 { color:var(--ink); }
.eyebrow{
  font-weight:700; font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--brand); margin-bottom:2px;
}
.kw-card{
  display:flex; justify-content:space-between; align-items:center; gap:10px;
  background:#fff; border:1px solid var(--line); border-left:4px solid var(--pin);
  border-radius:10px; padding:11px 14px; margin-bottom:8px; text-decoration:none; color:var(--ink) !important;
}
.kw-card.meta{ border-left-color:var(--meta); }
.kw-card .label{ font-weight:700; font-size:14px; }
.kw-card .angle{ font-size:11px; color:var(--ink-dim); }
.attr-box{
  background:#fff; border:1px solid var(--line); border-radius:9px; padding:10px 12px; margin-bottom:8px;
}
.attr-box .k{ font-size:11px; font-weight:700; color:var(--brand); text-transform:uppercase; letter-spacing:.04em; }
.attr-box .v{ font-size:13.5px; color:var(--ink); margin-top:2px; }
</style>
"""
st.markdown(PALETTE_CSS, unsafe_allow_html=True)

st.markdown('<div class="eyebrow">Ad Reference Light Table</div>', unsafe_allow_html=True)
st.title("레퍼런스 라이트테이블")
st.write("광고 레퍼런스 이미지를 올리면 업종·색감·레이아웃·무드·카피 톤을 분석해서, 핀터레스트와 메타 광고 라이브러리에서 바로 열리는 검색 키워드로 정리해 드립니다.")

tab_image, tab_text = st.tabs(["이미지로 분석", "텍스트로 분석"])

result = None
uploaded_image_bytes = None

with tab_image:
    file = st.file_uploader("레퍼런스 이미지 업로드", type=["jpg", "jpeg", "png", "webp"])
    if file:
        uploaded_image_bytes = file.getvalue()
        st.image(uploaded_image_bytes, use_container_width=True)
        if st.button("이미지 분석하기", type="primary", key="analyze_image"):
            with st.spinner("분석 중이에요..."):
                try:
                    result = analyze(uploaded_image_bytes, file.type, None)
                except Exception as e:
                    st.error(friendly_error(e))

with tab_text:
    desc = st.text_area("레퍼런스 설명", placeholder="예: 법무법인 광고, 신뢰감 있고 깔끔하게")
    if st.button("텍스트로 분석하기", type="primary", key="analyze_text"):
        if not desc.strip():
            st.warning("설명을 입력해주세요.")
        else:
            with st.spinner("분석 중이에요..."):
                try:
                    result = analyze(None, None, desc)
                except Exception as e:
                    st.error(friendly_error(e))

if result:
    st.divider()
    attrs = result.get("attributes", {})
    st.subheader(result.get("summary", ""))

    col1, col2 = st.columns(2)
    labels = [("업종", "industry"), ("색감", "colorPalette"), ("레이아웃", "layout"), ("무드", "mood")]
    for i, (label, key) in enumerate(labels):
        target = col1 if i % 2 == 0 else col2
        target.markdown(
            f'<div class="attr-box"><div class="k">{label}</div><div class="v">{attrs.get(key, "")}</div></div>',
            unsafe_allow_html=True,
        )
    if attrs.get("copyStyle"):
        st.markdown(
            f'<div class="attr-box"><div class="k">카피 스타일</div><div class="v">{attrs["copyStyle"]}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("### 📌 핀터레스트 검색 키워드")
    for kw in result.get("keywords", []):
        label = kw.get("label", "")
        angle = kw.get("angle", "")
        st.markdown(
            f'<a class="kw-card" href="{pin_url(label)}" target="_blank">'
            f'<div><div class="label">{label}</div><div class="angle">{angle}</div></div>'
            f'<div>↗</div></a>',
            unsafe_allow_html=True,
        )

    st.markdown("### 📘 메타 라이브러리 검색 키워드")
    for kw in result.get("metaKeywords", []):
        label = kw.get("label", "")
        angle = kw.get("angle", "")
        st.markdown(
            f'<a class="kw-card meta" href="{meta_url(label)}" target="_blank">'
            f'<div><div class="label">{label}</div><div class="angle">{angle}</div></div>'
            f'<div>↗</div></a>',
            unsafe_allow_html=True,
        )

    st.caption("핀터레스트/메타 라이브러리 모두 자동 크롤링·이미지 자동 수집은 이용약관상 금지되어 있습니다. 위 링크로 검색 결과를 열어 실제 이미지 확인/저장은 직접 진행해 주세요.")
