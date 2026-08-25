"""
Diagnostic version of the dial flow.

The panel (Semux) uses a Janus WebRTC softphone for the Dialer, not a
plain form POST. That means clicking "Call" tries to open a live
WebRTC session from inside the browser — which needs microphone
access and will silently do nothing in headless Chromium unless we
explicitly fake a media device.

This module launches the browser with fake-media flags, grants the
microphone permission, and logs everything relevant (console messages,
page errors, websocket frames to/from Janus, and any request/response
containing "janus"/"dial"/"call"/"sip") plus three screenshots, so we
can see exactly what's happening at each step.
"""

import os
from playwright.async_api import async_playwright

SCL_URL = "https://amarip.net"
USERNAME = os.environ["SCL_USERNAME"]
PASSWORD = os.environ["SCL_PASSWORD"]

KEYWORDS = ("janus", "dial", "call", "sip")


async def debug_call(number: str) -> dict:
    logs: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        context = await browser.new_context(permissions=["microphone"])
        page = await context.new_page()

        page.on("console", lambda msg: logs.append(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: logs.append(f"[pageerror] {exc}"))

        def on_websocket(ws):
            logs.append(f"[websocket opened] {ws.url}")
            ws.on("framesent", lambda payload: logs.append(f"[ws sent] {str(payload)[:300]}"))
            ws.on("framereceived", lambda payload: logs.append(f"[ws recv] {str(payload)[:300]}"))
            ws.on("close", lambda: logs.append(f"[websocket closed] {ws.url}"))

        page.on("websocket", on_websocket)

        def on_request(req):
            if any(k in req.url.lower() for k in KEYWORDS):
                logs.append(f"[request] {req.method} {req.url}")

        def on_response(res):
            if any(k in res.url.lower() for k in KEYWORDS):
                logs.append(f"[response] {res.status} {res.url}")

        page.on("request", on_request)
        page.on("response", on_response)

        # --- Login ---
        await page.goto(SCL_URL, wait_until="networkidle")
        await page.get_by_placeholder("Enter username").fill(USERNAME)
        await page.get_by_placeholder("Enter password").fill(PASSWORD)
        await page.get_by_role("button", name="Sign In").click()
        await page.wait_for_selector("text=Dashboard", timeout=15000)

        # --- Go to dialer, screenshot before touching anything ---
        await page.goto(f"{SCL_URL}/#dialer", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.screenshot(path="/tmp/debug_1_dialer_loaded.png")

        # --- Fill number, screenshot ---
        await page.get_by_placeholder("Enter number").fill(number)
        await page.screenshot(path="/tmp/debug_2_number_filled.png")

        # --- Click Call, wait, screenshot ---
        await page.get_by_role("button", name="Call").click()
        await page.wait_for_timeout(4000)
        await page.screenshot(path="/tmp/debug_3_after_call_click.png")

        with open("/tmp/debug_log.txt", "w") as f:
            f.write("\n".join(logs) if logs else "(nothing captured — no matching console/network/websocket activity)")

        await browser.close()

    return {
        "screenshots": [
            "/tmp/debug_1_dialer_loaded.png",
            "/tmp/debug_2_number_filled.png",
            "/tmp/debug_3_after_call_click.png",
        ],
        "log": "/tmp/debug_log.txt",
    }
