# Setting up the AI brain (at least one provider)

FRIDAY tries providers in the order listed in `config/settings.yaml` →
`brain.provider_priority` (default: gemini, groq, openrouter, together,
openai, ollama), skipping any provider with no API key configured, and
automatically failing over to the next one if a call fails mid-conversation.

You only need **one** working provider to get started. Recommended for a
free, fast option:

## Option A: Groq (free tier, very fast, recommended to start)

1. Go to https://console.groq.com/keys and create a free account.
2. Create an API key.
3. In `.env`:
   ```
   GROQ_API_KEY=your_key_here
   ```

## Option B: Gemini (free tier)

1. Go to https://aistudio.google.com/apikey and generate a key.
2. In `.env`:
   ```
   GEMINI_API_KEY=your_key_here
   ```

## Option C: Ollama (fully offline, no API key, needs a capable machine)

1. Install Ollama from https://ollama.com/download (Windows installer).
2. Pull a model that supports tool-calling well, e.g.:
   ```powershell
   ollama pull llama3.2
   ```
3. Leave `OLLAMA_HOST` in `.env` at its default
   (`http://localhost:11434`) — no API key needed.
4. Make sure Ollama is running (`ollama serve`, or it may already be
   running as a background service after install) before starting FRIDAY.

Note: local models are more likely to ignore or mishandle tool-calling
than Gemini/Groq/OpenAI-class models. If FRIDAY's automation commands
("open notepad", "delete this file") aren't triggering tools reliably on
Ollama, that's a model capability limit, not a bug in FRIDAY — try a
larger or more recent model, or fall back to a cloud provider for
automation-heavy use.

## Verifying it worked

Start FRIDAY (`python -m app.main`) and check the log for:
```
AI brain provider registered: groq (model=llama-3.3-70b-versatile)
Active AI providers (priority order): ['groq']
```

If you see `Active AI providers (priority order): none`, no provider was
configured — FRIDAY still runs (fast-path commands like "what time is
it" keep working), but anything needing actual reasoning will get a
spoken "I'm having trouble reaching my reasoning engine" instead of a
real answer, and log `No AI brain providers are configured`.

## Choosing models per provider

Override the default model for any provider in `config/settings.yaml`:

```yaml
brain:
  provider_priority: [groq, gemini, ollama]
  models:
    groq: "llama-3.3-70b-versatile"
    gemini: "gemini-2.0-flash"
    ollama: "llama3.2"
```
