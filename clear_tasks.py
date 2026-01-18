#!/usr/bin/env python3
"""Clear all tasks from a Vibe Kanban project."""

import argparse
import json
import sys
from pathlib import Path

import requests


def load_config():
    """Load config from config.json."""
    config_path = Path("config.json")
    if not config_path.exists():
        print(f"Error: {config_path} not found")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def fetch_tasks(api_url, project_id):
    """Fetch all tasks for a project."""
    try:
        resp = requests.get(f"{api_url}/api/tasks", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                all_tasks = data.get("data", [])
                return [t for t in all_tasks if t.get("project_id") == project_id]
        return []
    except requests.RequestException as e:
        print(f"Error fetching tasks: {e}")
        return []


def delete_task(api_url, task_id):
    """Delete a single task."""
    try:
        resp = requests.delete(f"{api_url}/api/tasks/{task_id}", timeout=30)
        return resp.status_code in [200, 204]
    except requests.RequestException as e:
        print(f"Error deleting task {task_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Clear tasks from Vibe Kanban project")
    parser.add_argument(
        "--project-id",
        "-p",
        help="Project ID to clear (if not specified, shows all projects)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    parser.add_argument(
        "--filter",
        "-f",
        help="Only delete tasks with this substring in title or content",
    )

    args = parser.parse_args()

    config = load_config()
    api_url = config.get("vibe_api_url", "http://localhost:3000")
    projects = config.get("projects", [])

    if not args.project_id:
        print("\nConfigured projects:")
        for i, proj in enumerate(projects, 1):
            print(f"  {i}. {proj['github_repo']} -> {proj['vibe_project_id']}")
        print("\nRun with --project-id <ID> to clear a specific project")
        return 0

    # Find project
    project_id = args.project_id
    project_name = None
    for proj in projects:
        if proj["vibe_project_id"] == project_id:
            project_name = proj["github_repo"]
            break

    if not project_name:
        project_name = f"Project {project_id}"

    # Fetch tasks
    print(f"\nFetching tasks for {project_name}...")
    tasks = fetch_tasks(api_url, project_id)

    if not tasks:
        print("No tasks found.")
        return 0

    # Filter if requested
    if args.filter:
        tasks = [
            t
            for t in tasks
            if args.filter.lower() in (t.get("title", "").lower())
            or args.filter.lower() in (t.get("content", "") or "").lower()
        ]
        print(f"Found {len(tasks)} tasks matching filter '{args.filter}'")
    else:
        print(f"Found {len(tasks)} tasks")

    if not tasks:
        return 0

    # Show tasks
    print("\nTasks to delete:")
    for task in tasks:
        title = task.get("title", "Untitled")
        task_id = task.get("id", "?")
        print(f"  - {title} ({task_id})")

    if args.dry_run:
        print("\n[Dry-run mode: no tasks deleted]")
        return 0

    # Confirm
    response = input(f"\nDelete {len(tasks)} task(s)? [y/N]: ").strip()
    if response.lower() != "y":
        print("Cancelled.")
        return 0

    # Delete
    deleted = 0
    for task in tasks:
        task_id = task.get("id")
        if task_id and delete_task(api_url, task_id):
            deleted += 1
            print(f"Deleted: {task.get('title', 'Untitled')}")
        else:
            print(f"Failed to delete: {task.get('title', 'Untitled')}")

    print(f"\n{deleted}/{len(tasks)} tasks deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
