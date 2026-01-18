import json
import logging
import time
import subprocess
import requests
import os
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path('config.json')

def load_config():
    if not CONFIG_PATH.exists():
        logger.error(f"Config file {CONFIG_PATH} not found.")
        return None
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def fetch_github_issues(repo):
    """Fetch open issues from GitHub using gh CLI."""
    try:
        # Fetch json fields: number, title, body, url
        cmd = [
            'gh', 'issue', 'list',
            '--repo', repo,
            '--state', 'open',
            '--limit', '50',
            '--json', 'number,title,body,url'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to fetch issues for {repo}: {e.stderr}")
        return []
    except json.JSONDecodeError:
        logger.error(f"Failed to parse GH CLI output for {repo}")
        return []

def fetch_vibe_tasks(api_url, project_id):
    """Fetch existing tasks from Vibe Kanban for a project."""
    try:
        # Vibe Kanban API usually supports filtering or we fetch all
        # Based on reverse engineering, GET /api/tasks might need project_id filtering client-side
        # or it accepts query params. For now let's assume we fetch all and filter in memory if needed.
        # Note: The API reverse engineering wasn't 100% conclusive on GET args.
        # We will try fetching all lists/tasks if possible.
        
        # Actually, let's look at the created task structure.
        # If there's no easy 'list tasks by project' endpoint documented,
        # we might have to fetch all tasks.
        # Let's try GET /api/tasks
        resp = requests.get(f"{api_url}/api/tasks")
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                all_tasks = data.get('data', [])
                # Filter by project_id
                return [t for t in all_tasks if t.get('project_id') == project_id]
        logger.error(f"Failed to fetch vibe tasks: {resp.status_code} {resp.text}")
        return []
    except requests.RequestException as e:
        logger.error(f"Error fetching vibe tasks: {e}")
        return []

def create_vibe_task(api_url, project_id, title, content):
    """Create a new task in Vibe Kanban."""
    payload = {
        "title": title,
        "project_id": project_id,
        "content": content
    }
    try:
        resp = requests.post(f"{api_url}/api/tasks", json=payload)
        if resp.status_code in [200, 201]:
             logger.info(f"Created task: {title}")
             return True
        else:
             logger.error(f"Failed to create task '{title}': {resp.status_code} {resp.text}")
             return False
    except requests.RequestException as e:
        logger.error(f"Error creating vibe task: {e}")
        return False

def main():
    logger.info("Starting Vibe Kanban GitHub Sync Service...")
    
    while True:
        config = load_config()
        if not config:
            time.sleep(60)
            continue
            
        vibe_url = config.get('vibe_api_url', 'http://localhost:3000')
        sync_interval = config.get('sync_interval_seconds', 60)
        
        for project in config.get('projects', []):
            gh_repo = project['github_repo']
            vibe_proj_id = project['vibe_project_id']
            
            logger.info(f"Syncing {gh_repo} -> Project {vibe_proj_id}")
            
            # 1. Fetch GH Issues
            gh_issues = fetch_github_issues(gh_repo)
            logger.info(f"Found {len(gh_issues)} open issues in {gh_repo}")
            
            # 2. Fetch Vibe Tasks
            vibe_tasks = fetch_vibe_tasks(vibe_url, vibe_proj_id)
            existing_contents = {t.get('content') or "" for t in vibe_tasks}
            existing_titles = {t.get('title') for t in vibe_tasks}

            # 3. Compare and Create
            for issue in gh_issues:
                issue_title = issue['title'] 
                issue_url = issue['url']
                issue_body = issue['body'] or ""
                
                # Construct content (body + link)
                # We can append the link to make it distinct/clickable
                task_content = f"{issue_body}\n\nOriginal Issue: {issue_url}"
                
                # Simple duplicate check: 
                # Check if exact title exists OR if the issue URL is in the content of any existing task
                is_duplicate = False
                
                if issue_title in existing_titles:
                    is_duplicate = True
                else:
                    # Check if URL is in any existing task content
                    for content in existing_contents:
                        if issue_url in content:
                            is_duplicate = True
                            break
                            
                if not is_duplicate:
                    logger.info(f"Creating task for issue #{issue['number']}: {issue_title}")
                    create_vibe_task(vibe_url, vibe_proj_id, issue_title, task_content)
                else:
                    logger.debug(f"Skipping duplicate issue #{issue['number']}")
        
        logger.info(f"Sync complete. Sleeping for {sync_interval} seconds...")
        time.sleep(sync_interval)

if __name__ == "__main__":
    main()
