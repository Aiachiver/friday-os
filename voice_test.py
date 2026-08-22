import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

print("Loading Whisper...")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Whisper loaded.")

print("Speak now...")

audio = sd.rec(
    int(5 * 16000),
    samplerate=16000,
    channels=1,
    dtype="float32",
)
sd.wait()

audio = audio.flatten()

segments, info = model.transcribe(
    audio,
    language="en",
    vad_filter=True,
)

text = " ".join(segment.text.strip() for segment in segments).strip()

print("You said:", text)

if "friday" in text.lower():
    print("✅ FRIDAY WAKE WORD DETECTED")
else:
    print("❌ Friday not detected")