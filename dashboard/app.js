const AGENTS={momentum:"Momentum",mean_reversion:"Mean Reversion",event_driven:"Event Driven",mcx:"MCX Specialist",arbitrage:"Cross-Market",research:"Research",bull:"Bull",bear:"Bear",quant:"Quant",news:"News/Social",redteam:"Red Team",risk:"Risk",chief:"Chief"};
const S={events:[],status:{},markets:{GOLD:"—",SILVER:"—",CRUDEOIL:"—",NATURALGAS:"—",COPPER:"—"},live:false,evidence:null};
Object.keys(AGENTS).forEach(k=>S.status[k]="IDLE");
const $=id=>document.getElementById(id);

function render(){
  $("clock").textContent=new Date().toLocaleTimeString();
  $("agents").innerHTML=Object.entries(AGENTS).map(([k,n])=>'<div class="row"><span>'+n+'</span><span class="pill '+(S.status[k]==="WORKING"?"good":"")+'">'+S.status[k]+"</span></div>").join("");
  $("markets").innerHTML=Object.entries(S.markets).map(([k,v])=>'<div class="row"><span>'+k+"</span><span>"+v+"</span></div>").join("");
  $("activity").innerHTML=S.events.slice(-35).reverse().map(e=>'<div class="event"><small>'+e.time+'</small><b>'+e.agent+"</b> — "+e.text+"</div>").join("");
  if(S.evidence){
    const f=S.evidence.features||{}, v=S.evidence.votes||{};
    const features=Object.entries(f).map(([k,val])=>'<span class="evidence-chip">'+k+' '+val+'</span>').join("");
    const votes=Object.entries(v).map(([k,val])=>'<div class="row"><span>'+k+'</span><span>'+Number(val).toFixed(3)+'</span></div>').join("");
    $("evidence").innerHTML='<b>'+S.evidence.symbol+'</b><div class="chips">'+features+'</div>'+votes+'<div class="evidence-decision">Decision: '+(S.evidence.decision||"ANALYZING")+'</div>';
  }
}

function event(id,text,move=true){
  if(S.status[id]!==undefined)S.status[id]="WORKING";
  const el=$(id);
  if(el){
    el.classList.add("busy");
    if(move)el.classList.add("move");
    setTimeout(()=>el.classList.remove("busy","move"),1800);
  }
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