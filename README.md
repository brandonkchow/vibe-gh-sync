# Vibe Kanban GitHub Sync Service

A standalone service that continuously creates Vibe Kanban tasks from GitHub issues.

## Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration:**
    *   Edit `config.json` to map your GitHub repositories to Vibe Kanban project IDs.
    *   Ensure Vibe Kanban is running (default: `http://localhost:3000`).

3.  **Authentication:**
    *   Ensure `gh` CLI is authenticated (the script uses `gh` to fetch issues).
    *   Alternatively, you can modify `main.py` to use a `GITHUB_TOKEN` env var if you prefer API calls directly (currently uses `gh` subprocess calls).

## Usage

Run the service:

```bash
python3 main.py
```

The service will loop every 60 seconds (configurable) and creation new tasks for any **open** GitHub issues that don't already exist in the Vibe Kanban project.
