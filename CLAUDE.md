# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python service that continuously syncs GitHub issues to Vibe Kanban tasks. It polls GitHub repositories for open issues and creates corresponding tasks in Vibe Kanban, with robust duplicate detection.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run interactive setup
python3 vibe_gh_sync.py --setup

# Run a single sync
python3 vibe_gh_sync.py --once

# Run continuous sync (loops every N seconds)
python3 vibe_gh_sync.py

# Clear duplicate tasks
python3 vibe_gh_sync.py --clear-tasks

# Show what would be synced without creating tasks
python3 vibe_gh_sync.py --dry-run
```

## Prerequisites

- `gh` CLI must be authenticated (`gh auth login`)
- Vibe Kanban server running (auto-detects port)

## Configuration

Edit `~/.config/vibe-sync/config.json` to configure:
- `vibe_api_url`: Vibe Kanban API endpoint (auto-detects if wrong/missing)
- `sync_interval_seconds`: Polling interval (default: 60)
- `projects`: Array mapping GitHub repos to Vibe Kanban project IDs

## Architecture

Single-file service (`vibe_gh_sync.py`) with a main loop that:
1. Auto-detects Vibe Kanban port if configured URL doesn't respond
2. Fetches open issues from GitHub repos via `gh issue list` subprocess
3. Fetches existing tasks from Vibe Kanban via `GET /api/tasks?project_id=X`
4. Creates new tasks for non-duplicate issues via `POST /api/tasks`

## Duplicate Detection

Uses three-layer duplicate detection:
1. **URL matching** (primary): Extracts GitHub issue URLs from task content using regex
2. **Title matching** (fallback): Checks exact title match
3. **In-session tracking**: Prevents duplicates within same sync run

## Port Auto-Detection

If the configured `vibe_api_url` doesn't respond, the service:
1. Scans active processes using `lsof` to find node/vibe-kanban processes
2. Extracts ports from listening sockets
3. Validates by calling `/api/projects` endpoint
4. Falls back to checking common ports (3000, 3001, 8080, 8000, 5000)
