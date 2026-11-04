"""두 파트(레퍼런스 키워드 · 카피 기획)를 오가는 상단 탭. 두 화면이 같이 쓴다.

st.page_link로 이동해서 세션(비밀번호 통과, 입력 내용, 파트 1 → 2 넘김)이 유지된다.
"""
import streamlit as st

TOOLS = [
    ("keyword", "app.py", "레퍼런스 키워드"),
    ("copy", "pages/2_카피_기획.py", "카피 기획"),
]

CSS = """
<style>
.st-key-tool_nav{ display:flex !important; flex-direction:row !important; gap:8px; padding:6px; margin:0 0 40px;
  background:#EDEDE7; border-radius:16px; }
[class*="st-key-tool_nav_"]{ flex:1; min-width:0; }
[class*="st-key-tool_nav_"] .stElementContainer, [class*="st-key-tool_nav_"] .stPageLink,
[class*="st-key-tool_nav_"] .stPageLink > div, [class*="st-key-tool_nav_"] .stPageLink > div > div{ width:100% !important; }
[class*="st-key-tool_nav_"] a{ display:flex !important; flex-direction:column; align-items:flex-start; gap:2px; width:100%;
  padding:12px 18px !important; border-radius:12px !important; text-decoration:none !important; transition:background .15s; }
[class*="st-key-tool_nav_"] a:hover{ background:rgba(255,255,255,.6) !important; }
[class*="st-key-tool_nav_"] a p{ font-size:16px !important; font-weight:700 !important; color:var(--ink-3) !important; margin:0; }
[class*="st-key-tool_nav_"][class*="_on"] a{ background:#fff !important; box-shadow:0 1px 2px rgba(17,17,17,.06), 0 4px 12px rgba(17,17,17,.06); }
[class*="st-key-tool_nav_"][class*="_on"] a p{ color:var(--ink) !important; }
[class*="st-key-tool_nav_"][class*="_on"] a p::before{ content:""; display:inline-block; width:8px; height:8px; border-radius:50%;
  background:var(--accent); margin-right:8px; vertical-align:middle; }
@media (max-width:720px){
  .st-key-tool_nav{ margin-bottom:28px; } [class*="st-key-tool_nav_"] a{ padding:10px 12px !important; }
  [class*="st-key-tool_nav_"] a p{ font-size:14px !important; }
}
</style>
"""


def tool_nav(active: str) -> None:
    """active: "keyword" 또는 "copy" """
    st.markdown(CSS, unsafe_allow_html=True)
    with st.container(key="tool_nav"):
        for key, page, label in TOOLS:
            with st.container(key=f"tool_nav_{key}_{'on' if key == active else 'off'}"):
                st.page_link(page, label=label)
