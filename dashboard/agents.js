/* Individual agent observability. Every status and research entry is derived from the registry/API and actual engine events. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const state = {agents:[],selected:null,query:"",group:"all",updatedAt:null};
  const stamp = v => v ? new Date(v).toLocaleString() : "Not recorded";
  const fmt = v => v === null || v === undefined || v === "" ? "Not available" : String(v);
  async function loadDirectory() {
    try {
      const response = await fetch("/api/agents",{cache:"no-store"});
      if(!response.ok) throw new Error("Agent registry API returned "+response.status);
      const payload = await response.json();
      state.agents = payload.agents || [];
      state.updatedAt = payload.generated_at;
      $("agent-network-status").textContent = "REGISTRY CONNECTED · "+state.agents.length+" CONFIGURED ROLES";
      $("agent-network-status").className = "agent-network-status ok";
      renderDirectory();
      if(state.selected) await loadDetail(state.selected);
      else if(state.agents.length) await loadDetail(state.agents[0].id);
    } catch(error) {
      $("agent-network-status").textContent = "REGISTRY OFFLINE · "+error.message;
      $("agent-network-status").className = "agent-network-status warn";
      $("agent-directory").innerHTML = '<div class="muted">Cannot load real registry. No agent status is being simulated.</div>';
    }
  }
  function renderDirectory() {
    const rows = state.agents.filter(a => (state.group==="all" || a.group===state.group) &&
      (a.id+" "+a.title+" "+a.role+" "+a.mission).toLowerCase().includes(state.query.toLowerCase()));
    $("agent-directory-count").textContent = rows.length+" shown / "+state.agents.length+" configured";
    $("agent-directory").innerHTML = rows.map(a =>
      '<button type="button" class="agent-directory-card '+(state.selected===a.id?"selected":"")+'" data-agent-id="'+esc(a.id)+'">'+
      '<span class="agent-card-top"><b>'+esc(a.title)+'</b><i class="agent-state '+(a.status==="ACTIVE"?"active":a.status==="NOT RUN / NO DATA"?"unknown":"")+'">'+esc(a.status)+'</i></span>'+
      '<span class="agent-card-id">'+esc(a.id)+' · '+esc(a.group)+'</span><span class="agent-card-mission">'+esc(a.mission)+'</span>'+
      '<span class="agent-card-last">Last seen: '+esc(stamp(a.last_seen))+'</span></button>'
    ).join("") || '<div class="muted">No agents match this filter.</div>';
    document.querySelectorAll("[data-agent-id]").forEach(button => button.addEventListener("click",()=>loadDetail(button.dataset.agentId)));
  }
  function section(title,content) { return '<section class="agent-detail-section"><h4>'+esc(title)+'</h4>'+content+'</section>'; }
  async function loadDetail(id) {
    state.selected=id;
    renderDirectory();
    const box=$("agent-detail");
    box.innerHTML='<div class="muted">Loading real agent record…</div>';
    try {
      const response=await fetch("/api/agent?id="+encodeURIComponent(id),{cache:"no-store"});
      if(!response.ok) throw new Error("Agent detail returned "+response.status);
      const a=await response.json();
      const research=(a.research||[]).slice().reverse();
      const activity=(a.events||[]).slice().reverse();
      const researchHtml=research.length?research.map(x=>{
        const evidence=(x.evidence||[]).map(v=>'<li>'+esc(typeof v==="string"?v:JSON.stringify(v))+'</li>').join("");
        return '<article class="agent-ledger-item"><div class="agent-ledger-meta"><b>'+esc(x.symbol||"Research")+'</b><span>'+esc(stamp(x.ts))+'</span></div>'+
          '<p>'+esc(x.thesis||x.text||"No thesis text in event")+'</p><p><b>Action:</b> '+esc(fmt(x.action))+' · <b>Confidence:</b> '+esc(fmt(x.confidence))+'</p>'+
          (evidence?'<ul>'+evidence+'</ul>':'<p class="muted">No evidence array was included in this event.</p>')+
          '<p class="muted">Source record: actual engine event; a source URL was not provided unless listed above.</p></article>';
      }).join(""):'<p class="muted">NO RESEARCH EVENTS RECORDED for this agent. The page will not invent sources or findings.</p>';
      const activityHtml=activity.length?activity.map(x=>'<article class="agent-ledger-item"><div class="agent-ledger-meta"><b>'+esc(x.type||"event")+'</b><span>'+esc(stamp(x.ts))+'</span></div><p>'+esc(x.text||x.thesis||x.decision||JSON.stringify(x.status||{}))+'</p></article>').join(""):'<p class="muted">No activity events recorded.</p>';
      const facts='<div class="agent-facts">'+[
        ["Agent ID",a.id],["Role",a.role],["Group",a.group],["Status",a.status],["Required role",a.required?"Yes":"No"],
        ["Last seen",stamp(a.last_seen)],["Last seen age (seconds)",fmt(a.last_seen_age_seconds)],["Recent evidence items",fmt(a.recent_evidence_count)],
        ["Order access",a.order_execution_access===false?"No direct access":a.order_execution_access],["Runtime version","Not reported by current event stream"]
      ].map(([k,v])=>'<div><small>'+esc(k)+'</small><b>'+esc(v)+'</b></div>').join("")+'</div>';
      box.innerHTML='<div class="agent-profile-head"><div><div class="agent-profile-eyebrow">INDIVIDUAL AGENT FILE</div><h3>'+esc(a.title)+'</h3><p>'+esc(a.mission)+'</p></div><span class="agent-state '+(a.status==="ACTIVE"?"active":"")+'">'+esc(a.status)+'</span></div>'+
        section("Identity & current state",facts)+
        section("Responsibilities & boundaries",'<p>'+esc(a.mission)+'</p><p class="muted">Configured role definition is not proof of a running worker. Research/analysis view is read-only; this page cannot place orders.</p>')+
        section("Research ledger",researchHtml)+
        section("Agent activity / messages",activityHtml)+
        section("Decision, votes & objections",'<p class="muted">These fields appear only when the engine emits them. Current schema has no complete per-agent vote/objection record for this profile.</p>')+
        section("Performance & validation",'<p class="muted">No per-agent out-of-sample metrics are exposed by the current event stream. Metrics remain unavailable rather than being shown as zero.</p>')+
        section("Errors & limitations",'<p>'+esc(a.status==="NOT RUN / NO DATA"?"No matching runtime activity has been recorded.":"Only recorded event fields are shown; missing source links, heartbeats or metrics are explicitly unavailable.")+'</p>');
    } catch(error) {
      box.innerHTML='<div class="muted">Unable to load agent detail: '+esc(error.message)+'</div>';
    }
    renderDirectory();
  }
  $("agent-search").addEventListener("input",e=>{state.query=e.target.value;renderDirectory();});
  $("agent-group").addEventListener("change",e=>{state.group=e.target.value;renderDirectory();});
  $("agent-refresh").addEventListener("click",loadDirectory);
  // Refresh read-only registry and selected profile periodically; no visual patrol/fake activity.
  loadDirectory();
  setInterval(loadDirectory,15000);
  const stream=new EventSource("/events");
  stream.onmessage=event=>{
    try {
      const item=JSON.parse(event.data);
      if(item.type==="status"||item.type==="activity"||item.type==="agent_analysis") loadDirectory();
    } catch(_) {}
  };
})();
