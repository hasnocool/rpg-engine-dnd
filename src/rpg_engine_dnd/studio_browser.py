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
aside { padding:1rem; border-right:1px solid #2a3543; overflow:auto; }
section { padding:1rem; min-width:0; }
input, textarea, button, select { width:100%; box-sizing:border-box; margin:.35rem 0; padding:.55rem; background:#18212b; color:#e7edf5; border:1px solid #344454; border-radius:6px; }
button { cursor:pointer; background:#26384b; }
button.primary { background:#315b83; }
textarea { min-height:180px; font-family:ui-monospace, monospace; }
#map { width:100%; height:460px; border:1px solid #344454; background:#0d1117; }
.node { fill:#2f81f7; stroke:#9ecbff; stroke-width:2; cursor:move; }
.edge { stroke:#65758b; stroke-width:2; }
pre { white-space:pre-wrap; word-break:break-word; background:#0d1117; padding:.8rem; border-radius:6px; }
.small { color:#9fb0c3; font-size:.9rem; }
hr { border:0; border-top:1px solid #2a3543; margin:1rem 0; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:.5rem; }
.badge { display:inline-block; padding:.15rem .45rem; border:1px solid #344454; border-radius:999px; margin:.15rem .25rem .15rem 0; font-size:.8rem; }
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
<hr>
<h3>Content library</h3>
<p class="small">Load bundled or imported content into this existing Studio project without replacing the Studio workflow.</p>
<label>Bundled campaign</label>
<select id="libraryProject"><option value="shattered-beacon">The Shattered Beacon</option></select>
<button id="loadLibrary" class="primary">Load selected campaign into Studio</button>
<div id="librarySummary" class="small"></div>
<label>Project content</label>
<select id="libraryItem"><option value="">Load a campaign first</option></select>
<button id="loadItem">Select and load item</button>
<details>
<summary>Edit selected library item</summary>
<label>Selected item JSON</label><textarea id="itemEditor" spellcheck="false">{}</textarea>
<div class="grid"><button id="applyItem">Apply item JSON</button><button id="exportItem">Export selected item</button></div>
</details>
<hr>
<button id="exportMap">Export current map item</button>
<label>Import exported Studio item</label><input id="importFile" type="file" accept="application/json,.json">
<button id="importItem">Import selected item</button>
<p class="small">Imported envelopes are hash-checked in the browser and validated again by the typed Studio project model when saved. Imported items join the same selectable content library.</p>
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
function itemKey(item){ return `${item.kind}/${item.item_id}`; }
function upsertItem(item){ state.items=state.items.filter(existing=>itemKey(existing)!==itemKey(item)); state.items.push(item); state.items.sort((a,b)=>itemKey(a).localeCompare(itemKey(b))); refreshItemSelector(itemKey(item)); }
function exportJson(name,value){ const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}); const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),0); }
function selectedItem(){ return state.items.find(item=>itemKey(item)===$('libraryItem').value)||null; }
function refreshItemSelector(preferred=''){ const select=$('libraryItem'); const current=preferred||select.value; select.innerHTML=''; if(!state.items.length){ const option=document.createElement('option'); option.value=''; option.textContent='No project content loaded'; select.appendChild(option); $('itemEditor').value='{}'; return; } for(const item of state.items){ const option=document.createElement('option'); option.value=itemKey(item); option.textContent=`${item.kind} · ${item.item_id}`; select.appendChild(option); } if(current&&state.items.some(i=>itemKey(i)===current)) select.value=current; updateItemEditor(); }
function updateItemEditor(){ const item=selectedItem(); $('itemEditor').value=item?JSON.stringify(item.content,null,2):'{}'; }
$('libraryItem').onchange=updateItemEditor;
const BUNDLED_PROJECTS = {'shattered-beacon':{project_id:'example-shattered-beacon',name:'The Shattered Beacon',description:'Original coastal mystery starter campaign.',items:[
{kind:'map',item_id:'beacon-coast',content:{nodes:[{id:'greyharbor',name:'Greyharbor',x:130,y:250,kind:'settlement'},{id:'salt-road',name:'Salt Road',x:285,y:250,kind:'road'},{id:'glass-marsh',name:'Glass Marsh',x:430,y:330,kind:'wilds'},{id:'old-watch',name:'Old Watchtower',x:440,y:145,kind:'ruin'},{id:'ember-grotto',name:'Ember Grotto',x:620,y:350,kind:'cave'},{id:'beacon-cliffs',name:'Beacon Cliffs',x:650,y:145,kind:'coast'},{id:'shattered-beacon',name:'Shattered Beacon',x:840,y:220,kind:'dungeon'}],edges:[{a:'greyharbor',b:'salt-road',cost:1},{a:'salt-road',b:'glass-marsh',cost:2},{a:'salt-road',b:'old-watch',cost:1},{a:'glass-marsh',b:'ember-grotto',cost:2},{a:'old-watch',b:'beacon-cliffs',cost:2},{a:'beacon-cliffs',b:'shattered-beacon',cost:1},{a:'ember-grotto',b:'shattered-beacon',cost:3}]}},
{kind:'rules',item_id:'shattered-beacon-rules',content:{max_level:12,critical_multiplier:2,diagonal_cost:1.5,death_saves_enabled:true}},
{kind:'creature',item_id:'brine-stalker',content:{creature_id:'brine-stalker',name:'Brine Stalker',stats:{armor:13,hp:18,speed:30,attack:4},tags:['coastal','ambusher','beast']}},
{kind:'creature',item_id:'cinder-moth',content:{creature_id:'cinder-moth',name:'Cinder Moth Swarm',stats:{armor:12,hp:14,speed:35,attack:3},tags:['fire','swarm','cave']}},
{kind:'creature',item_id:'beacon-warden',content:{creature_id:'beacon-warden',name:'Beacon Warden',stats:{armor:16,hp:42,speed:25,attack:6},tags:['construct','guardian','boss']}},
{kind:'spell',item_id:'lantern-spark',content:{spell_id:'lantern-spark',name:'Lantern Spark',level:0,school:'evocation',tags:['light','fire'],rule_graph_id:'spell.lantern-spark'}},
{kind:'spell',item_id:'tide-bind',content:{spell_id:'tide-bind',name:'Tide Bind',level:1,school:'transmutation',tags:['water','control'],rule_graph_id:'spell.tide-bind'}},
{kind:'spell',item_id:'beacon-pulse',content:{spell_id:'beacon-pulse',name:'Beacon Pulse',level:2,school:'abjuration',tags:['radiant','ward'],rule_graph_id:'spell.beacon-pulse'}},
{kind:'quest',item_id:'lights-out',content:{quest_id:'lights-out',title:'Lights Out at Greyharbor',objectives:[{objective_id:'inspect-watch',event_kind:'location.discovered',target:1},{objective_id:'recover-lens',event_kind:'item.recovered',target:1}],tags:['main','exploration']}},
{kind:'quest',item_id:'marsh-whispers',content:{quest_id:'marsh-whispers',title:'Whispers in the Glass Marsh',objectives:[{objective_id:'find-tracks',event_kind:'clue.discovered',target:2},{objective_id:'protect-scout',event_kind:'npc.escorted',target:1}],tags:['side','mystery']}},
{kind:'quest',item_id:'rekindle-beacon',content:{quest_id:'rekindle-beacon',title:'Rekindle the Shattered Beacon',objectives:[{objective_id:'defeat-warden',event_kind:'creature.defeated',target:1},{objective_id:'ignite-core',event_kind:'rule.beacon_ignited',target:1}],tags:['main','finale']}},
{kind:'rule_graph',item_id:'spell.lantern-spark',content:{rule_id:'spell.lantern-spark',entry_point:'damage',capabilities:['damage','emit'],allowed_state_paths:[],nodes:{damage:{node_id:'damage',op:'damage',args:{source_id:'caster',target_id:'target',expression:'1d4',damage_type:'fire'},next_node:'emit'},emit:{node_id:'emit',op:'emit',args:{event:'spell.lantern_spark.resolved'}}},provenance:{source:'original-example',license:'MIT'}}},
{kind:'rule_graph',item_id:'spell.tide-bind',content:{rule_id:'spell.tide-bind',entry_point:'condition',capabilities:['condition','emit'],allowed_state_paths:[],nodes:{condition:{node_id:'condition',op:'condition',args:{effect_id:'tide-bind',source_id:'caster',target_id:'target',kind:'restrained',payload:{duration_rounds:1}},next_node:'emit'},emit:{node_id:'emit',op:'emit',args:{event:'spell.tide_bind.resolved'}}},provenance:{source:'original-example',license:'MIT'}}},
{kind:'rule_graph',item_id:'spell.beacon-pulse',content:{rule_id:'spell.beacon-pulse',entry_point:'state',capabilities:['state','emit'],allowed_state_paths:['beacon.warded'],nodes:{state:{node_id:'state',op:'state',args:{path:'beacon.warded',value:true},next_node:'emit'},emit:{node_id:'emit',op:'emit',args:{event:'spell.beacon_pulse.resolved'}}},provenance:{source:'original-example',license:'MIT'}}},
{kind:'rule_graph',item_id:'campaign.rekindle-beacon',content:{rule_id:'campaign.rekindle-beacon',entry_point:'state',capabilities:['state','emit'],allowed_state_paths:['beacon.lit'],nodes:{state:{node_id:'state',op:'state',args:{path:'beacon.lit',value:true},next_node:'emit'},emit:{node_id:'emit',op:'emit',args:{event:'rule.beacon_ignited'}}},provenance:{source:'original-example',license:'MIT'}}},
{kind:'campaign',item_id:'shattered-beacon',content:{template_id:'shattered-beacon',name:'The Shattered Beacon',starting_scene:'greyharbor',entities:[{entity_id:'harbormaster-nera',components:{identity:{name:'Nera Vale',role:'harbormaster'},location:{node:'greyharbor'}}},{entity_id:'scout-orrin',components:{identity:{name:'Orrin Fen',role:'scout'},location:{node:'salt-road'}}}],metadata:{recommended_level:'1-3',map_item:'beacon-coast',main_quest:'lights-out',final_quest:'rekindle-beacon',content:'original-example'}}}
]}};
async function loadBundledProject(key){ const source=BUNDLED_PROJECTS[key]; if(!source) throw new Error('Unknown bundled Studio project.'); state.items=[]; for(const raw of source.items) state.items.push(await envelope(raw.kind,raw.item_id,raw.content)); state.items.sort((a,b)=>itemKey(a).localeCompare(itemKey(b))); const map=state.items.find(i=>i.kind==='map'); state.nodes=map?structuredClone(map.content.nodes||[]):[]; state.edges=map?structuredClone(map.content.edges||[]):[]; $('project').value=source.project_id; $('mapItem').value=map?map.item_id:'world-map'; refreshItemSelector(map?itemKey(map):''); const counts={}; for(const item of state.items) counts[item.kind]=(counts[item.kind]||0)+1; $('librarySummary').innerHTML=`<strong>${source.name}</strong><br>${source.description}<br>`+Object.entries(counts).map(([k,v])=>`<span class="badge">${k}: ${v}</span>`).join('')+'<br>Loaded into the editor. Use Save Studio project to persist changes.'; render(); }
$('loadLibrary').onclick=async()=>{ try{ await loadBundledProject($('libraryProject').value); }catch(e){ $('studio').textContent=String(e); } };
$('loadItem').onclick=()=>{ const item=selectedItem(); if(!item) return; updateItemEditor(); if(item.kind==='map'){ state.nodes=structuredClone(item.content.nodes||[]); state.edges=structuredClone(item.content.edges||[]); $('mapItem').value=item.item_id; render(); } };
$('applyItem').onclick=async()=>{ try{ const old=selectedItem(); if(!old) throw new Error('Select a project item first.'); const content=JSON.parse($('itemEditor').value); const updated=await envelope(old.kind,old.item_id,content); upsertItem(updated); if(updated.kind==='map'){ state.nodes=structuredClone(content.nodes||[]); state.edges=structuredClone(content.edges||[]); } render(); }catch(e){ $('studio').textContent=String(e); } };
$('exportItem').onclick=()=>{ const item=selectedItem(); if(item) exportJson(`${item.item_id}.studio.json`,item); };
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
refreshItemSelector();
render();
</script>
</body>
</html>'''