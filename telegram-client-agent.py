"""
MTS Client Intelligence Agent — Supabase Edition
Processes Fathom transcripts via @mention, pulls full client context
from Supabase (including web app sessions), and saves debrief back.
"""

import os
import re
import json
import logging
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

import httpx
from telegram import Update, Message
from telegram.ext import (
    Application, MessageHandler, CommandHandler, ContextTypes, filters,
)
import anthropic

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL      = os.environ["SUPABASE_URL"]
SUPABASE_KEY      = os.environ["SUPABASE_KEY"]
TIMEZONE          = os.environ.get("TIMEZONE", "America/Los_Angeles")
BOT_USERNAME      = os.environ.get("BOT_USERNAME", "MTSAgentBot")

TZ = ZoneInfo(TIMEZONE)

# Rolling chat history buffer
chat_history: dict[int, list[dict]] = defaultdict(list)
MAX_HISTORY = 500


# ── Supabase helpers ──────────────────────────────────────────────────────────
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

async def sb_get(table: str, params: dict = None) -> list:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=sb_headers(),
            params=params or {},
        )
        r.raise_for_status()
        return r.json()

async def sb_post(table: str, data) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=sb_headers(),
            json=data,
        )
        r.raise_for_status()
        result = r.json()
        return result[0] if isinstance(result, list) and result else result

async def sb_patch(table: str, data: dict, match: dict) -> None:
    params = {k: f"eq.{v}" for k, v in match.items()}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=sb_headers(),
            params=params,
            json=data,
        )
        r.raise_for_status()


# ── Client context from Supabase ──────────────────────────────────────────────
async def get_full_client_context(client_name: str, chat_id: int) -> dict:
    """Pull everything we know about a client from Supabase + Telegram history."""
    result = {
        "profile": {},
        "sessions": [],
        "ghost_items": [],
        "telegram_context": "",
        "client_id": None,
    }
    try:
        clients = await sb_get("clients", {"name": f"eq.{client_name}", "limit": "1"})
        if clients:
            client = clients[0]
            result["client_id"] = client["id"]
            result["profile"]   = client.get("profile") or {}

            sessions = await sb_get("sessions", {
                "client_id": f"eq.{client['id']}",
                "order": "created_at.desc",
                "limit": "5",
            })
            result["sessions"] = sessions or []

            ghosts = await sb_get("ghost_items", {
                "client_id": f"eq.{client['id']}",
                "resolved": "eq.false",
                "limit": "15",
            })
            result["ghost_items"] = ghosts or []
    except Exception as e:
        logger.warning(f"Supabase context error: {e}")

    # Telegram chat history for this client
    name_words = [w for w in client_name.lower().split() if len(w) > 3]
    history = chat_history.get(chat_id, [])
    relevant = [
        f"[{m['timestamp']}] {m['sender']}: {m['text']}"
        for m in history
        if any(w in m["text"].lower() for w in name_words)
    ]
    result["telegram_context"] = "\n".join(relevant[-30:]) or "(no recent Telegram messages)"
    return result


def format_client_context(client_name: str, ctx: dict) -> str:
    """Format Supabase context into a readable block for the AI prompt."""
    lines = []
    profile = ctx.get("profile") or {}
    if profile.get("notes"):
        lines.append(f"PROFILE: {profile['notes']}")
    if profile.get("businesses"):
        lines.append(f"Entities: {', '.join(profile['businesses'])}")
    if profile.get("serviceType") and profile["serviceType"] != "Unknown":
        lines.append(f"Service type: {profile['serviceType']}")
    if profile.get("filingStatus") and profile["filingStatus"] != "Unknown":
        lines.append(f"Filing status: {profile['filingStatus']}")

    sessions = ctx.get("sessions") or []
    if sessions:
        lines.append(f"\nPRIOR SESSIONS ({len(sessions)} on record):")
        for s in sessions[:3]:
            lines.append(f"- {s.get('meeting_date','?')} ({s.get('meeting_type','')}): {s.get('summary','')[:200]}")
            if s.get("mts_tasks"):
                pending = [t for t in (s["mts_tasks"] or []) if any(w in t.lower() for w in ["pending","follow","need","outstanding","waiting"])]
                if pending:
                    lines.append(f"  Still pending: {'; '.join(pending[:3])}")

    ghosts = ctx.get("ghost_items") or []
    if ghosts:
        lines.append(f"\nOPEN ITEMS ({len(ghosts)} unresolved):")
        for g in ghosts[:8]:
            lines.append(f"- {g['summary']}")

    lines.append(f"\nRECENT TELEGRAM MESSAGES MENTIONING THIS CLIENT:\n{ctx.get('telegram_context','(none)')}")
    return "\n".join(lines)


# ── Message listener ──────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    msg       = update.message
    chat_id   = msg.chat_id
    sender    = msg.from_user.full_name if msg.from_user else "Unknown"
    text      = msg.text or msg.caption or ""
    timestamp = datetime.now(tz=TZ).strftime("%Y-%m-%d %H:%M")

    history = chat_history[chat_id]
    history.append({"timestamp": timestamp, "sender": sender, "text": text})
    if len(history) > MAX_HISTORY:
        chat_history[chat_id] = history[-MAX_HISTORY:]

    bot_mention = f"@{BOT_USERNAME}"
    if bot_mention.lower() not in text.lower():
        return

    client_name = extract_client_name(text, bot_mention)
    if not client_name:
        await msg.reply_text(
            f"Tag me with a client name: @{BOT_USERNAME} Client Name\nThen attach the Fathom transcript."
        )
        return

    document = msg.document
    if not document:
        await msg.reply_text(
            f"Got it — ready for *{client_name}*. Please attach the Fathom transcript (.txt or .pdf).",
            parse_mode="Markdown",
        )
        return

    await process_meeting(context, msg, chat_id, client_name, document)


def extract_client_name(text: str, bot_mention: str) -> str | None:
    pattern = re.compile(re.escape(bot_mention) + r"\s+(.+?)(?:\n|$)", re.IGNORECASE)
    match   = pattern.search(text)
    if match:
        name = match.group(1).strip()
        return name if name else None
    return None


# ── Core processing ───────────────────────────────────────────────────────────
async def process_meeting(
    context: ContextTypes.DEFAULT_TYPE,
    msg: Message,
    chat_id: int,
    client_name: str,
    document,
) -> None:
    await msg.reply_text(
        f"Processing meeting for *{client_name}*...\n"
        "_Reading transcript, pulling Supabase context, and generating debrief..._",
        parse_mode="Markdown",
    )
    try:
        transcript = await download_file(context, document)
        if not transcript:
            await msg.reply_text("Could not read the transcript file. Please send as .txt or .pdf.")
            return

        ctx         = await get_full_client_context(client_name, chat_id)
        ctx_text    = format_client_context(client_name, ctx)
        debrief     = await generate_debrief(client_name, transcript, ctx_text)

        for chunk in split_message(debrief):
            await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")

        # Save debrief as a session in Supabase
        await save_debrief_to_supabase(client_name, debrief, ctx.get("client_id"))
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Debrief saved to *{client_name}*'s profile in Supabase — visible in the web app.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error processing {client_name}: {e}", exc_info=True)
        await msg.reply_text(f"Error: {str(e)[:200]}")


# ── File download ─────────────────────────────────────────────────────────────
async def download_file(context: ContextTypes.DEFAULT_TYPE, document) -> str | None:
    try:
        file = await context.bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        try:
            with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content.strip()) > 50:
                return content
        except Exception:
            pass
        try:
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            pass
        return None
    except Exception as e:
        logger.error(f"File download error: {e}")
        return None


# ── Save debrief to Supabase ──────────────────────────────────────────────────
async def save_debrief_to_supabase(client_name: str, debrief: str, client_id: str | None) -> None:
    try:
        if not client_id:
            # Create client if not exists
            clients = await sb_get("clients", {"name": f"eq.{client_name}", "limit": "1"})
            if clients:
                client_id = clients[0]["id"]
            else:
                new_client = await sb_post("clients", {"name": client_name, "profile": {}, "open_items": []})
                client_id = new_client["id"]

        today = datetime.now(tz=TZ).strftime("%B %d, %Y")
        await sb_post("sessions", {
            "client_id":    client_id,
            "client_name":  client_name,
            "meeting_date": today,
            "meeting_type": "Fathom Transcript Review",
            "hosted_by":    "Momen Tax Services",
            "summary":      debrief[:500],
            "notes_and_questions": [],
            "client_next_steps":   [],
            "mts_tasks":           [],
            "next_agenda":         [],
            "follow_up_email":     None,
            "flags":               [],
            "ghost_items":         [],
        })
        logger.info(f"Saved debrief session for {client_name}")
    except Exception as e:
        logger.error(f"Supabase save error: {e}")


# ── AI Debrief Generator ──────────────────────────────────────────────────────
async def generate_debrief(client_name: str, transcript: str, ctx_text: str) -> str:
    today = datetime.now(tz=TZ).strftime("%A, %B %d, %Y")

    prompt = f"""You are the client intelligence agent for Momen Tax Services.

CLIENT: {client_name}
DATE: {today}

CONTEXT FROM SUPABASE (prior sessions, profile, open items, Telegram history):
{ctx_text}

MEETING TRANSCRIPT:
{transcript[:8000]}

Produce a post-meeting debrief in Markdown:

## Meeting Debrief — {client_name} — {today}

### What Was Decided
### Action Items (owner + timeline)
- [ ] Task — Owner — Due
### Open Items & Unresolved Questions
### Context from Prior Conversations (what was said before that's relevant)
### Flags & Watch Items
### Suggested Next Steps (top 3-5, priority order)
### One-Paragraph Summary (3-5 sentences, suitable for CRM)

Rules: use names, be specific, don't invent details, professional tone. Output ONLY the debrief."""

    ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Commands ──────────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    count   = len(chat_history.get(chat_id, []))
    await update.message.reply_text(
        f"*MTS Client Agent — Supabase Edition*\n"
        f"Messages in context: *{count}*\n\n"
        f"Usage: `@{BOT_USERNAME} Client Name` + attach Fathom transcript",
        parse_mode="Markdown",
    )

async def cmd_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Look up a client in Supabase. Usage: /lookup Client Name"""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/lookup Client Name`", parse_mode="Markdown")
        return
    name = " ".join(args)
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Looking up *{name}*...", parse_mode="Markdown")
    ctx = await get_full_client_context(name, chat_id)
    ctx_text = format_client_context(name, ctx)
    await update.message.reply_text(f"*{name}*\n\n{ctx_text[:3000]}", parse_mode="Markdown")


# ── Utilities ─────────────────────────────────────────────────────────────────
def split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("lookup", cmd_lookup))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.Document.ALL) & ~filters.COMMAND,
        handle_message,
    ))

    logger.info("MTS Client Agent (Supabase) running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
