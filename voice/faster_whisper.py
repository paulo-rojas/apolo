from __future__ import annotations

import os
import shutil
import site
from pathlib import Path

from core.config import get_bool, get_float, get_int, get_str

_DLL_DIRECTORY_HANDLES = []


class FasterWhisperNotConfigured(RuntimeError):
    pass


class FasterWhisperTranscriber:
    """Lazy faster-whisper transcriber with optional CUDA acceleration."""

    def __init__(self):
        self.model_name = get_str("whisper.model", "small") or "small"
        self.device = get_str("whisper.device", "cuda") or "cuda"
        self.compute_type = get_str("whisper.compute_type", "float16") or "float16"
        self.fallback_device = get_str("whisper.fallback_device", "cpu") or "cpu"
        self.fallback_compute_type = get_str("whisper.fallback_compute_type", "int8") or "int8"
        self.fallback_model_name = get_str("whisper.fallback_model", "small") or self.model_name
        self.beam_size = get_int("whisper.beam_size", 1, minimum=1)
        dictation = get_bool("voice.dictation", False, env="APOLO_VOICE_DICTATION")
        self.prompt = None if dictation else get_str("whisper.prompt", None)
        self.hotwords = None if dictation else get_str("whisper.hotwords", None)
        self.max_new_tokens = get_int("whisper.max_new_tokens", 32, minimum=4)
        self.patience = get_float("whisper.patience", 1.0, minimum=0.0)
        self.cpu_threads = get_int("whisper.cpu_threads", get_int("whisper.threads", 4, minimum=1), minimum=1)
        self._model = None
        self._active_model_name = self.model_name
        self._active_device = self.device
        self._active_compute_type = self.compute_type
        if self.device == "cuda" and _cuda_runtime_missing():
            print(
                f"voice listener: CUDA runtime missing; using {self.fallback_model_name} {self.fallback_device}/{self.fallback_compute_type}",
                flush=True,
            )
            self._active_model_name = self.fallback_model_name
            self._active_device = self.fallback_device
            self._active_compute_type = self.fallback_compute_type

    @property
    def backend_label(self) -> str:
        return f"{self._active_model_name} {self._active_device}/{self._active_compute_type}"

    def _ensure_model(
        self,
        device: str | None = None,
        compute_type: str | None = None,
        model_name: str | None = None,
    ):
        if self._model is not None:
            return self._model
        _add_cuda_dll_directories()
        device = device or self._active_device
        compute_type = compute_type or self._active_compute_type
        model_name = model_name or self._active_model_name
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise FasterWhisperNotConfigured("faster-whisper no está instalado") from error
        try:
            self._model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=self.cpu_threads,
            )
            self._active_model_name = model_name
            self._active_device = device
            self._active_compute_type = compute_type
        except Exception as error:
            raise FasterWhisperNotConfigured(f"No se pudo iniciar faster-whisper ({model_name} {device}/{compute_type}): {error}") from error
        return self._model

    def transcribe_file(self, wav_path: str, language: str = "es") -> str:
        try:
            return self._transcribe_text(wav_path, language)
        except Exception as error:
            if not _is_cuda_runtime_error(error) or self._active_device == self.fallback_device:
                raise
            print(
                f"voice listener: CUDA unavailable ({error}); falling back to {self.fallback_model_name} {self.fallback_device}/{self.fallback_compute_type}",
                flush=True,
            )
            self._model = None
            self._ensure_model(self.fallback_device, self.fallback_compute_type, self.fallback_model_name)
            return self._transcribe_text(wav_path, language)

    def _transcribe_text(self, wav_path: str, language: str) -> str:
        segments, _ = self._transcribe(wav_path, language)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    def _transcribe(self, wav_path: str, language: str):
        return self._ensure_model().transcribe(
            str(Path(wav_path)),
            language=language,
            beam_size=self.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=self.prompt,
            hotwords=self.hotwords,
            max_new_tokens=self.max_new_tokens,
            patience=self.patience,
            best_of=1,
            repetition_penalty=1.08,
            no_repeat_ngram_size=3,
            temperature=0.0,
        )


def _is_cuda_runtime_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "cublas",
            "cudnn",
            "cuda",
            "cublas64",
            "cudnn64",
            "library",
        )
    )


def _cuda_runtime_missing() -> bool:
    if os.name != "nt":
        return False
    return _find_cuda_dll("cublas64_12.dll") is None


def _add_cuda_dll_directories() -> None:
    if os.name != "nt":
        return
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return
    existing_path = os.environ.get("PATH", "")
    path_parts = [part for part in existing_path.split(os.pathsep) if part]
    for directory in _cuda_dll_directories():
        if directory.exists():
            directory_text = str(directory)
            if directory_text not in path_parts:
                path_parts.insert(0, directory_text)
            try:
                handle = add_dll_directory(str(directory))
                _DLL_DIRECTORY_HANDLES.append(handle)
            except OSError:
                pass
    os.environ["PATH"] = os.pathsep.join(path_parts)


def _find_cuda_dll(name: str) -> Path | None:
    if shutil.which(name):
        return Path(shutil.which(name) or name)
    for directory in _cuda_dll_directories():
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _cuda_dll_directories() -> list[Path]:
    roots = [Path(p) for p in site.getsitepackages()]
    paths: list[Path] = []
    for root in roots:
        paths.extend(
            [
                root / "nvidia" / "cublas" / "bin",
                root / "nvidia" / "cudnn" / "bin",
                root / "nvidia" / "cuda_runtime" / "bin",
                root / "nvidia" / "cuda_nvrtc" / "bin",
            ]
        )
    return paths
