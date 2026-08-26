from __future__ import annotations

import threading
from typing import Callable

from core.config import get_float, get_int
from voice.audio_devices import selected_device


class AudioMonitor:
    """Small background microphone level adapter; unavailable audio is non-fatal."""

    def __init__(self, on_level: Callable[[float], None], sample_rate: int = 16000):
        self._on_level = on_level
        self._sample_rate = get_int("voice.vad.sample_rate", sample_rate, minimum=8000)
        self._sensitivity = get_float("voice.monitor.sensitivity", 30.0, minimum=1.0)
        self._noise_floor = get_float("voice.monitor.noise_floor", 0.004, minimum=0.0)
        self._smoothed = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="apolo-audio-level", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception:
            return

        def on_audio(indata, _frames, _time, _status):
            if self._stop.is_set():
                raise sd.CallbackStop
            samples = indata.astype("float32")
            rms = float(np.sqrt(np.mean(samples * samples)))
            raw_level = max(0.0, rms - self._noise_floor) * self._sensitivity
            level = min(1.0, raw_level)
            smoothing = 0.55 if level > self._smoothed else 0.82
            self._smoothed = self._smoothed * smoothing + level * (1.0 - smoothing)
            self._on_level(min(1.0, self._smoothed))

        try:
            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=512,
                device=selected_device("input"),
                callback=on_audio,
            ):
                self._stop.wait()
        except Exception:
            return
