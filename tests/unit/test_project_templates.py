"""
Tests project_templates.py by actually running what it generates, not
just checking file existence -- a template that writes syntactically
broken code would pass a "files exist" check but fail here, which is
the whole point: this module's docstring specifically claims the
generated projects "really run."
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.coding.project_templates import create_project_from_template


def test_unknown_template_fails_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        result = create_project_from_template("cobol-mainframe", "x", tmp)
    assert result["success"] is False
    assert "Unknown template" in result["error"]


def test_refuses_to_overwrite_a_nonempty_existing_directory():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "existing"
        base.mkdir()
        (base / "already_here.txt").write_text("don't clobber me")

        result = create_project_from_template("python-cli", "existing", tmp)
        assert result["success"] is False
        assert (base / "already_here.txt").exists()


class TestPythonCliTemplate:
    def test_generates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("python-cli", "greetme", tmp)
            assert result["success"] is True
            project_dir = Path(result["path"])
            for expected in ("pyproject.toml", "greetme/cli.py", "tests/test_cli.py", "README.md"):
                assert (project_dir / expected).exists(), expected

    def test_generated_cli_actually_runs_and_produces_correct_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("python-cli", "greetme", tmp)
            project_dir = Path(result["path"])

            env = {**os.environ, "PYTHONPATH": str(project_dir)}
            proc = subprocess.run(
                [sys.executable, "-m", "greetme.cli", "Suraj"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                env=env,
            )
            assert proc.returncode == 0
            assert "Hello, Suraj!" in proc.stdout

    def test_generated_test_suite_actually_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("python-cli", "greetme", tmp)
            project_dir = Path(result["path"])

            env = {**os.environ, "PYTHONPATH": str(project_dir)}
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                env=env,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
            assert "2 passed" in proc.stdout

    def test_project_name_with_hyphens_produces_valid_module_name(self):
        """Python module names can't contain hyphens -- the template must
        translate 'my-cool-tool' (a perfectly normal project name) into
        a valid 'my_cool_tool' package directory, not write something
        Python can't even import."""
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("python-cli", "my-cool-tool", tmp)
            assert result["success"] is True
            project_dir = Path(result["path"])
            assert (project_dir / "my_cool_tool" / "cli.py").exists()
            assert not (project_dir / "my-cool-tool").exists()


class TestFastAPITemplate:
    def test_generates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("fastapi", "myservice", tmp)
            assert result["success"] is True
            project_dir = Path(result["path"])
            for expected in ("main.py", "requirements.txt", "tests/test_main.py"):
                assert (project_dir / expected).exists(), expected

    def test_generated_app_actually_serves_real_requests(self):
        """Imports the generated main.py directly and hits it with
        FastAPI's real TestClient -- this is the generated project's own
        test approach, run for real rather than just trusted."""
        pytest.importorskip("fastapi")
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("fastapi", "myservice", tmp)
            project_dir = Path(result["path"])

            sys.path.insert(0, str(project_dir))
            try:
                import importlib

                main_module = importlib.import_module("main")
                from fastapi.testclient import TestClient

                client = TestClient(main_module.app)
                response = client.get("/")
                assert response.status_code == 200
                assert response.json()["service"] == "myservice"

                health = client.get("/health")
                assert health.status_code == 200
            finally:
                sys.path.remove(str(project_dir))
                sys.modules.pop("main", None)


class TestReactTemplate:
    def test_generates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("react", "myui", tmp)
            assert result["success"] is True
            project_dir = Path(result["path"])
            for expected in ("package.json", "index.html", "src/main.jsx", "src/App.jsx", "vite.config.js"):
                assert (project_dir / expected).exists(), expected

    def test_package_json_is_valid_json_with_expected_fields(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            result = create_project_from_template("react", "myui", tmp)
            project_dir = Path(result["path"])

            with open(project_dir / "package.json") as f:
                package = json.load(f)

            assert package["name"] == "myui"
            assert "react" in package["dependencies"]
            assert "dev" in package["scripts"]
