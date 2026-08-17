# Setting up the Spotify plugin

Spotify's API has no keyless tier for playback control, so this needs a
free Spotify Developer app (one-time, ~2 minutes) plus your own regular
Spotify account (Premium is required for playback control — Spotify's
API restriction, not FRIDAY's).

## Steps

1. Go to https://developer.spotify.com/dashboard and log in with your
   Spotify account.
2. Click **Create app**. Fill in any name/description.
3. For **Redirect URI**, enter exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   (must match `SPOTIFY_REDIRECT_URI` in `.env` exactly — the default
   already matches, only change both together if you do).
4. Save. Open the app you just created and copy the **Client ID** and
   **Client Secret**.
5. In `.env`:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   SPOTIFY_CLIENT_SECRET=your_client_secret_here
   SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
   ```
6. Start FRIDAY and try a Spotify command (e.g. *"Friday, play some
   music"*). The **first** call opens a browser window asking you to
   log in and approve access — this is normal OAuth consent, one-time.
   After approving, a token is cached at
   `data/spotify_token_cache.json` (gitignored) and you won't see the
   browser prompt again unless the token expires and can't silently
   refresh.

## Requirements

- **Spotify Premium** — required by Spotify's API for playback control
  (play/pause/skip/search-and-play). A free account can't control
  playback via any third-party app, this isn't a FRIDAY limitation.
- **An active device** — Spotify open somewhere (desktop app, phone,
  web player), even paused. If FRIDAY says "No active Spotify device
  found," open Spotify anywhere first.

## Without this setup

FRIDAY still starts normally — the Spotify plugin loads, but each tool
call returns a clear "Spotify isn't configured" message instead of
failing silently or crashing anything else.
