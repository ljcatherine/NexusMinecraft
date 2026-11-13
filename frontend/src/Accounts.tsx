import {useEffect,useState} from 'react';
import {Copy,Shield,UserPlus} from 'lucide-react';

type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
type Act=(fn:()=>Promise<any>,message?:string)=>Promise<void>;

export function Accounts({api,act}:{api:API,act:Act}){
 const [accounts,setAccounts]=useState<{users:{name:string,role:string}[],invites:{name:string,role:string,expires:number}[]}>({users:[],invites:[]});
 const [username,setUsername]=useState(''),[role,setRole]=useState('admin'),[link,setLink]=useState('');
 const refresh=async()=>setAccounts(await api('/accounts'));
 useEffect(()=>{act(refresh,'Accounts loaded')},[]);
 return <>
  <div className="panel"><div className="section-title"><h2>Panel accounts</h2><Shield size={18}/></div>
   <p className="muted">Administrators have the same server controls, console commands, file access and account invitations as you.</p>
   {accounts.users.map(user=><div className="player" key={user.name}><span className="avatar">{user.name.slice(0,2)}</span><div>{user.name}<small>{user.role} · Active</small></div></div>)}
   {accounts.invites.map(invite=><div className="player" key={invite.name}><span className="avatar"><UserPlus size={15}/></span><div>{invite.name}<small>{invite.role} · Awaiting password setup · Expires {new Date(invite.expires*1000).toLocaleString()}</small></div></div>)}
  </div>
  <form className="panel" onSubmit={event=>{event.preventDefault();act(async()=>{const result=await api('/invites','POST',{username,role});setLink(result.url);setUsername('');await refresh()},'Private invitation created')}}>
   <h2>Invite an administrator or viewer</h2><p className="muted">Each invitation can be used once and expires in 24 hours. The recipient chooses their own password. Creating another invitation for a pending username revokes its earlier link.</p>
   <div className="toolbar"><input aria-label="New account username" placeholder="Username" value={username} onChange={e=>setUsername(e.target.value)} required pattern="[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}" maxLength={64}/><select aria-label="New account role" value={role} onChange={e=>setRole(e.target.value)}><option value="admin">Administrator — full access</option><option value="viewer">Viewer — read only</option></select><button className="primary"><UserPlus size={15}/>Create invitation</button></div>
   {link&&<div className="invite-result"><label>Private setup link<input aria-label="Private invitation link" value={link} readOnly/></label><button type="button" onClick={()=>act(()=>navigator.clipboard.writeText(link),'Invitation copied')}><Copy size={14}/>Copy link</button><p className="muted">Share this link privately with the intended person. It grants the selected account permissions.</p></div>}
  </form>
 </>;
}

export function InviteRegistration({token,api,onComplete}:{token:string,api:API,onComplete:(name:string)=>void}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 return <div className="login"><form className="login-box" onSubmit={async event=>{event.preventDefault();const fields=new FormData(event.currentTarget);const password=String(fields.get('password'));if(password!==fields.get('confirmation')){setError('Passwords do not match');return}setBusy(true);setError('');try{const result=await api('/invites/redeem','POST',{token,password});onComplete(result.username)}catch(error){setError(String(error))}finally{setBusy(false)}}}>
  <div className="brand-icon"><img src="/nexus-icon.svg" alt=""/></div><p className="eyebrow">YOUR PERSONAL ACCOUNT</p><h1>Join the control room.</h1><p className="muted">Choose your own password to activate your invitation.</p>
  <label>Password<input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required/></label><label>Confirm password<input name="confirmation" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required/></label>
  {error&&<p role="alert" className="error">{error}</p>}<button className="primary" disabled={busy}>{busy?'Creating account…':'Activate account'}</button><small>One-use invitation · Your password stays private</small>
 </form></div>;
}
