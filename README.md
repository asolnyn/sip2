# SCL VoIP Telegram Bot

Logs into the amarip.net (SCL) panel, dials a number on command, hangs up
as soon as it's answered, and fetches CDR on request.

## Commands
- `/call <number>` — dial a number; bot hangs up automatically once answered
- `/cdr [limit]` — fetch the latest CDR rows (default 20)

## Environment variables (set these in Railway)
| Variable | Description |
|---|---|
| `SCL_USERNAME` | Your amarip.net login username |
| `SCL_PASSWORD` | Your amarip.net login password |
| `TG_API_ID` | From https://my.telegram.org |
| `TG_API_HASH` | From https://my.telegram.org |
| `TG_BOT_TOKEN` | From @BotFather |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot (recommended — this bot can spend your VoIP balance) |

## Deploy on Railway
1. Push this folder to a GitHub repo.
2. In Railway: New Project → Deploy from GitHub repo.
3. Railway will detect the `Dockerfile` and build automatically.
4. Add the environment variables above under the service's Variables tab.
5. Deploy. Check logs to confirm the bot starts (`Pyrogram` login line).

## Still needed to finish this (two TODOs in `scl_automation.py`)

The login and dial steps are wired up from your screenshots and should
just work. Two pieces are placeholders because I haven't seen the UI
for them yet:

1. **Detecting "answered" + the hang-up button** — send a screenshot of
   the Dialer page *while a call is ringing or connected*. I need to see
   what changes on screen (a timer, a "Hang Up" button, a status label)
   so `monitor_and_hangup()` can react to the real thing instead of the
   placeholder `"Hang Up"` button name currently in the code.

2. **CDR table shape** — send a screenshot of the CDR page. I need the
   actual column layout so `fetch_cdr()` scrapes the right thing instead
   of assuming a plain `<table>`.

Once I have those two screenshots I'll swap in the real selectors and
this should work end-to-end.
