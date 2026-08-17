# FRIDAY OS

A production-grade AI desktop operating assistant for Windows — voice-driven,
memory-aware, and built to run quietly in the system tray for years without
turning into unmaintainable spaghetti.

Status: **Phase 1 — Foundation** (architecture, config, logging, GUI shell).
See [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)
for the full design and the phase roadmap.

## Quick start (Windows, PowerShell)

```powershell
# 1. Clone and enter the repo
git clone <your-repo-url> friday_os
cd friday_os

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install Phase 1 dependencies
pip install -r requirements.txt

# 4. Create your .env from the template
Copy-Item .env.example .env
# then edit .env and fill in API keys as you reach the phases that need them

# 5. Run
python -m app.main
```

You should see a FRIDAY icon appear in your system tray with a
"Skeleton boot successful" notification, and the dashboard shows a
live status card. Database migrations run automatically on startup —
you don't need to run `alembic upgrade head` by hand.

**To get full functionality**, complete these one-time setups (all
optional — FRIDAY degrades gracefully and stays usable without them):
- `docs/architecture/WAKE_WORD_SETUP.md` — enables voice input ("Friday" wake word)
- `docs/architecture/AI_BRAIN_SETUP.md` — enables real reasoning (one free API key, ~2 minutes)
- `docs/architecture/FINANCE_SETUP.md` — market data, portfolio, and price alerts (no setup needed, just usage examples)
- `docs/architecture/VISION_SETUP.md` — OCR and image/screen understanding
- `docs/architecture/PLUGIN_SYSTEM.md` / `SPOTIFY_SETUP.md` — plugins, including Spotify playback control
- `docs/architecture/CODING_ASSISTANT_SETUP.md` — git/GitHub tools and project scaffolding

Building an installer or shipping this to another machine? Read
`docs/architecture/INSTALLER_GUIDE.md`, then work through
`docs/architecture/WINDOWS_VERIFICATION_CHECKLIST.md` — it covers
everything that depends on real audio hardware, a real Windows API, or a
real network path that this project's own dev/CI environment can't verify.

## Project layout

See `ARCHITECTURE.md` for the full explanation. Short version:

- `app/core/` — orchestrator, event bus, scheduler, config (the spine)
- `app/voice/` — wake word, STT, TTS (Phase 2)
- `app/brain/` — multi-provider LLM router + memory (Phase 3)
- `app/automation/` — desktop + browser + coding automation (Phase 3)
- `app/finance/`, `app/vision/`, `app/research/`, `app/productivity/`
  — domain services (Phases 3-5, plus a follow-up pass); system
  monitoring/threat detection lives in `app/plugins/builtin/system_monitor_plugin.py`
  rather than a separate top-level module, since it's a self-contained
  capability with no other module depending on it
- `app/coding/` — git/GitHub tools and project scaffolding templates
- `app/productivity/` — notes and reminders
- `app/plugins/` — plugin system + built-in plugins (Phase 6)
- `app/gui/` — PySide6 dashboard, tray, settings, plugin manager
- `app/data/` — SQLAlchemy models + repositories
- `installer/` — PyInstaller + Inno Setup packaging (Phase 7)

## Development

```powershell
pytest                          # run tests (178+ tests, ~10-20s, no network needed)
ruff check .                     # lint
black .                           # format
mypy app                          # type check
```

All four are clean on `main` and run in CI on every push/PR (see
`.github/workflows/ci.yml`). See `CONTRIBUTING.md` for the fuller dev
guide — where new code should go, the house style for testing external
services (always mocked, never real network calls), and the database
migration workflow.

## Building a distributable installer

See `docs/architecture/INSTALLER_GUIDE.md` for the full guide. Short
version: `.\scripts\build_installer.ps1` on Windows produces a real
`FridayOS-Setup-X.Y.Z.exe`. This step is Windows-only (PyInstaller
doesn't cross-compile).

## Philosophy

FRIDAY is not a chatbot wrapper. Domain logic never talks to a specific SDK
directly — it talks to interfaces, with adapters underneath. This is what
lets us swap Gemini for Ollama, or add a new TTS engine, by touching one
file instead of the whole app.
