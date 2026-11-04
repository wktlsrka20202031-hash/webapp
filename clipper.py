"""'상세페이지 가져오기' 북마크 버튼.

쿠팡·스마트스토어처럼 서버에서 자동으로 못 읽는 사이트용이다. 사용자가 자기 브라우저에서 상세페이지를 연 채로
북마크를 누르면, 그 화면에 보이는 글과 상세 이미지 주소가 복사된다. 카피 기획 화면에 붙여넣으면
copy_engine.parse_clip()이 읽어서 이미지를 받는다.
"""
from urllib.parse import quote

import streamlit.components.v1 as components

# 북마크로 실행되는 코드. 한 줄로 합쳐서 javascript: 주소로 만든다 (그래서 // 주석은 쓰지 않는다)
_JS = r"""
(function(){
var MARK='[상세페이지 가져오기]', MAX=60, seen={}, urls=[];
var SKIP=/(review|related|recommend|banner|swiper|slide|coupon|popup|sticker|ranking|header|footer|gnb|nav)/i;
function area(el){ for(var p=el.parentElement;p&&p!==document.body;p=p.parentElement){
  var n=(p.id||'')+' '+(typeof p.className==='string'?p.className:''); if(SKIP.test(n)) return false; } return true; }
function add(u){ if(!u||u.indexOf('data:')===0) return; try{u=new URL(u,location.href).href;}catch(e){return;} if(u===location.href) return;
  if(/\.(svg|gif)(\?|$)/i.test(u)||/(icon|logo|sprite|blank|spacer|loading)/i.test(u)) return;
  if(!seen[u]){seen[u]=1;urls.push(u);} }
function scan(doc){ var imgs=doc.querySelectorAll('img');
  for(var i=0;i<imgs.length;i++){ var m=imgs[i]; if(!area(m)) continue;
    var w=m.naturalWidth||parseInt(m.getAttribute('width')||'0',10); if(w&&w<400) continue;
    add(m.getAttribute('ec-data-src')||m.getAttribute('data-src')||m.getAttribute('data-original')||m.getAttribute('data-lazy-src')||m.currentSrc||m.getAttribute('src')); } }
scan(document);
var frs=document.querySelectorAll('iframe'); for(var f=0;f<frs.length;f++){ try{ scan(frs[f].contentDocument); }catch(e){} }
var text=(document.body.innerText||'').replace(/\n{3,}/g,'\n\n').slice(0,20000);
var out=MARK+' '+location.href+'\n제목: '+document.title+'\n---본문---\n'+text+'\n---이미지---\n'+urls.slice(0,MAX).join('\n');
var n=Math.min(urls.length,MAX), msg='복사했어요 (글 '+text.length+'자, 이미지 '+n+'장).\n카피 기획 화면의 「복사한 텍스트」 칸에 붙여넣고 버튼을 누르세요.';
var ta=document.createElement('textarea'); ta.value=out; ta.style.cssText='position:fixed;top:0;left:0;opacity:0;';
document.body.appendChild(ta); ta.select(); var ok=false; try{ok=document.execCommand('copy');}catch(e){}
if(ok){ document.body.removeChild(ta); alert(msg); return; }
ta.style.cssText='position:fixed;top:10%;left:10%;width:80%;height:70%;z-index:2147483647;background:#fff;color:#111;font-size:12px;';
ta.select(); alert('자동 복사가 막혀 있어요. 열린 상자에서 Ctrl+C(맥은 ⌘+C)로 복사한 뒤 붙여넣으세요.');
})();
"""

BOOKMARKLET = "javascript:" + quote(" ".join(ln.strip() for ln in _JS.strip().splitlines()), safe="")


def render_installer() -> None:
    """북마크바로 끌어다 놓는 버튼과 사용법. st.markdown은 javascript: 링크를 지우므로 components로 그린다."""
    components.html(f"""
<style>
  body{{ margin:0; font-family:'Pretendard Variable',Pretendard,-apple-system,'Noto Sans KR',sans-serif; color:#444; }}
  .wrap{{ display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
  a.bm{{ display:inline-flex; align-items:center; gap:8px; background:#12997C; color:#fff; text-decoration:none; font-weight:700;
        font-size:15px; padding:12px 20px; border-radius:999px; cursor:grab; box-shadow:0 6px 16px rgba(18,153,124,.22); }}
  ol{{ margin:12px 0 0; padding-left:20px; font-size:14px; line-height:1.8; }}
  b{{ color:#111; }}
</style>
<div class="wrap">
  <a class="bm" href="{BOOKMARKLET}" onclick="alert('이 버튼은 누르는 게 아니라 브라우저 위쪽 북마크바로 끌어다 놓는 버튼이에요.'); return false;">📋 상세페이지 가져오기</a>
  <span style="font-size:14px">← 이 버튼을 브라우저 <b>북마크바로 끌어다 놓으세요</b> (처음 한 번만)</span>
</div>
<ol>
  <li>쿠팡·스마트스토어 등에서 상품 상세페이지를 열고, <b>'상세정보 펼쳐보기'</b>를 누른 뒤 끝까지 한 번 스크롤해요.</li>
  <li>북마크바의 <b>📋 상세페이지 가져오기</b>를 누르면 글과 상세 이미지가 복사돼요.</li>
  <li>이 화면의 <b>「복사한 텍스트」</b> 칸에 붙여넣고(Ctrl+V) 버튼을 누르면 끝이에요.</li>
</ol>
""", height=150)
