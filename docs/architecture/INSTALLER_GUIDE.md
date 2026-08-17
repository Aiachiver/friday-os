# Building the Windows installer

This produces a real, double-clickable `FridayOS-Setup-X.Y.Z.exe` that
installs FRIDAY OS like any normal Windows application: Start Menu
entry, optional desktop icon, optional "start at login," and a proper
uninstaller.

**This entire process is Windows-only.** PyInstaller doesn't
cross-compile (a Windows .exe can only be built on Windows), and Inno
Setup's compiler (`ISCC.exe`) is a Windows tool. If you're reading this
from a Linux/Mac dev environment, you'll need an actual Windows machine
or VM for this step — everything else in this project runs fine
cross-platform for development, but packaging doesn't.

## One-time setup

1. **Inno Setup** — download and install from
   https://jrsoftware.org/isdl.php (free). Version 6.3 or newer (this
   project's `.iss` script uses the modern `x64compatible` architecture
   directive, introduced in 6.3).
2. Everything else (PyInstaller, etc.) is already in `requirements.txt`.

## Building

```powershell
cd friday_os
.venv\Scripts\Activate.ps1
.\scripts\build_installer.ps1
```

This runs PyInstaller, then Inno Setup, and prints the final installer
path (`installer\output\FridayOS-Setup-X.Y.Z.exe`) when done. The
script checks each step's actual output before proceeding to the next —
if PyInstaller silently produced a broken build, you'll find out at the
PyInstaller step, not after waiting for Inno Setup too.

Expect this to take several minutes and produce a build in the
900MB-1GB range — faster-whisper's inference backend (ctranslate2),
PySide6, matplotlib, and Playwright's dependencies are all substantial.
This is normal for a desktop app bundling local speech recognition; it's
not a sign anything went wrong.

## What the installer does and doesn't do

- **Does**: install per-user (no admin required — matches
  `startup_manager.py`'s per-user HKCU scope), create Start Menu +
  optional desktop shortcuts, offer a "start at login" checkbox, and
  clean up properly on uninstall.
- **Does NOT delete your data on uninstall.** Conversation history,
  remembered facts, portfolio, notes — all of it lives in
  `%LOCALAPPDATA%\FridayOS`, separate from the installed application
  directory, and the uninstaller explicitly leaves it alone. The
  uninstaller tells you exactly where it is in case you want to remove
  it yourself.
- **Does NOT bundle Tesseract, Ollama, or Playwright's browser
  binaries.** These are separate installs by design (see
  `VISION_SETUP.md`, `AI_BRAIN_SETUP.md`) — bundling a browser binary
  alone would add another 300+MB, and Tesseract/Ollama both have their
  own official Windows installers that are better maintained than
  anything this project could bundle and keep updated itself.

## Code signing (not included)

This installer is **unsigned**. Running it on a machine other than the
one that built it will trigger a Windows SmartScreen "unknown publisher"
warning — this is expected, not a bug, and there's no way around it
without a code-signing certificate.

Getting one (from a CA like DigiCert, Sectigo, or via a cheaper
OV-cert reseller) and signing both `FridayOS.exe` (via `signtool.exe`,
ideally as a PyInstaller post-build step) and the installer `.exe`
itself is the standard path to a "no warnings" install experience, but
it's a paid, ongoing commitment (certs expire and need renewal) that's
outside what this project can respectably automate for you — this is a
decision to make once you're distributing to other people, not
something to block local/personal use on.

## Testing the installer

There's no substitute for actually running it on a real (or fresh VM)
Windows machine and confirming:
- The app launches and the dashboard appears
- "Start at login" actually adds the Startup-folder shortcut
  (`shell:startup`) and it works after a real reboot
- Uninstalling removes the app but leaves `%LOCALAPPDATA%\FridayOS`
  intact, and running the installer again afterward finds your old data

This project's automated test suite (`pytest`) covers the Python
application logic extensively, but by nature can't cover "does the
actual installer .exe work on a real Windows box" — that step needs a
human running it once per release.
