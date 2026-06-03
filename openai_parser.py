import json
import os
import re

from datetime import date
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


TASK_CATEGORIES = [
    "travel",
    "visit",
    "pets",
    "food",
    "work",
    "long-term",
    "home",
    "health",
    "admin",
    "shopping"
]

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def extract_due_date_fallback(task_text: str) -> str | None:
    """
    Deterministic fallback for clear date phrases.

    Handles:
    - 23-26 June
    - 23–26 June
    - 23 to 26 June
    - 23 June
    - June 23
    - June 23-26

    For ranges, uses the start date.
    If no year is provided, uses the next upcoming occurrence.
    """

    text = task_text.lower()
    today = date.today()

    patterns = [
        # 23-26 June / 23–26 June / 23 to 26 June
        r"\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s+([a-z]+)\b",

        # June 23-26 / June 23–26 / June 23 to 26
        r"\b([a-z]+)\s+(\d{1,2})\s*(?:-|–|—|to)?\s*(\d{1,2})?\b",

        # 23 June
        r"\b(\d{1,2})\s+([a-z]+)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        groups = match.groups()

        # Pattern: 23-26 June
        if groups[0] and groups[0].isdigit() and len(groups) == 3:
            day = int(groups[0])
            month_name = groups[2]

        # Pattern: June 23 or June 23-26
        elif groups[0] and groups[0].isalpha():
            month_name = groups[0]
            day = int(groups[1])

        # Pattern: 23 June
        elif groups[0] and groups[0].isdigit():
            day = int(groups[0])
            month_name = groups[1]

        else:
            continue

        month = MONTHS.get(month_name.lower())

        if not month:
            continue

        year = today.year

        try:
            candidate = date(year, month, day)
        except ValueError:
            continue

        if candidate < today:
            candidate = date(year + 1, month, day)

        return candidate.isoformat()

    return None


def postprocess_parsed_task(task_text: str, parsed: dict) -> dict:
    """
    Fix model mistakes deterministically.
    """

    # 1. Force due_date from clear date expressions if model missed it.
    fallback_due_date = extract_due_date_fallback(task_text)
    if fallback_due_date and not parsed.get("due_date"):
        parsed["due_date"] = fallback_due_date

    # 2. Avoid useless generic names.
    generic_names = {"task", "new task", "todo", "reminder"}

    name = str(parsed.get("name") or "").strip()

    if not name or name.lower() in generic_names:
        cleaned = task_text

        # Remove common metadata phrases from task name.
        cleaned = re.sub(r"\bpriority\s*[1-4]\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bprio\s*[1-4]\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bp[1-4]\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bsize\s*(S|M|L|XL)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bcategory\s+\w+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")

        if cleaned:
            parsed["name"] = cleaned[:80]
        else:
            parsed["name"] = "Untitled task"

    # 3. Normalize category.
    category = parsed.get("category")

    if isinstance(category, str):
        normalized = category.strip().lower()

        # Helpful aliases.
        aliases = {
            "shop": "shopping",
            "shopping": "shopping",
            "buying": "shopping",
            "purchase": "shopping",
            "purchases": "shopping",
            "amazon": "shopping",
        }

        normalized = aliases.get(normalized, normalized)
        parsed["category"] = normalized

    # 4. If category is still missing or invalid, ask.
    if parsed.get("category") not in TASK_CATEGORIES:
        parsed["category"] = None

    # 5. Rebuild missing_fields safely.
    missing_fields = []

    if parsed.get("priority") is None:
        missing_fields.append("priority")

    if parsed.get("size") is None:
        missing_fields.append("size")

    if parsed.get("category") is None:
        missing_fields.append("category")

    parsed["missing_fields"] = missing_fields

    if missing_fields:
        needed = []

        if "priority" in missing_fields:
            needed.append("priority 1–4")

        if "size" in missing_fields:
            needed.append("size S, M, L, or XL")

        if "category" in missing_fields:
            needed.append(
                "category: travel, visit, pets, food, shopping, work, long-term, home, health, admin"
            )

        parsed["clarifying_question"] = "Please provide: " + "; ".join(needed) + "."
    else:
        parsed["clarifying_question"] = None

    return parsed


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Check that your .env file exists and contains "
            "OPENAI_API_KEY=your_key_here"
        )

    return OpenAI(api_key=api_key)


def parse_task_text(task_text: str) -> dict:
    """
    Converts natural-language task text into structured task JSON.

    Required fields:
    - priority: 1-4
    - size: S/M/L/XL

    Optional:
    - due_date
    """

    today = date.today().isoformat()

    system_prompt = f"""
You are a strict task parsing assistant.

Today's date is {today}.
The user's timezone is Europe/Berlin.

Extract a task from the user's message.

Return ONLY valid JSON. No markdown. No explanation.

Required JSON format:
{{
  "name": "string",
  "description": "string",
  "priority": 1,
  "size": "S",
  "category": "work or null",
  "due_date": "YYYY-MM-DD or null",
  "missing_fields": [],
  "clarifying_question": null
}}

Rules:
- priority is mandatory and must be an integer from 1 to 4.
- size is mandatory and must be one of: S, M, L, XL.
- category is required, but if unclear, ask the user to choose one.
- due_date is optional. Use null if not provided.

- ONLY priority and size can be included in missing_fields.
- NEVER include name, description, category, or due_date in missing_fields.

- If name is unclear, generate a short clear name.
- If description is missing, generate a useful one-sentence description.

- category must be one of: {", ".join(TASK_CATEGORIES)}.
- Do NOT guess category if the task could reasonably belong to multiple categories.
- If category is unclear, set category to null and include "category" in missing_fields.
- When category is missing, clarifying_question should ask the user to choose from the allowed categories or suggest a new category.

- Do NOT guess priority unless the user clearly states it or uses a clear priority word.
- Do NOT guess size unless the user clearly states it or uses a clear size/effort word.
- If priority is not clearly provided, set priority to null and include "priority" in missing_fields.
- If size is not clearly provided, set size to null and include "size" in missing_fields.

Due date rules:

- If the user mentions a specific date, use it as due_date.
- If the user mentions a date range, use the start date of the range as due_date.
- If the user says "remind me about X from DATE1 to DATE2", use DATE1 as due_date.
- If the user says "remind me before DATE", use the day before DATE as due_date.
- If the user says "remind me one day before DATE", use one day before DATE as due_date.
- If the user says only "remind me about X on DATE", use DATE as due_date.
- If the user mentions only a month/day without a year, use the next upcoming occurrence.

- If mandatory fields are missing, clarifying_question should ask for only the missing mandatory fields.
- If no mandatory fields are missing, clarifying_question must be null.

Priority meaning:
4 = low / someday
3 = normal
2 = important
1 = urgent / critical

Size meaning:
S = small tasks for 1 day max
M = medium tasks for 1-3 days
L = large tasks for more than 3 days or with multiple steps
XL = huge tasks that require significant time or effort, often with multiple steps or dependencies

You may infer priority ONLY from clear priority words:
- urgent, critical, ASAP, emergency, highest priority -> priority 1
- important, high priority -> priority 2
- normal priority, regular priority -> priority 3
- low priority, someday, not urgent, no rush -> priority 4

You may infer size ONLY from clear size/effort words:
- small, simple, quick, size S -> S
- medium, size M -> M
- large, big, multi-day, size L -> L
- huge, complex, dependency-heavy, significant effort, size XL -> XL

Examples:
- "Clean apartment" -> priority null, size null, missing_fields ["priority", "size"]
- "Clean apartment priority 3 size M" -> priority 3, size M
- "Buy cat food tomorrow priority 2 size S" -> priority 2, size S
- "Prepare visa documents urgent and large" -> priority 1, size L
"""

    client = get_openai_client()

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_text},
        ],
    )

    raw_content = response.choices[0].message.content

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI returned invalid JSON: {raw_content}") from exc

    parsed = postprocess_parsed_task(task_text, parsed)

    return parsed


def parse_followup_metadata(followup_text: str) -> dict:
    """
    Extract ONLY the metadata fields (priority, size, category) from follow-up text.
    
    This is used when the user provides additional information after the initial task parse.
    It extracts only the updated metadata without trying to re-parse the task name/description.
    
    Returns a dict with:
    - priority: 1-4 or None
    - size: S/M/L/XL or None
    - category: one of TASK_CATEGORIES or None
    """
    
    text = followup_text.lower()
    extracted = {
        "priority": None,
        "size": None,
        "category": None,
    }
    
    # Extract priority (1-4, p1-p4, priority 1-4, urgent, etc.)
    priority_patterns = [
        (r'\bp\s*4\b|\bpriority\s*4\b', 4),
        (r'\bp\s*3\b|\bpriority\s*3\b', 3),
        (r'\bp\s*2\b|\bpriority\s*2\b', 2),
        (r'\bp\s*1\b|\bpriority\s*1\b', 1),
        (r'\burgen\w*\b|\bcritica\w*\b|\basap\b|\bhighest\s*priority\b', 1),
        (r'\bimportan\w*\b|\bhigh\s*priority\b', 2),
        (r'\bnormal\s*priority\b|\bregular\s*priority\b', 3),
        (r'\blow\s*priority\b|\bsomeday\b|\bno\s*rush\b', 4),
    ]
    
    for pattern, priority in priority_patterns:
        if re.search(pattern, text):
            extracted["priority"] = priority
            break
    
    # Extract size (S, M, L, XL, small, medium, large, huge, etc.)
    size_patterns = [
        (r'\bxl\b|\bhuge\b|\bcomplex\b|\bdependency\b|\bsignificant\s*effort\b', 'XL'),
        (r'\bl\b|\blarge\b|\bbig\b|\bmulti.?day\b|\bseveral\s*days\b', 'L'),
        (r'\bm\b|\bmedium\b', 'M'),
        (r'\bs\b|\bsmall\b|\bsimple\b|\bquick\b', 'S'),
    ]
    
    for pattern, size in size_patterns:
        if re.search(pattern, text):
            extracted["size"] = size
            break
    
    # Extract category (exact match from TASK_CATEGORIES or aliases)
    category_aliases = {
        "shop": "shopping",
        "shopping": "shopping",
        "buying": "shopping",
        "purchase": "shopping",
        "purchases": "shopping",
        "amazon": "shopping",
        "travel": "travel",
        "trip": "travel",
        "visit": "visit",
        "pets": "pets",
        "animals": "pets",
        "food": "food",
        "eat": "food",
        "work": "work",
        "job": "work",
        "long-term": "long-term",
        "longterm": "long-term",
        "long term": "long-term",
        "home": "home",
        "house": "home",
        "health": "health",
        "medical": "health",
        "admin": "admin",
        "administration": "admin",
    }
    
    for alias, canonical in category_aliases.items():
        if re.search(rf'\b{re.escape(alias)}\b', text):
            extracted["category"] = canonical
            break
    
    return extracted
