# Setting up Vision / OCR

Two separate capabilities, two separate setup needs:

## 1. OCR (exact text extraction) — requires installing Tesseract

`pytesseract` is just a thin Python wrapper — it calls out to the actual
Tesseract OCR engine, which is a native binary you install separately.

1. Download the Windows installer from
   https://github.com/UB-Mannheim/tesseract/wiki (this is the standard
   community-maintained Windows build).
2. Run it. Note the install path — default is
   `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. Either:
   - Add that folder to your Windows PATH during/after install, **or**
   - Leave it off PATH and instead set it explicitly in `.env`:
     ```
     TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
     ```
4. Verify from PowerShell:
   ```powershell
   tesseract --version
   ```
   If that command isn't found but you set `TESSERACT_CMD` in `.env`,
   that's fine — FRIDAY reads the explicit path directly and doesn't
   need it on PATH.

Without this, `ocr_image`, `analyze_screen` (mode="ocr"), and
`extract_pdf_text` (for scanned pages) will return a clear
"Tesseract OCR engine is not installed" error rather than crashing —
everything else in FRIDAY keeps working.

## 2. AI vision (image description, object recognition, "what's on my screen")

No separate setup — this reuses whichever AI provider you already
configured in `docs/architecture/AI_BRAIN_SETUP.md`, **as long as the
model you're using supports vision**. Not all models do:

| Provider | Vision-capable model |
|---|---|
| Gemini | `gemini-2.0-flash` (already the default) |
| OpenAI | `gpt-4o-mini` (already the default) |
| Groq | vision-capable Llama models only — check Groq's current model list; the default `llama-3.3-70b-versatile` is text-only |
| Ollama | a vision-tagged local model, e.g. `llama3.2-vision` — the default `llama3.2` is text-only |

If your active (first-priority) provider's model doesn't support
vision, `describe_image`/`analyze_screen(mode="describe")` will fail on
it and automatically fail over to the next configured provider — same
behavior as any other provider outage. If you want vision to reliably
work, put a vision-capable provider/model first in
`brain.provider_priority`, or override just that use case by setting a
vision-capable model for your primary provider in
`config/settings.yaml`:

```yaml
brain:
  models:
    gemini: "gemini-2.0-flash"   # already vision-capable by default
```

## Testing it once set up

```
"Friday, describe what's on my screen"
"Friday, read the text in C:\Users\Suraj\Desktop\screenshot.png"
"Friday, extract the text from my_document.pdf"
```
