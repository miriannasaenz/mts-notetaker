# MTS Intelligence Suite
**Momen Tax Services | Internal Tools Documentation**

---

## Overview

This suite consists of three tools built for MTS internal operations:

1. **MTS Meeting Agent** — a web app for processing meeting transcripts, managing client profiles, and generating meeting summaries + follow-up emails
2. **Telegram EOD Bot** — monitors all company Telegram group chats and sends a morning debrief + end-of-day report
3. **Telegram Client Agent** — processes Fathom meeting transcripts shared via Telegram and returns a structured debrief

---

## 1. MTS Meeting Agent (Web App)

### What it does
- Paste any meeting transcript or Fathom summary and generate a full MTS-formatted output in one click
- Outputs: overview, notes & questions, client next steps, MTS tasks, suggested next agenda, flags, and a ready-to-send follow-up email
- Automatically builds and updates client profiles (phone, email, businesses, industry, filing status, spouse, service type, last meeting date)
- Stores full session history per client — every past meeting is saved and searchable
- Sessions are collapsible and fully editable (date, meeting type, all sections, email)
- Client names are editable and renameable
- Agenda Builder generates pre-meeting agendas from client history
- Password protected

### How to access
Hosted on GitHub Pages at:
`https://miriannasaenz.github.io/mts-notetaker/`

The file must be named `index.html` in the root of the repo for GitHub Pages to serve it correctly.

### First-time setup
1. Open the URL
2. Enter the site password
3. Enter your Anthropic API key (get from console.anthropic.com → API Keys)
4. The key saves to your browser — you won't be asked again on that device

### How to use

**Processing a transcript:**
1. Go to **New Meeting** tab
2. Paste your transcript, voice memo text, or Fathom summary
3. Optionally paste the meeting agenda at the top — the agent will use it to answer each question directly
4. Click **Generate Summary**
5. Review the output — client next steps and MTS tasks are checkable
6. Use **Copy All** to copy the full summary, or **Copy Email** for just the follow-up email

**Client Profiles:**
- Go to **Clients** tab to see all stored clients
- Use the search bar to filter
- Click any client to open their profile
- Profile fields auto-populate when you open a client (reads session history)
- Click **Edit** to manually update any field
- Click **Refresh** to regenerate the profile from session history at any time
- Sessions are listed newest-first and collapse/expand by clicking the header
- Click **Edit** on any session to edit date, type, summary, all sections, and the email

**Agenda Builder:**
- Go to **Agenda Builder** tab
- Type a client name or click a known client
- Click **Build Agenda** — generates from session history and open items

### Data storage
All client data is stored in your **browser's localStorage** — it persists as long as you use the same browser on the same device. It does not sync across devices. Do not use incognito mode or data will not be saved.

---

## 2. Telegram EOD Bot

### What it does
- Sits silently in all Telegram group chats
- Sends a **Morning Debrief at 8:00 AM PT** — pulls from yesterday's EOD report, open items, ghost items, and suggests a game plan for the day
- Sends an **EOD Report at 5:00 PM PT** — analyzes everything said that day across all chats
- Both reports cover: completed items, action items, unresolved questions, decisions made, key topics, ghost items (things mentioned but never followed up on), and a watch list

### Commands (use in any group chat)
| Command | What it does |
|---|---|
| `/status` | Shows messages logged today and next report times |
| `/report` | Manually triggers an EOD report right now |
| `/morning` | Manually triggers a morning debrief right now |
| `/clear` | Clears today's message log for this chat |

### Hosting
Deployed on Railway. To access:
1. Go to railway.app → your `mts-telegram-bot` project
2. View logs under the service → Logs tab
3. The bot auto-restarts if it crashes

### Environment variables (set in Railway)
| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `TIMEZONE` | `America/Los_Angeles` |
| `EOD_HOUR` | `17` (5 PM) |
| `EOD_MINUTE` | `0` |
| `AM_HOUR` | `8` (8 AM) |
| `AM_MINUTE` | `0` |

### Files
- `telegram-eod-bot.py` — main bot file (upload to GitHub repo, Railway deploys automatically)
- `telegram-eod-requirements.txt` — Python dependencies
- `telegram-eod-Procfile` — tells Railway how to run it

### Changing report times
Update `EOD_HOUR`, `EOD_MINUTE`, `AM_HOUR`, or `AM_MINUTE` in Railway → Variables. Railway restarts the bot automatically.

---

## 3. Telegram Client Agent

### What it does
- Sits in any Telegram group chat
- When you tag it with a client name and attach a Fathom transcript file, it generates a full post-meeting debrief
- Cross-references Telegram chat history for that client and includes prior context in the debrief
- Debrief includes: what was decided, action items with owners, open questions, context from prior conversations, flags, suggested next steps, and a one-paragraph CRM-ready summary

### How to use
In any group chat where the bot is added:
```
@YourBotUsername Client Name
[attach Fathom transcript as .txt or .pdf]
```

**Example:**
```
@MTSClientAgentBot Jakob Lively Lighting
[attach transcript.txt]
```

**Check status:**
```
/status
```

### File format
The bot reads `.txt` files natively. For Fathom PDFs: export as text or copy-paste the transcript into a `.txt` file before sending.

### Hosting
Separate Railway project from the EOD bot. Same deployment process — connect a GitHub repo with the agent files and set environment variables.

### Environment variables
| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | New bot token (different from EOD bot) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `BOT_USERNAME` | Bot username without @ (e.g. `MTSClientAgentBot`) |
| `TIMEZONE` | `America/Los_Angeles` |

### Files
- `telegram-client-agent.py` — main agent file
- `telegram-client-requirements.txt` — Python dependencies
- A `Procfile` with content: `worker: python agent.py`

---

## Adding bots to a new Telegram group
1. Open the group → tap the group name → Add Members
2. Search for the bot's username
3. Add it
4. Important: BotFather privacy mode must be set to **Disabled** for the bot to read all messages (not just commands). To check: open BotFather → `/setprivacy` → select the bot → it should say Disabled

---

## Contact / Ownership
Built for internal use at Momen Tax Services.
Maintained by Mirianna Saenz