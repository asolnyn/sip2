import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

from scl_automation import run_call, run_cdr_fetch, run_call_with_message
from scl_debug import debug_call

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]

# Only these Telegram user IDs may use the bot. Comma-separated in env.
ALLOWED_USERS = {int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x}

app = Client(
    "scl-bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def authorized(_, __, message: Message) -> bool:
    return (not ALLOWED_USERS) or (message.from_user and message.from_user.id in ALLOWED_USERS)


auth_filter = filters.create(authorized)


@app.on_message(filters.command("call") & auth_filter)
async def call_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /call <number>")
        return

    number = message.command[1]
    status_msg = await message.reply(f"Dialing {number}...")

    try:
        result = await run_call(number)
    except Exception as e:
        await status_msg.edit(f"Call failed: {e}")
        return

    if result == "answered_and_hungup":
        await status_msg.edit(f"{number} answered — hung up.")
    else:
        await status_msg.edit(f"{number} — no answer within timeout.")


@app.on_message(filters.command("cdr") & auth_filter)
async def cdr_handler(client: Client, message: Message):
    limit = 20
    if len(message.command) > 1 and message.command[1].isdigit():
        limit = int(message.command[1])

    status_msg = await message.reply("Fetching CDR...")

    try:
        rows = await run_cdr_fetch(limit=limit)
    except Exception as e:
        await status_msg.edit(f"CDR fetch failed: {e}")
        return

    if not rows:
        await status_msg.edit("No CDR entries found.")
        return

    lines = ["\t".join(cell.strip() for cell in row) for row in rows]
    text = "\n".join(lines)

    # Telegram messages cap at ~4096 chars; send as a file if too long.
    if len(text) > 3500:
        path = "/tmp/cdr.txt"
        with open(path, "w") as f:
            f.write(text)
        await message.reply_document(path, caption=f"CDR ({len(rows)} rows)")
        await status_msg.delete()
    else:
        await status_msg.edit(f"CDR ({len(rows)} rows):\n\n{text}")


@app.on_message(filters.command("debugcall") & auth_filter)
async def debugcall_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /debugcall <number>")
        return

    number = message.command[1]
    status_msg = await message.reply(f"Running diagnostic dial to {number}...")

    try:
        result = await debug_call(number)
    except Exception as e:
        await status_msg.edit(f"Diagnostic failed: {e}")
        return

    await status_msg.edit("Diagnostic complete — sending screenshots and log.")
    for shot in result["screenshots"]:
        await message.reply_photo(shot)
    await message.reply_document(result["log"], caption="Console/network/websocket log")


@app.on_message(filters.command("voicecall") & auth_filter)
async def voicecall_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: reply to a voice note or audio file with /voicecall <number>")
        return

    reply = message.reply_to_message
    if not reply or not (reply.voice or reply.audio):
        await message.reply("Reply to a voice note or audio file with this command.")
        return

    number = message.command[1]
    status_msg = await message.reply("Downloading and converting audio...")

    src_path = await reply.download(file_name="/tmp/voice_src")
    wav_path = "/tmp/voice_call.wav"

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", src_path,
        "-ar", "48000", "-ac", "1", "-sample_fmt", "s16", wav_path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if proc.returncode != 0:
        await status_msg.edit("Audio conversion failed.")
        return

    await status_msg.edit(f"Dialing {number} to play your message...")

    try:
        result = await run_call_with_message(number, wav_path)
    except Exception as e:
        await status_msg.edit(f"Call failed: {e}")
        return

    labels = {
        "message_played_and_hungup": f"{number} answered — message played, call ended.",
        "no_answer_timeout": f"{number} — no answer within timeout.",
    }
    await status_msg.edit(labels.get(result, result))


if __name__ == "__main__":
    app.run()
