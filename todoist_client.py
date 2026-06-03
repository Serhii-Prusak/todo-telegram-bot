import os
import requests
from dotenv import load_dotenv

load_dotenv()

TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
TODOIST_PROJECT_NAME = os.getenv("TODOIST_PROJECT_NAME", "Task Assistant")

TODOIST_API_BASE = "https://api.todoist.com/api/v1"


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


def get_projects() -> list[dict]:
    all_projects = []
    cursor = None

    while True:
        params = {}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{TODOIST_API_BASE}/projects",
            headers=_headers(),
            params=params,
            timeout=20,
        )
        _raise_for_todoist_error(response)

        data = response.json()
        projects = _extract_results(data)
        all_projects.extend(projects)

        if isinstance(data, dict):
            cursor = data.get("next_cursor")
            if cursor:
                continue

        break

    return all_projects


def find_project_id_by_name(project_name: str) -> str | None:
    projects = get_projects()

    # Temporary debug print. You can remove this later.
    print("Todoist projects:")
    for project in projects:
        print(project)

    for project in projects:
        if not isinstance(project, dict):
            continue

        if project.get("name", "").lower() == project_name.lower():
            return project.get("id")

    return None


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
    project_name: str = TODOIST_PROJECT_NAME,
) -> dict:
    project_id = find_project_id_by_name(project_name)

    if not project_id:
        raise RuntimeError(
            f"Could not find Todoist project named '{project_name}'. "
            "Please check the project name in Todoist or TODOIST_PROJECT_NAME in .env."
        )

    todoist_api_priority = map_user_priority_to_todoist_api(priority)

    content = f"[P{priority}][{size}][{category}] {name}"

    payload = {
        "content": content,
        "description": description,
        "project_id": project_id,
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


def get_active_tasks(project_name: str = TODOIST_PROJECT_NAME) -> list[dict]:
    project_id = find_project_id_by_name(project_name)

    if not project_id:
        raise RuntimeError(
            f"Could not find Todoist project named '{project_name}'. "
            "Please check the project name in Todoist or TODOIST_PROJECT_NAME in .env."
        )

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
    