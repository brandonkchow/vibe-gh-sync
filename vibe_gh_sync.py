import argparse
import json
import logging
import re
import signal
import subprocess
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    logger.info("Shutdown signal received, finishing current sync...")
    shutdown_requested = True


def install_signal_handlers():
    """Install signal handlers for graceful shutdown during sync."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


CONFIG_PATH = Path("config.json")
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "vibe-sync" / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        logger.error(f"Config file {CONFIG_PATH} not found.")
        return None
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config, path=None):
    """Save config to file."""
    save_path = path or CONFIG_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config saved to {save_path}")


def fetch_vibe_projects(api_url):
    """Fetch available projects from Vibe Kanban."""
    try:
        resp = requests.get(f"{api_url}/api/projects", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data.get("data", [])
        return []
    except requests.RequestException:
        return []


def find_vibe_kanban_cli():
    """Find the vibe-kanban CLI executable."""
    # Try which directly
    try:
        result = subprocess.run(
            ["which", "vibe-kanban"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.SubprocessError:
        pass

    # Check common locations
    possible_paths = [
        "/opt/homebrew/bin/vibe-kanban",  # Homebrew on Apple Silicon
        "/usr/local/bin/vibe-kanban",  # Homebrew on Intel Mac
    ]

    for path in possible_paths:
        if Path(path).exists():
            return path

    return None


def start_vibe_kanban():
    """Start Vibe Kanban server in the background."""
    cli_path = find_vibe_kanban_cli()
    if not cli_path:
        print("Could not find vibe-kanban CLI.")
        print("Install it with: npm install -g vibe-kanban")
        return False

    print(f"Starting Vibe Kanban ({cli_path})...")

    try:
        # Start in background, redirect output to /dev/null
        subprocess.Popen(
            [cli_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait a moment for it to start
        print("Waiting for server to start...")
        for i in range(10):
            time.sleep(1)
            url = detect_vibe_api()
            if url:
                print(f"Vibe Kanban is running at {url}")
                return True
            print(f"  Checking... ({i + 1}/10)")

        print("Vibe Kanban started but couldn't verify it's running.")
        return False

    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"Failed to start Vibe Kanban: {e}")
        return False


def get_github_username():
    """Get the authenticated GitHub username from gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.SubprocessError:
        pass
    return None


def detect_vibe_api():
    """Auto-detect Vibe Kanban API URL by checking common ports and active processes."""
    import subprocess

    # First, try to find vibe-kanban process and extract port from lsof
    try:
        result = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "node" in line.lower() or "vibe" in line.lower():
                    # Extract port from lines like "node    12345 user   20u  IPv4 0x... TCP 127.0.0.1:52948 (LISTEN)"
                    parts = line.split()
                    for part in parts:
                        if ":" in part and ("127.0.0.1" in part or "localhost" in part):
                            port = part.split(":")[-1].strip()
                            if port.isdigit():
                                url = f"http://127.0.0.1:{port}"
                                try:
                                    resp = requests.get(f"{url}/api/projects", timeout=2)
                                    if resp.status_code == 200:
                                        data = resp.json()
                                        if data.get("success") and "data" in data:
                                            logger.info(f"Auto-detected Vibe Kanban at {url}")
                                            return url
                                except requests.RequestException:
                                    continue
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Fallback to checking common ports
    common_ports = [3000, 3001, 8080, 8000, 5000]
    for port in common_ports:
        url = f"http://localhost:{port}"
        try:
            resp = requests.get(f"{url}/api/projects", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and "data" in data:
                    logger.info(f"Found Vibe Kanban at {url}")
                    return url
        except requests.RequestException:
            continue

    return None


def interactive_setup(config_path):
    """Interactive setup wizard for creating config."""
    try:
        return _interactive_setup_impl(config_path)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        return None


def _interactive_setup_impl(config_path):
    """Implementation of interactive setup."""
    print("\n=== Vibe Sync Setup ===\n")

    # Check if config exists
    if config_path.exists():
        response = input(f"Config already exists at {config_path}. Overwrite? [y/N]: ")
        if response.lower() != "y":
            print("Setup cancelled.")
            return None

    config = {
        "vibe_api_url": "http://localhost:3000",
        "sync_interval_seconds": 60,
        "issue_limit": 100,
        "projects": [],
    }

    # Try to auto-detect Vibe Kanban
    print("Searching for Vibe Kanban...")
    detected_url = detect_vibe_api()

    if not detected_url:
        # Offer to start it
        print("Vibe Kanban is not running.")
        cli_path = find_vibe_kanban_cli()
        if cli_path:
            start = input("Start Vibe Kanban now? [Y/n]: ").strip()
            if start.lower() != "n":
                if start_vibe_kanban():
                    detected_url = detect_vibe_api()
        else:
            print("vibe-kanban CLI not found. Install with: npm install -g vibe-kanban")

    if detected_url:
        config["vibe_api_url"] = detected_url
        print(f"Found Vibe Kanban at {detected_url}")
        use_detected = input("Use this URL? [Y/n]: ").strip()
        if use_detected.lower() == "n":
            url = input("Enter Vibe Kanban API URL: ").strip()
            if url:
                config["vibe_api_url"] = url
    else:
        print("Could not connect to Vibe Kanban.")
        default_url = config["vibe_api_url"]
        url = input(f"Enter Vibe Kanban API URL [{default_url}]: ").strip()
        if url:
            config["vibe_api_url"] = url

    # Test connection and fetch projects
    print(f"\nConnecting to {config['vibe_api_url']}...")
    projects = fetch_vibe_projects(config["vibe_api_url"])

    # Get GitHub username for auto-suggesting repos
    gh_username = get_github_username()
    if gh_username:
        print(f"GitHub user: {gh_username}")

    if not projects:
        print("Could not fetch projects from Vibe Kanban.")
        print("Make sure Vibe Kanban is running and the URL is correct.")
        manual = input("Enter project ID manually? [y/N]: ")
        if manual.lower() != "y":
            return None
        vibe_project_id = input("Vibe Project ID: ").strip()
        if not vibe_project_id:
            print("No project ID provided. Setup cancelled.")
            return None
        projects = [{"id": vibe_project_id, "name": "Manual Entry"}]
        selected_projects = projects
    else:
        print(f"\nFound {len(projects)} Vibe projects:")
        for i, proj in enumerate(projects, 1):
            print(f"  {i}. {proj.get('name', 'Unnamed')} ({proj.get('id', 'N/A')})")

        print("\nSelect projects to sync (comma-separated, or 'all'):")
        selection = input("Selection: ").strip()

        if selection.lower() == "all":
            selected_projects = projects
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(",")]
                selected_projects = [
                    projects[i] for i in indices if 0 <= i < len(projects)
                ]
                if not selected_projects:
                    print("No valid selection.")
                    return None
            except ValueError:
                print("Invalid input.")
                return None

    # Add each selected project
    for vibe_project in selected_projects:
        project_name = vibe_project.get("name", "")

        # Auto-suggest GitHub repo based on project name and GitHub username
        if gh_username and project_name:
            suggested_repo = f"{gh_username}/{project_name}"
            print(f"\nProject: {project_name}")
            gh_repo = input(f"GitHub repo [{suggested_repo}]: ").strip()
            if not gh_repo:
                gh_repo = suggested_repo
        else:
            print(f"\nProject: {project_name}")
            gh_repo = input("GitHub repo (owner/repo): ").strip()
            if not gh_repo:
                print(f"Skipping {project_name} - no repo provided.")
                continue

        # Verify gh CLI access
        print(f"Verifying access to {gh_repo}...")
        issues = fetch_github_issues(gh_repo, limit=1)
        if issues is None or issues == []:
            # Empty list is OK (no issues), None means error
            if issues is None:
                print(f"Warning: Could not verify access to {gh_repo}")
                proceed = input("Add anyway? [y/N]: ").strip()
                if proceed.lower() != "y":
                    continue
            else:
                print(f"Connected to {gh_repo} (no open issues)")
        else:
            print(f"Connected to {gh_repo} ({len(issues)} open issues)")

        config["projects"].append(
            {
                "github_repo": gh_repo,
                "vibe_project_id": vibe_project.get("id"),
            }
        )

    if not config["projects"]:
        print("No projects configured. Setup cancelled.")
        return None

    # Sync interval
    default_interval = config["sync_interval_seconds"]
    interval = input(f"\nSync interval in seconds [{default_interval}]: ")
    if interval.strip().isdigit():
        config["sync_interval_seconds"] = int(interval)

    # Save config
    save_config(config, config_path)
    print("\nSetup complete! You can now run: vibe-sync")
    return config


def select_projects_interactive(config):
    """Let user select which projects to sync."""
    projects = config.get("projects", [])

    if not projects:
        print("No projects configured. Run 'vibe-sync --setup' first.")
        return None

    if len(projects) == 1:
        return config

    print("\nConfigured repositories:")
    print("  0. All repositories")
    for i, proj in enumerate(projects, 1):
        print(f"  {i}. {proj['github_repo']}")

    prompt = "\nSelect repo(s) to sync (comma-separated, or 0 for all): "
    selection = input(prompt).strip()

    if selection == "0" or selection == "":
        return config

    try:
        indices = [int(x.strip()) - 1 for x in selection.split(",")]
        selected = [projects[i] for i in indices if 0 <= i < len(projects)]
        if not selected:
            print("No valid selection. Using all repos.")
            return config
        return {**config, "projects": selected}
    except (ValueError, IndexError):
        print("Invalid selection. Using all repos.")
        return config


def fetch_github_issues(repo, limit=100):
    """Fetch open issues from GitHub using gh CLI."""
    try:
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,body,url",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=60
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to fetch issues for {repo}: {e.stderr}")
        return []
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout fetching issues for {repo}")
        return []
    except json.JSONDecodeError:
        logger.error(f"Failed to parse GH CLI output for {repo}")
        return []


def fetch_vibe_tasks(api_url, project_id):
    """Fetch existing tasks from Vibe Kanban for a project."""
    try:
        resp = requests.get(
            f"{api_url}/api/tasks",
            params={"project_id": project_id},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data.get("data", [])
            else:
                logger.error(f"Vibe API returned success=false: {data}")
        else:
            logger.error(f"Failed to fetch vibe tasks: {resp.status_code} {resp.text}")
        return []
    except requests.Timeout:
        logger.error("Timeout fetching vibe tasks")
        return []
    except requests.RequestException as e:
        logger.error(f"Error fetching vibe tasks: {e}")
        return []


def create_vibe_task(api_url, project_id, title, content):
    """Create a new task in Vibe Kanban."""
    payload = {"title": title, "project_id": project_id, "content": content}
    try:
        resp = requests.post(f"{api_url}/api/tasks", json=payload, timeout=30)
        if resp.status_code in [200, 201]:
            logger.info(f"Created task: {title}")
            return True
        else:
            logger.error(
                f"Failed to create task '{title}': {resp.status_code} {resp.text}"
            )
            return False
    except requests.Timeout:
        logger.error(f"Timeout creating task '{title}'")
        return False
    except requests.RequestException as e:
        logger.error(f"Error creating vibe task: {e}")
        return False


def get_vibe_api_url(config):
    """Get Vibe API URL from config, with auto-detection fallback."""
    configured_url = config.get("vibe_api_url")

    # First, try the configured URL
    if configured_url:
        try:
            resp = requests.get(f"{configured_url}/api/projects", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return configured_url
        except requests.RequestException:
            logger.warning(f"Configured URL {configured_url} not responding, attempting auto-detection...")

    # Auto-detect if configured URL doesn't work
    detected_url = detect_vibe_api()
    if detected_url:
        logger.info(f"Using auto-detected URL: {detected_url}")
        # Update config in memory (not saved to file)
        config["vibe_api_url"] = detected_url
        return detected_url

    # Final fallback
    logger.error("Could not connect to Vibe Kanban. Make sure it's running.")
    return configured_url or "http://localhost:3000"


def run_sync(config, once=False):
    """Run the sync loop."""
    global shutdown_requested

    # Install signal handlers for graceful shutdown
    install_signal_handlers()

    vibe_url = get_vibe_api_url(config)
    sync_interval = config.get("sync_interval_seconds", 60)
    issue_limit = config.get("issue_limit", 100)

    while not shutdown_requested:
        for project in config.get("projects", []):
            if shutdown_requested:
                break

            gh_repo = project["github_repo"]
            vibe_proj_id = project["vibe_project_id"]

            logger.info(f"Syncing {gh_repo} -> Project {vibe_proj_id}")

            # 1. Fetch GH Issues
            gh_issues = fetch_github_issues(gh_repo, limit=issue_limit)
            logger.info(f"Found {len(gh_issues)} open issues in {gh_repo}")

            # 2. Fetch Vibe Tasks
            vibe_tasks = fetch_vibe_tasks(vibe_url, vibe_proj_id)

            # Build set of existing issue URLs for O(1) lookup
            existing_urls = set()
            existing_titles = set()  # Also track titles as backup
            for task in vibe_tasks:
                content = task.get("content") or ""
                title = task.get("title", "")

                # Track title for backup duplicate detection
                if title:
                    existing_titles.add(title.strip())

                # Extract URL if present in content - handle multiple formats
                # Format 1: "Original Issue: <url>"
                if "Original Issue: " in content:
                    url_start = content.find("Original Issue: ") + len(
                        "Original Issue: "
                    )
                    url_end = content.find("\n", url_start)
                    if url_end == -1:
                        url_end = len(content)
                    url = content[url_start:url_end].strip()
                    if url:
                        existing_urls.add(url)

                # Format 2: Also check for any github.com URLs in content
                github_urls = re.findall(r'https://github\.com/[^\s\)]+', content)
                for url in github_urls:
                    existing_urls.add(url.strip())

            # 3. Compare and Create (use URL as primary duplicate check)
            for issue in gh_issues:
                issue_title = issue["title"]
                issue_url = issue["url"]
                issue_body = issue["body"] or ""

                task_content = f"{issue_body}\n\nOriginal Issue: {issue_url}"

                # Check for duplicates using both URL (primary) and title (fallback)
                is_duplicate = (
                    issue_url in existing_urls or
                    issue_title.strip() in existing_titles
                )

                if is_duplicate:
                    logger.debug(f"Skipping duplicate issue #{issue['number']}: {issue_title}")
                else:
                    logger.info(
                        f"Creating task for issue #{issue['number']}: {issue_title}"
                    )
                    success = create_vibe_task(vibe_url, vibe_proj_id, issue_title, task_content)
                    # Track newly created tasks to avoid duplicates within same sync
                    if success:
                        existing_urls.add(issue_url)
                        existing_titles.add(issue_title.strip())

        if once:
            logger.info("Single sync complete.")
            break

        if not shutdown_requested:
            logger.info(f"Sync complete. Sleeping for {sync_interval} seconds...")
            # Use smaller sleep intervals to check shutdown flag
            for _ in range(sync_interval):
                if shutdown_requested:
                    break
                time.sleep(1)


def delete_task(api_url, task_id):
    """Delete a single task."""
    try:
        resp = requests.delete(f"{api_url}/api/tasks/{task_id}", timeout=30)
        return resp.status_code in [200, 204]
    except requests.RequestException as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        return False


def clear_tasks_interactive(config, task_filter=None):
    """Clear tasks from Vibe Kanban project."""
    vibe_url = get_vibe_api_url(config)
    projects = config.get("projects", [])

    if not projects:
        print("No projects configured. Run 'vibe-sync --setup' first.")
        return 1

    # Show projects
    print("\nConfigured projects:")
    for i, proj in enumerate(projects, 1):
        print(f"  {i}. {proj['github_repo']} -> {proj['vibe_project_id']}")

    # Select project
    if len(projects) == 1:
        selected_idx = 0
    else:
        selection = input("\nSelect project to clear (number): ").strip()
        try:
            selected_idx = int(selection) - 1
            if not 0 <= selected_idx < len(projects):
                print("Invalid selection.")
                return 1
        except ValueError:
            print("Invalid input.")
            return 1

    project = projects[selected_idx]
    project_id = project["vibe_project_id"]
    project_name = project["github_repo"]

    # Fetch tasks
    print(f"\nFetching tasks for {project_name}...")
    tasks = fetch_vibe_tasks(vibe_url, project_id)

    if not tasks:
        print("No tasks found.")
        return 0

    # Filter if requested
    if task_filter:
        tasks = [
            t
            for t in tasks
            if task_filter.lower() in (t.get("title", "").lower())
            or task_filter.lower() in (t.get("content", "") or "").lower()
        ]
        print(f"Found {len(tasks)} tasks matching filter '{task_filter}'")
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

    # Confirm
    response = input(f"\nDelete {len(tasks)} task(s)? [y/N]: ").strip()
    if response.lower() != "y":
        print("Cancelled.")
        return 0

    # Delete
    deleted = 0
    for task in tasks:
        task_id = task.get("id")
        if task_id and delete_task(vibe_url, task_id):
            deleted += 1
            print(f"Deleted: {task.get('title', 'Untitled')}")
        else:
            print(f"Failed to delete: {task.get('title', 'Untitled')}")

    print(f"\n{deleted}/{len(tasks)} tasks deleted.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Sync GitHub issues to Vibe Kanban tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vibe-sync --setup                Create or update config interactively
  vibe-sync                        Start continuous sync (select repos interactively)
  vibe-sync --once                 Run a single sync and exit
  vibe-sync --all                  Sync all configured repos (no prompt)
  vibe-sync --dry-run              Show what would be synced without creating tasks
  vibe-sync --clear-tasks          Clear tasks from Vibe Kanban project
  vibe-sync -c /path/to/config.json  Use custom config file
""",
    )
    parser.add_argument(
        "--setup",
        "-s",
        action="store_true",
        help="Run interactive setup to create/update config",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Path to config file (default: ~/.config/vibe-sync/config.json)",
    )
    parser.add_argument(
        "--once",
        "-1",
        action="store_true",
        help="Run a single sync and exit (don't loop)",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Sync all configured repos without prompting",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be synced without creating tasks",
    )
    parser.add_argument(
        "--clear-tasks",
        action="store_true",
        help="Clear tasks from Vibe Kanban project",
    )
    parser.add_argument(
        "--filter",
        "-f",
        help="Filter tasks when clearing (only with --clear-tasks)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Determine config path
    global CONFIG_PATH
    if args.config:
        CONFIG_PATH = args.config
    elif DEFAULT_CONFIG_PATH.exists():
        CONFIG_PATH = DEFAULT_CONFIG_PATH
    elif Path("config.json").exists():
        CONFIG_PATH = Path("config.json")
    else:
        CONFIG_PATH = DEFAULT_CONFIG_PATH

    # Run setup if requested or if no config exists
    if args.setup:
        config = interactive_setup(CONFIG_PATH)
        if not config:
            return 1
        return 0

    # Load config
    config = load_config()
    if not config:
        print(f"No config found at {CONFIG_PATH}")
        response = input("Would you like to run setup now? [Y/n]: ").strip()
        if response.lower() != "n":
            config = interactive_setup(CONFIG_PATH)
            if not config:
                return 1
        else:
            return 1

    # Handle --clear-tasks
    if args.clear_tasks:
        return clear_tasks_interactive(config, task_filter=args.filter)

    # Select projects interactively unless --all is specified
    if not args.all and len(config.get("projects", [])) > 1:
        config = select_projects_interactive(config)
        if not config:
            return 1

    if args.dry_run:
        print("Dry-run mode: showing what would be synced")
        return dry_run(config)

    logger.info("Starting Vibe Kanban GitHub Sync Service...")
    run_sync(config, once=args.once)
    logger.info("Shutdown complete.")
    return 0


def dry_run(config):
    """Show what would be synced without creating tasks."""
    vibe_url = get_vibe_api_url(config)
    issue_limit = config.get("issue_limit", 100)

    for project in config.get("projects", []):
        gh_repo = project["github_repo"]
        vibe_proj_id = project["vibe_project_id"]

        print(f"\n=== {gh_repo} -> Project {vibe_proj_id} ===")

        gh_issues = fetch_github_issues(gh_repo, limit=issue_limit)
        vibe_tasks = fetch_vibe_tasks(vibe_url, vibe_proj_id)

        # Build set of existing issue URLs
        existing_urls = set()
        existing_titles = set()
        for task in vibe_tasks:
            content = task.get("content") or ""
            title = task.get("title", "")

            if title:
                existing_titles.add(title.strip())

            if "Original Issue: " in content:
                url_start = content.find("Original Issue: ") + len("Original Issue: ")
                url_end = content.find("\n", url_start)
                if url_end == -1:
                    url_end = len(content)
                url = content[url_start:url_end].strip()
                if url:
                    existing_urls.add(url)

            # Also check for any github.com URLs in content
            github_urls = re.findall(r'https://github\.com/[^\s\)]+', content)
            for url in github_urls:
                existing_urls.add(url.strip())

        new_issues = []
        for issue in gh_issues:
            is_duplicate = (
                issue["url"] in existing_urls or
                issue["title"].strip() in existing_titles
            )
            if not is_duplicate:
                new_issues.append(issue)

        print(f"GitHub issues: {len(gh_issues)}")
        print(f"Existing Vibe tasks: {len(vibe_tasks)}")
        print(f"New issues to sync: {len(new_issues)}")

        if new_issues:
            print("\nWould create tasks for:")
            for issue in new_issues:
                print(f"  #{issue['number']}: {issue['title']}")
        else:
            print("\nNo new issues to sync.")

    return 0


if __name__ == "__main__":
    main()
