"""One-time helper for creating a Zerodha Kite access token.
Run locally/cloud, complete Zerodha's login, then exchange the request token.
The resulting access token is intentionally printed only to stdout; put it in
KITE_ACCESS_TOKEN as a secret and never commit it.
"""
import os, sys
from kiteconnect import KiteConnect

api_key=os.getenv("KITE_API_KEY")
api_secret=os.getenv("KITE_API_SECRET")
if not api_key or not api_secret:
    raise SystemExit("Set KITE_API_KEY and KITE_API_SECRET first.")
k=KiteConnect(api_key=api_key)
print("Open this login URL:\n"+k.login_url())
request_token=input("Paste request_token from the redirect URL: ").strip()
s=k.generate_session(request_token,api_secret=api_secret)
print("ACCESS_TOKEN="+s["access_token"])
