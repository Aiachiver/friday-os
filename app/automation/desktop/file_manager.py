"""
File management automation: search, move, rename, create folders, and
delete (to the recycle bin/trash by default, never a hard delete unless
explicitly requested twice). Every destructive method returns a plain
result dict rather than raising for expected conditions (file not found,
etc.) so the AI brain's tool-calling layer can report the outcome back
to the user in natural language instead of crashing the turn.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any

from send2trash import send2trash

from app.utils.logger import get_logger

log = get_logger(__name__)

_MAX_SEARCH_RESULTS = 50


def search_files(query: str, root: str, max_results: int = _MAX_SEARCH_RESULTS) -> dict[str, Any]:
    """Recursively searches `root` for files/folders whose name matches
    `query` (case-insensitive substring or glob pattern, e.g. '*.pdf')."""
    root_path = Path(root).expanduser()
    if not root_path.exists():
        return {"success": False, "error": f"Search root does not exist: {root}"}

    pattern_is_glob = any(ch in query for ch in "*?[]")
    query_lower = query.lower()
    matches: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        for name in dirnames + filenames:
            is_match = fnmatch.fnmatch(name.lower(), query_lower) if pattern_is_glob else query_lower in name.lower()
            if is_match:
                matches.append(str(Path(dirpath) / name))
                if len(matches) >= max_results:
                    return {"success": True, "results": matches, "truncated": True}

    return {"success": True, "results": matches, "truncated": False}


def move_file(source: str, destination: str) -> dict[str, Any]:
    source_path = Path(source).expanduser()
    dest_path = Path(destination).expanduser()

    if not source_path.exists():
        return {"success": False, "error": f"Source does not exist: {source}"}
    if dest_path.exists() and dest_path.is_dir():
        dest_path = dest_path / source_path.name

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(dest_path))
    except OSError as exc:
        log.exception("move_file failed")
        return {"success": False, "error": str(exc)}

    log.info("Moved {} -> {}", source_path, dest_path)
    return {"success": True, "new_path": str(dest_path)}


def rename_file(path: str, new_name: str) -> dict[str, Any]:
    source_path = Path(path).expanduser()
    if not source_path.exists():
        return {"success": False, "error": f"Path does not exist: {path}"}
    if "/" in new_name or "\\" in new_name:
        return {"success": False, "error": "new_name must be a filename, not a path"}

    dest_path = source_path.parent / new_name
    try:
        source_path.rename(dest_path)
    except OSError as exc:
        log.exception("rename_file failed")
        return {"success": False, "error": str(exc)}

    log.info("Renamed {} -> {}", source_path, dest_path)
    return {"success": True, "new_path": str(dest_path)}


def create_folder(path: str) -> dict[str, Any]:
    folder_path = Path(path).expanduser()
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.exception("create_folder failed")
        return {"success": False, "error": str(exc)}

    log.info("Created folder {}", folder_path)
    return {"success": True, "path": str(folder_path)}


def delete_file(path: str, permanent: bool = False) -> dict[str, Any]:
    """
    Deletes a file or folder. By default sends it to the OS recycle
    bin/trash (recoverable) via send2trash. `permanent=True` bypasses the
    recycle bin entirely — the orchestrator only sets that after a second,
    explicit user confirmation; this function itself does not gate on
    confirmation, since that's a conversation-flow concern, not a
    filesystem concern.
    """
    target_path = Path(path).expanduser()
    if not target_path.exists():
        return {"success": False, "error": f"Path does not exist: {path}"}

    try:
        if permanent:
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
            log.warning("Permanently deleted {}", target_path)
            return {"success": True, "permanent": True}
        else:
            send2trash(str(target_path))
            log.info("Sent to recycle bin: {}", target_path)
            return {"success": True, "permanent": False}
    except OSError as exc:
        log.exception("delete_file failed")
        return {"success": False, "error": str(exc)}


_MAX_READ_CHARS = 20000  # keeps a huge log file or binary-ish file from blowing out the LLM context


def read_file_content(path: str, max_chars: int = _MAX_READ_CHARS) -> dict[str, Any]:
    """Reads a text file's contents, truncated if it's large. Used for
    both general file inspection and the coding assistant's "explain
    this code" / "debug this file" flows — those don't need a separate
    dedicated tool, they're just this plus the AI brain reasoning over
    what comes back, the same multi-round tool-calling pattern every
    other capability in this project already uses."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return {"success": False, "error": f"File does not exist: {path}"}
    if file_path.is_dir():
        return {"success": False, "error": f"Path is a directory, not a file: {path}"}

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.exception("read_file_content failed")
        return {"success": False, "error": str(exc)}

    truncated = len(content) > max_chars
    return {
        "success": True,
        "path": str(file_path),
        "content": content[:max_chars],
        "truncated": truncated,
    }


def write_file_content(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    """Writes text to a file, creating parent directories as needed.
    Refuses to clobber an existing file unless `overwrite=True` — this
    is the same "ask before doing something hard to undo" spirit as
    delete_file's recycle-bin default, just for a different kind of
    data loss (silently replacing someone's file contents)."""
    file_path = Path(path).expanduser()
    if file_path.exists() and not overwrite:
        return {
            "success": False,
            "error": f"{path} already exists. Pass overwrite=True to replace it.",
        }

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        log.exception("write_file_content failed")
        return {"success": False, "error": str(exc)}

    log.info("Wrote {} characters to {}", len(content), file_path)
    return {"success": True, "path": str(file_path), "bytes_written": len(content.encode("utf-8"))}
