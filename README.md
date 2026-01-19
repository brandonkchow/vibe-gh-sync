# Vibe Kanban GitHub Sync Service

A standalone service that continuously creates Vibe Kanban tasks from GitHub issues.

## Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run Interactive Setup:**
    ```bash
    vibe-sync --setup
    ```
    This will create `~/.config/vibe-sync/config.json` and guide you through configuration.

3.  **Authentication:**
    *   Ensure `gh` CLI is authenticated: `gh auth login`
    *   Vibe Kanban server must be running (auto-detects port)

## Usage

```bash
# Run a single sync
vibe-sync --once

# Run continuous sync (loops every 60 seconds)
vibe-sync

# Show what would be synced (dry run)
vibe-sync --dry-run

# Clear tasks (WARNING: Only works in Claude Code!)
vibe-sync --clear-tasks --yes
```

## Task Deletion Limitation

**IMPORTANT**: The `--clear-tasks` command only works when run from **Claude Code sessions** with MCP access.

- The Vibe Kanban API does not support HTTP DELETE operations
- Task deletion requires the `mcp-cli` tool and `vibe_kanban/delete_task` MCP tool
- Running `--clear-tasks` standalone will fail with "mcp-cli: command not found"
- **Alternative**: Delete tasks manually via the Vibe Kanban UI
