"""
Project scaffolding: generates a minimal, real, runnable starting
structure for a new project — not a full framework install, just the
skeleton a person would otherwise copy-paste from a tutorial or an old
project. Each template writes actual files with actual working content
(a CLI that really runs, a FastAPI app that really starts) rather than
empty placeholders, because a template that doesn't run defeats the
point of having one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)

_SUPPORTED_TEMPLATES = ("python-cli", "fastapi", "react")


def _write(base: Path, relative_path: str, content: str) -> None:
    target = base / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _python_cli_template(project_name: str, base: Path) -> list[str]:
    module_name = project_name.replace("-", "_")
    files = {
        "pyproject.toml": f"""[project]
name = "{project_name}"
version = "0.1.0"
description = ""
requires-python = ">=3.10"

[project.scripts]
{project_name} = "{module_name}.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""",
        f"{module_name}/__init__.py": "",
        f"{module_name}/cli.py": '''"""Command-line entry point."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="{name}")
    parser.add_argument("name", nargs="?", default="world", help="who to greet")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    print(f"Hello, {args.name}!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace(
            "{name}", project_name
        ),
        "tests/__init__.py": "",
        "tests/test_cli.py": f"""from {module_name}.cli import main


def test_default_greeting(capsys):
    exit_code = main([])
    assert exit_code == 0
    assert "Hello, world!" in capsys.readouterr().out


def test_custom_name(capsys):
    exit_code = main(["Suraj"])
    assert exit_code == 0
    assert "Hello, Suraj!" in capsys.readouterr().out
""",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n*.egg-info/\n",
        "README.md": f"# {project_name}\n\n```\npip install -e .\n{project_name}\n```\n",
    }
    for rel_path, content in files.items():
        _write(base, rel_path, content)
    return list(files.keys())


def _fastapi_template(project_name: str, base: Path) -> list[str]:
    files = {
        "main.py": '''"""FastAPI entry point. Run with: uvicorn main:app --reload"""

from fastapi import FastAPI

app = FastAPI(title="{name}")


@app.get("/")
def read_root() -> dict:
    return {"status": "ok", "service": "{name}"}


@app.get("/health")
def health_check() -> dict:
    return {"status": "healthy"}
'''.replace(
            "{name}", project_name
        ),
        "requirements.txt": "fastapi>=0.110\nuvicorn[standard]>=0.29\npytest>=8.0\nhttpx>=0.27\n",
        "tests/__init__.py": "",
        "tests/test_main.py": """from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_root_returns_ok():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
""",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n",
        "README.md": f"# {project_name}\n\n```\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n",
    }
    for rel_path, content in files.items():
        _write(base, rel_path, content)
    return list(files.keys())


def _react_template(project_name: str, base: Path) -> list[str]:
    files = {
        "package.json": f"""{{
  "name": "{project_name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "test": "vitest"
  }},
  "dependencies": {{
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  }},
  "devDependencies": {{
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }}
}}
""",
        "index.html": f"""<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>{project_name}</title></head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
        "src/main.jsx": """import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
""",
        "src/App.jsx": f"""export default function App() {{
  return (
    <main>
      <h1>{project_name}</h1>
      <p>Edit src/App.jsx to get started.</p>
    </main>
  );
}}
""",
        "vite.config.js": """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
""",
        ".gitignore": "node_modules/\ndist/\n",
        "README.md": f"# {project_name}\n\n```\nnpm install\nnpm run dev\n```\n",
    }
    for rel_path, content in files.items():
        _write(base, rel_path, content)
    return list(files.keys())


_TEMPLATE_BUILDERS = {
    "python-cli": _python_cli_template,
    "fastapi": _fastapi_template,
    "react": _react_template,
}


def create_project_from_template(template: str, project_name: str, target_dir: str) -> dict[str, Any]:
    if template not in _SUPPORTED_TEMPLATES:
        return {
            "success": False,
            "error": f"Unknown template '{template}'. Supported: {list(_SUPPORTED_TEMPLATES)}",
        }

    base = Path(target_dir).expanduser() / project_name
    if base.exists() and any(base.iterdir()):
        return {"success": False, "error": f"{base} already exists and is not empty."}

    try:
        files_written = _TEMPLATE_BUILDERS[template](project_name, base)
    except OSError as exc:
        log.exception("create_project_from_template failed")
        return {"success": False, "error": str(exc)}

    log.info("Created {} project '{}' at {} ({} files)", template, project_name, base, len(files_written))
    return {
        "success": True,
        "template": template,
        "path": str(base),
        "files_created": files_written,
    }
