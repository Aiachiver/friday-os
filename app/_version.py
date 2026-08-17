"""
Single source of truth for FRIDAY OS's version number.

Read by:
  - pyproject.toml (via hatchling's dynamic version, [tool.hatch.version])
  - app/core/update_checker.py (compares this against the latest GitHub release)
  - scripts/build_installer.ps1 (stamps the version into the Inno Setup installer)

Bump this one line for a release; everything else derives from it.
"""

__version__ = "0.6.0"
