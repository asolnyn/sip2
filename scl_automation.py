"""
Browser automation for the amarip.net (SCL) VoIP gateway panel.

NOTE ON SELECTORS:
Login and Dialer selectors below are based on placeholder/button text
visible in the screenshots you shared, so they should work as-is.

The "wait for answer, then hang up" logic and the CDR scraper are
built on reasonable guesses (a call-control button appears on the
Dialer page during an active call; CDR is a plain HTML table). These
two are marked with TODO and will very likely need a small tweak once
you send me:
  1. A screenshot of the Dialer page WHILE a call is ringing/answered
  2. A screenshot of the CDR page

Until then, this will run, but the "detect answered -> hang up" and
"scrape CDR" steps may need selector fixes.
"""

import asyncio
import os
import re
import subprocess
from playwright.async_api import async_playwright, Page, Browser

TIMER_RE = re.compile(r"^\d{2}:\d{2}$")

SCL_URL = "https://amarip.net"
USERNAME = os.environ["SCL_USERNAME"]
PASSWORD = os.environ["SCL_PASSWORD"]


async def login(playwright) -> tuple[Browser, Page]:
    """Launch a headless browser and log into the SCL panel."""
    browser = await playwright.chromium.launch(
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
    await page.goto(SCL_URL, wait_until="networkidle")

    await page.get_by_placeholder("Enter username").fill(USERNAME)
    await page.get_by_placeholder("Enter password").fill(PASSWORD)
    await page.get_by_role("button", name="Sign In").click()

    # Wait for the dashboard/sidebar to appear as proof of login.
    await page.wait_for_selector("text=Dashboard", timeout=15000)
    return browser, page


async def dial_number(page: Page, number: str) -> None:
    """Go to the Dialer and place a call."""
    await page.goto(f"{SCL_URL}/#dialer", wait_until="networkidle")
    # Give the SIP registration over websocket a moment to complete
    # before dialing (page "networkidle" doesn't account for it).
    await page.wait_for_timeout(1500)
    await page.get_by_placeholder("Enter number").fill(number)
    await page.get_by_role("button", name="Call").click()


async def monitor_and_hangup(page: Page, ring_timeout: int = 40) -> str:
    """
    Poll the Dialer page after placing a call. The call modal shows a
    duration timer (e.g. "00:00") and an "End call" button. The timer
    stays at 00:00 while ringing and starts counting once the other
    side picks up — that's how we detect "answered". As soon as it
    does, we hang up immediately.
    """
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < ring_timeout:
        end_call_btn = page.get_by_role("button", name="End call")
        if await end_call_btn.count() == 0:
            # Modal is gone — call ended on its own (rejected, failed,
            # or the ring cycle expired on the carrier side).
            return "call_ended_before_answer"

        timer_texts = await page.locator("text=/^\\d{2}:\\d{2}$/").all_inner_texts()
        if any(t != "00:00" for t in timer_texts):
            await end_call_btn.click()
            return "answered_and_hungup"

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    # Ring timeout reached and still ringing — hang up ourselves so we
    # don't leave a call open.
    end_call_btn = page.get_by_role("button", name="End call")
    if await end_call_btn.count() > 0:
        await end_call_btn.click()
    return "no_answer_timeout"


async def fetch_cdr(page: Page, limit: int = 20) -> list[list[str]]:
    """
    Navigate to the CDR page and scrape the table rows.

    TODO: once you send a screenshot of the CDR page, confirm the table
    selector below matches (currently assumes a plain <table>).
    """
    await page.goto(f"{SCL_URL}/#cdr", wait_until="networkidle")
    await page.wait_for_selector("table", timeout=15000)

    rows = await page.locator("table tbody tr").all()
    results = []
    for row in rows[:limit]:
        cells = await row.locator("td").all_inner_texts()
        results.append(cells)
    return results


async def run_call(number: str) -> str:
    """Full flow: login -> dial -> monitor -> hangup -> close browser."""
    async with async_playwright() as pw:
        browser, page = await login(pw)
        try:
            await dial_number(page, number)
            result = await monitor_and_hangup(page)
        finally:
            await browser.close()
        return result


async def run_cdr_fetch(limit: int = 20) -> list[list[str]]:
    async with async_playwright() as pw:
        browser, page = await login(pw)
        try:
            rows = await fetch_cdr(page, limit=limit)
        finally:
            await browser.close()
        return rows


# ---------------------------------------------------------------------
# Voice-message calling: plays a WAV file into the call once answered,
# instead of hanging up immediately.
# ---------------------------------------------------------------------

async def login_with_audio(playwright, audio_path: str) -> tuple[Browser, Page]:
    """Same as login(), but feeds `audio_path` into the fake microphone
    instead of silence, so it gets sent as the outgoing call audio."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            f"--use-file-for-fake-audio-capture={audio_path}",
        ],
    )
    context = await browser.new_context(permissions=["microphone"])
    page = await context.new_page()
    await page.goto(SCL_URL, wait_until="networkidle")

    await page.get_by_placeholder("Enter username").fill(USERNAME)
    await page.get_by_placeholder("Enter password").fill(PASSWORD)
    await page.get_by_role("button", name="Sign In").click()
    await page.wait_for_selector("text=Dashboard", timeout=15000)
    return browser, page


def get_audio_duration(path: str) -> float:
    """Uses ffprobe to get the length (seconds) of the WAV file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 15.0  # fallback if ffprobe couldn't read it


async def wait_for_answer(page: Page, ring_timeout: int = 40) -> bool:
    """Poll until the call is answered (timer advances past 00:00) or
    ring_timeout elapses. Returns True if answered, False otherwise."""
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < ring_timeout:
        end_call_btn = page.get_by_role("button", name="End call")
        if await end_call_btn.count() == 0:
            return False  # call ended before being answered
        timer_texts = await page.locator("text=/^\\d{2}:\\d{2}$/").all_inner_texts()
        if any(t != "00:00" for t in timer_texts):
            return True
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return False


async def hangup(page: Page) -> None:
    end_call_btn = page.get_by_role("button", name="End call")
    if await end_call_btn.count() > 0:
        await end_call_btn.click()


async def run_call_with_message(number: str, audio_path: str, ring_timeout: int = 40) -> str:
    """Dial, wait for answer, play the audio file fully, then hang up."""
    duration = get_audio_duration(audio_path)
    async with async_playwright() as pw:
        browser, page = await login_with_audio(pw, audio_path)
        try:
            await dial_number(page, number)
            answered = await wait_for_answer(page, ring_timeout=ring_timeout)
            if answered:
                await asyncio.sleep(duration + 1.5)  # let the message finish playing
                await hangup(page)
                return "message_played_and_hungup"
            else:
                await hangup(page)
                return "no_answer_timeout"
        finally:
            await browser.close()
