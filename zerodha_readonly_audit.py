"""Read-only Zerodha connectivity audit.

This script deliberately has no order-placement, cancellation, or exit calls.
It verifies authenticated account access and reports only non-sensitive metadata.
"""
import os
import sys

from kiteconnect import KiteConnect


def main() -> int:
    api_key = os.getenv("KITE_API_KEY", "")
    access_token = os.getenv("KITE_ACCESS_TOKEN", "")

    if not api_key or not access_token:
        print("FAIL: KITE_API_KEY and KITE_ACCESS_TOKEN must be configured.")
        return 2

    try:
        client = KiteConnect(api_key=api_key)
        client.set_access_token(access_token)

        profile = client.profile()
        if not isinstance(profile, dict) or not profile.get("user_id"):
            print("FAIL: authenticated profile response was invalid.")
            return 1

        margins = client.margins("equity")
        positions = client.positions()

        available = None
        if isinstance(margins, dict):
            data = margins.get("available", {})
            if isinstance(data, dict):
                for key in ("live_balance", "cash", "opening_balance"):
                    if data.get(key) is not None:
                        available = float(data[key])
                        break

        day = positions.get("day", []) if isinstance(positions, dict) else []
        net = positions.get("net", []) if isinstance(positions, dict) else []

        print("PASS: Zerodha authentication")
        print(f"PASS: account access (user_id present)")
        print(f"PASS: equity margin access (available_balance={'present' if available is not None else 'not reported'})")
        print(f"PASS: positions access (day={len(day)}, net={len(net)})")
        print("PASS: read-only audit completed")
        print("NO ORDERS WERE PLACED")

        # Quote access is intentionally optional: Kite Personal API may not
        # include live market-data access. This must not turn account
        # connectivity into a false failure.
        try:
            quote = client.quote(["NSE:RELIANCE"])
            if isinstance(quote, dict) and "NSE:RELIANCE" in quote:
                print("INFO: quote endpoint responded for NSE:RELIANCE")
            else:
                print("INFO: quote endpoint returned no NSE:RELIANCE payload")
        except Exception as exc:
            print(f"INFO: quote endpoint unavailable ({type(exc).__name__}); account audit still passed")

        return 0
    except Exception as exc:
        print(f"FAIL: Zerodha read-only audit ({type(exc).__name__}): {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
