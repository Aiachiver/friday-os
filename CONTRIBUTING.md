# Contributing to FRIDAY OS

## Dev environment setup

```powershell
git clone <your-repo-url> friday_os
cd friday_os
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
```

See `README.md` for the full quick-start and `docs/architecture/` for
the one-time setup guides (wake word, AI provider, vision, Spotify).
None of them are required to start developing — the app degrades
gracefully and runs in text-only, brain-less mode without any of them
configured, which is often exactly what you want while iterating on
something unrelated (e.g. the finance module doesn't care whether
voice is set up).

## Running the test suite

```powershell
pytest                          # full suite
pytest tests/unit/test_orchestrator_brain.py -v   # one file
pytest -k "confirmation"        # anything matching a keyword
pytest --cov=app --cov-report=html   # coverage report -> htmlcov/index.html
```

The suite is fast (~10s for 180+ tests) because it deliberately avoids
real network calls and real audio hardware — external services (LLM
providers, yfinance, GitHub's API, Spotify, weather) are always tested
against fakes/mocks that exercise the real parsing and control-flow
logic, not the real service. See any `tests/unit/test_*.py` file for
the pattern: a small `_Fake*` class standing in for the SDK client,
injected via `monkeypatch`.

**If you're adding a feature that talks to an external service**, follow
that same pattern — write the fake, assert on what your code does with
realistic response shapes (including realistic error shapes: rate
limits, missing fields, timeouts), and keep the suite network-free.

## Code style

```powershell
ruff check .        # lint
black .              # format
mypy app             # type check
```

`pyproject.toml` has the configuration for all three. Nothing exotic —
standard line length 100, strict-ish mypy, ruff's default-ish rule set
plus import sorting.

## Where things go

If you're adding a new capability, match the existing layering (see
`docs/architecture/ARCHITECTURE.md` section 2 for the full rationale):

- **A new automation action** (controls the OS, a file, the browser) →
  `app/automation/`, then register it as a tool in `app/brain/tools.py`.
  Mark `requires_confirmation=True` if it's destructive or hard to undo.
- **A new domain capability that doesn't fit automation** (finance,
  vision, research, productivity) → its own module under `app/`, same
  "plain function returning a result dict" pattern as everything else,
  registered as a tool the same way.
- **Something a third party might want without touching core code** →
  a plugin instead (`docs/architecture/PLUGIN_SYSTEM.md`). If you're not
  sure whether something belongs in core or as a plugin, default to
  plugin — it's strictly easier to promote a plugin into core later
  than to extract core code into a plugin.
- **A new LLM provider** → check `app/brain/router.py`'s
  `_PROVIDER_REGISTRY` first; if it exposes an OpenAI-compatible
  `/chat/completions` endpoint (most do now), it's a 5-line registry
  entry, not a new adapter class.

## Database changes

Never hand-edit `data/db/friday.db` or write raw `ALTER TABLE`. Change
`app/data/models.py`, then:

```powershell
alembic revision --autogenerate -m "describe the change"
```

**Always read the generated migration before committing it.** Autogenerate
is a good first draft, not a guarantee — it has repeatedly missed things
or gotten column defaults slightly wrong in this project's own history
(see the docstring on `PortfolioHolding` in `app/data/models.py` for a
concrete example of a bug this exact oversight caused). Apply and test it
locally (`alembic upgrade head`) before opening a PR.

## Pull request expectations

- Tests for new logic — see "Running the test suite" above for the
  house style on mocking external services.
- Run `ruff check .`, `black .`, and `mypy app` clean.
- If you touched a setup-dependent area (voice, AI brain, vision,
  plugins), update the matching doc in `docs/architecture/` in the same
  PR — a passing test suite doesn't catch a stale setup guide, and
  several real bugs in this project's history were exactly that
  (a doc or a test fixture describing an older version of the code it
  was supposed to cover).
