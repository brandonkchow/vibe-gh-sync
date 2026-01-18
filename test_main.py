import json
from unittest.mock import patch, MagicMock
import subprocess

import vibe_gh_sync as main


class TestLoadConfig:
    def test_load_config_success(self, tmp_path, monkeypatch):
        config_data = {"vibe_api_url": "http://test:3000", "projects": []}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        monkeypatch.setattr(main, "CONFIG_PATH", config_file)

        result = main.load_config()
        assert result == config_data

    def test_load_config_missing_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(main, "CONFIG_PATH", config_file)

        result = main.load_config()
        assert result is None


class TestFetchGithubIssues:
    def test_fetch_github_issues_success(self):
        mock_issues = [
            {
                "number": 1,
                "title": "Issue 1",
                "body": "Body 1",
                "url": "https://github.com/org/repo/issues/1",
            },
            {
                "number": 2,
                "title": "Issue 2",
                "body": "Body 2",
                "url": "https://github.com/org/repo/issues/2",
            },
        ]
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(mock_issues)

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = main.fetch_github_issues("org/repo", limit=50)

            assert result == mock_issues
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "gh" in call_args
            assert "--repo" in call_args
            assert "org/repo" in call_args
            assert "--limit" in call_args
            assert "50" in call_args

    def test_fetch_github_issues_subprocess_error(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "gh", stderr="error"),
        ):
            result = main.fetch_github_issues("org/repo")
            assert result == []

    def test_fetch_github_issues_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 60)):
            result = main.fetch_github_issues("org/repo")
            assert result == []

    def test_fetch_github_issues_invalid_json(self):
        mock_result = MagicMock()
        mock_result.stdout = "not valid json"

        with patch("subprocess.run", return_value=mock_result):
            result = main.fetch_github_issues("org/repo")
            assert result == []


class TestFetchVibeTasks:
    def test_fetch_vibe_tasks_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": [
                {"id": "1", "title": "Task 1", "project_id": "proj-1"},
                {"id": "3", "title": "Task 3", "project_id": "proj-1"},
            ],
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = main.fetch_vibe_tasks("http://localhost:3000", "proj-1")

            # Should pass project_id as query param
            mock_get.assert_called_once_with(
                "http://localhost:3000/api/tasks",
                params={"project_id": "proj-1"},
                timeout=30
            )
            assert len(result) == 2
            assert all(t["project_id"] == "proj-1" for t in result)

    def test_fetch_vibe_tasks_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("requests.get", return_value=mock_response):
            result = main.fetch_vibe_tasks("http://localhost:3000", "proj-1")
            assert result == []

    def test_fetch_vibe_tasks_success_false(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error": "Something went wrong",
        }

        with patch("requests.get", return_value=mock_response):
            result = main.fetch_vibe_tasks("http://localhost:3000", "proj-1")
            assert result == []

    def test_fetch_vibe_tasks_timeout(self):
        import requests

        with patch("requests.get", side_effect=requests.Timeout()):
            result = main.fetch_vibe_tasks("http://localhost:3000", "proj-1")
            assert result == []

    def test_fetch_vibe_tasks_request_exception(self):
        import requests

        with patch(
            "requests.get", side_effect=requests.RequestException("Connection error")
        ):
            result = main.fetch_vibe_tasks("http://localhost:3000", "proj-1")
            assert result == []


class TestCreateVibeTask:
    def test_create_vibe_task_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = main.create_vibe_task(
                "http://localhost:3000", "proj-1", "Test Task", "Task description"
            )

            assert result is True
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["json"] == {
                "title": "Test Task",
                "project_id": "proj-1",
                "description": "Task description",
            }

    def test_create_vibe_task_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("requests.post", return_value=mock_response):
            result = main.create_vibe_task(
                "http://localhost:3000", "proj-1", "Test Task", "Task content"
            )
            assert result is False

    def test_create_vibe_task_timeout(self):
        import requests

        with patch("requests.post", side_effect=requests.Timeout()):
            result = main.create_vibe_task(
                "http://localhost:3000", "proj-1", "Test Task", "Task content"
            )
            assert result is False


class TestDuplicateDetection:
    """Test the URL extraction logic used for duplicate detection."""

    def test_url_extraction_from_content(self):
        content = (
            "Some body text\n\nOriginal Issue: https://github.com/org/repo/issues/123"
        )

        existing_urls = set()
        if "Original Issue: " in content:
            url_start = content.find("Original Issue: ") + len("Original Issue: ")
            url_end = content.find("\n", url_start)
            if url_end == -1:
                url_end = len(content)
            existing_urls.add(content[url_start:url_end].strip())

        assert "https://github.com/org/repo/issues/123" in existing_urls

    def test_url_extraction_with_trailing_newline(self):
        content = "Body\n\nOriginal Issue: https://github.com/org/repo/issues/456\n"

        existing_urls = set()
        if "Original Issue: " in content:
            url_start = content.find("Original Issue: ") + len("Original Issue: ")
            url_end = content.find("\n", url_start)
            if url_end == -1:
                url_end = len(content)
            existing_urls.add(content[url_start:url_end].strip())

        assert "https://github.com/org/repo/issues/456" in existing_urls

    def test_no_url_in_content(self):
        content = "Just some regular task content without a URL"

        existing_urls = set()
        if "Original Issue: " in content:
            url_start = content.find("Original Issue: ") + len("Original Issue: ")
            url_end = content.find("\n", url_start)
            if url_end == -1:
                url_end = len(content)
            existing_urls.add(content[url_start:url_end].strip())

        assert len(existing_urls) == 0


class TestSignalHandler:
    def test_signal_handler_sets_shutdown_flag(self):
        main.shutdown_requested = False
        main.signal_handler(None, None)
        assert main.shutdown_requested is True
        # Reset for other tests
        main.shutdown_requested = False
