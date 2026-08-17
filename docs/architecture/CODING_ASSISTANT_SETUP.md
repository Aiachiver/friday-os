# Coding assistant

Project scaffolding, git operations, and GitHub repo creation. Most of
this needs zero setup.

## Requirements

- **git** — needs to be installed and on `PATH`. If you do any
  development on this machine at all, you almost certainly already have
  it (`git --version` to check). `git_init`, `git_status`, `git_commit`,
  and `git_current_branch` all need this; none of them need a GitHub
  account or token — they work with local git alone.
- **GITHUB_TOKEN** (optional) — only needed for `create_github_repo`
  (creating a new repo on GitHub itself, not local git operations).
  Create a fine-grained personal access token with "Repository
  creation" permission at https://github.com/settings/tokens, then in
  `.env`:
  ```
  GITHUB_TOKEN=your_token_here
  ```
  Without this, everything else still works — you'll just get a clear
  "GITHUB_TOKEN isn't configured" message if you ask FRIDAY to create a
  GitHub repo.

## What "generate code" actually means here

There's no dedicated "write me a function" tool, on purpose — that's
just the AI brain's normal conversational ability, the same as any
other question you'd ask it. What FRIDAY *does* add on top of that is
the ability to actually **save** what it generates (`write_file_content`)
and **read** existing code to explain or debug it (`read_file_content`),
so a request like "write a script that renames all my screenshots and
save it to my Desktop" is one conversation, not "here's some code, now
go copy-paste it yourself."

## Project templates

Three templates, each producing real, immediately-runnable code (not
placeholder stubs) — verified by actually running each one's generated
test suite as part of this project's own test suite:

| Template | What you get |
|---|---|
| `python-cli` | A `pyproject.toml`-based CLI with an installable console script, using `argparse` |
| `fastapi` | A minimal FastAPI app with `/` and `/health` endpoints, `uvicorn`-ready |
| `react` | A Vite + React scaffold (`npm install && npm run dev` to start) |

Ask for one directly: *"Friday, scaffold a FastAPI project called
inventory-api in my projects folder."*
