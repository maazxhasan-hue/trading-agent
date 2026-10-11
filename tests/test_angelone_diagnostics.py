from scripts.diagnose_angelone_auth import _safe_environment, diagnose

def test_diagnostics_redact_env_and_log_secrets(tmp_path):
    log=tmp_path/"auth.log"
    log.write_text("AngelOne login error pin=secret-pin totp=secret-totp Authorization: Bearer secret-jwt cookie=secret-cookie refreshToken=secret-refresh API_KEY=secret-key\n")
    def run(cmd):
        if cmd[0]=="systemctl": return "active"
        return "agent_supervisor.py\nmcx_agent.py\n"
    result=diagnose(system_reader=run,public_ip_reader=lambda:"203.0.113.2",state_reader=lambda:{"status":"RATE_LIMITED","cooldown_remaining_seconds":45},env={"ANGELONE_CLIENT_PUBLIC_IP":"203.0.113.2","ANGELONE_AUTH_LOG":str(log),"ANGELONE_PIN":"secret-pin"})
    rendered=str(result)
    for secret in ("secret-pin","secret-totp","secret-jwt","secret-cookie","secret-refresh","secret-key"): assert secret not in rendered
    assert result["recent_auth_errors"]

def test_diagnostics_report_ip_and_cooldown():
    result=diagnose(system_reader=lambda cmd:"active" if cmd[0]=="systemctl" else "",public_ip_reader=lambda:"198.51.100.2",state_reader=lambda:{"status":"RATE_LIMITED","cooldown_remaining_seconds":90},env={"ANGELONE_CLIENT_PUBLIC_IP":"198.51.100.2"})
    assert result["public_ip_matches"] is True
    assert result["auth"]["cooldown_remaining_seconds"]==90

def test_diagnostics_missing_ip_is_unknown_not_mismatch():
    result=diagnose(system_reader=lambda cmd:"active" if cmd[0]=="systemctl" else "",public_ip_reader=lambda:"198.51.100.2",state_reader=lambda:{"status":"AUTH_REQUIRED"},env={})
    assert result["configured_public_ip"] is None
    assert result["public_ip_matches"] is None

def test_safe_environment_reads_only_allowlisted_systemd_values(tmp_path, monkeypatch):
    envfile=tmp_path/"service.env"
    envfile.write_text("ANGELONE_CLIENT_PUBLIC_IP=198.51.100.7\nANGELONE_AUTH_STATE_PATH=/tmp/auth-state.json\nANGELONE_AUTH_LOG=/tmp/auth.log\nANGELONE_API_KEY=secret-api-key\nANGELONE_PIN=secret-pin\n")
    for key in ("ANGELONE_CLIENT_PUBLIC_IP","ANGELONE_AUTH_STATE_PATH","ANGELONE_AUTH_LOG"):
        monkeypatch.delenv(key,raising=False)
    result=_safe_environment(lambda cmd:f"{envfile} (ignore_errors=no)" if "EnvironmentFiles" in cmd else "")
    assert result["ANGELONE_CLIENT_PUBLIC_IP"]=="198.51.100.7"
    assert result["ANGELONE_AUTH_STATE_PATH"]=="/tmp/auth-state.json"
    assert "ANGELONE_API_KEY" not in result
    assert "ANGELONE_PIN" not in result
    monkeypatch.delenv("ANGELONE_AUTH_STATE_PATH",raising=False)

def test_diagnostics_never_calls_smartapi():
    commands=[]
    result=diagnose(system_reader=lambda cmd:commands.append(cmd) or ("active" if cmd[0]=="systemctl" else ""),public_ip_reader=lambda:"",state_reader=lambda:{"status":"AUTH_REQUIRED"},env={})
    assert all(c[0] in {"systemctl", "ps", "journalctl", "crontab"} for c in commands)
    assert result["auth"]["status"]=="AUTH_REQUIRED"

def test_diagnostics_count_matching_timers_services_and_cron_without_echoing_commands():
    def run(cmd):
        joined=" ".join(cmd)
        if "is-active" in joined: return "active"
        if "list-units" in joined: return "angelone-extra.service loaded active running unsafe-secret-value\n"
        if "list-timers" in joined: return "n/a n/a n/a n/a angelone-refresh.timer angelone-refresh.service\n"
        if cmd[0]=="crontab": return "*/5 * * * * angelone-refresh # secret-in-command\n"
        return ""
    result=diagnose(system_reader=run,public_ip_reader=lambda:"",state_reader=lambda:{"status":"AUTH_REQUIRED"},env={})
    assert result["matching_systemd_services"]==[{"unit":"angelone-extra.service","state":"active"}]
    assert result["matching_systemd_timers"]==["angelone-refresh.timer"]
    assert result["matching_cron_entries"]==1
    assert "unsafe-secret-value" not in str(result) and "secret-in-command" not in str(result)
