# Windows verification checklist

Everything in this project has been tested as thoroughly as a Linux
sandbox allows — 233 automated tests, full lint/format/type-check
compliance, and extensive manual verification of every subsystem's
logic. But a sandbox with no microphone, no speakers, no Windows APIs,
and a network locked to package registries genuinely cannot verify
some things. This is the complete list of what still needs a real
Windows machine, gathered from every phase of this build, with concrete
steps and what "working" looks like for each.

Nothing here is a known bug — it's the honest boundary of what could be
verified without one. Work through this once, top to bottom, on a real
Windows install before considering the project release-ready.

## 1. Voice pipeline

- [ ] **Wake word.** After completing `docs/architecture/WAKE_WORD_SETUP.md`,
      say "Friday" from across a normal room. Expect: the dashboard status
      card flips to "Listening," and you hear "Yes, Suraj" (or your
      configured name) within ~1 second.
      *Why untestable here:* Porcupine needs a real microphone and a
      trained `.ppn` keyword file; this sandbox has neither.
- [ ] **Speech recognition accuracy.** Say a few different commands
      ("what time is it," "open notepad," a longer sentence). Expect:
      faster-whisper transcribes correctly within ~1-2s on a `base`
      model / CPU. If it's slow or inaccurate, see the model-size table
      in `WAKE_WORD_SETUP.md`.
      *Why untestable here:* needs a real mic; the model itself was
      never even downloaded in this sandbox (no network route to
      Hugging Face).
- [ ] **Text-to-speech quality.** Confirm Edge TTS actually sounds
      natural (not the `pyttsx3` fallback voice) for a normal reply.
      *Why untestable here:* no audio output device, and no network
      route to Microsoft's edge-tts service.
- [ ] **TTS fallback actually triggers.** Temporarily disconnect from
      the internet, ask a question, confirm it falls back to `pyttsx3`
      instead of just failing silently.
- [ ] **Mic doesn't hear FRIDAY's own voice.** While FRIDAY is speaking
      a long reply, confirm it doesn't re-trigger the wake word or start
      transcribing itself (tests `pause_listening`/`resume_listening`).

## 2. Windows system integration

All of these are real `ctypes.windll` / `winreg` / `pywin32` / `pycaw`
calls that literally cannot execute on Linux — confirmed via
`platform="win32"` mypy type-checking only, never runtime-executed.

- [ ] `set_volume` — "Friday, set volume to 50%"
- [ ] `set_brightness` — "Friday, set brightness to 70%"
- [ ] `lock_pc` — "Friday, lock my computer" (**save your work first**)
- [ ] `sleep_pc` — after confirming, PC actually sleeps
- [ ] `shutdown_pc` / `restart_pc` — confirmation flow works, then the
      PC actually shuts down/restarts on schedule (**save your work first**)
- [ ] `open_application` / `close_application` — try a few real apps
- [ ] Start-with-Windows toggle (Settings dialog, General tab) — toggle
      it on, reboot, confirm FRIDAY starts minimized to tray
      (`--startup` flag path), not with the dashboard popping up

## 3. Browser automation

- [ ] `playwright install chromium` actually downloads a browser
      (never attempted here — no network route to Playwright's CDN)
- [ ] "Friday, search Google for X" opens a real, visible browser window
- [ ] "Friday, read this page" after navigating somewhere — confirm the
      extracted text is genuinely useful, not garbled

## 4. Vision

- [ ] Tesseract OCR on a real screenshot with real text — confirm
      accuracy is reasonable (the one test with real Tesseract in this
      sandbox used small synthetic text; real-world photos/screenshots
      may behave differently)
- [ ] `describe_image` / `analyze_screen` — needs a vision-capable model
      (Gemini/GPT-4o-class); confirm image upload actually round-trips
      through your configured provider correctly

## 5. Spotify plugin

- [ ] Full OAuth flow: first command triggers a real browser consent
      screen, confirm the token caches and you're not re-prompted next time
- [ ] Playback control actually works with a real active device

## 6. The installer itself

None of this has ever executed — `ISCC.exe` and PowerShell are both
Windows-only tools unavailable in this sandbox. See
`docs/architecture/INSTALLER_GUIDE.md` for the full build steps; this
is the acceptance checklist for the result:

- [ ] `scripts/build_installer.ps1` runs to completion and produces
      `installer/output/FridayOS-Setup-X.Y.Z.exe`
- [ ] Running that installer on a **different, clean** Windows machine
      (or a fresh VM) actually installs and launches
- [ ] "Start at login" checkbox during install creates a real Startup-folder
      shortcut that survives a reboot
- [ ] Uninstalling removes the app but leaves `%LOCALAPPDATA%\FridayOS`
      (your data) intact — reinstalling should pick your data back up
- [ ] Expect a SmartScreen "unknown publisher" warning (installer is
      unsigned, by design — see `INSTALLER_GUIDE.md`'s code-signing section)

## 7. GitHub integration

- [ ] `create_github_repo` with a real `GITHUB_TOKEN` — the request/response
      handling is tested against mocked responses; a real API call has
      never actually round-tripped in this build

## 8. The subjective part

Everything above is "does it work." This one is "is it good":

- [ ] Have a real, extended conversation — not single commands. Does the
      short-term memory (last 20 turns) actually make follow-up
      questions feel coherent?
- [ ] Ask it to do something moderately complex requiring 2-3 chained
      tool calls. Does the multi-round tool-calling loop feel responsive,
      or does it stall?
- [ ] Does the personality (from `app/brain/prompts.py`) actually read
      as "warm, capable, concise" in practice, or does it need tuning?
      This is a prompt-engineering judgment call no test suite can make
      for you.
