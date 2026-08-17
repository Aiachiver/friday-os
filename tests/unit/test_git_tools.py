"""Tests git_tools against a REAL temp git repository via actual `git`
CLI calls — not mocked, since git is a legitimate, always-present
prerequisite for this functionality and mocking subprocess calls to it
would mostly just test that we called subprocess.run correctly, not
that git itself does what we expect."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.coding import git_tools


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        git_tools.git_init(tmp)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
        yield Path(tmp)


def test_git_init_creates_a_real_repo():
    with tempfile.TemporaryDirectory() as tmp:
        result = git_tools.git_init(tmp)
        assert result["success"] is True
        assert (Path(tmp) / ".git").is_dir()


def test_git_init_missing_path_fails_cleanly():
    result = git_tools.git_init("/definitely/not/a/real/path")
    assert result["success"] is False


def test_git_status_on_clean_empty_repo(repo):
    result = git_tools.git_status(str(repo))
    assert result["success"] is True
    assert result["clean"] is True
    assert result["changed_files"] == []


def test_git_status_detects_untracked_file(repo):
    (repo / "new_file.txt").write_text("content")
    result = git_tools.git_status(str(repo))
    assert result["success"] is True
    assert result["clean"] is False
    assert any("new_file.txt" in f for f in result["changed_files"])


def test_git_status_on_non_repo_fails_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        result = git_tools.git_status(tmp)
        assert result["success"] is False


def test_git_add_commit_creates_a_real_commit(repo):
    (repo / "file.py").write_text("x = 1")
    result = git_tools.git_add_commit(str(repo), "Add file.py")

    assert result["success"] is True
    assert result["committed"] is True

    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True)
    assert "Add file.py" in log.stdout


def test_git_add_commit_with_nothing_changed_is_not_an_error(repo):
    (repo / "file.py").write_text("x = 1")
    git_tools.git_add_commit(str(repo), "first commit")

    result = git_tools.git_add_commit(str(repo), "empty commit attempt")
    assert result["success"] is True
    assert result["committed"] is False


def test_git_current_branch_after_first_commit(repo):
    (repo / "file.py").write_text("x = 1")
    git_tools.git_add_commit(str(repo), "first commit")

    result = git_tools.git_current_branch(str(repo))
    assert result["success"] is True
    assert result["branch"] in ("main", "master")  # depends on the system's git default


def test_git_current_branch_on_non_repo_fails_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        result = git_tools.git_current_branch(tmp)
        assert result["success"] is False
