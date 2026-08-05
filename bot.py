import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)
from openai_parser import parse_task_text, parse_followup_metadata
from todoist_client import create_task, get_active_tasks, close_task
from datetime import date, datetime
from zoneinfo import ZoneInfo
from db import (
    init_db,
    save_pending_task,
    get_pending_task,
    clear_pending_task,
    set_chat_mode,
    get_chat_mode,
    clear_chat_mode,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def parse_telegram_ids(raw_value: str | None, variable_name: str) -> frozenset[int]:
    if not raw_value:
        return frozenset()

    parsed_ids = set()
    for raw_id in raw_value.split(","):
        value = raw_id.strip()
        if not value:
            continue

        try:
            parsed_ids.add(int(value))
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid Telegram ID {value!r} in {variable_name}. "
                "Use comma-separated numeric IDs."
            ) from exc

    return frozenset(parsed_ids)


LEGACY_TELEGRAM_CHAT_IDS = parse_telegram_ids(
    os.getenv("TELEGRAM_CHAT_ID"),
    "TELEGRAM_CHAT_ID",
)
TELEGRAM_ALLOWED_USER_IDS = parse_telegram_ids(
    os.getenv("TELEGRAM_ALLOWED_USER_IDS"),
    "TELEGRAM_ALLOWED_USER_IDS",
) or LEGACY_TELEGRAM_CHAT_IDS
TELEGRAM_DIGEST_CHAT_IDS = parse_telegram_ids(
    os.getenv("TELEGRAM_DIGEST_CHAT_IDS"),
    "TELEGRAM_DIGEST_CHAT_IDS",
) or TELEGRAM_ALLOWED_USER_IDS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def is_chat_id_command(update: Update) -> bool:
    message = update.effective_message
    if not message or not message.text:
        return False

    command = message.text.split(maxsplit=1)[0].lower()
    command = command.split("@", maxsplit=1)[0]
    return command == "/chatid"


async def enforce_allowlist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context

    # Anyone may retrieve their own ID so the owner can add them to the allowlist.
    if is_chat_id_command(update):
        return

    user = update.effective_user
    if user and user.id in TELEGRAM_ALLOWED_USER_IDS:
        return

    user_id = user.id if user else "unknown"
    logging.warning("Blocked Telegram update from unauthorized user ID %s", user_id)

    if update.callback_query:
        await update.callback_query.answer(
            "This bot is private. Send /chatid and ask the owner for access.",
            show_alert=True,
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            "🔒 This bot is private.\n\n"
            "Send /chatid, then ask the bot owner to add your user ID."
        )

    raise ApplicationHandlerStop


# --------------------Bot command handlers--------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "👋 Hi! I am your Task Assistant bot.\n\n"
        "Available commands:\n"
        "/start — show welcome message\n"
        "/help — show help\n"
        "/add <task> — add a new task to Todoist\n\n"
        "Example:\n"
        "/add Buy cat food tomorrow priority 4 size S"
    )
    await update.message.reply_text(
        message,
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "📌 Task Assistant Help\n\n"
        "Commands:\n"
        "/add <task> — add a new task to Todoist\n"
        "/list — show all active tasks\n"
        "/today — show tasks due today\n"
        "/overdue — show overdue tasks\n"
        "/close — show task completion buttons\n"
        "/done <task_id> — close a task by ID\n"
        "/digest — show full task digest\n\n"
        "/soon — show tasks due in the next 3 days\n"
        "/cancel — cancel pending task draft\n"
        "/menu — show button menu\n"
        "Required fields:\n"
        "• priority: 1–4\n"
        "  P1 = highest / urgent\n"
        "  P2 = important\n"
        "  P3 = normal\n"
        "  P4 = low / no rush\n\n"
        "• size: S, M, L, XL\n"
        "  S = small task for 1 day max\n"
        "  M = medium task for 1–3 days\n"
        "  L = large task for more than 3 days or multiple steps\n"
        "  XL = huge task with significant effort/dependencies\n\n"
        "Optional:\n"
        "• due date\n\n"
        "Examples:\n"
        "/add Buy cat food tomorrow priority 2 size S\n"
        "/add Prepare visa documents next week, urgent and large\n"
        "/add Clean apartment"
    )
    await update.message.reply_text(
        message,
        reply_markup=main_menu_keyboard(),
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    if not tasks:
        await update.message.reply_text(
            "🎉 No active tasks found.",
            reply_markup=navigation_keyboard(),
        )
        return

    message = grouped_task_message(tasks, title="📋 Active tasks")

    await update.message.reply_text(
        message,
        reply_markup=task_view_keyboard(),
    )


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    short_id_input = " ".join(context.args).strip()

    if not short_id_input:
        await update.message.reply_text(
            "Please send the task ID after /done.\n\n"
            "Example:\n"
            "/done 123456"
        )
        return

    try:
        tasks = get_active_tasks()
        task = find_task_by_short_id(tasks, short_id_input)
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    if not task:
        await update.message.reply_text(
            f"I could not find an active task ending with ID {short_id_input}.\n\n"
            "Use /close to finish tasks with buttons."
        )
        return

    task_id = str(task.get("id"))
    task_content = task.get("content", "Untitled task")

    await update.message.reply_text(
        "Are you sure you finished this task?\n\n"
        f"{task_content}",
        reply_markup=confirm_done_keyboard(task_id),
    )


async def today_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    today = get_today_berlin()

    today_only = [
        task for task in tasks
        if get_task_due_date(task) == today
    ]

    today_only = sort_tasks_by_due_and_priority(today_only)

    if not today_only:
        await update.message.reply_text(
            "🎉 No tasks due today.",
            reply_markup=navigation_keyboard(),
        )
        return

    lines = [f"📌 Tasks due today ({today.isoformat()}):\n"]

    for task in today_only:
        lines.append(format_task_line(task))

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=task_view_keyboard(),
    )


async def overdue_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    today = get_today_berlin()

    overdue_only = [
        task for task in tasks
        if get_task_due_date(task) is not None
        and get_task_due_date(task) < today
    ]

    overdue_only = sort_tasks_by_due_and_priority(overdue_only)

    if not overdue_only:
        await update.message.reply_text(
            "✅ No overdue tasks.",
            reply_markup=navigation_keyboard(),
        )
        return

    lines = [f"🚨 OVERDUE tasks ({today.isoformat()}):\n"]

    for task in overdue_only:
        due_date = get_task_due_date(task)
        days_overdue = (today - due_date).days if due_date else 0

        lines.append(
            f"{format_task_line(task)} — overdue by {days_overdue} day(s)"
        )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=task_view_keyboard(),
    )


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    task_text = " ".join(context.args).strip()

    if not task_text:
        set_chat_mode(update.effective_chat.id, "awaiting_new_task")

        await update.message.reply_text(
            "➕ Send me the task text now.\n\n"
            "Example:\n"
            "Buy cat food tomorrow priority 2 size S\n\n"
            "I will parse it, ask for missing priority/size if needed, "
            "and then add it to Todoist.",
            reply_markup=pending_input_keyboard(),
        )
        return

    await parse_and_create_task_from_text(update, task_text)


async def digest_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    message = build_digest_message(tasks)
    await update.message.reply_text(
        message,
        reply_markup=digest_keyboard(),
    )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else "Unavailable"
    current_chat_id = update.effective_chat.id if update.effective_chat else "Unavailable"
    await update.message.reply_text(
        f"Your Telegram user ID is:\n{user_id}\n\n"
        f"This chat ID is:\n{current_chat_id}\n\n"
        "In a private chat, these IDs are normally the same."
    )


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TELEGRAM_DIGEST_CHAT_IDS:
        logging.error(
            "No daily digest recipients configured. Set "
            "TELEGRAM_DIGEST_CHAT_IDS or TELEGRAM_ALLOWED_USER_IDS in .env."
        )
        return

    try:
        tasks = get_active_tasks()
        message = build_digest_message(tasks)
    except Exception:
        logging.exception("Failed to build daily digest")
        message = "I could not build the daily task digest. Please check the bot logs."

    for recipient_chat_id in sorted(TELEGRAM_DIGEST_CHAT_IDS):
        try:
            await context.bot.send_message(
                chat_id=recipient_chat_id,
                text=message,
                reply_markup=digest_keyboard(),
            )
        except Exception:
            logging.exception(
                "Failed to send daily digest to Telegram chat ID %s",
                recipient_chat_id,
            )


async def handle_followup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    mode = get_chat_mode(chat_id)
    pending = get_pending_task(chat_id)

    if pending:
        await update.message.reply_text("🔍 Updating task draft...")
        await complete_pending_task_from_followup(update, pending, text)
        return

    if mode == "awaiting_new_task":
        await parse_and_create_task_from_text(update, text)
        return

    await update.message.reply_text(
        "I do not have a pending task for this message.\n\n"
        "Use /add to create a new task.",
        reply_markup=navigation_keyboard(),
    )


async def complete_pending_task_from_followup(
    update: Update,
    pending: dict,
    text: str,
) -> None:
    chat_id = update.effective_chat.id

    # Extract metadata from follow-up text using regex-based method
    # This preserves the original task name/description and only updates the metadata
    followup_metadata = parse_followup_metadata(text)

    # Merge with existing parsed task
    existing = pending["parsed"]
    parsed = existing.copy()

    # Ensure name/description are preserved and non-empty
    if not parsed.get("name"):
        parsed["name"] = pending.get("original_text", "Untitled task")[:80]

    if not parsed.get("description"):
        parsed["description"] = parsed.get("name")

    if followup_metadata.get("priority") is not None:
        parsed["priority"] = followup_metadata["priority"]

    if followup_metadata.get("size") is not None:
        parsed["size"] = followup_metadata["size"]

    if followup_metadata.get("category") is not None:
        parsed["category"] = followup_metadata["category"]

    # Rebuild missing_fields
    missing_fields = []

    if parsed.get("priority") is None:
        missing_fields.append("priority")

    if parsed.get("size") is None:
        missing_fields.append("size")

    if parsed.get("category") is None:
        missing_fields.append("category")

    parsed["missing_fields"] = missing_fields

    if missing_fields:
        questions = []

        if "priority" in missing_fields:
            questions.append("priority 1–4")

        if "size" in missing_fields:
            questions.append("size S, M, L, or XL")

        if "category" in missing_fields:
            questions.append(
                "category: travel, visit, pets, food, shopping, work, long-term, home, health, admin"
            )

        question = "Please provide: " + "; ".join(questions) + "."

        save_pending_task(
            chat_id=chat_id,
            original_text=pending["original_text"],
            parsed=parsed,
        )

        await update.message.reply_text(
            "⚠️ Still missing required information.\n\n"
            f"{question}\n\n"
            "You can reply naturally, for example:\n"
            "priority 3 size M category admin",
            reply_markup=pending_input_keyboard(),
        )
        return

    try:
        todoist_task = create_task(
            name=parsed["name"],
            description=parsed["description"],
            priority=int(parsed["priority"]),
            size=parsed["size"],
            category=parsed["category"],
            due_date=parsed.get("due_date"),
        )
    except Exception as exc:
        logging.exception("Failed to create Todoist task from follow-up")
        await update.message.reply_text(
            "Task was parsed, but I could not create it in Todoist.\n\n"
            f"Error: {exc}",
            reply_markup=navigation_keyboard(),
        )
        return

    clear_pending_task(chat_id)
    clear_chat_mode(chat_id)

    task_url = todoist_task.get("url")

    message = (
        "🎉 Task created in Todoist!\n\n"
        f"{format_task_preview(parsed)}"
    )

    if task_url:
        message += f"\n\nOpen in Todoist:\n{task_url}"

    await update.message.reply_text(
        message,
        reply_markup=navigation_keyboard(),
    )


async def soon_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    today = get_today_berlin()
    soon_limit = today.toordinal() + 3

    soon_only = []

    for task in tasks:
        due_date = get_task_due_date(task)

        if due_date is not None and today < due_date and due_date.toordinal() <= soon_limit:
            soon_only.append(task)

    soon_only = sort_tasks_by_due_and_priority(soon_only)

    if not soon_only:
        await update.message.reply_text(
            "✅ No tasks due soon.",
            reply_markup=navigation_keyboard(),
        )
        return

    lines = ["⚠️ Tasks due soon:\n"]

    for task in soon_only:
        due_date = get_task_due_date(task)
        days_left = (due_date - today).days if due_date else 0
        due_text = "tomorrow" if days_left == 1 else f"in {days_left} days"
        lines.append(f"{format_task_line(task)} — due {due_text}")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=task_view_keyboard(),
    )


async def close_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tasks = get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to fetch Todoist tasks")
        await update.message.reply_text(
            "I could not fetch tasks from Todoist.\n\n"
            f"Error: {exc}"
        )
        return

    await update.message.reply_text(
        build_close_tasks_message(tasks),
        reply_markup=task_done_keyboard(tasks) if tasks else navigation_keyboard(),
    )


async def cancel_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    pending = get_pending_task(chat_id)
    mode = get_chat_mode(chat_id)

    clear_chat_mode(chat_id)

    if pending:
        clear_pending_task(chat_id)
        await update.message.reply_text(
            "❌ Pending task draft cancelled.",
            reply_markup=navigation_keyboard(),
        )
        return

    if mode:
        await update.message.reply_text(
            "❌ Current input mode cancelled.",
            reply_markup=navigation_keyboard(),
        )
        return

    await update.message.reply_text(
        "There is no pending task draft to cancel.",
        reply_markup=navigation_keyboard(),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏠 Task Assistant Menu\n\n"
        "Choose what you want to do:",
        reply_markup=main_menu_keyboard(),
    )
    
# --------------------Helper functions--------------------
async def parse_and_create_task_from_text(
    update: Update,
    task_text: str,
) -> None:
    await update.message.reply_text("🔍 Parsing task...")

    try:
        parsed = parse_task_text(task_text)
    except Exception as exc:
        logging.exception("Failed to parse task")
        await update.message.reply_text(
            "Sorry, I could not parse this task yet.\n\n"
            f"Error: {exc}",
            reply_markup=navigation_keyboard(),
        )
        return

    missing_fields = parsed.get("missing_fields", [])

    if missing_fields:
        question = parsed.get("clarifying_question") or (
            "I need a bit more information: " + ", ".join(missing_fields)
        )

        save_pending_task(
            chat_id=update.effective_chat.id,
            original_text=task_text,
            parsed=parsed,
        )
        clear_chat_mode(update.effective_chat.id)

        await update.message.reply_text(
            "⚠️ I need a bit more information before creating this task.\n\n"
            f"{question}\n\n"
            "You can reply naturally, for example:\n"
            "priority 3 size M category admin",
            reply_markup=pending_input_keyboard(),
        )
        return

    await update.message.reply_text(
        "✅ Parsed task:\n\n"
        f"{format_task_preview(parsed)}\n\n"
        "Creating it in Todoist..."
    )

    try:
        todoist_task = create_task(
            name=parsed["name"],
            description=parsed["description"],
            priority=int(parsed["priority"]),
            size=parsed["size"],
            category=parsed["category"],
            due_date=parsed.get("due_date"),
        )
    except Exception as exc:
        logging.exception("Failed to create Todoist task")
        await update.message.reply_text(
            "Task was parsed, but I could not create it in Todoist.\n\n"
            f"Error: {exc}",
            reply_markup=navigation_keyboard(),
        )
        return

    clear_chat_mode(update.effective_chat.id)

    task_url = todoist_task.get("url")

    message = (
        "🎉 Task created in Todoist!\n\n"
        f"{format_task_preview(parsed)}"
    )

    if task_url:
        message += f"\n\nOpen in Todoist:\n{task_url}"

    await update.message.reply_text(
        message,
        reply_markup=navigation_keyboard(),
    )


def format_task_preview(parsed: dict) -> str:
    due_date = parsed.get("due_date") or "No due date"

    return (
        f"[P{parsed.get('priority')}][{parsed.get('size')}][{parsed.get('category')}] "
        f"{parsed.get('name')}\n"
        f"Due: {due_date}\n"
        f"Description: {parsed.get('description')}"
    )


def short_task_id(task_id: str) -> str:
    return str(task_id)[-6:]


def task_display_title(task: dict) -> str:
    content = task.get("content", "Untitled task")

    # Remove metadata prefix visually:
    # [P3][M][home] Clean apartment -> Clean apartment
    if "] " in content:
        return content.split("] ", maxsplit=1)[-1]

    return content


def task_metadata(task: dict) -> dict:
    content = task.get("content", "")
    metadata = {
        "priority": None,
        "size": None,
        "category": None,
    }

    if not content.startswith("[P") or "] " not in content:
        return metadata

    metadata_text = content.split("] ", maxsplit=1)[0]
    parts = metadata_text.strip("[]").split("][")

    for part in parts:
        if part.startswith("P") and part[1:].isdigit():
            metadata["priority"] = part
        elif part in {"S", "M", "L", "XL"}:
            metadata["size"] = part
        else:
            metadata["category"] = part

    return metadata


def format_task_line(
    task: dict,
    include_id: bool = False,
    include_metadata: bool = False,
) -> str:
    task_id = str(task.get("id"))
    content = task_display_title(task)
    metadata = task_metadata(task)

    due = task.get("due")
    due_text = "No due date"

    if isinstance(due, dict):
        due_text = due.get("date") or due.get("datetime") or "No due date"

    metadata_text = ""
    if include_metadata:
        metadata_parts = [
            part for part in [metadata["priority"], metadata["size"]]
            if part
        ]

        if metadata_parts:
            metadata_text = f"{' / '.join(metadata_parts)} · "

    if include_id:
        return f"• {short_task_id(task_id)} — {metadata_text}{content} — {due_text}"

    return f"• {metadata_text}{content} — {due_text}"


def find_task_by_short_id(tasks: list[dict], short_id: str) -> dict | None:
    for task in tasks:
        task_id = str(task.get("id"))
        if task_id.endswith(short_id):
            return task

    return None


def get_task_due_date(task: dict) -> date | None:
    due = task.get("due")

    if not isinstance(due, dict):
        return None

    due_value = due.get("date") or due.get("datetime")

    if not due_value:
        return None

    # due.date usually looks like "2026-05-29"
    # due.datetime may look like "2026-05-29T10:00:00Z"
    try:
        return date.fromisoformat(due_value[:10])
    except ValueError:
        return None


def get_today_berlin() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def sort_tasks_by_due_and_priority(tasks: list[dict]) -> list[dict]:
    def sort_key(task: dict):
        due_date = get_task_due_date(task)

        # Todoist API priority: 4 highest, 1 lowest
        api_priority = task.get("priority", 1)

        # Tasks without due date go last
        due_sort = due_date or date.max

        # Higher priority first
        priority_sort = -int(api_priority or 1)

        return due_sort, priority_sort

    return sorted(tasks, key=sort_key)


def build_digest_message(tasks: list[dict]) -> str:
    today = get_today_berlin()
    soon_limit = today.toordinal() + 3

    overdue = []
    today_tasks_list = []
    due_soon = []
    future = []
    no_due_date = []

    for task in tasks:
        due_date = get_task_due_date(task)

        if due_date is None:
            no_due_date.append(task)
        elif due_date < today:
            overdue.append(task)
        elif due_date == today:
            today_tasks_list.append(task)
        elif due_date.toordinal() <= soon_limit:
            due_soon.append(task)
        else:
            future.append(task)

    overdue = sort_tasks_by_due_and_priority(overdue)
    today_tasks_list = sort_tasks_by_due_and_priority(today_tasks_list)
    due_soon = sort_tasks_by_due_and_priority(due_soon)
    future = sort_tasks_by_due_and_priority(future)
    no_due_date = sort_tasks_by_due_and_priority(no_due_date)

    lines = [
        f"🌅 Task Digest — {today.isoformat()}",
        "",
        (
            f"Overdue: {len(overdue)} | Today: {len(today_tasks_list)} | "
            f"Soon: {len(due_soon)} | Later: {len(future)} | No date: {len(no_due_date)}"
        ),
        "",
    ]

    if overdue:
        lines.append("🚨 OVERDUE")
        for task in overdue:
            due_date = get_task_due_date(task)
            days_overdue = (today - due_date).days if due_date else 0
            lines.append(
                f"{format_task_line(task, include_metadata=True)} — "
                f"overdue by {days_overdue} day(s)"
            )
        lines.append("")

    if today_tasks_list:
        lines.append("📌 Today")
        for task in today_tasks_list:
            lines.append(format_task_line(task, include_metadata=True))
        lines.append("")

    if due_soon:
        lines.append("⚠️ Due soon")
        for task in due_soon:
            due_date = get_task_due_date(task)
            days_left = (due_date - today).days if due_date else 0

            if days_left == 1:
                due_text = "tomorrow"
            else:
                due_text = f"in {days_left} days"

            lines.append(
                f"{format_task_line(task, include_metadata=True)} — due {due_text}"
            )
        lines.append("")

    if future:
        lines.append(f"🗓 Later ({len(future)})")
        for task in future[:5]:
            lines.append(format_task_line(task, include_metadata=True))
        if len(future) > 5:
            lines.append(f"• ...and {len(future) - 5} more")
        lines.append("")

    if no_due_date:
        lines.append(f"🧊 No due date ({len(no_due_date)})")
        for task in no_due_date[:5]:
            lines.append(format_task_line(task, include_metadata=True))
        if len(no_due_date) > 5:
            lines.append(f"• ...and {len(no_due_date) - 5} more")
        lines.append("")

    if not any([overdue, today_tasks_list, due_soon, future, no_due_date]):
        lines.append("🎉 No active tasks found.")

    return "\n".join(lines)


def build_close_tasks_message(tasks: list[dict]) -> str:
    if not tasks:
        return "🎉 No active tasks found."

    visible_count = min(len(tasks), 10)
    lines = [f"✅ Close tasks\n\nChoose one task below. Showing {visible_count} of {len(tasks)} active task(s).\n"]

    for task in sort_tasks_by_due_and_priority(tasks)[:visible_count]:
        lines.append(format_task_line(task))

    if len(tasks) > visible_count:
        lines.append("")
        lines.append("Use /today, /soon, or /overdue first if you want a smaller list.")

    return "\n".join(lines)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add task", callback_data="cmd:help_add"),
            ],
            [
                InlineKeyboardButton("📋 All tasks", callback_data="cmd:list"),
                InlineKeyboardButton("📌 Today", callback_data="cmd:today"),
            ],
            [
                InlineKeyboardButton("⚠️ Soon", callback_data="cmd:soon"),
                InlineKeyboardButton("🚨 Overdue", callback_data="cmd:overdue"),
            ],
            [
                InlineKeyboardButton("🌅 Digest", callback_data="cmd:digest"),
                InlineKeyboardButton("✅ Close tasks", callback_data="cmd:close"),
            ],
        ]
    )


def confirm_done_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, finish it", callback_data=f"confirm_done:{task_id}"),
                InlineKeyboardButton("↩️ No", callback_data="cancel_done"),
            ],
            [
                InlineKeyboardButton("📋 All tasks", callback_data="cmd:list"),
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def grouped_task_message(
    tasks: list[dict],
    title: str = "📋 Active tasks",
    include_future: bool = True,
    include_no_due_date: bool = True,
) -> str:
    today = get_today_berlin()
    soon_limit = today.toordinal() + 3

    overdue = []
    today_tasks_list = []
    due_soon = []
    future = []
    no_due_date = []

    for task in tasks:
        due_date = get_task_due_date(task)

        if due_date is None:
            no_due_date.append(task)
        elif due_date < today:
            overdue.append(task)
        elif due_date == today:
            today_tasks_list.append(task)
        elif due_date.toordinal() <= soon_limit:
            due_soon.append(task)
        else:
            future.append(task)

    overdue = sort_tasks_by_due_and_priority(overdue)
    today_tasks_list = sort_tasks_by_due_and_priority(today_tasks_list)
    due_soon = sort_tasks_by_due_and_priority(due_soon)
    future = sort_tasks_by_due_and_priority(future)
    no_due_date = sort_tasks_by_due_and_priority(no_due_date)

    lines = [f"{title}\n"]

    if overdue:
        lines.append("🚨 OVERDUE")
        for task in overdue:
            due_date = get_task_due_date(task)
            days_overdue = (today - due_date).days if due_date else 0
            lines.append(f"{format_task_line(task)} — overdue by {days_overdue} day(s)")
        lines.append("")

    if today_tasks_list:
        lines.append("📌 Today")
        for task in today_tasks_list:
            lines.append(format_task_line(task))
        lines.append("")

    if due_soon:
        lines.append("⚠️ Due soon")
        for task in due_soon:
            due_date = get_task_due_date(task)
            days_left = (due_date - today).days if due_date else 0
            due_text = "tomorrow" if days_left == 1 else f"in {days_left} days"
            lines.append(f"{format_task_line(task)} — due {due_text}")
        lines.append("")

    if include_future and future:
        lines.append("🗓 Future")
        for task in future:
            lines.append(format_task_line(task))
        lines.append("")

    if include_no_due_date and no_due_date:
        lines.append("🧊 No due date")
        for task in no_due_date:
            lines.append(format_task_line(task))
        lines.append("")

    if len(lines) == 1:
        lines.append("🎉 No matching tasks found.")

    return "\n".join(lines)

# -----------------Button helpers-----------------
def navigation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add task", callback_data="cmd:help_add"),
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def task_completed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📋 All tasks", callback_data="cmd:list"),
                InlineKeyboardButton("✅ Close tasks", callback_data="cmd:close"),
            ],
            [
                InlineKeyboardButton("➕ Add task", callback_data="cmd:help_add"),
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def task_view_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Close tasks", callback_data="cmd:close"),
                InlineKeyboardButton("➕ Add task", callback_data="cmd:help_add"),
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def digest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def pending_input_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="cmd:cancel"),
                InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
            ],
        ]
    )


def task_done_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    buttons = []

    for task in sort_tasks_by_due_and_priority(tasks)[:10]:
        task_id = str(task.get("id"))
        button_title = task_display_title(task)

        if len(button_title) > 40:
            button_title = button_title[:37] + "..."

        buttons.append(
            [
                InlineKeyboardButton(
                    f"✅ {button_title}",
                    callback_data=f"ask_done:{task_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton("➕ Add task", callback_data="cmd:help_add"),
            InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
        ]
    )

    return InlineKeyboardMarkup(buttons)


async def get_active_tasks_for_button(query, action: str) -> list[dict] | None:
    try:
        return get_active_tasks()
    except Exception as exc:
        logging.exception("Failed to %s", action)
        await query.edit_message_text(
            f"I could not {action}.\n\nError: {exc}",
            reply_markup=navigation_keyboard(),
        )
        return None


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cmd:list":
        tasks = await get_active_tasks_for_button(query, "fetch tasks from Todoist")
        if tasks is None:
            return

        if not tasks:
            await query.edit_message_text(
                "🎉 No active tasks found.",
                reply_markup=navigation_keyboard(),
            )
            return

        message = grouped_task_message(tasks, title="📋 Active tasks")

        await query.edit_message_text(
            message,
            reply_markup=task_view_keyboard(),
        )
        return

    if data == "cmd:today":
        tasks = await get_active_tasks_for_button(query, "fetch tasks from Todoist")
        if tasks is None:
            return

        today = get_today_berlin()

        today_only = [
            task for task in tasks
            if get_task_due_date(task) == today
        ]

        today_only = sort_tasks_by_due_and_priority(today_only)

        if not today_only:
            await query.edit_message_text(
                "🎉 No tasks due today.",
                reply_markup=navigation_keyboard(),
            )
            return

        lines = [f"📌 Tasks due today ({today.isoformat()}):\n"]
        for task in today_only:
            lines.append(format_task_line(task))

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=task_view_keyboard(),
        )
        return

    if data == "cmd:overdue":
        tasks = await get_active_tasks_for_button(query, "fetch tasks from Todoist")
        if tasks is None:
            return

        today = get_today_berlin()

        overdue_only = [
            task for task in tasks
            if get_task_due_date(task) is not None
            and get_task_due_date(task) < today
        ]

        overdue_only = sort_tasks_by_due_and_priority(overdue_only)

        if not overdue_only:
            await query.edit_message_text(
                "✅ No overdue tasks.",
                reply_markup=navigation_keyboard(),
            )
            return

        lines = [f"🚨 OVERDUE tasks ({today.isoformat()}):\n"]

        for task in overdue_only:
            due_date = get_task_due_date(task)
            days_overdue = (today - due_date).days if due_date else 0
            lines.append(
                f"{format_task_line(task)} — overdue by {days_overdue} day(s)"
            )

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=task_view_keyboard(),
        )
        return

    if data == "cmd:digest":
        tasks = await get_active_tasks_for_button(query, "build the task digest")
        if tasks is None:
            return

        message = build_digest_message(tasks)

        await query.edit_message_text(
            message,
            reply_markup=digest_keyboard(),
        )
        return

    if data == "cmd:close":
        tasks = await get_active_tasks_for_button(query, "fetch tasks from Todoist")
        if tasks is None:
            return

        await query.edit_message_text(
            build_close_tasks_message(tasks),
            reply_markup=task_done_keyboard(tasks) if tasks else navigation_keyboard(),
        )
        return

    if data == "cmd:menu":
        await query.edit_message_text(
            "🏠 Task Assistant Menu\n\nChoose what you want to do:",
            reply_markup=main_menu_keyboard(),
        )
        return
    
    if data == "cmd:help_add":
        chat_id = query.message.chat_id
        set_chat_mode(chat_id, "awaiting_new_task")

        await query.edit_message_text(
            "➕ Send me the task text now.\n\n"
            "Example:\n"
            "Buy cat food tomorrow priority 2 size S\n\n"
            "I will parse it, ask for missing priority/size if needed, "
            "and then add it to Todoist.",
            reply_markup=pending_input_keyboard(),
        )
        return
    
    if data == "cmd:cancel":
        chat_id = query.message.chat_id
        pending = get_pending_task(chat_id)
        mode = get_chat_mode(chat_id)

        clear_chat_mode(chat_id)

        if pending:
            clear_pending_task(chat_id)
            await query.edit_message_text(
                "❌ Pending task draft cancelled.",
                reply_markup=navigation_keyboard(),
            )
            return

        if mode:
            await query.edit_message_text(
                "❌ Current input mode cancelled.",
                reply_markup=navigation_keyboard(),
            )
            return

        await query.edit_message_text(
            "There is no pending task draft to cancel.",
            reply_markup=navigation_keyboard(),
        )
        return
    
    if data == "cmd:soon":
        tasks = await get_active_tasks_for_button(query, "fetch tasks from Todoist")
        if tasks is None:
            return

        today = get_today_berlin()
        soon_limit = today.toordinal() + 3

        soon_only = []

        for task in tasks:
            due_date = get_task_due_date(task)

            if due_date is not None and today < due_date and due_date.toordinal() <= soon_limit:
                soon_only.append(task)

        soon_only = sort_tasks_by_due_and_priority(soon_only)

        if not soon_only:
            await query.edit_message_text(
                "✅ No tasks due soon.",
                reply_markup=navigation_keyboard(),
            )
            return

        lines = ["⚠️ Tasks due soon:\n"]

        for task in soon_only:
            due_date = get_task_due_date(task)
            days_left = (due_date - today).days if due_date else 0
            due_text = "tomorrow" if days_left == 1 else f"in {days_left} days"
            lines.append(f"{format_task_line(task)} — due {due_text}")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=task_view_keyboard(),
        )
        return
    
    if data.startswith("ask_done:"):
        task_id = data.replace("ask_done:", "", 1)

        try:
            tasks = get_active_tasks()
            task = next((t for t in tasks if str(t.get("id")) == task_id), None)
        except Exception as exc:
            logging.exception("Failed to fetch task for confirmation")
            await query.edit_message_text(
                f"I could not check this task.\n\nError: {exc}",
                reply_markup=navigation_keyboard(),
            )
            return

        if not task:
            await query.edit_message_text(
                "I could not find this active task. It may already be completed.",
                reply_markup=navigation_keyboard(),
            )
            return

        await query.edit_message_text(
            "Are you sure you finished this task?\n\n"
            f"{task.get('content', 'Untitled task')}",
            reply_markup=confirm_done_keyboard(task_id),
        )
        return

    if data.startswith("confirm_done:"):
        task_id = data.replace("confirm_done:", "", 1)

        try:
            close_task(task_id)
        except Exception as exc:
            logging.exception("Failed to close task from confirmation")
            await query.edit_message_text(
                f"I could not close this task.\n\nError: {exc}",
                reply_markup=navigation_keyboard(),
            )
            return

        await query.edit_message_text(
            "✅ Task completed!",
            reply_markup=task_completed_keyboard(),
        )
        return

    if data == "cancel_done":
        await query.edit_message_text(
            "↩️ Okay, task was not closed.",
            reply_markup=navigation_keyboard(),
        )
        return


# legacy: merge_pending_task_with_followup removed in favor of deterministic
# follow-up metadata extraction. See handle_followup_message for current logic.
        
# -------------------------------------------------------------
def main() -> None:
    init_db()

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env file")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Run access control before all command, message, and callback handlers.
    app.add_handler(TypeHandler(Update, enforce_allowlist), group=-1)

    app.job_queue.run_daily(
        send_daily_digest,
        time=datetime.strptime("08:45", "%H:%M").time().replace(
            tzinfo=ZoneInfo("Europe/Berlin")
        ),
        name="daily_task_digest",
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("today", today_tasks))
    app.add_handler(CommandHandler("overdue", overdue_tasks))
    app.add_handler(CommandHandler("digest", digest_tasks))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(CommandHandler("soon", soon_tasks))
    app.add_handler(CommandHandler("cancel", cancel_pending))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("close", close_tasks_menu))

    app.add_handler(CallbackQueryHandler(handle_button))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_followup_message))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
