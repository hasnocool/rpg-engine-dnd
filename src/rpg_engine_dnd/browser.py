"""Navigation shell preserving the original browser and the newer Creator Studio."""

from __future__ import annotations

from html import escape

from .studio_browser import BROWSER_HTML as STUDIO_BROWSER_HTML


ORIGINAL_BROWSER_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>rpg-engine-dnd</title>
<style>
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
body { margin: 0; background:#11151b; color:#e7edf5; }
header { padding:1rem 1.4rem; border-bottom:1px solid #2a3543; display:flex; gap:1rem; align-items:center; }
main { display:grid; grid-template-columns: 320px 1fr; min-height:calc(100vh - 64px); }
aside { padding:1rem; border-right:1px solid #2a3543; }
section { padding:1rem; }
input, textarea, button { width:100%; box-sizing:border-box; margin:.35rem 0; padding:.55rem; background:#18212b; color:#e7edf5; border:1px solid #344454; border-radius:6px; }
button { cursor:pointer; background:#26384b; }
#map { width:100%; height:460px; border:1px solid #344454; background:#0d1117; }
.node { fill:#2f81f7; stroke:#9ecbff; stroke-width:2; cursor:move; }
.edge { stroke:#65758b; stroke-width:2; }
pre { white-space:pre-wrap; word-break:break-word; background:#0d1117; padding:.8rem; border-radius:6px; }
.small { color:#9fb0c3; font-size:.9rem; }
</style>
</head>
<body>
<header><strong>rpg-engine-dnd v3</strong><span class="small">authoritative deterministic runtime + Creator Studio</span></header>
<main>
<aside>
<label>Campaign ID</label><input id="campaign" value="demo">
<label>Owner ID</label><input id="owner" value="local-owner">
<button id="create">Create campaign</button>
<button id="refresh">Refresh scoped world</button>
<hr>
<label>Entity ID</label><input id="entity" value="hero">
<label>Name</label><input id="name" value="Hero">
<button id="addEntity">Create entity</button>
<hr>
<label>Studio project</label><input id="project" value="demo-project">
<button id="saveProject">Save map project</button>
<button id="snapshotProject">Snapshot revision</button>
</aside>
<section>
<h2>World</h2><pre id="world">No campaign loaded.</pre>
<h2>Visual map editor</h2>
<p class="small">Click empty space to add nodes. Drag nodes to reposition them. Shift-click two nodes to create an edge.</p>
<svg id="map" viewBox="0 0 1000 460"></svg>
<pre id="studio">Studio state will appear here.</pre>
</section>
</main>
<script>
const $ = id => document.getElementById(id);
const state = { nodes: [], edges: [], selected: [], drag: null };
const headers = () => ({'Content-Type':'application/json','X-Owner-ID':$('owner').value});
async function request(path, opts={}) { const r=await fetch(path,opts); const t=await r.text(); if(!r.ok) throw new Error(t); return t?JSON.parse(t):{}; }
$('create').onclick = async()=>{ await request('/v3/campaigns',{method:'POST',headers:headers(),body:JSON.stringify({campaign_id:$('campaign').value,seed:'browser',owner_id:$('owner').value})}); await refresh(); };
async function refresh(){ try { $('world').textContent=JSON.stringify(await request(`/v3/campaigns/${$('campaign').value}`,{headers:headers()}),null,2); } catch(e){$('world').textContent=e;} }
$('refresh').onclick=refresh;
$('addEntity').onclick=async()=>{ const id=$('entity').value; await request(`/v3/campaigns/${$('campaign').value}/commands`,{method:'POST',headers:headers(),body:JSON.stringify({kind:'entity.create',command_id:`browser:${Date.now()}`,entity_id:id,components:{identity:{name:$('name').value},position:{x:0,y:0}}})}); await refresh(); };
function render(){ const svg=$('map'); svg.innerHTML=''; for(const e of state.edges){ const a=state.nodes.find(n=>n.id===e.a), b=state.nodes.find(n=>n.id===e.b); if(!a||!b)continue; const l=document.createElementNS('http://www.w3.org/2000/svg','line'); Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'edge'}).forEach(([k,v])=>l.setAttribute(k,v)); svg.appendChild(l); } for(const n of state.nodes){ const c=document.createElementNS('http://www.w3.org/2000/svg','circle'); Object.entries({cx:n.x,cy:n.y,r:18,class:'node'}).forEach(([k,v])=>c.setAttribute(k,v)); c.onpointerdown=e=>{e.stopPropagation(); if(e.shiftKey){state.selected.push(n.id); state.selected=[...new Set(state.selected)].slice(-2); if(state.selected.length===2){state.edges.push({a:state.selected[0],b:state.selected[1]}); state.selected=[]; render();}} else {state.drag=n.id;c.setPointerCapture(e.pointerId);} }; c.onpointermove=e=>{if(state.drag===n.id){const rect=svg.getBoundingClientRect();n.x=(e.clientX-rect.left)*1000/rect.width;n.y=(e.clientY-rect.top)*460/rect.height;render();}}; c.onpointerup=()=>state.drag=null; svg.appendChild(c); } $('studio').textContent=JSON.stringify(state,null,2); }
$('map').onclick=e=>{ const rect=$('map').getBoundingClientRect(); state.nodes.push({id:`node-${state.nodes.length+1}`,x:(e.clientX-rect.left)*1000/rect.width,y:(e.clientY-rect.top)*460/rect.height}); render(); };
$('saveProject').onclick=async()=>{ const document={map:{nodes:state.nodes,edges:state.edges}}; const out=await request('/v3/studio/projects',{method:'POST',headers:headers(),body:JSON.stringify({project_id:$('project').value,name:$('project').value,document})}); $('studio').textContent=JSON.stringify(out,null,2); };
$('snapshotProject').onclick=async()=>{ const out=await request(`/v3/studio/projects/${$('project').value}/snapshot`,{method:'POST',headers:headers()}); $('studio').textContent=JSON.stringify(out,null,2); };
render();
</script>
</body>
</html>'''


def _frame_source(document: str) -> str:
    return escape(document, quote=True)


BROWSER_HTML = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>rpg-engine-dnd</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#0d1117; color:#e7edf5; overflow:hidden; }}
nav {{ height:52px; display:flex; align-items:center; gap:.5rem; padding:.55rem .8rem; background:#11151b; border-bottom:1px solid #2a3543; }}
nav strong {{ margin-right:.75rem; }}
nav button {{ width:auto; margin:0; padding:.45rem .8rem; border:1px solid #344454; border-radius:6px; color:#dce7f5; background:#18212b; cursor:pointer; }}
nav button.active {{ background:#315b83; border-color:#4d7ba8; }}
.viewport {{ width:100%; height:calc(100vh - 52px); border:0; display:block; background:#11151b; }}
.viewport[hidden] {{ display:none; }}
</style>
</head>
<body>
<nav aria-label="Application navigation">
<strong>rpg-engine-dnd</strong>
<button id="navBrowser" type="button" data-view="browser">Browser</button>
<button id="navStudio" type="button" data-view="studio">Creator Studio</button>
</nav>
<iframe id="browserView" class="viewport" title="Original RPG browser" srcdoc="{_frame_source(ORIGINAL_BROWSER_HTML)}"></iframe>
<iframe id="studioView" class="viewport" title="Creator Studio" srcdoc="{_frame_source(STUDIO_BROWSER_HTML)}" hidden></iframe>
<script>
const views = {{browser: document.getElementById('browserView'), studio: document.getElementById('studioView')}};
const buttons = {{browser: document.getElementById('navBrowser'), studio: document.getElementById('navStudio')}};
function selectView(view, updateHash=true) {{
  const selected = view === 'studio' ? 'studio' : 'browser';
  for (const [name, frame] of Object.entries(views)) frame.hidden = name !== selected;
  for (const [name, button] of Object.entries(buttons)) button.classList.toggle('active', name === selected);
  if (updateHash) history.replaceState(null, '', selected === 'studio' ? '#creator-studio' : '#browser');
}}
buttons.browser.onclick = () => selectView('browser');
buttons.studio.onclick = () => selectView('studio');
window.addEventListener('hashchange', () => selectView(location.hash === '#creator-studio' ? 'studio' : 'browser', false));
selectView(location.hash === '#creator-studio' ? 'studio' : 'browser', false);
</script>
</body>
</html>'''
