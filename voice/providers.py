from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SpeechToTextProvider(Protocol):
    @property
    def backend_label(self) -> str:
        ...

    def transcribe_file(self, wav_path: str, language: str = "es") -> str:
        ...


class VADProvider(Protocol):
    def is_voice_frame(self, rms: float) -> bool:
        ...


class IntentResolver(Protocol):
    def interpret(self, raw_text: str, normalized_text: str, context: dict) -> object:
        ...


class ReasoningProvider(Protocol):
    def interpret(self, raw_text: str, normalized_text: str, context: dict) -> object:
        ...


class MemoryProvider(Protocol):
    def read_context(self) -> dict:
        ...

    def remember(self, text: str, source: str = "voice") -> dict:
        ...


class MusicProvider(Protocol):
    def play(self, query: str, artist: str = "", album: str = "") -> dict:
        ...


def create_speech_to_text_provider(name: str) -> SpeechToTextProvider:
    backend = (name or "faster-whisper").strip().lower()
    if backend == "faster-whisper":
        from .faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber()
    if backend in {"whisper-cpp", "whisper.cpp"}:
        from .whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber()
    raise ValueError(f"unsupported speech-to-text provider: {name}")


def wav_path_for_voice_command(temp_dir: str | Path) -> Path:
    return Path(temp_dir) / "apolo_voice_command.wav"
