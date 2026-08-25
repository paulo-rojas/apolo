import os
import subprocess
from pathlib import Path
from typing import Optional

from core.config import get_str


class WhisperCppNotConfigured(RuntimeError):
    pass


def whisper_model_name() -> str:
    model = (get_str("whisper.model", "small", env="APOLO_WHISPER_MODEL") or "small").lower()
    allowed = {"tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"}
    if model not in allowed:
        raise ValueError(
            "APOLO_WHISPER_MODEL must be one of: tiny, base, small, medium, "
            "large-v2, large-v3, large-v3-turbo"
        )
    return model


def whisper_model_path() -> Path:
    explicit = get_str("whisper.model_path", env="APOLO_WHISPER_MODEL_PATH")
    if explicit:
        return Path(os.path.expandvars(explicit))
    return Path("models") / f"ggml-{whisper_model_name()}.bin"


def whisper_prompt() -> Optional[str]:
    return get_str("whisper.prompt", env="APOLO_WHISPER_PROMPT")


class WhisperCppTranscriber:
    def __init__(self, executable: Optional[str] = None, model_path: Optional[str] = None):
        configured_executable = get_str("whisper.executable", env="APOLO_WHISPER_CPP_EXE")
        self.executable = Path(os.path.expandvars(executable or configured_executable or ""))
        self.model_path = Path(os.path.expandvars(model_path)) if model_path else whisper_model_path()

    def transcribe_file(self, wav_path: str, language: str = "es") -> str:
        if not self.executable.is_file():
            raise WhisperCppNotConfigured("APOLO_WHISPER_CPP_EXE must point to whisper.cpp executable")
        if not self.model_path.is_file():
            raise WhisperCppNotConfigured(f"whisper.cpp model not found: {self.model_path}")

        cmd = [
            str(self.executable),
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "-l",
            language,
            "-nt",
        ]
        prompt = whisper_prompt()
        if prompt:
            cmd.extend(["--prompt", prompt])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return _extract_transcript(result.stdout)


def _extract_transcript(output: str) -> str:
    lines = []
    for line in output.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("[") and "]" in clean:
            clean = clean.split("]", 1)[1].strip()
        lines.append(clean)
    return " ".join(lines).strip()
