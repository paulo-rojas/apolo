from __future__ import annotations

import threading
import os
import tempfile
from pathlib import Path
from typing import Callable

from core.config import get_float, get_str
from .audio_devices import selected_device


class KokoroNotConfigured(RuntimeError):
    pass


class KokoroSpeaker:
    """Lazy local Kokoro-82M speaker using the ONNX runtime backend."""

    def __init__(self, on_level: Callable[[float], None] | None = None):
        root = Path(__file__).resolve().parents[1]
        self.model_path = Path(get_str("kokoro.model_path", str(root / "models" / "kokoro" / "kokoro-v1.0.onnx")))
        self.voices_path = Path(get_str("kokoro.voices_path", str(root / "models" / "kokoro" / "voices-v1.0.bin")))
        self.voice = get_str("kokoro.voice", "em_alex") or "em_alex"
        self.speed = get_float("kokoro.speed", 1.0, minimum=0.5)
        self._on_level = on_level or (lambda _level: None)
        self._engine = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._engine is not None:
            return self._engine
        if not self.model_path.is_file() or not self.voices_path.is_file():
            raise KokoroNotConfigured(f"Kokoro model files not found in {self.model_path.parent}")
        from kokoro_onnx import Kokoro

        self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        return self._engine

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        with self._lock:
            engine = self._ensure()
            samples, sample_rate = engine.create(text.strip(), voice=self.voice, speed=self.speed, lang="es")
            try:
                self._on_level(0.65)
                output_device = selected_device("output")
                if output_device is not None:
                    import sounddevice as sd

                    sd.play(samples, sample_rate, device=output_device)
                    sd.wait()
                elif os.name == "nt":
                    import soundfile as sf
                    import winsound

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
                        audio_path = audio_file.name
                    try:
                        sf.write(audio_path, samples, sample_rate, subtype="PCM_16")
                        winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_SYNC)
                    finally:
                        Path(audio_path).unlink(missing_ok=True)
                else:
                    import sounddevice as sd

                    sd.play(samples, sample_rate)
                    sd.wait()
            finally:
                self._on_level(0.0)

    def stop(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        finally:
            self._on_level(0.0)
