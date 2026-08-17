# Setting up the "Friday" wake word (one-time)

Porcupine's free built-in keyword list doesn't include "Friday" (it has
Jarvis, Computer, Picovoice, etc., but not this one), so a custom keyword
has to be trained once. This takes about 2 minutes and is free.

## Steps

1. Go to https://console.picovoice.ai/ and create a free account.
2. Copy your **AccessKey** from the console dashboard.
3. Open `.env` in the project root and set:
   ```
   PICOVOICE_ACCESS_KEY=your_access_key_here
   ```
4. In the console, go to **Porcupine → Create Wake Word**.
5. Type `Friday`, choose **Windows** as the target platform, and generate it.
6. Download the resulting `.ppn` file.
7. Place it at `resources/wake_word/friday_windows.ppn` in the project
   (create the `resources/wake_word/` folder if it doesn't exist), or
   anywhere else — just point `.env` at wherever you put it:
   ```
   FRIDAY_KEYWORD_PATH=resources/wake_word/friday_windows.ppn
   ```
8. Run `python -m app.main`. You should see in the log:
   ```
   Wake word engine: Porcupine (keyword_path=resources/wake_word/friday_windows.ppn)
   ...
   FRIDAY OS ready. Say "Friday" to begin.
   ```
   and the dashboard's status card will show "Listening for wake word"
   instead of "Voice input disabled."

Until you complete this, FRIDAY runs in **text-only mode** automatically
— you can still talk to it via the dashboard's text box, and it will
still speak replies out loud. Nothing crashes; the app just tells you
exactly what's missing in the log and keeps running.

## Choosing your faster-whisper model size

`config/settings.yaml` → `voice.stt_model_size` controls transcription
speed vs. accuracy. Rough guide for a single short voice command (not
long-form dictation):

| Hardware | Recommended `stt_model_size` | `stt_device` |
|---|---|---|
| NVIDIA GPU (even a modest one) | `small` or `medium` | `cuda` |
| Recent CPU (i5/i7/Ryzen 5/7, last ~5 years) | `base` | `cpu` |
| Older/modest CPU or laptop | `tiny` | `cpu` |

Start with `base` on CPU — it's a good default and usually transcribes a
short command in well under a second. Move up to `small`/`medium` only if
you have a GPU and want higher accuracy on longer or more complex speech;
move down to `tiny` if `base` feels laggy on your machine.

The first time each model size runs, faster-whisper downloads the model
weights from Hugging Face (a few hundred MB) and caches them locally —
that first run will pause for the download; every run after is instant.

## Verifying your microphone

If FRIDAY starts in voice mode but never seems to hear you, list your
input devices and confirm the right one is selected:

```python
from app.voice.audio_io import list_input_devices
for d in list_input_devices():
    print(d)
```

Then set the device index explicitly by passing `input_device=<index>` to
`ConversationManager` in `app/main.py` if the OS default mic isn't the
one you want to use.
