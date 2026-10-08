const AGENTS={momentum:"Momentum",mean_reversion:"Mean Reversion",event_driven:"Event Driven",mcx:"MCX Specialist",arbitrage:"Cross-Market",research:"Research",bull:"Bull",bear:"Bear",quant:"Quant",news:"News/Social",redteam:"Red Team",risk:"Risk",chief:"Chief"};
const S={events:[],status:{},markets:{GOLD:"—",SILVER:"—",CRUDEOIL:"—",NATURALGAS:"—",COPPER:"—"},live:false,evidence:null,portfolio:null,trades:[]};
Object.keys(AGENTS).forEach(k=>S.status[k]="IDLE");
const $=id=>document.getElementById(id);

function render(){
  $("clock").textContent=new Date().toLocaleTimeString();
  $("agents").innerHTML=Object.entries(AGENTS).map(([k,n])=>'<div class="row"><span>'+n+'</span><span class="pill '+(S.status[k]==="WORKING"?"good":"")+'">'+S.status[k]+"</span></div>").join("");
  $("markets").innerHTML=Object.entries(S.markets).map(([k,v])=>'<div class="row"><span>'+k+"</span><span>"+v+"</span></div>").join("");
  if(S.portfolio){
    const p=S.portfolio;
    const pnlClass=Number(p.daily_pnl||0)>=0?"good":"bad";
    $("portfolio").innerHTML=
      '<div class="stats-grid">'+
      '<div><small>Equity</small><b>₹'+Number(p.equity||0).toFixed(2)+'</b></div>'+
      '<div><small>Cash</small><b>₹'+Number(p.cash||0).toFixed(2)+'</b></div>'+
      '<div><small>Daily P&L</small><b class="'+pnlClass+'">₹'+Number(p.daily_pnl||0).toFixed(2)+'</b></div>'+
      '<div><small>Realized</small><b>₹'+Number(p.realized_pnl||0).toFixed(2)+'</b></div>'+
      '<div><small>Unrealized</small><b>₹'+Number(p.unrealized_pnl||0).toFixed(2)+'</b></div>'+
      '<div><small>Open</small><b>'+Number(p.open_positions||0)+'</b></div>'+
      '<div><small>Total Trades</small><b>'+Number(p.total_paper_trades||0)+'</b></div>'+
      '<div><small>Exposure</small><b>'+((Number(p.gross_exposure_fraction||0))*100).toFixed(2)+'%</b></div>'+
      '</div>';
  }
  $("trades").innerHTML=S.trades.slice(-12).reverse().map(t=>{
    const pnl=t.pnl===undefined?"":' P&L ₹'+Number(t.pnl).toFixed(2);
    return '<div class="trade '+(t.action==="OPEN"?"open":"close")+'"><b>'+t.action+'</b> '+t.symbol+' '+t.side+' × '+t.quantity+' @ '+Number(t.price||0).toFixed(2)+pnl+'<small>'+(t.reason||("score "+Number(t.score||0).toFixed(2)))+'</small></div>';
  }).join("") || '<div class="muted">No paper trades yet.</div>';
  $("activity").innerHTML=S.events.slice(-35).reverse().map(e=>'<div class="event"><small>'+e.time+'</small><b>'+e.agent+"</b> — "+e.text+"</div>").join("");
  if(S.evidence){
    const f=S.evidence.features||{}, v=S.evidence.votes||{};
    const features=Object.entries(f).map(([k,val])=>'<span class="evidence-chip">'+k+' '+val+'</span>').join("");
    const votes=Object.entries(v).map(([k,val])=>'<div class="row"><span>'+k+'</span><span>'+Number(val).toFixed(3)+'</span></div>').join("");
    $("evidence").innerHTML='<b>'+S.evidence.symbol+'</b><div class="chips">'+features+'</div>'+votes+'<div class="evidence-decision">Decision: '+(S.evidence.decision||"ANALYZING")+'</div>';
  }
}

const WORK_ROUTES={
  research:["momentum","event_driven","mcx","chief"],
  momentum:["research","chief","risk"],
  mean_reversion:["research","chief","risk"],
  event_driven:["research","chief","risk"],
  mcx:["research","momentum","chief"],
  arbitrage:["research","risk","chief"],
  bull:["quant","chief","discussion"],
  bear:["quant","risk","chief"],
  quant:["chief","risk","discussion"],
  news:["research","chief","discussion"],
  redteam:["risk","chief"],
  risk:["chief","trading"],
  chief:["risk","trading","discussion"]
};
const LAST_SPOT={};

function centerOf(el,container){
  if(!el)return null;
  const a=el.getBoundingClientRect(), b=container.getBoundingClientRect();
  return {x:a.left+a.width/2-b.left,y:a.top+a.height/2-b.top};
}
function ensureRoamer(id){
  const layer=$("roaming-layer");
  let el=$(id);
  if(!layer||!el)return null;
  let r=document.getElementById("roamer-"+id);
  if(!r){
    r=document.createElement("div");
    r.id="roamer-"+id;
    r.className="roamer worker-suit";
    r.innerHTML='<span class="worker-head"></span><span class="worker-body"></span><span class="worker-label">'+(AGENTS[id]||id)+'</span>';
    layer.appendChild(r);
  }
  return r;
}
function moveWorker(id,text){
  const layer=$("roaming-layer"), home=$(id);
  if(!layer||!home)return;
  const targets=WORK_ROUTES[id]||["chief","risk"];
  const lower=(text||"").toLowerCase();
  let targetId=targets.find(t=>lower.includes(t.replace("_"," ")))||targets[0];
  if(targetId==="discussion")targetId="quant";
  if(targetId==="trading")targetId="walker";
  const target=$(targetId);
  if(!target)return;
  const start=LAST_SPOT[id]||centerOf(home,layer);
  const end=targetId==="walker"
    ? centerOf($("walker"),layer)
    : centerOf(target,layer);
  if(!start||!end)return;
  const r=ensureRoamer(id);
  if(!r)return;
  home.classList.add("home-hidden");
  r.style.left=start.x+"px"; r.style.top=start.y+"px";
  r.classList.remove("moving");
  void r.offsetWidth;
  r.style.setProperty("--tx",end.x-start.x+"px");
  r.style.setProperty("--ty",end.y-start.y+"px");
  r.classList.add("moving");
  const duration=Math.min(5200,Math.max(1800,Math.hypot(end.x-start.x,end.y-start.y)*4));
  setTimeout(()=>{
    r.style.left=end.x+"px"; r.style.top=end.y+"px"; r.classList.remove("moving");
    LAST_SPOT[id]={x:end.x,y:end.y};
  },duration);
}
function event(id,text,move=true){
  if(S.status[id]!==undefined)S.status[id]="WORKING";
  const el=$(id);
  if(el){
    el.classList.add("busy");
    setTimeout(()=>el.classList.remove("busy"),1800);
  }
  if(move)moveWorker(id,text);
  S.events.push({time:new Date().toLocaleTimeString(),agent:AGENTS[id]||id,text});
  if(S.events.length>100)S.events.shift();
  render();
}

function applySnapshot(x){
  S.evidence=x;
  if($("debate")&&x.debate)$("debate").textContent=x.debate;
}

function connect(){
  const es=new EventSource("/events");
  es.onopen=()=>{
    S.live=true;
    $("conn").textContent="● LIVE ENGINE";
    $("conn").style.color="var(--good)";
  };
  es.onmessage=e=>{
    try{
      const x=JSON.parse(e.data);
      if(x.type==="status")Object.assign(S.status,x.status||{});
      else if(x.type==="market")S.markets[x.symbol]=x.value;
      else if(x.type==="portfolio")S.portfolio=x;
      else if(x.type==="trade"){S.trades.push(x);if(S.trades.length>100)S.trades.shift();}
      else if(x.type==="activity")event(x.agent,x.text,x.move!==false);
      else if(x.type==="snapshot")applySnapshot(x);
      else if(x.type==="heartbeat")event("research",x.text,false);
      render();
    }catch(err){}
  };
  es.onerror=()=>{
    S.live=false;
    $("conn").textContent="● WAITING FOR ENGINE";
    $("conn").style.color="var(--warn)";
  };
}
setInterval(render,1000);
render();
connect();