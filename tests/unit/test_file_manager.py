import tempfile
from pathlib import Path

import pytest

from app.automation.desktop import file_manager


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "notes.txt").write_text("hello")
        (root / "report.pdf").write_text("fake pdf")
        sub = root / "subdir"
        sub.mkdir()
        (sub / "budget.xlsx").write_text("fake xlsx")
        yield root


def test_search_files_substring_match(workspace):
    result = file_manager.search_files("report", str(workspace))
    assert result["success"] is True
    assert any("report.pdf" in path for path in result["results"])


def test_search_files_glob_match(workspace):
    result = file_manager.search_files("*.xlsx", str(workspace))
    assert result["success"] is True
    assert any("budget.xlsx" in path for path in result["results"])


def test_search_files_missing_root_reports_error():
    result = file_manager.search_files("anything", "/definitely/not/a/real/path")
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_move_file_relocates_and_reports_new_path(workspace):
    dest_dir = workspace / "archive"
    dest_dir.mkdir()
    result = file_manager.move_file(str(workspace / "notes.txt"), str(dest_dir))

    assert result["success"] is True
    assert Path(result["new_path"]).exists()
    assert not (workspace / "notes.txt").exists()


def test_move_file_missing_source_fails_cleanly():
    result = file_manager.move_file("/no/such/file.txt", "/tmp")
    assert result["success"] is False


def test_rename_file_changes_name(workspace):
    result = file_manager.rename_file(str(workspace / "notes.txt"), "renamed.txt")
    assert result["success"] is True
    assert (workspace / "renamed.txt").exists()
    assert not (workspace / "notes.txt").exists()


def test_rename_file_rejects_path_separators(workspace):
    result = file_manager.rename_file(str(workspace / "notes.txt"), "../escape.txt")
    assert result["success"] is False


def test_create_folder_makes_nested_dirs(workspace):
    target = workspace / "a" / "b" / "c"
    result = file_manager.create_folder(str(target))
    assert result["success"] is True
    assert target.is_dir()


def test_delete_file_sends_to_trash_by_default(workspace):
    target = workspace / "notes.txt"
    result = file_manager.delete_file(str(target))
    assert result["success"] is True
    assert result["permanent"] is False
    assert not target.exists()


def test_delete_file_permanent_removes_immediately(workspace):
    target = workspace / "report.pdf"
    result = file_manager.delete_file(str(target), permanent=True)
    assert result["success"] is True
    assert result["permanent"] is True
    assert not target.exists()


def test_delete_missing_file_fails_cleanly(workspace):
    result = file_manager.delete_file(str(workspace / "does_not_exist.txt"))
    assert result["success"] is False


def test_read_file_content_returns_full_text(workspace):
    result = file_manager.read_file_content(str(workspace / "notes.txt"))
    assert result["success"] is True
    assert result["content"] == "hello"
    assert result["truncated"] is False


def test_read_file_content_missing_file_fails_cleanly():
    result = file_manager.read_file_content("/definitely/not/a/real/file.txt")
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_read_file_content_rejects_a_directory(workspace):
    result = file_manager.read_file_content(str(workspace))
    assert result["success"] is False
    assert "directory" in result["error"]


def test_read_file_content_truncates_large_files(workspace):
    big_file = workspace / "big.txt"
    big_file.write_text("x" * 1000)
    result = file_manager.read_file_content(str(big_file), max_chars=100)
    assert result["success"] is True
    assert result["truncated"] is True
    assert len(result["content"]) == 100


def test_write_file_content_creates_new_file(workspace):
    target = workspace / "generated.py"
    result = file_manager.write_file_content(str(target), "print('hello')")
    assert result["success"] is True
    assert target.read_text() == "print('hello')"


def test_write_file_content_creates_parent_directories(workspace):
    target = workspace / "src" / "nested" / "module.py"
    result = file_manager.write_file_content(str(target), "x = 1")
    assert result["success"] is True
    assert target.exists()


def test_write_file_content_refuses_to_overwrite_by_default(workspace):
    target = workspace / "notes.txt"
    original_content = target.read_text()
    result = file_manager.write_file_content(str(target), "clobbered")
    assert result["success"] is False
    assert target.read_text() == original_content  # untouched


def test_write_file_content_overwrites_when_explicitly_told(workspace):
    target = workspace / "notes.txt"
    result = file_manager.write_file_content(str(target), "new content", overwrite=True)
    assert result["success"] is True
    assert target.read_text() == "new content"
