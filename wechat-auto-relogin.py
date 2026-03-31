#!/usr/bin/env python3
"""
Monitor WeChat login status and auto re-login when logged out.
Polls /api/status/auth every 30s; triggers login WebSocket on logout.
"""
import asyncio
import json
import logging
import sys
import time

import httpx
import websockets

TOKEN_FILE = "/root/.config/agent-wechat/token"
API_BASE   = "http://localhost:6174"
CHECK_INTERVAL   = 30   # seconds between status polls
LOGIN_TIMEOUT    = 300  # seconds to wait for phone confirmation
COOLDOWN_AFTER   = 60   # seconds to wait after a successful re-login before checking again
MAX_RETRIES      = 3    # max consecutive login attempts before giving up until next cycle


def load_token():
    return open(TOKEN_FILE).read().strip()


async def check_status(client, headers):
    r = await client.get(f"{API_BASE}/api/status/auth", headers=headers, timeout=10)
    return r.json()


async def trigger_login(headers):
    uri = "ws://localhost:6174/api/ws/login"
    logging.info("Connecting to login WebSocket...")
    try:
        async with websockets.connect(uri, additional_headers=headers, open_timeout=30) as ws:
            logging.info("Login WebSocket connected, waiting for phone confirmation...")
            deadline = asyncio.get_event_loop().time() + LOGIN_TIMEOUT
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    logging.error("Login timed out waiting for phone confirmation")
                    return False
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 10.0))
                except asyncio.TimeoutError:
                    continue
                data = json.loads(raw)
                evt = data.get("type", "")
                logging.info("Login event: %s", data)
                if evt == "login_success":
                    logging.info("Re-login successful!")
                    return True
                if evt in ("error", "timeout"):
                    logging.error("Login failed with event: %s", data)
                    return False
    except Exception as e:
        logging.error("Login WebSocket error: %s", e)
        return False


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/tmp/wechat-auto-relogin.log"),
        ],
    )
    logging.info("WeChat auto-relogin monitor started (check interval=%ds)", CHECK_INTERVAL)

    headers = {"Authorization": f"Bearer {load_token()}"}
    consecutive_failures = 0

    async with httpx.AsyncClient() as client:
        while True:
            try:
                status = await check_status(client, headers)
                state = status.get("status")
                logging.debug("Status: %s", state)

                if state == "logged_out":
                    logging.warning("WeChat is logged out, attempting re-login (attempt %d/%d)...",
                                    consecutive_failures + 1, MAX_RETRIES)
                    success = await trigger_login(headers)
                    if success:
                        consecutive_failures = 0
                        logging.info("Waiting %ds before next check...", COOLDOWN_AFTER)
                        await asyncio.sleep(COOLDOWN_AFTER)
                        continue
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= MAX_RETRIES:
                            logging.error("Failed %d times in a row, pausing for 5 min", MAX_RETRIES)
                            await asyncio.sleep(300)
                            consecutive_failures = 0
                        else:
                            await asyncio.sleep(CHECK_INTERVAL)
                        continue
                else:
                    consecutive_failures = 0

            except Exception as e:
                logging.error("Monitor loop error: %s", e)

            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
