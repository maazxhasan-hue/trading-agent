const AGENTS={momentum:"Momentum",mean_reversion:"Mean Reversion",event_driven:"Event Driven",mcx:"MCX Specialist",arbitrage:"Cross-Market",research:"Research",bull:"Bull",bear:"Bear",quant:"Quant",news:"News/Social",redteam:"Red Team",risk:"Risk",chief:"Chief"};
const S={events:[],status:{},analysis:[],markets:{GOLD:"—",SILVER:"—",CRUDEOIL:"—",NATURALGAS:"—",COPPER:"—"},quotes:{},live:false,evidence:null,portfolio:null,trades:[],candles:{},learning:null,activeMarket:null};
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"\']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","\'":"&#39;"}[ch]));

function render(){
  $("clock").textContent=new Date().toLocaleTimeString();
  $("agents").innerHTML=Object.entries(AGENTS).map(([k,n])=>{
    const st=S.status[k]||"NOT RUN / NO DATA";
    return '<div class="row"><span>'+n+'</span><span class="pill '+(["WORKING","ACTIVE"].includes(st)?"good":"")+'">'+esc(st)+"</span></div>";
  }).join("");
  $("markets").innerHTML=Object.entries(S.markets).map(([k,v])=>{
    const q=S.quotes[k]||{};
    const age=q.quote_timestamp?Math.max(0,(Date.now()/1000)-Number(q.quote_timestamp)):null;
    const freshness=age!==null&&isFinite(age)?age.toFixed(1)+"s":"research";
    return '<div class="row market-row '+(S.activeMarket===k?"selected":"")+'" data-symbol="'+k+'"><span><b>'+k+'</b><small>'+((q.provider)||"engine feed")+'</small></span><span><b>'+v+'</b><small>'+freshness+'</small></span></div>';
  }).join("");
  document.querySelectorAll(".market-row").forEach(el=>el.onclick=()=>{S.activeMarket=el.dataset.symbol;renderCandlePanel();});
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
  renderCandlePanel();
  renderLearning();
  renderAnalysis();
  $("trades").innerHTML=S.trades.slice(-12).reverse().map(t=>{
    const pnl=t.pnl===undefined?"":' P&L ₹'+Number(t.pnl).toFixed(2);
    return '<div class="trade '+(t.action==="OPEN"?"open":"close")+'"><b>'+esc(t.action)+'</b> '+esc(t.symbol)+' '+esc(t.side)+' × '+esc(t.quantity)+' @ '+Number(t.price||0).toFixed(2)+esc(pnl)+'<small>'+esc(t.reason||("score "+Number(t.score||0).toFixed(2)))+'</small></div>';
  }).join("") || '<div class="muted">No paper trades yet.</div>';
  $("activity").innerHTML=S.events.slice(-35).reverse().map(e=>'<div class="event"><small>'+esc(e.time)+'</small><b>'+esc(e.agent)+"</b> — "+esc(e.text)+"</div>").join("");
  if(S.evidence){
    const f=S.evidence.features||{}, v=S.evidence.votes||{};
    const features=Object.entries(f).map(([k,val])=>'<span class="evidence-chip">'+esc(k)+' '+esc(val)+'</span>').join("");
    const votes=Object.entries(v).map(([k,val])=>'<div class="row"><span>'+esc(k)+'</span><span>'+Number(val).toFixed(3)+'</span></div>').join("");
    $("evidence").innerHTML='<b>'+esc(S.evidence.symbol)+'</b><div class="chips">'+features+'</div>'+votes+'<div class="evidence-decision">Decision: '+esc(S.evidence.decision||"ANALYZING")+'</div>';
  }
}

const WORK_ROUTES={
  research:["momentum","event_driven","mcx","arbitrage","chief","risk"],
  momentum:["research","chief","risk","mean_reversion","event_driven"],
  mean_reversion:["momentum","research","chief","risk","event_driven"],
  event_driven:["research","momentum","mcx","chief","risk","redteam"],
  mcx:["research","momentum","chief","risk","event_driven"],
  arbitrage:["research","mcx","risk","chief","quant"],
  bull:["quant","chief","research","discussion","risk"],
  bear:["quant","risk","chief","redteam","discussion"],
  quant:["bull","bear","chief","risk","research","discussion"],
  news:["research","chief","discussion","event_driven","quant"],
  redteam:["risk","chief","research","discussion"],
  risk:["chief","redteam","trading","research","momentum"],
  chief:["research","risk","trading","discussion","mcx","quant"]
};
const LAST_SPOT={};
const PATROL_INDEX={};

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
    r.innerHTML='<span class="worker-head"></span><span class="worker-body"></span><span class="worker-label">'+esc(AGENTS[id]||id)+'</span>';
    layer.appendChild(r);
  }
  return r;
}
function moveWorker(id,text){
  const layer=$("roaming-layer"), home=$(id);
  if(!layer||!home)return;
  const targets=WORK_ROUTES[id]||["chief","risk"];
  const lower=(text||"").toLowerCase();
  let targetId=targets.find(t=>lower.includes(t.replace("_"," ")));
  if(!targetId){
    PATROL_INDEX[id]=((PATROL_INDEX[id]||0)+1)%targets.length;
    targetId=targets[PATROL_INDEX[id]];
  }
  if(targetId==="discussion")targetId="quant";
  if(targetId==="trading")targetId="walker";
  const target=$(targetId);
  if(!target)return;
  const start=LAST_SPOT[id]||centerOf(home,layer);
  const end=targetId==="walker"?centerOf($("walker"),layer):centerOf(target,layer);
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

function start24x7Patrol(){
  // Every worker gets a real cabin-to-cabin route. The patrol is visual only;
  // real engine events always take priority over the next patrol destination.
  Object.keys(AGENTS).forEach((id,i)=>{
    setTimeout(()=>moveWorker(id,"continuous cabin patrol"),700+i*260);
  });
  setInterval(()=>{
    Object.keys(AGENTS).forEach((id,i)=>{
      if(S.status[id]!=="WORKING")S.status[id]="MONITORING";
      setTimeout(()=>moveWorker(id,"continuous cabin patrol"),i*180);
    });
    render();
  },8000);
}

function renderCandlePanel(){
  const symbol=S.activeMarket||Object.keys(S.candles)[0]||Object.keys(S.markets)[0];
  if(!symbol)return;
  S.activeMarket=symbol;
  const rows=S.candles[symbol]||[];
  const q=S.quotes[symbol]||{};
  const latest=rows[rows.length-1];
  const price=q.value!==undefined?q.value:(latest?latest.close:null);
  $("candle-symbol").textContent=symbol;
  $("candle-provider").textContent=(q.provider||"engine feed")+" • "+(q.interval||"5m");
  $("candle-price").textContent=price==null?"—":Number(price).toFixed(8);
  $("candle-ohlc").textContent=latest
    ? "O "+Number(latest.open).toFixed(4)+"  H "+Number(latest.high).toFixed(4)+"  L "+Number(latest.low).toFixed(4)+"  C "+Number(latest.close).toFixed(4)
    : "Waiting for candle data…";
  const svg=$("candle-chart");
  if(!svg)return;
  if(rows.length<2){svg.innerHTML='<text x="50%" y="50%" text-anchor="middle" class="chart-empty">Waiting for exact OHLC candles…</text>';return;}
  const data=rows.slice(-60), W=900,H=300,pad=24;
  const lo=Math.min(...data.map(x=>Number(x.low))), hi=Math.max(...data.map(x=>Number(x.high)));
  const span=Math.max(hi-lo,1e-9), slot=(W-pad*2)/data.length, body=Math.max(2,slot*.56);
  const y=v=>pad+(hi-v)/span*(H-pad*2);
  svg.innerHTML=data.map((d,i)=>{
    const x=pad+i*slot+slot/2, o=y(Number(d.open)), cl=y(Number(d.close)), h=y(Number(d.high)), l=y(Number(d.low));
    const up=Number(d.close)>=Number(d.open), top=Math.min(o,cl), bh=Math.max(2,Math.abs(cl-o));
    const stamp=d.time?new Date(d.time).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):"";
    return '<g class="candle '+(up?"up":"down")+'"><title>'+stamp+' O '+d.open+' H '+d.high+' L '+d.low+' C '+d.close+'</title><line x1="'+x+'" y1="'+h+'" x2="'+x+'" y2="'+l+'"/><rect x="'+(x-body/2)+'" y="'+top+'" width="'+body+'" height="'+bh+'" rx="1"/></g>';
  }).join("");
}
function renderAnalysis(){
  const box=$("analysis");
  if(!box)return;
  const rows=S.analysis.slice(-10).reverse().map(x=>{
    const ev=(x.evidence||[]).slice(0,3).join(" • ");
    return '<div class="analysis-card"><div class="analysis-top"><b>'+esc(x.agent||"Agent")+'</b><span>'+esc(x.symbol||"—")+'</span><span class="analysis-action">'+esc(x.action||"ANALYZING")+'</span></div><div class="analysis-thesis">'+esc(x.thesis||"Evaluating market evidence…")+'</div><div class="analysis-evidence">'+esc(ev||"No additional evidence reported")+'</div><small>confidence '+(x.confidence==null?"—":(Number(x.confidence)*100).toFixed(1)+"%")+' • adaptation '+esc(x.adaptation||"baseline")+'</small></div>';
  }).join("");
  box.innerHTML=rows||'<div class="muted">Waiting for agent analysis…</div>';
}
function renderLearning(){
  const l=S.learning;
  if(!l){$("learning").innerHTML='<div class="muted">Waiting for the learning engine…</div>';return;}
  const names=Object.keys(l.details||{});
  const rows=names.map(a=>{
    const d=l.details[a]||{}, acc=d.accuracy==null?"—":(Number(d.accuracy)*100).toFixed(1)+"%";
    const recent=d.recent_accuracy==null?"—":(Number(d.recent_accuracy)*100).toFixed(1)+"%";
    const weight=d.weight===undefined?(d.forecasts>=30?((Number(d.accuracy)-.5)*1.2+1).toFixed(2):"1.00"):Number(d.weight).toFixed(2);
    const delta=(Number(weight)-1);
    const adaptation=delta>0.02?"boosted":delta<-0.02?"reduced":"baseline";
    return '<div class="learning-row"><div><b>'+esc(a.replace("-v3",""))+'</b><small>'+esc((d.qualified?"QUALIFIED":"LEARNING")+" • "+(d.reason||"evaluating"))+'</small></div><div><span>'+Number(d.forecasts||0)+' forecasts</span><span>acc '+acc+'</span><span>recent '+recent+'</span><span>weight '+weight+' ('+adaptation+')</span></div></div>';
  }).join("");
  const last=(l.last_resolved||[]).slice(-4).reverse().map(x=>{
    const move=x.realized_move==null?"":(Number(x.realized_move)*100).toFixed(3)+"%";
    return '<div class="learn-event"><b>'+esc(x.market_id||"market")+'</b> '+(Number(x.outcome)>0?"UP":Number(x.outcome)<0?"DOWN":"NEUTRAL")+' <small>'+move+'</small></div>';
  }).join("");
  $("learning").innerHTML='<div class="learning-head"><b>Intelligence & Adaptation</b><span>'+Number(l.observations||0)+' observations • '+Number(l.history||0)+' resolved • '+Number(l.resolved||0)+' new</span></div>'+rows+'<div class="learning-new"><b>What changed recently</b>'+ (last||'<div class="muted">No resolved learning updates yet.</div>')+'</div>';
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
      else if(x.type==="market"){S.markets[x.symbol]=x.value;S.quotes[x.symbol]=x;if(!S.activeMarket)S.activeMarket=x.symbol;}
      else if(x.type==="candles"){S.candles[x.symbol]=x.candles||[];S.activeMarket=S.activeMarket||x.symbol;}
      else if(x.type==="learning")S.learning=x;
      else if(x.type==="agent_analysis"){S.analysis.push(x);if(S.analysis.length>100)S.analysis.shift();}
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
