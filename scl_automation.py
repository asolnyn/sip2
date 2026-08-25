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
from playwright.async_api import async_playwright, Page, Browser

SCL_URL = "https://amarip.net"
USERNAME = os.environ["SCL_USERNAME"]
PASSWORD = os.environ["SCL_PASSWORD"]


async def login(playwright) -> tuple[Browser, Page]:
    """Launch a headless browser and log into the SCL panel."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = await browser.new_page()
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
    await page.get_by_placeholder("Enter number").fill(number)
    await page.get_by_role("button", name="Call").click()


async def monitor_and_hangup(page: Page, ring_timeout: int = 45) -> str:
    """
    Poll the Dialer page after placing a call. As soon as it looks like
    the other side picked up, hang up immediately.

    TODO: once you send a screenshot of the Dialer mid-call, replace the
    placeholder detection logic below with the real selector/text that
    shows up (e.g. a call timer like "00:01", or a "Hang Up" button that
    replaces the "Call" button).
    """
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < ring_timeout:
        # --- Placeholder detection logic (needs real selector) ---
        hangup_btn = page.get_by_role("button", name="Hang Up")
        if await hangup_btn.count() > 0:
            await hangup_btn.click()
            return "answered_and_hungup"
        # -----------------------------------------------------------

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

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
