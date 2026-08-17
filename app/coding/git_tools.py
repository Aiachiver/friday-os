"""
Git integration via the `git` CLI (subprocess), not a Python git binding
— avoids adding GitPython or pygit2 as a dependency just to shell out to
the exact same binary those libraries wrap anyway, and `git` is already
a prerequisite for anyone doing software development on the machine
this runs on.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)

_GIT_TIMEOUT_SECONDS = 30


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5, check=False)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def git_init(path: str) -> dict[str, Any]:
    repo_path = Path(path).expanduser()
    if not repo_path.exists():
        return {"success": False, "error": f"Path does not exist: {path}"}
    if not _git_available():
        return {"success": False, "error": "git is not installed or not on PATH."}

    try:
        result = _run_git(["init"], cwd=str(repo_path))
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git init timed out."}

    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip()}

    log.info("Initialized git repo at {}", repo_path)
    return {"success": True, "path": str(repo_path)}


def git_status(path: str) -> dict[str, Any]:
    repo_path = Path(path).expanduser()
    try:
        result = _run_git(["status", "--porcelain", "--branch"], cwd=str(repo_path))
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git status timed out."}

    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip() or "Not a git repository."}

    lines = result.stdout.splitlines()
    branch_line = lines[0] if lines else ""
    changed_files = [line[3:] for line in lines[1:]]  # strip the 2-char status code + space

    return {
        "success": True,
        "branch_info": branch_line.lstrip("#").strip(),
        "changed_files": changed_files,
        "clean": len(changed_files) == 0,
    }


def git_add_commit(path: str, message: str, add_all: bool = True) -> dict[str, Any]:
    repo_path = Path(path).expanduser()

    if add_all:
        try:
            add_result = _run_git(["add", "-A"], cwd=str(repo_path))
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "git add timed out."}
        if add_result.returncode != 0:
            return {"success": False, "error": add_result.stderr.strip()}

    try:
        commit_result = _run_git(["commit", "-m", message], cwd=str(repo_path))
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git commit timed out."}

    if commit_result.returncode != 0:
        # "nothing to commit" isn't really a failure from the caller's
        # perspective -- it's a legitimate, common outcome worth
        # reporting plainly rather than as an error.
        if "nothing to commit" in commit_result.stdout.lower():
            return {"success": True, "committed": False, "message": "Nothing to commit — working tree clean."}
        return {"success": False, "error": commit_result.stderr.strip() or commit_result.stdout.strip()}

    log.info("Committed to {}: {!r}", repo_path, message)
    return {"success": True, "committed": True, "message": message}


def git_current_branch(path: str) -> dict[str, Any]:
    repo_path = Path(path).expanduser()
    try:
        result = _run_git(["branch", "--show-current"], cwd=str(repo_path))
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git branch timed out."}

    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip() or "Not a git repository."}

    branch = result.stdout.strip()
    return {"success": True, "branch": branch or "(detached HEAD)"}
