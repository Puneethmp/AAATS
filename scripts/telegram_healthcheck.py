#!/usr/bin/env python3
"""
AAATS Telegram bot healthcheck (L1).

Runs INSIDE the aaats-telegram-bot container as the Docker HEALTHCHECK.
Validates that the token the bot is actually running with authenticates
against the Telegram API (getMe -> 200 with ok=true).

Why this exists
---------------
The recurring failure is "config rotated but process not reloaded": the
.env token is updated but the long-lived container keeps the OLD token in
memory and crash-loops on 401 Unauthorized, while Docker still reports the
container as "Up". A plain process-liveness healthcheck cannot see this
because the process IS running (it just can't authenticate).

By reading the SAME env var the bot reads (ALERTS__TELEGRAM_BOT_TOKEN) and
calling getMe, an invalid/revoked token makes the container go `unhealthy`
within one interval. The box watchdog (L3) then force-recreates it, and the
GitHub Actions check (L4) alerts out-of-band.

Exit codes
----------
0  token valid (getMe ok)  -> Docker marks container healthy
1  token missing / invalid / network error -> Docker marks container unhealthy

Stdlib only (no requests) so it works in the minimal container image.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("ALERTS__TELEGRAM_BOT_TOKEN", "").strip()
TIMEOUT_SEC = float(os.environ.get("TG_HEALTHCHECK_TIMEOUT", "8"))


def main() -> int:
    if not TOKEN:
        print("FAIL: ALERTS__TELEGRAM_BOT_TOKEN is empty", file=sys.stderr)
        return 1

    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            if resp.status != 200:
                print(f"FAIL: getMe HTTP {resp.status}", file=sys.stderr)
                return 1
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                print(f"FAIL: getMe ok=false: {body}", file=sys.stderr)
                return 1
            uname = body.get("result", {}).get("username", "?")
            print(f"OK: getMe authenticated as @{uname}")
            return 0
    except urllib.error.HTTPError as e:
        # 401 = revoked/invalid token. This is THE failure mode we catch.
        print(f"FAIL: getMe HTTPError {e.code} (401=revoked token)", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - any failure => unhealthy
        print(f"FAIL: getMe error: {e!r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
