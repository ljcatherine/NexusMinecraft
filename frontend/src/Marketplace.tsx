import {useEffect,useState} from 'react';
import {Download,ExternalLink,Search,ShieldAlert,ShieldCheck} from 'lucide-react';

type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
type Act=(fn:()=>Promise<any>,message?:string)=>Promise<void>;
type Row=Record<string,any>;

const SOURCES:Record<string,string>={modrinth:'Modrinth',hangar:'Hangar',spiget:'SpigotMC'};
const SOFTWARE:Record<string,string>={paper:'Paper',purpur:'Purpur',folia:'Folia',spigot:'Spigot',bukkit:'Bukkit',forge:'Forge',neoforge:'NeoForge',fabric:'Fabric',quilt:'Quilt'};
const SUPPORTS:Record<string,string[]>={modrinth:Object.keys(SOFTWARE),hangar:['paper','purpur','folia'],spiget:['paper','purpur','spigot','bukkit']};
const count=(n:number|null|undefined)=>n==null?'':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(n>=1e4?0:1)+'k':String(n);
const size=(n:number|null|undefined)=>n==null?'':n>=1048576?(n/1048576).toFixed(1)+' MiB':(n/1024).toFixed(0)+' KiB';
const icon=(url:string|null)=>!url?null:url.startsWith('data:image/')?url:'/api/marketplace/icon?url='+encodeURIComponent(url);

export function Marketplace({sid,admin,api,act,onInstalled}:{sid:string,admin:boolean,api:API,act:Act,onInstalled:()=>void}){
 const [ctx,setCtx]=useState<Row|null>(null),[software,setSoftware]=useState(''),[version,setVersion]=useState(''),[source,setSource]=useState('modrinth');
 const [query,setQuery]=useState(''),[results,setResults]=useState<Row[]>([]),[total,setTotal]=useState<number|null>(null),[offset,setOffset]=useState(0);
 const [open,setOpen]=useState<string|null>(null),[versions,setVersions]=useState<Row[]|null>(null),[loading,setLoading]=useState(false);
 const kind=['forge','neoforge','fabric','quilt'].includes(software)?'mod':'plugin';

 useEffect(()=>{act(async()=>{const c=await api(`/servers/${sid}/marketplace/context`);setCtx(c);setSoftware(c.software);setVersion(c.version||'');setSource(c.sources[0]||'modrinth')},'Ready to browse')},[sid]);
 useEffect(()=>{if(software&&!SUPPORTS[source].includes(software))setSource('modrinth')},[software]);
 useEffect(()=>{if(ctx&&software)search(0)},[ctx,software,source]);

 async function search(from=0){
  setLoading(true);setOpen(null);setVersions(null);
  try{
   const params=new URLSearchParams({source,software,q:query,version,offset:String(from)});
   const r=await api(`/servers/${sid}/marketplace/search?${params}`);
   setResults(from?[...results,...r.results]:r.results);setTotal(r.total);setOffset(from);
  }catch(e){await act(async()=>{throw e})}finally{setLoading(false)}
 }
 async function showVersions(p:Row){
  if(open===p.id){setOpen(null);return}
  setOpen(p.id);setVersions(null);
  await act(async()=>setVersions(await api(`/servers/${sid}/marketplace/versions?${new URLSearchParams({source:p.source,project:p.id,software,version})}`)),'Versions loaded');
 }
 async function install(p:Row,v:Row){
  const where=ctx?.directory||'plugins';
  if(!confirm(`Install ${p.name} ${v.name} into /${where}?\n\nA ${kind} runs code with the Minecraft server account's permissions. Only continue if you trust ${p.name} and its author.`))return;
  const unverified=!v.verified;
  if(unverified&&!confirm(`${SOURCES[p.source]} doesn't publish a checksum for this file, so the panel can't verify it wasn't altered. Install the unverified file anyway?`))return;
  await act(async()=>{
   const r=await api(`/servers/${sid}/marketplace/install`,'POST',{source:p.source,project:p.id,version_id:String(v.id),software,version:version||null,confirmed:true,allow_unverified:unverified});
   onInstalled();return r;
  },`${p.name} installed to /${where}. Restart the server to load it.`);
 }

 return <div className="market">
  <form className="panel market-controls" onSubmit={e=>{e.preventDefault();search(0)}}>
   <div className="market-search"><Search size={16}/><input aria-label={`Search ${kind}s`} placeholder={`Search ${kind}s…`} value={query} onChange={e=>setQuery(e.target.value)}/><button className="primary" disabled={loading}>Search</button></div>
   <div className="market-filters">
    <div className="segmented" role="radiogroup" aria-label="Source">
     {Object.entries(SOURCES).map(([id,label])=><button type="button" key={id} role="radio" aria-checked={source===id} className={source===id?'on':''} disabled={!SUPPORTS[id].includes(software)} title={SUPPORTS[id].includes(software)?'':`${label} has no ${kind}s for ${SOFTWARE[software]||software}`} onClick={()=>setSource(id)}>{label}</button>)}
    </div>
    <label className="inline">Software<select value={software} onChange={e=>setSoftware(e.target.value)}>
     <optgroup label="Plugins">{['paper','purpur','folia','spigot','bukkit'].map(s=><option key={s} value={s}>{SOFTWARE[s]}</option>)}</optgroup>
     <optgroup label="Mods">{['forge','neoforge','fabric','quilt'].map(s=><option key={s} value={s}>{SOFTWARE[s]}</option>)}</optgroup>
    </select></label>
    <label className="inline">Minecraft<input value={version} onChange={e=>setVersion(e.target.value.trim())} placeholder="Any" inputMode="decimal" pattern="\d{1,2}\.\d{1,2}(\.\d{1,2})?" title="For example 1.21.4" size={7}/></label>
   </div>
   {ctx&&<small className="market-detected">Detected {SOFTWARE[ctx.software]||ctx.software}{ctx.version?' '+ctx.version:''} from {ctx.detected_from}. Results only include {kind}s for the software and version above.</small>}
  </form>

  {!loading&&!results.length&&<div className="panel empty">No {kind}s found for {SOFTWARE[software]} {version} on {SOURCES[source]}.</div>}
  <div className="market-grid">
   {results.map(p=><article className={'market-card'+(open===p.id?' open':'')} key={p.source+p.id}>
    <div className="market-head">
     {icon(p.icon)?<img className="market-icon" src={icon(p.icon)!} alt="" loading="lazy"/>:<span className="market-icon letter" aria-hidden="true">{(p.name||'?').slice(0,1)}</span>}
     <div className="market-title"><h3>{p.name}</h3><small>{p.author?`by ${p.author} · `:''}{count(p.downloads)} downloads</small></div>
     <span className={'market-badge '+(p.verified?'ok':'warn')} title={p.verified?'Files carry a published checksum that the panel verifies':'No published checksum'}>{p.verified?<ShieldCheck size={13}/>:<ShieldAlert size={13}/>}{SOURCES[p.source]}</span>
    </div>
    <p className="market-summary">{p.summary}</p>
    {p.note&&!p.installable&&<p className="market-note">{p.note}</p>}
    <div className="market-actions">
     <a className="button" href={p.page} target="_blank" rel="noopener noreferrer">Project page<ExternalLink size={13}/></a>
     {p.installable&&<button className={open===p.id?'':'primary'} onClick={()=>showVersions(p)}>{open===p.id?'Hide versions':'Choose version'}</button>}
    </div>
    {open===p.id&&<div className="market-versions">
     {!versions&&<small className="muted">Loading versions…</small>}
     {versions&&!versions.length&&<small className="muted">No downloadable versions for {SOFTWARE[software]} {version}.</small>}
     {versions?.map(v=><div className="market-version" key={v.id}>
      <div><strong>{v.name}</strong> <span className={'chip '+(v.channel==='Release'?'':'pre')}>{v.channel}</span>
       <small>{(v.game_versions||[]).join(', ')}{v.size?` · ${size(v.size)}`:''}{v.published?` · ${new Date(v.published).toLocaleDateString()}`:''}{v.verified?` · ${String(v.hash_algorithm).toUpperCase()} verified`:' · unverified'}</small></div>
      {admin?<button onClick={()=>install(p,v)}><Download size={14}/>Install</button>:<small className="muted">Admins can install</small>}
     </div>)}
    </div>}
   </article>)}
  </div>
  {results.length>0&&(total==null||offset+20<total)&&<div className="market-more"><button disabled={loading} onClick={()=>search(offset+20)}>{loading?'Loading…':'Load more'}</button></div>}
 </div>;
}
