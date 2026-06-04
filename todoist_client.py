import os
import requests
from dotenv import load_dotenv

load_dotenv()

TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
TODOIST_PROJECT_ID = os.getenv("TODOIST_PROJECT_ID")

TODOIST_API_BASE = "https://api.todoist.com/api/v1"


def _clean_env(value: str | None) -> str | None:
    if not value:
        return None

    value = value.strip()

    if not value or value.startswith("your_") or value.endswith("_here"):
        return None

    return value


def _project_id() -> str:
    project_id = _clean_env(TODOIST_PROJECT_ID)

    if not project_id:
        raise RuntimeError(
            "Missing TODOIST_PROJECT_ID. Set it to the Todoist project ID in .env."
        )

    return project_id


def _headers() -> dict:
    if not TODOIST_API_TOKEN:
        raise RuntimeError("Missing TODOIST_API_TOKEN. Check your .env file.")

    return {
        "Authorization": f"Bearer {TODOIST_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _raise_for_todoist_error(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Todoist API error {response.status_code}: {response.text}"
        ) from exc


def _extract_results(response_json):
    """
    Todoist API v1 may return either:
    - a direct list: [{...}, {...}]
    - a paginated object: {"results": [{...}], "next_cursor": "..."}
    """

    if isinstance(response_json, list):
        return response_json

    if isinstance(response_json, dict):
        if isinstance(response_json.get("results"), list):
            return response_json["results"]
        if isinstance(response_json.get("items"), list):
            return response_json["items"]

    raise RuntimeError(f"Unexpected Todoist API response format: {response_json}")


def map_user_priority_to_todoist_api(priority: int) -> int:
    """
    User-facing priority follows Todoist UI:
    P1 = highest
    P2 = important
    P3 = normal
    P4 = low

    Todoist API uses the reverse numeric direction:
    API 4 = highest
    API 3 = important
    API 2 = normal-ish
    API 1 = lowest / natural

    Mapping:
    User P1 -> API 4
    User P2 -> API 3
    User P3 -> API 2
    User P4 -> API 1
    """

    mapping = {
        1: 4,
        2: 3,
        3: 2,
        4: 1,
    }

    return mapping.get(priority, 1)


def create_task(
    name: str,
    description: str,
    priority: int,
    size: str,
    category: str,
    due_date: str | None = None,
) -> dict:
    todoist_api_priority = map_user_priority_to_todoist_api(priority)

    content = f"[P{priority}][{size}][{category}] {name}"

    payload = {
        "content": content,
        "description": description,
        "project_id": _project_id(),
        "priority": todoist_api_priority,
        "labels": [category],
    }

    if due_date:
        payload["due_date"] = due_date

    response = requests.post(
        f"{TODOIST_API_BASE}/tasks",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    _raise_for_todoist_error(response)
    return response.json()


def get_active_tasks() -> list[dict]:
    project_id = _project_id()
    all_tasks = []
    cursor = None

    while True:
        params = {
            "project_id": project_id,
        }

        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{TODOIST_API_BASE}/tasks",
            headers=_headers(),
            params=params,
            timeout=20,
        )
        _raise_for_todoist_error(response)

        data = response.json()
        tasks = _extract_results(data)
        all_tasks.extend(tasks)

        if isinstance(data, dict):
            cursor = data.get("next_cursor")
            if cursor:
                continue

        break

    return all_tasks


def close_task(task_id: str) -> None:
    if not task_id:
        raise RuntimeError("Missing task_id.")

    response = requests.post(
        f"{TODOIST_API_BASE}/tasks/{task_id}/close",
        headers=_headers(),
        timeout=20,
    )
    _raise_for_todoist_error(response)
