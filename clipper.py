"""'상세페이지 가져오기' 북마크 버튼 — 클릭 한 번으로 카피 기획 화면에 자료를 넘긴다.

쿠팡·스마트스토어처럼 서버에서 자동으로 못 읽는 사이트용이다. 사용자가 자기 브라우저에서 상세페이지를 연 채로
북마크를 누르면:
  1) '상세정보 펼쳐보기' 버튼을 눌러 주고, 끝까지 빠르게 스크롤해서 지연 로딩 이미지를 불러온다.
  2) 화면에 보이는 글과 상세 이미지 주소를 모은다 (예비로 클립보드에도 복사).
  3) 카피 기획 화면을 새 탭으로 열고 postMessage로 자료를 보낸다.
     카피 기획 화면의 receive_clip()이 받으면 자동으로 분석이 시작된다.
사용자가 이미 보고 있는 화면을 읽는 것이라 사이트 서버에 따로 접속하지 않는다.
"""
from urllib.parse import quote, urlparse

import streamlit as st
import streamlit.components.v1 as components_v1
import streamlit.components.v2 as components_v2

MSG_TYPE = "copyclip-v1"
PAGE_PATH = "카피_기획"  # pages/2_카피_기획.py 의 주소 경로

# 북마크로 실행되는 코드. 한 줄로 합쳐서 javascript: 주소로 만든다 (그래서 // 주석은 쓰지 않는다)
_JS = r"""
(function(){
if(window.__cpRunning){return;} window.__cpRunning=1;
var APP='__APP__', MARK='[상세페이지 가져오기]', MAX=80, seen={}, urls=[];
var box=document.createElement('div');
box.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#111;color:#fff;padding:14px 18px;border-radius:12px;font:600 14px/1.5 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.3);max-width:320px;';
document.body.appendChild(box);
function say(t){box.textContent=t;}
function bye(ms){setTimeout(function(){if(box.parentNode){box.parentNode.removeChild(box);} window.__cpRunning=0;},ms);}
say('상세페이지를 읽는 중… (3초)');
var bs=document.querySelectorAll('button,a,[role=button]');
for(var i=0;i<bs.length;i++){var t=(bs[i].innerText||'').replace(/\s+/g,' ').trim();
  if(t.length<25&&/(상세\s?정보\s?(펼쳐|더\s?보기)|상품\s?정보\s?(펼쳐|더\s?보기)|상세\s?설명\s?(펼쳐|더\s?보기)|펼쳐\s?보기)/.test(t)){try{bs[i].click();}catch(e){}}}
var SKIP=/(review|related|recommend|banner|swiper|slide|coupon|popup|sticker|ranking|header|footer|gnb|nav)/i;
function area(el){for(var p=el.parentElement;p&&p!==document.body;p=p.parentElement){
  var n=(p.id||'')+' '+(typeof p.className==='string'?p.className:''); if(SKIP.test(n)){return false;}} return true;}
function add(u){if(!u||u.indexOf('data:')===0){return;} try{u=new URL(u,location.href).href;}catch(e){return;} if(u===location.href){return;}
  if(/\.(svg|gif)(\?|$)/i.test(u)||/(icon|logo|sprite|blank|spacer|loading)/i.test(u)){return;}
  if(!seen[u]){seen[u]=1;urls.push(u);}}
function scan(doc){var imgs=doc.querySelectorAll('img');
  for(var i=0;i<imgs.length;i++){var m=imgs[i]; if(!area(m)){continue;}
    var w=m.naturalWidth||parseInt(m.getAttribute('width')||'0',10); if(w&&w<400){continue;}
    add(m.getAttribute('ec-data-src')||m.getAttribute('data-src')||m.getAttribute('data-original')||m.getAttribute('data-lazy-src')||m.getAttribute('data-lazy')||m.currentSrc||m.getAttribute('src'));}}
var t0=Date.now(), y0=window.scrollY;
function step(){window.scrollBy(0,Math.round(window.innerHeight*0.9));
  if(Date.now()-t0<3000&&(window.innerHeight+window.scrollY)<document.documentElement.scrollHeight-10){setTimeout(step,110);}else{setTimeout(finish,250);}}
function finish(){
  scan(document);
  var frs=document.querySelectorAll('iframe'); for(var f=0;f<frs.length;f++){try{scan(frs[f].contentDocument);}catch(e){}}
  window.scrollTo(0,y0);
  var text=(document.body.innerText||'').replace(/\n{3,}/g,'\n\n').slice(0,30000);
  var og=document.querySelector('meta[property="og:title"]');
  var title=(og&&og.content)||document.title;
  var out=MARK+' '+location.href+'\n제목: '+title+'\n---본문---\n'+text+'\n---이미지---\n'+urls.slice(0,MAX).join('\n');
  var ta=document.createElement('textarea'); ta.value=out; ta.style.cssText='position:fixed;top:0;left:0;opacity:0;';
  document.body.appendChild(ta); ta.select(); try{document.execCommand('copy');}catch(e){} document.body.removeChild(ta);
  var w=window.open(APP,'_blank');
  if(w){send(w,out);return;}
  say('');
  var b=document.createElement('button'); b.textContent='카피 기획으로 보내기 →';
  b.style.cssText='background:#12997C;color:#fff;border:0;border-radius:999px;padding:10px 18px;font:700 14px sans-serif;cursor:pointer;';
  b.onclick=function(){var w2=window.open(APP,'_blank'); if(w2){send(w2,out);}};
  box.appendChild(b);}
function send(w,out){
  say('카피 기획 화면으로 보내는 중… (앱이 열리면 자동으로 시작돼요)');
  var done=false, tries=0;
  function onMsg(e){if(e.data&&e.data.type==='copyclip-ack'){done=true; window.removeEventListener('message',onMsg);
    say('보냈어요! 카피 기획 탭에서 자동으로 진행돼요.'); bye(5000);}}
  window.addEventListener('message',onMsg);
  var iv=setInterval(function(){
    if(done){clearInterval(iv);return;}
    if(tries++>200||w.closed){clearInterval(iv); window.removeEventListener('message',onMsg);
      say('앱이 자료를 받지 못했어요. 내용은 복사해 두었으니 카피 기획 화면의 「복사한 텍스트」 칸에 붙여넣어 주세요.'); bye(15000); return;}
    try{w.postMessage({type:'copyclip-v1',payload:out},'*');}catch(e){}},600);}
step();
})();
"""

# 카피 기획 화면에서 북마크가 보낸 자료를 받는 코드 (앱 페이지 안에서 실행)
_RECEIVER_JS = """
export default function(component) {
  const { setTriggerValue } = component;
  const targets = [window];
  try { if (window.top !== window && window.top.location.host === window.location.host) targets.push(window.top); } catch (e) {}
  const handler = (e) => {
    const d = e.data;
    if (!d || d.type !== '%s' || typeof d.payload !== 'string') return;
    try { if (e.source) e.source.postMessage({ type: 'copyclip-ack' }, '*'); } catch (err) {}
    if (window.__cpLast === d.payload) return;
    window.__cpLast = d.payload;
    setTriggerValue('clip', d.payload.slice(0, 200000));
  };
  targets.forEach((t) => t.addEventListener('message', handler));
  return () => targets.forEach((t) => t.removeEventListener('message', handler));
}
""" % MSG_TYPE

_receiver = components_v2.component("copy_clip_receiver", js=_RECEIVER_JS)


def receive_clip() -> str | None:
    """북마크가 보낸 자료가 이번 실행에 도착했으면 그 글(parse_clip 형식), 아니면 None."""
    res = _receiver(key="copy_clip_receiver", on_clip_change=lambda: None)
    return getattr(res, "clip", None)


def app_page_url() -> str:
    """카피 기획 화면의 공개 주소 (앱 주소 + 페이지 경로)."""
    try:
        u = urlparse(st.context.url or "")
    except Exception:  # noqa: BLE001
        u = None
    if not u or not u.netloc:
        return ""
    return f"{u.scheme}://{u.netloc}/{quote(PAGE_PATH)}"


def bookmarklet(app_url: str) -> str:
    js = " ".join(ln.strip() for ln in _JS.strip().splitlines()).replace("__APP__", app_url.replace("'", "%27"))
    return "javascript:" + quote(js, safe="")


def title_from_clip(body: str) -> str:
    """복사본의 '제목:' 줄에서 제품명만 (뒤에 붙는 쇼핑몰·카테고리 이름은 뗀다)."""
    for ln in (body or "").splitlines()[:3]:
        if ln.startswith("제목:"):
            t = ln[3:].strip()
            for sep in (" | ", " : ", " - ", " – "):
                t = t.split(sep)[0]
            return t.strip()[:80]
    return ""


def render_installer() -> None:
    """북마크바로 끌어다 놓는 버튼과 사용법. st.markdown은 javascript: 링크를 지우므로 components로 그린다."""
    url = app_page_url()
    if not url:
        st.caption("이 화면의 주소를 알 수 없어서 가져오기 버튼을 만들지 못했어요. 새로고침해 주세요.")
        return
    components_v1.html(f"""
<style>
  body{{ margin:0; font-family:'Pretendard Variable',Pretendard,-apple-system,'Noto Sans KR',sans-serif; color:#444; }}
  .wrap{{ display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
  a.bm{{ display:inline-flex; align-items:center; gap:8px; background:#12997C; color:#fff; text-decoration:none; font-weight:700;
        font-size:15px; padding:12px 20px; border-radius:999px; cursor:grab; box-shadow:0 6px 16px rgba(18,153,124,.22); }}
  ol{{ margin:12px 0 0; padding-left:20px; font-size:14px; line-height:1.8; }}
  b{{ color:#111; }}
</style>
<div class="wrap">
  <a class="bm" href="{bookmarklet(url)}" onclick="alert('이 버튼은 누르는 게 아니라 브라우저 위쪽 북마크바로 끌어다 놓는 버튼이에요.'); return false;">📋 카피 기획으로 보내기</a>
  <span style="font-size:14px">← 이 버튼을 브라우저 <b>북마크바로 끌어다 놓으세요</b> (처음 한 번만)</span>
</div>
<ol>
  <li>쿠팡·스마트스토어 등에서 상품 상세페이지를 열어요.</li>
  <li>북마크바의 <b>📋 카피 기획으로 보내기</b>를 한 번 누르면 끝이에요. 상세정보를 펼치고 스크롤해서 읽은 뒤,
      카피 기획 화면이 새 탭으로 열리면서 소구점·카피까지 자동으로 만들어져요.</li>
  <li>예전에 끌어다 놓은 버튼이 있다면 지우고 이 버튼으로 다시 끌어다 놓아 주세요.</li>
</ol>
""", height=170)
