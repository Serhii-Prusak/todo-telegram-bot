# Todo Telegram Bot

A personal Telegram task assistant that uses OpenAI to parse natural-language tasks, creates tasks in Todoist, and sends daily task digests.

## Features

- Add tasks from Telegram
- Parse natural-language task text using OpenAI
- Create tasks in Todoist
- Required fields:
  - Priority: P1–P4
  - Size: S, M, L, XL
  - Category
- Optional due date
- Follow-up flow when required fields are missing
- View tasks from Telegram
- Complete tasks from Telegram with confirmation
- Daily automatic digest
- Runs as a background service on macOS

## Stack

- Python
- Telegram Bot API
- OpenAI API
- Todoist API v1
- SQLite
- python-telegram-bot
- macOS launchd for background service

## Project Structure

```text
todo-telegram-bot/
  bot.py
  openai_parser.py
  todoist_client.py
  db.py
  requirements.txt
  .env
  task_assistant.db
  logs/
    bot.out.log
    bot.err.log
```

## Requirements

- Python 3.11+
- Telegram bot token from BotFather
- Todoist API token
- OpenAI API key
- Todoist project, for example: `Task Assistant`
- Todoist labels/categories

## Todoist Labels

Recommended labels:

```text
travel
visit
pets
food
shopping
work
long-term
home
health
admin
```

Create these labels in Todoist before using the bot.

## Priority Meaning

The bot uses Todoist UI-style priority:

```text
P1 = highest / urgent
P2 = important
P3 = normal
P4 = low / no rush
```

Internally, Todoist API uses reverse priority values, so the bot maps them automatically:

```text
Bot P1 -> Todoist API priority 4
Bot P2 -> Todoist API priority 3
Bot P3 -> Todoist API priority 2
Bot P4 -> Todoist API priority 1
```

## Size Meaning

```text
S = small task for 1 day max
M = medium task for 1–3 days
L = large task for more than 3 days or multiple steps
XL = huge task with significant time, effort, steps, or dependencies
```

## Setup

### 1. Create and activate virtual environment

```bash
cd /Users/lana/Projects/todo-telegram-bot

python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Example `requirements.txt`:

```txt
python-telegram-bot[job-queue]==21.10
python-dotenv==1.0.1
openai==1.59.7
requests==2.32.3
```

The `job-queue` extra is needed for automatic daily digest scheduling.

### 3. Create `.env`

Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

TODOIST_API_TOKEN=your_todoist_api_token_here
TODOIST_PROJECT_NAME=Task Assistant
TODOIST_PROJECT_ID=your_todoist_project_id_here

OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

TIMEZONE=Europe/Berlin
```

Do not commit `.env` to GitHub.

## Getting Telegram Chat ID

Run the bot and send:

```text
/chatid
```

The bot replies with your chat ID. Add it to `.env` as:

```env
TELEGRAM_CHAT_ID=123456789
```

## Running Locally

```bash
cd /Users/lana/Projects/todo-telegram-bot
source .venv/bin/activate
python bot.py
```

Stop with:

```text
Ctrl+C
```

## Telegram Commands

### `/start`

Shows welcome message and menu buttons.

### `/help`

Shows command list, priority rules, size rules, and examples.

### `/menu`

Shows the main button menu.

### `/add <task>`

Adds a new task.

Example:

```text
/add Buy cat food tomorrow priority 2 size S category pets
```

If required fields are missing, the bot asks a follow-up question.

Example:

```text
/add Clean apartment
```

Bot asks for missing fields:

```text
Please provide priority, size, and category.
```

Then reply:

```text
priority 3 size M category home
```

### Add Task Button

From `/menu`, press:

```text
➕ Add task
```

Then send the task text without `/add`.

Example:

```text
Buy cat food tomorrow priority 2 size S category pets
```

### `/list`

Shows all active tasks grouped by:

```text
Overdue
Today
Due soon
Future
No due date
```

Task buttons are shown below the message.

### `/today`

Shows tasks due today.

### `/soon`

Shows tasks due in the next 3 days.

### `/overdue`

Shows overdue tasks.

### `/digest`

Shows the full task digest manually.

### `/done <task_id>`

Starts task-completion confirmation.

Example:

```text
/done 123456
```

The bot asks:

```text
Are you sure you finished this task?
```

Then you can confirm or cancel.

### Task Completion Buttons

Task lists include task-name buttons. Pressing one asks for confirmation before closing the task in Todoist.

### `/cancel`

Cancels a pending task draft or current add-task input mode.

### `/chatid`

Shows the current Telegram chat ID.

## Daily Digest

The bot sends an automatic digest every day at 07:00 Europe/Berlin.

The digest includes:

```text
Overdue tasks
Tasks due today
Tasks due soon
Future tasks
Tasks without due date
```

The automatic digest works only while the bot process is running.

## macOS Background Service

The bot can run in the background using `launchd`.

### Service file

Location:

```bash
~/Library/LaunchAgents/com.lana.todo-telegram-bot.plist
```

Example plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.lana.todo-telegram-bot</string>

    <key>ProgramArguments</key>
    <array>
      <string>/Users/lana/Projects/todo-telegram-bot/.venv/bin/python</string>
      <string>/Users/lana/Projects/todo-telegram-bot/bot.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/lana/Projects/todo-telegram-bot</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/lana/Projects/todo-telegram-bot/logs/bot.out.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/lana/Projects/todo-telegram-bot/logs/bot.err.log</string>
  </dict>
</plist>
```

### Start service

```bash
launchctl load ~/Library/LaunchAgents/com.lana.todo-telegram-bot.plist
launchctl start com.lana.todo-telegram-bot
```

### Stop service

```bash
launchctl stop com.lana.todo-telegram-bot
```

### Restart after code changes

```bash
launchctl stop com.lana.todo-telegram-bot
launchctl start com.lana.todo-telegram-bot
```

### Unload service

```bash
launchctl unload ~/Library/LaunchAgents/com.lana.todo-telegram-bot.plist
```

### Check service status

```bash
launchctl list | grep todo-telegram-bot
```

### Check logs

```bash
tail -f /Users/lana/Projects/todo-telegram-bot/logs/bot.out.log
```

```bash
tail -f /Users/lana/Projects/todo-telegram-bot/logs/bot.err.log
```

## SQLite Database

The bot uses SQLite for:

- Pending task drafts
- Current chat input modes

Database file:

```text
task_assistant.db
```

To initialize database manually:

```bash
cd /Users/lana/Projects/todo-telegram-bot
source .venv/bin/activate
python -c "from db import init_db; init_db(); print('DB initialized')"
```

To clear pending drafts and modes:

```bash
cd /Users/lana/Projects/todo-telegram-bot
source .venv/bin/activate
python -c "from db import init_db; init_db(); import sqlite3; conn=sqlite3.connect('task_assistant.db'); conn.execute('DELETE FROM pending_tasks'); conn.execute('DELETE FROM chat_modes'); conn.commit(); print('cleared')"
```

## Troubleshooting

### Bot replies twice

Most likely two bot processes are running.

Check:

```bash
pgrep -af "todo-telegram-bot|bot.py|python"
```

Kill old processes:

```bash
pkill -f bot.py
```

If needed:

```bash
kill -9 <PID>
```

### Telegram Markdown error

If Telegram says:

```text
Can't parse entities
```

Remove `parse_mode="Markdown"` from that reply or escape user/task text before sending.

### `no such table: chat_modes`

Run database initialization:

```bash
cd /Users/lana/Projects/todo-telegram-bot
source .venv/bin/activate
python -c "from db import init_db; init_db(); print('DB initialized')"
```

Then restart the service.

### Todoist endpoint deprecated

Use Todoist API v1:

```text
https://api.todoist.com/api/v1
```

Do not use the old REST v2 base URL:

```text
https://api.todoist.com/rest/v2
```

### Todoist task creation is slow

Add `TODOIST_PROJECT_ID` to `.env` so the bot does not fetch all projects every time.

### OpenAI API key missing

Check `.env`:

```env
OPENAI_API_KEY=sk-...
```

No spaces around `=`.

Correct:

```env
OPENAI_API_KEY=sk-...
```

Wrong:

```env
OPENAI_API_KEY = sk-...
```

### Date range not detected

The parser should use the first date in a range.

Example:

```text
Remind me about Prime Days on 23-26 June
```

Expected due date:

```text
June 23
```

If the model misses it, the fallback date parser in `openai_parser.py` should set it.

## Security Notes

- Never commit `.env`
- Do not paste API keys or Telegram tokens in chats, logs, or GitHub
- If a Telegram token is leaked, revoke it with BotFather
- If an OpenAI API key is leaked, delete it in the OpenAI Platform and create a new one
- Keep API usage limits low while testing

## Future Ideas

Not implemented yet:

- XP and gold for completed tasks
- Level-up choices
- Luck stat
- Streaks
- Recurring tasks
- Task rescheduling from Telegram
- Editing tasks from Telegram
- Hosting on VPS for 24/7 reliability
- Web dashboard
