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
WATCH_SECONDS = 30
SCREENSHOT_EVERY = 5


async def debug_call(number: str, audio_path: str | None = None) -> dict:
    """
    If audio_path is given, launches with --use-file-for-fake-audio-capture
    pointing at it (same as /voicecall), so we can debug that path too.
    """
    logs: list[str] = []

    async with async_playwright() as pw:
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
        ]
        if audio_path:
            launch_args.append(f"--use-file-for-fake-audio-capture={audio_path}")

        browser = await pw.chromium.launch(headless=True, args=launch_args)
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

        # --- Click Call, then watch the full call lifecycle instead of
        # a fixed short wait, taking a screenshot every few seconds ---
        await page.get_by_role("button", name="Call").click()

        shot_paths = []
        elapsed = 0
        outcome = "timed_out_watching"
        shot_index = 3

        while elapsed < WATCH_SECONDS:
            await page.wait_for_timeout(SCREENSHOT_EVERY * 1000)
            elapsed += SCREENSHOT_EVERY

            path = f"/tmp/debug_{shot_index}_t{elapsed}s.png"
            await page.screenshot(path=path)
            shot_paths.append(path)
            shot_index += 1

            end_call_btn = page.get_by_role("button", name="End call")
            if await end_call_btn.count() == 0:
                logs.append(f"[debug] End call button gone at t={elapsed}s — call ended on its own")
                outcome = "call_ended_before_answer"
                break

            timer_texts = await page.locator("text=/^\\d{2}:\\d{2}$/").all_inner_texts()
            if any(t != "00:00" for t in timer_texts):
                logs.append(f"[debug] Timer advanced at t={elapsed}s ({timer_texts}) — treating as answered")
                await end_call_btn.click()
                outcome = "answered_and_hungup"
                break
        else:
            end_call_btn = page.get_by_role("button", name="End call")
            if await end_call_btn.count() > 0:
                await end_call_btn.click()

        logs.append(f"[debug] outcome: {outcome}")

        with open("/tmp/debug_log.txt", "w") as f:
            f.write("\n".join(logs) if logs else "(nothing captured — no matching console/network/websocket activity)")

        await browser.close()

    return {
        "screenshots": [
            "/tmp/debug_1_dialer_loaded.png",
            "/tmp/debug_2_number_filled.png",
        ] + shot_paths,
        "log": "/tmp/debug_log.txt",
    }
