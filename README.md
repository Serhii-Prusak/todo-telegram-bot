# Todo Telegram Bot

A local Telegram task assistant that uses OpenAI to parse natural-language tasks, creates tasks in Todoist, and can send a daily task digest while the bot process is running.

## Features

- Add tasks from Telegram
- Parse natural-language task text using OpenAI
- Create tasks in Todoist
- Ask follow-up questions when required fields are missing
- View active, today, soon, overdue, and digest task lists
- Complete Todoist tasks from Telegram with confirmation
- Store pending drafts and input mode in local SQLite

Gamification is intentionally left for a future update.

## Stack

- Python 3.11+
- Telegram Bot API
- OpenAI API
- Todoist API v1
- SQLite
- python-telegram-bot

## Project Structure

```text
/todo-telegram-bot
  bot.py
  openai_parser.py
  todoist_client.py
  db.py
  requirements.txt
  .env
  task_assistant.db
```

## Requirements

- Telegram bot token from BotFather
- Todoist API token
- OpenAI API key
- Todoist project ID
- Todoist labels/categories

Recommended Todoist labels:

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

## Task Metadata

Priority uses Todoist UI-style values:

```text
P1 = highest / urgent
P2 = important
P3 = normal
P4 = low / no rush
```

The Todoist API uses the reverse numeric direction, and the bot maps it automatically:

```text
Bot P1 -> Todoist API priority 4
Bot P2 -> Todoist API priority 3
Bot P3 -> Todoist API priority 2
Bot P4 -> Todoist API priority 1
```

Size values:

```text
S = small task for 1 day max
M = medium task for 1-3 days
L = large task for more than 3 days or multiple steps
XL = huge task with significant effort, steps, or dependencies
```

## Setup

Create and activate a virtual environment:

```bash
cd /todo-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env` in the project root:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

TODOIST_API_TOKEN=your_todoist_api_token_here
TODOIST_PROJECT_ID=your_real_todoist_project_id

OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

TIMEZONE=Europe/Berlin
```

Do not commit `.env`.

## Running Locally

Start the bot from the project root:

```bash
cd /todo-telegram-bot
source .venv/bin/activate
python bot.py
```

Stop the bot with `Ctrl+C`.

The automatic digest only runs while `python bot.py` is running locally. A small server deployment can be added later for always-on use.

## Getting Telegram Chat ID

Run the bot and send:

```text
/chatid
```

The bot replies with your chat ID. Add it to `.env`:

```env
TELEGRAM_CHAT_ID=123456789
```

## Telegram Commands

```text
/start   Show welcome message
/help    Show command help
/menu    Show the main button menu
/add     Start adding a task
/list    Show all active tasks
/today   Show tasks due today
/soon    Show tasks due in the next 3 days
/overdue Show overdue tasks
/digest  Show full task digest
/close   Show task-completion buttons
/done    Close a task by ID
/cancel  Cancel a pending task draft or input mode
/chatid  Show the current Telegram chat ID
```

Add a task directly:

```text
/add Buy cat food tomorrow priority 2 size S category pets
```

Or press `Add task` in `/menu`, then send the task text without `/add`.

If required fields are missing, the bot asks for a follow-up:

```text
priority 3 size M category home
```

Task list views are read-only so they stay easy to scan. Use `/close` or the `Close tasks` button when you want to finish tasks from Telegram. Digest is a daily report view and only links back to the menu.

## Daily Digest

The bot sends an automatic digest every day while it is running locally.

The digest includes:

```text
Overdue tasks
Tasks due today
Tasks due soon
Future tasks
Tasks without due date
```

## SQLite Database

The bot uses local SQLite for:

- Pending task drafts
- Current chat input modes

Database file:

```text
task_assistant.db
```

Initialize the database manually:

```bash
cd /todo-telegram-bot
source .venv/bin/activate
python -c "from db import init_db; init_db(); print('DB initialized')"
```

Clear pending drafts and modes:

```bash
cd /todo-telegram-bot
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

Stop the extra local process:

```bash
pkill -f bot.py
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
cd /todo-telegram-bot
source .venv/bin/activate
python -c "from db import init_db; init_db(); print('DB initialized')"
```

Then restart `python bot.py`.

### Todoist endpoint deprecated

Use Todoist API v1:

```text
https://api.todoist.com/api/v1
```

Do not use the old REST v2 base URL:

```text
https://api.todoist.com/rest/v2
```

### Todoist project ID missing or invalid

Set `TODOIST_PROJECT_ID` in `.env` to the real Todoist project ID. Do not leave placeholder values such as `your_project_id_here`.

### OpenAI API key missing

Check `.env`:

```env
OPENAI_API_KEY=sk-...
```

No spaces around `=`.

## Security Notes

- Never commit `.env`
- Do not paste API keys or Telegram tokens in chats, logs, or GitHub
- If a Telegram token is leaked, revoke it with BotFather
- If an OpenAI API key is leaked, delete it in the OpenAI Platform and create a new one
- Keep API usage limits low while testing
- Keep local machine paths and usernames out of public documentation

## Future Ideas

- Small server deployment for always-on use
- XP, levels, streaks, or other gamification
- Recurring tasks
- Task rescheduling from Telegram
- Editing tasks from Telegram
- Web dashboard
