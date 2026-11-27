// KANTOOR: het dashboard en de agents als pixel-kantoor. Leest dezelfde gegevens als de AGENTS-pagina
// (docs/agents/<id>.json en data/agents.json) en de posts uit status.json. Klik op iemand voor details.
(function(){
const W=320,H=200;
// Wie zit waar. x,y = linksboven van het bureau (in game-pixels). Kleuren: haar, huid, shirt.
const SEATS={
  strateeg:      {room:"directie", x:20,  y:52, look:["#2b1b10","#e8b48a","#5BC0FF"], role:"Strateeg"},
  hoofdredacteur:{room:"directie", x:62,  y:52, look:["#9a9a9a","#c98a5e","#ffffff"], role:"Hoofdredacteur"},
  battle:        {room:"redactie", x:128, y:52, look:["#111111","#f1c19a","#FF2E88"], role:"Battle-redacteur"},
  podcast:       {room:"redactie", x:174, y:52, look:["#7a3b12","#8d5a3b","#C6FF00"], role:"Podcast-redacteur"},
  nieuws:        {room:"redactie", x:220, y:52, look:["#e0c060","#f3cfae","#FF9F43"], role:"Nieuwsredacteur"},
  community:     {room:"redactie", x:266, y:52, look:["#3a2a5a","#c68e6a","#b388ff"], role:"Community"},
  qc:            {room:"controle", x:20,  y:132,look:["#222222","#e2a77f","#ffffff"], role:"Kwaliteitscontrole"},
  scout:         {room:"controle", x:62,  y:132,look:["#b5651d","#f0c8a0","#2ecc71"], role:"Nieuwsscout"},
  analist:       {room:"analyse",  x:128, y:132,look:["#444444","#d9a27a","#5BC0FF"], role:"Analist"},
  tags:          {room:"analyse",  x:174, y:132,look:["#6b4226","#eac0a0","#FF9F43"], role:"Tagsonderzoeker"},
  wachter:       {room:"server",   x:286, y:140,look:["#1d1d1d","#a8704c","#7a7a80"], role:"Systeemwachter"}
};
const ROOMS=[
  {id:"directie",label:"DIRECTIE",   x:6,  y:30, w:104,h:70, floor:"#2a2430"},
  {id:"redactie",label:"REDACTIE",   x:116,y:30, w:198,h:70, floor:"#22282a"},
  {id:"controle",label:"CONTROLE",   x:6,  y:108,w:104,h:86, floor:"#262a22"},
  {id:"analyse", label:"ANALYSE",    x:116,y:108,w:98, h:86, floor:"#24242c"},
  {id:"server",  label:"JOUW BUREAU", x:220,y:108,w:94, h:86, floor:"#2c2622"}
];
const STC={bezig:"#C6FF00",wacht:"#7a7a80",pauze:"#ffb000",uit:"#444",fout:"#FF2E88",gepland:"#5BC0FF",aandacht:"#FF9F43"};
let pick=null, timer=null;

const r=(x,y,w,h,c,extra="")=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}" ${extra}/>`;

function person(x,y,look,st){
  const [hair,skin,shirt]=look, cls=st==="bezig"?"of-type":st==="fout"?"of-panic":"";
  // 8 breed, 11 hoog; zit achter het bureau, dus alleen bovenlijf zichtbaar
  return `<g class="${cls}">${r(x+2,y,4,1,hair)}${r(x+1,y+1,6,2,hair)}${r(x+1,y+3,6,3,skin)}${r(x+1,y+3,1,1,hair)}${r(x+6,y+3,1,1,hair)}
    ${r(x+2,y+4,1,1,"#111")}${r(x+5,y+4,1,1,"#111")}${r(x,y+6,8,5,shirt)}${r(x+3,y+6,2,1,skin)}
    <g class="of-arms">${r(x-1,y+8,2,3,shirt)}${r(x+7,y+8,2,3,shirt)}${r(x-1,y+11,2,1,skin)}${r(x+7,y+11,2,1,skin)}</g></g>`}

function desk(id,s,a,st){
  const {x,y}=s, on=st!=="uit", scr=st==="bezig"?"#C6FF00":st==="fout"?"#FF2E88":st==="gepland"?"#1e3a52":on?"#3b4a55":"#151517";
  let g=`<g class="of-seat" data-of="${id}">`;
  g+=r(x+4,y-2,24,8,"#3a3a40");                                   // stoel (rugleuning)
  g+=on&&st!=="gepland"?person(x+12,y-6,s.look,st):"";              // agent achter het bureau
  if(st==="gepland")g+=person(x+12,y-6,s.look,"wacht")+`<text x="${x+22}" y="${y-8}" class="of-zz">z</text>`;
  g+=r(x,y+4,32,10,"#6b4a2b")+r(x,y+4,32,2,"#8a6038")+r(x+1,y+14,2,6,"#4a3320")+r(x+29,y+14,2,6,"#4a3320"); // bureau
  g+=r(x+2,y-4,10,8,"#111")+r(x+3,y-3,8,6,scr,st==="bezig"?'class="of-glow"':"")+r(x+6,y+4,2,1,"#111"); // scherm
  if(st==="bezig")g+=r(x+4,y-1,5,1,"#111")+r(x+4,y+1,3,1,"#111");  // code op het scherm
  g+=r(x+20,y+5,7,2,"#ddd");                                        // toetsenbord
  g+=`<circle cx="${x+30}" cy="${y-3}" r="1.6" fill="${STC[st]||"#7a7a80"}" ${st==="fout"||st==="bezig"?'class="of-blink"':""}/>`;
  if(id==="podcast")g+=r(x+26,y+1,3,3,"#222")+r(x+27,y,1,1,"#888");  // microfoon
  if(id==="battle")g+=r(x+13,y+2,4,2,"#d33")+r(x+14,y+1,2,1,"#d33"); // auto'tje
  if(id==="analist")g+=r(x+14,y+1,1,3,"#5BC0FF")+r(x+16,y,1,4,"#C6FF00")+r(x+18,y+2,1,2,"#FF2E88");
  const tip=a.doing||((a.history||[])[0]||{}).text||"";
  g+=`<text x="${x+16}" y="${y+25}" class="of-name" text-anchor="middle">${esc((s.role||id).toUpperCase())}</text>`;
  return g+`<rect x="${x-2}" y="${y-10}" width="36" height="38" fill="transparent"><title>${esc((a.name||s.role)+": "+(tip||st))}</title></rect></g>`}

function scene(){
  const P=typeof posts==="function"&&S?posts():[], rev=typeof toReview==="function"&&S?toReview().length:0;
  const ready=P.filter(p=>["ready","approved"].includes(p.status)).length;
  const hour=+new Date().toLocaleString("en-GB",{timeZone:"Europe/Amsterdam",hour:"2-digit",hour12:false});
  const night=hour<7||hour>=19, sky=night?"#0b1030":hour<9||hour>=17?"#f08a4b":"#7ec8ff";
  const macBusy=["battle","podcast","nieuws","community"].some(id=>(AG[id]||{}).state==="bezig");
  let s=`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges" class="of-svg">`;
  s+=r(0,0,W,H,"#121214")+r(0,0,W,26,"#2e2e33");
  for(let i=0;i<5;i++){const wx=14+i*48;s+=r(wx,5,30,15,"#555")+r(wx+1,6,28,13,sky);
    if(night)s+=r(wx+5+i%3*6,8+i%2*4,1,1,"#fff")+r(wx+19-i%2*5,12,1,1,"#ffd")+(i===2?r(wx+22,8,3,3,"#f5f3ce"):"");
    else s+=r(wx+3,15,24,4,"#5aa05a")+(i===1?r(wx+20,8,4,4,"#ffe066"):"");
    s+=r(wx+14,6,1,13,"#555")}
  s+=`<text x="${W-6}" y="23" class="of-wall" text-anchor="end">SIDEWAYS WIRE HQ</text>`;
  for(const R of ROOMS){s+=r(R.x,R.y,R.w,R.h,R.floor)+`<rect x="${R.x}" y="${R.y}" width="${R.w}" height="${R.h}" fill="none" stroke="#3a3a40" stroke-width="2"/>`;
    for(let yy=R.y+8;yy<R.y+R.h;yy+=8)s+=r(R.x+1,yy,R.w-2,1,"rgba(255,255,255,.025)");
    s+=`<text x="${R.x+4}" y="${R.y+7}" class="of-room">${R.label}</text>`}
  // deuropeningen
  s+=r(110,60,6,14,"#1a1a1d")+r(214,140,6,14,"#1a1a1d")+r(40,100,20,8,"#1a1a1d")+r(160,100,20,8,"#1a1a1d")+r(260,100,20,8,"#1a1a1d");
  // planten en details
  for(const [px,py] of [[100,84],[304,84],[100,180],[206,180]])s+=r(px,py+4,6,6,"#8a5a3a")+r(px-1,py,8,5,"#3fa34d")+r(px+1,py-3,4,4,"#4fc35d");
  s+=r(10,36,14,9,"#eee")+r(11,37,12,7,"#fff")+`<text x="17" y="43" class="of-tiny" text-anchor="middle">PLAN</text>`;   // whiteboard directie
  // koffie-automaat in de redactie
  s+=r(300,36,10,16,"#555")+r(302,38,6,4,"#222")+r(304,46,2,3,"#8a5a3a");
  // Joshua's bureau met inbox-stapel
  const jx=230,jy=138, pile=Math.min(10,Math.ceil(rev/6));
  s+=`<g class="of-seat" data-of="joshua">`+r(jx+4,jy-2,24,8,"#3a3a40")+r(jx,jy+4,40,10,"#5a4030")+r(jx,jy+4,40,2,"#7a5638")+r(jx+1,jy+14,2,6,"#3a2a1a")+r(jx+37,jy+14,2,6,"#3a2a1a");
  s+=r(jx+14,jy-6,14,10,"#111")+r(jx+15,jy-5,12,8,"#2b3a46")+`<text x="${jx+21}" y="${jy}" class="of-tiny" text-anchor="middle" fill="#C6FF00">${ready}</text>`;
  for(let i=0;i<pile;i++)s+=r(jx+3,jy+3-i*1.4,9,1.4,i%2?"#f5f5f5":"#ddd");
  if(rev)s+=`<text x="${jx+7}" y="${jy-pile*1.4-1}" class="of-tiny of-blink" text-anchor="middle" fill="#FF2E88">${rev}</text>`;
  s+=`<text x="${jx+20}" y="${jy+24}" class="of-tiny" text-anchor="middle">LEGE STOEL: JIJ</text><rect x="${jx-2}" y="${jy-12}" width="44" height="34" fill="transparent"/></g>`;
  // Mac Studio-serverkast
  const mx=286,my=114;
  s+=`<g class="of-seat" data-of="mac">`+r(mx,my,22,22,"#2a2a2e")+r(mx+1,my+1,20,20,"#bfc3c8")+r(mx+3,my+16,16,2,"#9aa0a6");
  for(let i=0;i<4;i++)s+=r(mx+4+i*4,my+4,2,2,macBusy?(i%2?"#C6FF00":"#5BC0FF"):"#555",macBusy?`class="of-blink" style="animation-delay:${i*.2}s"`:"");
  s+=`<text x="${mx+11}" y="${my+13}" class="of-tiny" text-anchor="middle" fill="#333">MAC</text></g>`;
  for(const [id,seat] of Object.entries(SEATS)){
    const a=AG[id]||{},c=((AGCFG||{}).agents||{})[id]||{},st=c.on===false?"uit":(a.state||"wacht");
    if(id==="wachter")continue;
    s+=desk(id,seat,a,st)}
  // systeemwachter loopt zijn ronde door de gang
  const w=AG.wachter||{},wst=w.state||"wacht";
  s+=`<g class="of-seat of-walk" data-of="wachter">${person(0,0,SEATS.wachter.look,wst)}${r(1,11,2,3,"#333")}${r(5,11,2,3,"#333")}<rect x="-3" y="-3" width="14" height="20" fill="transparent"/></g>`;
  return s+`</svg>`}

function bubbles(){
  let h="";
  for(const [id,seat] of Object.entries(SEATS)){if(id==="wachter")continue;
    const a=AG[id]||{},c=((AGCFG||{}).agents||{})[id]||{},st=c.on===false?"uit":(a.state||"wacht");
    let t=st==="fout"?"Hulp! "+((a.errors||[]).slice(-1)[0]||"er ging iets mis"):a.doing||((a.history||[])[0]||{}).text||"";
    if(!["bezig","fout"].includes(st)||!t)continue;          // alleen wie bezig is of hulp nodig heeft praat
    t=t.length>40?t.slice(0,38)+"…":t;
    h+=`<div class="of-bub of-${st}" style="left:${(seat.x+16)/W*100}%;top:${(seat.y-14)/H*100}%">${esc(t)}</div>`}
  return h}


// ---------- game-laag: levels per agent en dagopdrachten voor Joshua ----------
const XP_OF={
  battle:P=>P.filter(p=>["battle","live"].includes(cat(p))).length,
  podcast:P=>P.filter(p=>["pod","vlog"].includes(cat(p))).length,
  nieuws:P=>P.filter(p=>cat(p)==="posts").length,
  community:()=>(S.replies||[]).length,
  qc:P=>Math.round(P.filter(p=>p.qc).length/4),
  scout:()=>(S.inbox||[]).length,
};
window.agentLevel=function(id){
  const P=S?posts():[],a=AG[id]||{},base=XP_OF[id]?XP_OF[id](P):0;
  const xp=(base+(a.history||[]).length)*10,lvl=Math.floor(Math.sqrt(xp/40))+1,cur=40*(lvl-1)**2,next=40*lvl**2;
  return {xp,lvl,pct:Math.max(0,Math.min(100,Math.round((xp-cur)/(next-cur)*100)))}};
const today=()=>new Date().toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"});
window.officeWeek=function(){
  const P=S?posts():[],wk=Date.now()-7*864e5,in7=t=>t&&new Date(t)>wk;
  return {made:P.filter(p=>in7(p.created||p.built)).length,live:P.filter(p=>p.status==="posted"&&in7(p.posted_at)).length,
    ok:P.filter(p=>p.approved_by==="joshua"&&in7(p.approved)).length,
    top:Object.keys(SEATS).map(id=>({id,n:(AG[id]||{}).name||SEATS[id].role,...agentLevel(id)})).sort((a,b)=>b.xp-a.xp).slice(0,3)}};
function weekHTML(){const W=officeWeek(),sun=new Date().toLocaleDateString("en-GB",{timeZone:"Europe/Amsterdam",weekday:"long"})==="Sunday";
  return `<div class="of-q" style="margin-top:14px;${sun?"border-color:#C6FF00":""}"><div class="of-q-h">${sun?"WEEKFINALE":"DEZE WEEK"} <b>uitslag</b></div>
    <div class="of-week">${W.top.map((t,i)=>`<div class="p${i+1}"><span>${["🥇","🥈","🥉"][i]}</span><b>${esc(t.n)}</b><small>LV ${t.lvl}</small></div>`).join("")}</div>
    <div class="of-wk"><div><b>${W.made}</b><span>gemaakt</span></div><div><b>${W.ok}</b><span>door jou goedgekeurd</span></div><div><b>${W.live}</b><span>live gegaan</span></div></div></div>`}
window.officeQuests=function(){
  const P=S?posts():[],rev=S?toReview().length:0,d=today();
  const appr=P.filter(p=>p.approved_by==="joshua"&&p.approved&&new Date(p.approved).toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"})===d).length;
  const tips=((typeof TIPS!=="undefined"&&TIPS.tips)||[]).filter(t=>(t.at||"").slice(0,10)===d).length;
  const errs=Object.values(AG).filter(a=>a.state==="fout").length;
  return [
    {t:"Stapel leeg",d:rev?`nog ${rev} te beoordelen`:"alles beoordeeld",done:rev===0,href:"#beoordelen"},
    {t:"10 posts goedgekeurd",d:`${Math.min(appr,10)} van 10 vandaag`,done:appr>=10,pct:Math.min(100,appr*10),href:"#beoordelen"},
    {t:"Tip een nieuwtje",d:tips?"gedaan":"plak een link bij AGENTS",done:tips>0,href:"#agents"},
    {t:"Geen storingen",d:errs?`${errs} agent${errs>1?"s":""} met een fout`:"alles draait",done:errs===0,href:"#agents"}]};
function questsHTML(){const Q=officeQuests(),n=Q.filter(q=>q.done).length;
  const st=window.officeStreak?officeStreak():0;
  return `<div class="of-q"><div class="of-q-h">DAGOPDRACHTEN <b>${st?`🔥 ${st} ${st>1?"dagen":"dag"} · `:""}${n}/${Q.length}</b></div>${Q.map(q=>`<a class="of-q-i ${q.done?"ok":""}" href="${q.href}"><span>${q.done?"✓":"○"}</span><div><b>${q.t}</b><small>${q.d}</small>${q.pct!=null&&!q.done?`<i><em style="width:${q.pct}%"></em></i>`:""}</div></a>`).join("")}</div>`}

function hud(){
  const P=S?posts():[],rev=S?toReview().length:0,ready=P.filter(p=>["ready","approved"].includes(p.status)).length;
  const busy=Object.values(AG).filter(a=>a.state==="bezig").length,err=Object.values(AG).filter(a=>a.state==="fout").length;
  const posted=P.filter(p=>p.status==="posted").length;
  const item=(l,v,c,href)=>`<a class="of-hud-i" ${href?`href="${href}"`:""}><span>${l}</span><b style="color:${c}">${v}</b></a>`;
  return item("AAN HET WERK",busy,"#C6FF00","")+item("WACHT OP JOU",rev,rev?"#FF2E88":"#fff","#beoordelen")+item("VOORRAAD",ready,"#5BC0FF","#planning")+item("GEPLAATST",posted,"#fff","#stats")+item("PROBLEMEN",err,err?"#FF2E88":"#7a7a80","#agents")}

function panel(){
  const el=document.getElementById("of-panel");if(!pick){
    const L=Object.keys(SEATS).map(id=>({id,n:(AG[id]||{}).name||SEATS[id].role,...agentLevel(id)})).sort((a,b)=>b.xp-a.xp).slice(0,6);
    const A=window.officeAchievements?officeAchievements():[],F=window.officeFollowers?officeFollowers():0;
    const next=[[1000,"een tribune langs het pad"],[10000,"een tweede tribune"],[100000,"een eigen arena met dak"]].find(([n])=>F<n);
    el.innerHTML=questsHTML()+`<div class="of-q-h" style="margin-top:14px">PRESTATIES <b>${A.filter(a=>a.at).length}/${A.length}</b></div><div class="of-ach">${A.map(a=>`<span class="${a.at?"ok":""}" title="${a.at?"behaald "+a.at:"nog niet behaald"}">${a.at?"🏆":"🔒"} ${esc(a.t)}</span>`).join("")}</div>
    ${next?`<p class="muted" style="font-size:12px;margin:10px 0 0">Het terrein groeit mee: bij ${next[0].toLocaleString("nl-NL")} volgers komt er ${next[1]} (nu ${F}).</p>`:""}
    ${weekHTML()}
    <div class="of-q-h" style="margin-top:14px">RANGLIJST</div>${L.map((x,i)=>`<div class="of-rank" data-of="${x.id}"><span>${i+1}</span><b>${esc(x.n)}</b><small>LV ${x.lvl}</small></div>`).join("")}<p class="muted" style="font-size:12px;margin-top:10px">Klik op iemand in het kantoor voor details.</p>`;return}
  if(pick==="joshua"){const R=S?toReview().sort((a,b)=>hot(b)-hot(a)||(b.urgency||0)-(a.urgency||0)):[],n=R.length,p=R[0];
    const m=p&&(p.media||[])[0],vid=m&&/\.mp4/.test(m);
    el.innerHTML=`<h2>JOUW BUREAU</h2><p>${n?`Er liggen <b>${n}</b> posts op je stapel.`:"Je stapel is leeg. Lekker bezig."}</p>
    ${p?`<div class="of-rev" data-rid="${esc(p.id)}"><div class="muted" style="font-size:11px;letter-spacing:1px">BOVENOP DE STAPEL</div>
      ${m?(vid?`<video src="${esc(m)}" muted loop autoplay playsinline></video>`:`<img src="${esc(m)}" alt="">`):""}
      <b>${esc(p.title||p.hook||p.id)}</b>${p.check_reason?`<small style="color:#FF9F43">Let op: ${esc(p.check_reason)}</small>`:""}
      <small>${esc((p.caption||"").slice(0,160))}${(p.caption||"").length>160?"…":""}</small>
      <div class="row" style="gap:6px;margin-top:8px;flex-wrap:wrap"><button class="btn g" data-ofrev="ok">GOEDKEUREN</button><button class="btn p" data-ofrev="skip">OVERSLAAN</button><a class="btn" href="#beoordelen/${esc(p.id)}">OPENEN</a></div></div>`:""}
    <div style="margin-top:14px">${questsHTML()}</div>`;return}
  if(pick==="mac"){const L=["battle","podcast","nieuws","community"].map(id=>`<div style="margin:3px 0"><b>${esc((AG[id]||{}).name||id)}</b>: ${esc((AG[id]||{}).state||"wacht")}${(AG[id]||{}).doing?" · "+esc(AG[id].doing):""}</div>`).join("");
    const K=window.officeKeys?officeKeys():[],col={ok:"#C6FF00","verloopt bijna":"#FF9F43",verlopen:"#FF2E88","werkt niet":"#FF2E88"};
    const KS=K.length?K.map(k=>`<div class="of-key"><i style="background:${col[k.state]||"#7a7a80"}"></i><b>${esc(k.name)}</b><small>${esc(k.state)}${k.expires?` · verloopt ${new Date(k.expires).toLocaleDateString("nl-NL",{day:"numeric",month:"short",year:"numeric"})}${k.days_left!=null?` (${Math.max(0,Math.round(k.days_left))} dagen)`:""}`:k.state==="ok"?" · verloopt niet":""}${k.note?" · "+esc(k.note):""}</small></div>`).join(""):`<p class="muted">De sleutels worden een keer per dag gecontroleerd; de eerste controle volgt bij de volgende ronde.</p>`;
    el.innerHTML=`<h2>SERVERKAST</h2><p class="muted">Hier draaien de redacteuren met het lokale taalmodel op de Mac Studio, en worden de clips geknipt.</p>${L}
      <div class="of-q-h" style="margin-top:14px">SLEUTELS</div>${KS}
      <p class="muted" style="font-size:12px">Rookt de kast of draait er een rood zwaailicht op je garage, dan verloopt hier binnen 7 dagen iets of werkt iets niet.</p>`;return}
  const a=AG[pick]||{},c=((AGCFG||{}).agents||{})[pick]||{},st=c.on===false?"uit":(a.state||"wacht"),H=(a.history||[]).slice(0,6);
  el.innerHTML=`<h2><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${STC[st]};margin-right:8px"></span>${esc(a.name||SEATS[pick].role)}</h2>
    <p class="muted" style="margin:2px 0 8px">${esc(SEATS[pick].role)} · ${esc(a.where||"")} · ${esc(st.toUpperCase())}${a.updated?" · "+ago(a.updated):""}</p>
    ${(()=>{const L=agentLevel(pick);return `<div class="of-lv"><b>LEVEL ${L.lvl}</b><span>${L.xp} XP</span><i><em style="width:${L.pct}%"></em></i></div>`})()}
    <p>${a.doing?esc(a.doing):`<span class="muted">Niets te doen op dit moment.</span>`}</p>
    ${a.briefing?`<p style="border-left:3px solid #C6FF00;padding-left:8px;white-space:pre-line">${esc(a.briefing)}</p>`:""}
    ${a.plan?`<p style="border-left:3px solid #5BC0FF;padding-left:8px;white-space:pre-line">${esc(a.plan)}</p>`:""}
    ${typeof problemsHTML==="function"?problemsHTML(pick):""}
    <textarea class="of-note" data-ofnote="${pick}" placeholder="Instructie voor ${esc(a.name||SEATS[pick].role)}, bijvoorbeeld: meer Drift Masters">${esc(c.note||"")}</textarea>
    <button class="btn" data-ofnotesave="${pick}" style="margin-top:6px">INSTRUCTIE OPSLAAN</button>
    <div class="muted" style="font-size:12px;letter-spacing:1px;margin-top:10px">LAATST GEDAAN</div>
    ${H.length?H.map(h=>`<div style="font-size:13px;margin:3px 0"><span class="muted">${fmtWhen(h.at)}</span> · ${esc(h.text)}</div>`).join(""):`<div class="muted">Nog niets gedaan.</div>`}
    <div class="row" style="gap:8px;margin-top:10px;flex-wrap:wrap"><a class="btn" href="#agents">BIJSTUREN</a><button class="btn ${c.on===false?"g":""}" data-oftoggle="${pick}">${c.on===false?"AANZETTEN":"UITZETTEN"}</button><button class="btn" data-close>TERUG</button></div>`}

function draw(){
  const box=document.getElementById("of-box");if(!box)return;
  box.innerHTML=scene()+bubbles();
  document.getElementById("of-hud").innerHTML=hud();
  panel()}

window.officePick=id=>{pick=id;panel()};
window.drawOffice=async function(){
  const b3=document.getElementById("of3"),b2=document.getElementById("of-box");
  document.getElementById("of-hud").innerHTML=hud();panel();
  try{await loadAgents()}catch(e){}
  document.getElementById("of-hud").innerHTML=hud();panel();
  // 3D-terrein als de browser het kan; anders het pixel-kantoor
  const use3d=window.office3d&&!window.__no3d&&office3d.start();
  b3.parentElement.style.display=use3d?"":"none";b2.style.display=use3d?"none":"";
  if(!use3d)draw();
  clearInterval(timer);timer=setInterval(()=>{if(!location.hash.startsWith("#kantoor")||document.hidden){if(window.office3d)office3d.stop();return}
    document.getElementById("of-hud").innerHTML=hud();panel();if(use3d){office3d.start()}else draw()},30000)};
window.addEventListener("hashchange",()=>{if(!location.hash.startsWith("#kantoor")&&window.office3d)office3d.stop()});

document.addEventListener("click",async e=>{
  const rv=e.target.closest&&e.target.closest("[data-ofrev]");
  if(rv){if(!key){toast("Zet eerst de dashboard-sleutel.",1);return}const id=rv.closest("[data-rid]").dataset.rid,a=rv.dataset.ofrev,p=posts().find(x=>x.id===id);rv.disabled=true;
    try{if(a==="ok"){await changePost(id,x=>{x.status="approved";x.check=false;x.approved_by="joshua";x.approved=new Date().toISOString();delete x.want_at},"approve");
        Object.assign(p,{status:"approved",check:false,approved_by:"joshua",approved:new Date().toISOString()});remember("post",id,"approved");toast("Goedgekeurd.");if(window.officePing)officePing(990);runBuild().catch(()=>{})}
      else{await changePost(id,x=>{x.status="skipped"},"skip");p.status="skipped";remember("post",id,"skipped");toast("Overgeslagen.")}
      drawCounts();document.getElementById("of-hud").innerHTML=hud();panel();if(window.office3d)office3d.update()}catch(x){toast(x.message,1);rv.disabled=false}return}
  const ns=e.target.closest&&e.target.closest("[data-ofnotesave]");
  if(ns){if(!key){toast("Zet eerst de dashboard-sleutel.",1);return}const id=ns.dataset.ofnotesave,v=document.querySelector(`[data-ofnote="${id}"]`).value.trim();ns.disabled=true;
    try{await saveAgents(d=>{const c=d.agents[id]=d.agents[id]||{on:true,note:""};c.note=v;c.by="joshua";c.locked=true});toast("Instructie opgeslagen. De agent gebruikt hem vanaf de volgende ronde.")}catch(x){toast(x.message,1)}ns.disabled=false;return}
  const tg=e.target.closest&&e.target.closest("[data-oftoggle]");
  if(tg){if(!key){toast("Zet eerst de dashboard-sleutel.",1);return}const id=tg.dataset.oftoggle;tg.disabled=true;
    try{await saveAgents(d=>{const c=d.agents[id]=d.agents[id]||{on:true,note:""};c.on=c.on===false});panel();if(window.office3d)office3d.update();toast("Opgeslagen. Werkt vanaf de volgende ronde.")}catch(x){toast(x.message,1)}tg.disabled=false;return}
  if(e.target.closest&&e.target.closest("#of-panel [data-close]")){pick=null;panel();return}
  const g=e.target.closest&&e.target.closest("#s-kantoor [data-of]");if(!g)return;if(g.classList.contains("of-rank")&&window.office3d){const id=g.dataset.of;pick=id;panel();window.dispatchEvent(new CustomEvent("office-focus",{detail:id}));return}
  pick=g.dataset.of;panel();document.querySelectorAll("#s-kantoor .of-seat").forEach(x=>x.classList.toggle("of-sel",x.dataset.of===pick))});
})();
window.addEventListener("office3d-ready",()=>{if(location.hash.startsWith("#kantoor")&&typeof S!=="undefined"&&S)drawOffice()});
