import json
import agent_supervisor
from agent_supervisor import AgentSupervisor

def test_health_reports_rate_limited_without_login(monkeypatch):
    calls=[]
    monkeypatch.setattr(agent_supervisor,"read_auth_status",lambda:calls.append("status") or {"status":"RATE_LIMITED","cooldown_remaining_seconds":30})
    supervisor=AgentSupervisor.__new__(AgentSupervisor)
    payload=supervisor.health_payload()
    assert payload["broker_auth"]["status"]=="RATE_LIMITED"
    assert calls==["status"]

def test_metrics_do_not_expose_tokens_or_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_supervisor,"read_auth_status",lambda:{"status":"RATE_LIMITED","cooldown_remaining_seconds":4})
    supervisor=AgentSupervisor.__new__(AgentSupervisor)
    monkeypatch.setattr(supervisor,"_learning_path",lambda backend:str(tmp_path/"learn.json"))
    data=supervisor.metrics()
    rendered=json.dumps(data)
    for secret in ("jwtToken","refreshToken","Authorization","ANGELONE_PIN"): assert secret not in rendered
    assert data["broker_auth"]["status"]=="RATE_LIMITED"
