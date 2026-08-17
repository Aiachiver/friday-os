import tempfile
from pathlib import Path

import pytest

from app.automation.desktop import file_manager


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def test_read_file_content_returns_real_text(workspace):
    target = workspace / "notes.txt"
    target.write_text("hello world")

    result = file_manager.read_file_content(str(target))
    assert result["success"] is True
    assert result["content"] == "hello world"
    assert result["truncated"] is False


def test_read_file_content_truncates_large_files(workspace):
    target = workspace / "big.txt"
    target.write_text("x" * 1000)

    result = file_manager.read_file_content(str(target), max_chars=100)
    assert result["success"] is True
    assert len(result["content"]) == 100
    assert result["truncated"] is True


def test_read_file_content_missing_file_fails_cleanly(workspace):
    result = file_manager.read_file_content(str(workspace / "nope.txt"))
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_read_file_content_rejects_directory(workspace):
    result = file_manager.read_file_content(str(workspace))
    assert result["success"] is False
    assert "directory" in result["error"]


def test_write_file_content_creates_new_file(workspace):
    target = workspace / "generated.py"
    result = file_manager.write_file_content(str(target), "print('hi')")

    assert result["success"] is True
    assert target.read_text() == "print('hi')"


def test_write_file_content_creates_parent_directories(workspace):
    target = workspace / "src" / "nested" / "module.py"
    result = file_manager.write_file_content(str(target), "x = 1")

    assert result["success"] is True
    assert target.exists()
    assert target.read_text() == "x = 1"


def test_write_file_content_refuses_to_clobber_by_default(workspace):
    target = workspace / "existing.py"
    target.write_text("original")

    result = file_manager.write_file_content(str(target), "new content")

    assert result["success"] is False
    assert target.read_text() == "original"  # untouched


def test_write_file_content_overwrites_when_explicitly_allowed(workspace):
    target = workspace / "existing.py"
    target.write_text("original")

    result = file_manager.write_file_content(str(target), "new content", overwrite=True)

    assert result["success"] is True
    assert target.read_text() == "new content"
