from angelone_market_data import AngelOneNSEFeed
from angelone_mcx_market_data import AngelOneMCXFeed


def test_feed_reuses_injected_broker():
    broker = object()
    assert AngelOneNSEFeed(broker=broker).broker is broker
    assert AngelOneMCXFeed(broker=broker).broker is broker

def test_status_reads_do_not_login(monkeypatch, tmp_path):
    from angelone_auth import AngelOneAuthManager, AuthSettings
    calls=[]
    manager=AngelOneAuthManager(settings=AuthSettings(state_path=tmp_path/"state.json"),transport=lambda:calls.append(1))
    assert manager.status()["status"]=="AUTH_REQUIRED"
    assert calls==[]

def test_rate_limited_adapter_fails_closed(monkeypatch):
    import angelone_adapter as module
    from angelone_auth import AuthBlocked
    class Manager:
        def get_client(self): raise AuthBlocked("Angel One authentication is rate limited.")
        def status(self): return {"status":"RATE_LIMITED","cooldown_remaining_seconds":100}
    monkeypatch.setattr(module,"_manager_for_environment",lambda *args:Manager())
    # This test covers auth-state handling, independent of the optional SDK.
    monkeypatch.setattr(module,"SmartConnect",object)
    monkeypatch.setattr(module,"pyotp",object())
    for key,value in {"TRADING_BACKEND":"angelone_nse","LIVE_TRADING":"false","ANGELONE_READONLY":"true","ANGELONE_API_KEY":"k","ANGELONE_CLIENT_CODE":"c","ANGELONE_PIN":"p","ANGELONE_TOTP_SECRET":"t","ANGELONE_CLIENT_PUBLIC_IP":"127.0.0.1"}.items(): monkeypatch.setenv(key,value)
    try:
        module.AngelOneExecution()
    except module.AngelOneLocked as exc:
        assert "rate limited" in str(exc)
    else:
        raise AssertionError("rate-limited auth must fail closed")

def test_sdk_logs_never_emit_auth_material(monkeypatch, tmp_path, caplog):
    import angelone_adapter as module
    from angelone_auth import AuthBlocked
    class Totp:
        def __init__(self, secret): pass
        def now(self): return "secret-totp"
    class FakeClient:
        root="https://example.invalid"
        timeout=1
        _routes={"api.login":"/rest/auth/angelbroking/user/v1/loginByPassword"}
        def __init__(self, api_key): self.api_key=api_key
        def requestHeaders(self): return {"X-PrivateKey":self.api_key}
        def setAccessToken(self, token): pass
        def setRefreshToken(self, token): pass
        def setFeedToken(self, token): pass
        def setUserId(self, value): pass
    class Response:
        status_code=403
        headers={"Authorization":"secret-header","Set-Cookie":"secret-cookie"}
        def json(self): return {"status":False,"message":"Access denied because of exceeding access rate","data":{"token":"secret-jwt"}}
    monkeypatch.setattr(module,"SmartConnect",FakeClient)
    monkeypatch.setattr(module,"pyotp",type("Pyotp",(),{"TOTP":Totp}))
    monkeypatch.setattr(module.requests,"post",lambda *args,**kwargs:Response())
    state=str(tmp_path/"auth.json")
    monkeypatch.setenv("ANGELONE_AUTH_STATE_PATH",state)
    manager=module._manager_for_environment("secret-key","client","secret-pin","secret-totp","127.0.0.1","127.0.0.1")
    with caplog.at_level("DEBUG"):
        try: manager.get_client()
        except AuthBlocked: pass
    rendered=caplog.text+str(manager.status())
    for secret in ("secret-key","secret-pin","secret-totp","secret-header","secret-cookie","secret-jwt"): assert secret not in rendered
    module._AUTH_MANAGERS.pop(state,None)
