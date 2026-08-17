"""Built-in zero-build browser client and SVG Creator Studio surface."""

BROWSER_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>rpg-engine-dnd</title>
<style>
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
body { margin: 0; background:#11151b; color:#e7edf5; }
header { padding:1rem 1.4rem; border-bottom:1px solid #2a3543; display:flex; gap:1rem; align-items:center; }
main { display:grid; grid-template-columns: 340px 1fr; min-height:calc(100vh - 64px); }
aside { padding:1rem; border-right:1px solid #2a3543; }
section { padding:1rem; }
input, textarea, button, select { width:100%; box-sizing:border-box; margin:.35rem 0; padding:.55rem; background:#18212b; color:#e7edf5; border:1px solid #344454; border-radius:6px; }
button { cursor:pointer; background:#26384b; }
#map { width:100%; height:460px; border:1px solid #344454; background:#0d1117; }
.node { fill:#2f81f7; stroke:#9ecbff; stroke-width:2; cursor:move; }
.edge { stroke:#65758b; stroke-width:2; }
pre { white-space:pre-wrap; word-break:break-word; background:#0d1117; padding:.8rem; border-radius:6px; }
.small { color:#9fb0c3; font-size:.9rem; }
hr { border:0; border-top:1px solid #2a3543; margin:1rem 0; }
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
<label>Map item ID</label><input id="mapItem" value="world-map">
<button id="saveProject">Save Studio project</button>
<button id="snapshotProject">Snapshot revision</button>
<button id="exportMap">Export current map item</button>
<label>Import exported Studio item</label><input id="importFile" type="file" accept="application/json,.json">
<button id="importItem">Import selected item</button>
<p class="small">Imported envelopes are hash-checked in the browser and validated again by the typed Studio project model when saved.</p>
</aside>
<section>
<h2>World</h2><pre id="world">No campaign loaded.</pre>
<h2>Visual map editor</h2>
<p class="small">Click empty space to add nodes. Drag nodes to reposition them. Shift-click two nodes to create an edge.</p>
<svg id="map" viewBox="0 0 1000 460"></svg>
<h3>Creator Studio state</h3><pre id="studio">Studio state will appear here.</pre>
</section>
</main>
<script>
const $ = id => document.getElementById(id);
const state = { nodes: [], edges: [], selected: [], drag: null, items: [] };
const headers = () => ({'Content-Type':'application/json','X-Owner-ID':$('owner').value});
async function request(path, opts={}) { const r=await fetch(path,opts); const t=await r.text(); if(!r.ok) throw new Error(t); return t?JSON.parse(t):{}; }
function canonical(value){ if(Array.isArray(value)) return '['+value.map(canonical).join(',')+']'; if(value && typeof value==='object'){return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';} return JSON.stringify(value); }
async function sha256(value){ const bytes=new TextEncoder().encode(canonical(value)); const digest=await crypto.subtle.digest('SHA-256',bytes); return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join(''); }
async function envelope(kind,itemId,content){ return {schema_version:1,kind,item_id:itemId,content_hash:await sha256(content),content}; }
function upsertItem(item){ state.items=state.items.filter(existing=>!(existing.kind===item.kind && existing.item_id===item.item_id)); state.items.push(item); state.items.sort((a,b)=>(a.kind+'/'+a.item_id).localeCompare(b.kind+'/'+b.item_id)); }
function exportJson(name,value){ const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}); const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),0); }
$('create').onclick = async()=>{ await request('/v3/campaigns',{method:'POST',headers:headers(),body:JSON.stringify({campaign_id:$('campaign').value,seed:'browser',owner_id:$('owner').value})}); await refresh(); };
async function refresh(){ try { $('world').textContent=JSON.stringify(await request(`/v3/campaigns/${$('campaign').value}`,{headers:headers()}),null,2); } catch(e){$('world').textContent=e;} }
$('refresh').onclick=refresh;
$('addEntity').onclick=async()=>{ const id=$('entity').value; await request(`/v3/campaigns/${$('campaign').value}/commands`,{method:'POST',headers:headers(),body:JSON.stringify({kind:'entity.create',command_id:`browser:${Date.now()}`,entity_id:id,components:{identity:{name:$('name').value},position:{x:0,y:0}}})}); await refresh(); };
function render(){ const svg=$('map'); svg.innerHTML=''; for(const e of state.edges){ const a=state.nodes.find(n=>n.id===e.a), b=state.nodes.find(n=>n.id===e.b); if(!a||!b)continue; const l=document.createElementNS('http://www.w3.org/2000/svg','line'); Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'edge'}).forEach(([k,v])=>l.setAttribute(k,v)); svg.appendChild(l); } for(const n of state.nodes){ const c=document.createElementNS('http://www.w3.org/2000/svg','circle'); Object.entries({cx:n.x,cy:n.y,r:18,class:'node'}).forEach(([k,v])=>c.setAttribute(k,v)); c.onpointerdown=e=>{e.stopPropagation(); if(e.shiftKey){state.selected.push(n.id); state.selected=[...new Set(state.selected)].slice(-2); if(state.selected.length===2){state.edges.push({a:state.selected[0],b:state.selected[1]}); state.selected=[]; render();}} else {state.drag=n.id;c.setPointerCapture(e.pointerId);} }; c.onpointermove=e=>{if(state.drag===n.id){const rect=svg.getBoundingClientRect();n.x=(e.clientX-rect.left)*1000/rect.width;n.y=(e.clientY-rect.top)*460/rect.height;render();}}; c.onpointerup=()=>state.drag=null; svg.appendChild(c); } $('studio').textContent=JSON.stringify({map:{nodes:state.nodes,edges:state.edges},items:state.items},null,2); }
$('map').onclick=e=>{ const rect=$('map').getBoundingClientRect(); state.nodes.push({id:`node-${state.nodes.length+1}`,x:(e.clientX-rect.left)*1000/rect.width,y:(e.clientY-rect.top)*460/rect.height}); render(); };
$('saveProject').onclick=async()=>{ const map=await envelope('map',$('mapItem').value,{nodes:state.nodes,edges:state.edges}); upsertItem(map); const document={map:{nodes:state.nodes,edges:state.edges},items:state.items}; const out=await request('/v3/studio/projects',{method:'POST',headers:headers(),body:JSON.stringify({project_id:$('project').value,name:$('project').value,document})}); $('studio').textContent=JSON.stringify(out,null,2); };
$('snapshotProject').onclick=async()=>{ const out=await request(`/v3/studio/projects/${$('project').value}/snapshot`,{method:'POST',headers:headers()}); $('studio').textContent=JSON.stringify(out,null,2); };
$('exportMap').onclick=async()=>{ const item=await envelope('map',$('mapItem').value,{nodes:state.nodes,edges:state.edges}); upsertItem(item); exportJson(`${item.item_id}.studio.json`,item); render(); };
$('importItem').onclick=async()=>{ try { const file=$('importFile').files[0]; if(!file) throw new Error('Choose a Studio JSON export first.'); const item=JSON.parse(await file.text()); if(item.schema_version!==1 || !item.kind || !item.item_id || !item.content || !item.content_hash) throw new Error('Not a Studio item envelope.'); if(await sha256(item.content)!==item.content_hash) throw new Error('Studio item hash verification failed.'); upsertItem(item); if(item.kind==='map'){state.nodes=Array.isArray(item.content.nodes)?item.content.nodes:[];state.edges=Array.isArray(item.content.edges)?item.content.edges:[];$('mapItem').value=item.item_id;} render(); } catch(e){$('studio').textContent=String(e);} };
render();
</script>
</body>
</html>'''
