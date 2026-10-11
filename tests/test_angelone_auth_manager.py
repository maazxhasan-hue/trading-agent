import logging
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from angelone_auth import AngelOneAuthManager, AuthResponse, AuthSettings, AuthBlocked

def success():
    return AuthResponse(200, {}, {"status": True, "data": {"jwtToken": "secret-jwt", "refreshToken": "secret-refresh", "feedToken": "secret-feed"}})

def make_manager(path, transport, **kwargs):
    now = kwargs.pop("now", lambda: datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("Asia/Kolkata")))
    return AngelOneAuthManager(settings=AuthSettings(state_path=Path(path), cooldown_seconds=60, min_interval_seconds=1, **kwargs), transport=transport, clock=now, sleeper=lambda _: None, jitter=lambda: 0)

def test_rate_limit_403_enters_cooldown_without_retry(tmp_path):
    calls=[]
    manager=make_manager(tmp_path/"state.json", lambda: calls.append(1) or AuthResponse(403, {}, {"message":"Access denied because of exceeding access rate"}))
    for _ in range(2):
        with pytest.raises(AuthBlocked): manager.get_client()
    assert len(calls)==1 and manager.status()["status"]=="RATE_LIMITED"

def test_cooldown_survives_manager_restart(tmp_path):
    path=tmp_path/"state.json"
    manager=make_manager(path, lambda: AuthResponse(403, {}, {"message":"exceeding access rate"}))
    with pytest.raises(AuthBlocked): manager.get_client()
    restarted=make_manager(path, lambda: pytest.fail("must remain cooled down"))
    assert restarted.status()["status"]=="RATE_LIMITED"
    with pytest.raises(AuthBlocked): restarted.get_client()

def test_concurrent_processes_share_one_login(tmp_path):
    path=tmp_path/"state.json"; calls=[]; lock=threading.Lock()
    def login():
        with lock: calls.append(1)
        time.sleep(.05)
        return success()
    managers=[make_manager(path, login) for _ in range(8)]
    workers=[threading.Thread(target=m.get_client) for m in managers]
    for w in workers: w.start()
    for w in workers: w.join()
    assert len(calls)==1

def test_valid_session_is_reused_until_india_midnight(tmp_path):
    current=[datetime(2026,1,1,23,59,tzinfo=ZoneInfo("Asia/Kolkata"))]; calls=[]
    def login(): calls.append(1); return success()
    manager=make_manager(tmp_path/"state.json",login,now=lambda:current[0])
    first=manager.get_client(); assert manager.get_client() is first
    current[0]=datetime(2026,1,2,0,0,tzinfo=ZoneInfo("Asia/Kolkata"))
    manager.get_client(); assert len(calls)==2

def test_expired_jwt_uses_documented_refresh_once(tmp_path):
    calls=[]; refreshes=[]
    def login(): calls.append(1); return success()
    def refresh(tokens):
        refreshes.append(tokens["refreshToken"])
        return AuthResponse(200, {}, {"status": True, "data": {"jwtToken": "new-jwt", "feedToken": "new-feed"}})
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=tmp_path/"state.json"),transport=login,refresh_transport=refresh)
    manager.get_client(); manager.handle_expired_session()
    assert len(calls)==1 and refreshes==["secret-refresh"]
    assert manager.status()["status"]=="AUTHENTICATED"

def test_transient_network_failures_use_bounded_backoff(tmp_path):
    calls=[]; sleeps=[]
    def login():
        calls.append(1)
        if len(calls)<3: raise OSError("secret network details")
        return success()
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=tmp_path/"state.json",max_attempts=3),transport=login,sleeper=sleeps.append,jitter=lambda:0)
    manager.get_client(); assert len(calls)==3 and len(sleeps) >= 2

def test_state_file_is_private_and_atomic(tmp_path):
    path=tmp_path/"state.json"; manager=make_manager(path,success); manager.get_client()
    assert path.stat().st_mode & 0o777==0o600
    assert not list(tmp_path.glob("*.tmp"))

def test_auth_event_redacts_credentials_and_headers(tmp_path,caplog):
    response=AuthResponse(403,{"Authorization":"Bearer secret-jwt","Set-Cookie":"secret-cookie"},{"message":"Access denied because of exceeding access rate","pin":"secret-pin","totp":"secret-totp"})
    manager=make_manager(tmp_path/"state.json",lambda:response)
    with caplog.at_level(logging.INFO):
        with pytest.raises(AuthBlocked): manager.get_client()
    output=caplog.text+str(manager.status())
    for secret in ("secret-jwt","secret-cookie","secret-pin","secret-totp"): assert secret not in output

def test_corrupt_state_fails_closed_without_login(tmp_path):
    path=tmp_path/"state.json"; path.write_text("{not-json")
    calls=[]; manager=make_manager(path,lambda:calls.append(1) or success())
    with pytest.raises(AuthBlocked): manager.get_client()
    assert calls==[]

def _process_login_worker(state_path, counter_path):
    def login():
        with open(counter_path,"a",encoding="utf-8") as stream: stream.write("attempt\n")
        time.sleep(.08)
        return success()
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=Path(state_path)),transport=login)
    manager.get_client()

def test_concurrent_processes_share_one_login(tmp_path):
    import multiprocessing
    state=tmp_path/"process-state.json"; counter=tmp_path/"calls.txt"
    ctx=multiprocessing.get_context("fork")
    workers=[ctx.Process(target=_process_login_worker,args=(str(state),str(counter))) for _ in range(4)]
    for worker in workers: worker.start()
    for worker in workers: worker.join(5)
    assert all(worker.exitcode==0 for worker in workers)
    assert counter.read_text().splitlines()==["attempt"]

def test_retry_after_is_honored(tmp_path):
    current=datetime(2026,1,1,12,tzinfo=ZoneInfo("Asia/Kolkata"))
    manager=make_manager(tmp_path/"state.json",lambda:AuthResponse(403,{"Retry-After":"123"},{"message":"exceeding access rate"}),now=lambda:current)
    with pytest.raises(AuthBlocked): manager.get_client()
    status=manager.status()
    assert status["status"]=="RATE_LIMITED" and status["cooldown_remaining_seconds"]==123

def test_status_does_not_create_auth_state_files(tmp_path):
    path=tmp_path/"absent"/"state.json"
    manager=make_manager(path,lambda:pytest.fail("status must not login"))
    assert manager.status()["status"]=="AUTH_REQUIRED"
    assert not path.parent.exists()

def test_state_write_failure_never_starts_login(tmp_path, monkeypatch):
    manager=make_manager(tmp_path/"state.json",lambda:pytest.fail("state must be persisted before login"))
    monkeypatch.setattr(manager,"_write",lambda state: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError): manager.get_client()

def test_refresh_403_is_persisted_and_never_retried(tmp_path):
    login_calls=[]; refresh_calls=[]
    def login(): login_calls.append(1); return success()
    def refresh(tokens):
        refresh_calls.append(1)
        return AuthResponse(403,{"Retry-After":"75"},{"message":"access denied"})
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=tmp_path/"state.json",cooldown_seconds=60),transport=login,refresh_transport=refresh)
    manager.get_client()
    for _ in range(2):
        with pytest.raises(AuthBlocked): manager.handle_expired_session()
    status=manager.status()
    assert len(login_calls)==1 and len(refresh_calls)==1
    assert status["status"]=="RATE_LIMITED" and status["cooldown_remaining_seconds"]==75
    assert status["last_event"]["endpoint"].endswith("generateTokens")

def test_refresh_network_failure_fails_closed_without_repeat(tmp_path):
    refresh_calls=[]
    def refresh(tokens): refresh_calls.append(1); raise OSError("transport details")
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=tmp_path/"state.json"),transport=success,refresh_transport=refresh)
    manager.get_client()
    for _ in range(2):
        with pytest.raises(AuthBlocked): manager.handle_expired_session()
    assert refresh_calls==[1]
    assert manager.status()["status"]=="UNAVAILABLE"
