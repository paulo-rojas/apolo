from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import wave
from pathlib import Path
from typing import Any

from core.config import get_bool, get_float, get_int, get_str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture one utterance with RealtimeSTT.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", default=get_str("whisper.language", "es") or "es")
    args = parser.parse_args(argv)

    chunks: list[bytes] = []
    recorder = None
    started_at = time.monotonic()
    try:
        try:
            from RealtimeSTT import AudioToTextRecorder
        except Exception as error:
            _print_result({"ok": False, "error": f"RealtimeSTT unavailable: {error}"})
            return 2

        recorder = AudioToTextRecorder(
            **_recorder_kwargs(args.language, lambda chunk: _append_audio_chunk(chunks, chunk))
        )
        text = str(recorder.text() or "").strip()
        duration_ms = _write_audio(Path(args.output), chunks)
        _print_result(
            {
                "ok": True,
                "text": text,
                "duration_ms": duration_ms,
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                "backend": _backend_label(),
                "audio": str(Path(args.output)),
            }
        )
        return 0
    except Exception as error:
        _print_result({"ok": False, "error": str(error), "backend": _backend_label()})
        return 1
    finally:
        if recorder is not None:
            try:
                recorder.shutdown()
            except Exception:
                pass


def _recorder_kwargs(language: str, on_chunk) -> dict[str, Any]:
    vad_silence_ms = get_int("voice.vad.silence_ms", 700, minimum=100)
    pre_roll_ms = get_int("voice.vad.pre_roll_ms", 240, minimum=0)
    min_duration_ms = get_int("voice.min_duration_ms", 250, minimum=0)
    return {
        "transcription_engine": get_str("realtime_stt.engine", "faster_whisper") or "faster_whisper",
        "model": get_str("realtime_stt.model", get_str("whisper.model", "small") or "small"),
        "language": language,
        "device": get_str("realtime_stt.device", get_str("whisper.device", "cuda") or "cuda"),
        "compute_type": get_str("realtime_stt.compute_type", get_str("whisper.compute_type", "float16") or "float16"),
        "beam_size": get_int("realtime_stt.beam_size", get_int("whisper.beam_size", 3, minimum=1), minimum=1),
        "initial_prompt": get_str("realtime_stt.prompt", get_str("whisper.prompt", None)),
        "input_device_index": _input_device_index(),
        "sample_rate": get_int("realtime_stt.sample_rate", get_int("voice.vad.sample_rate", 16000, minimum=8000), minimum=8000),
        "post_speech_silence_duration": get_float("realtime_stt.post_speech_silence_duration", vad_silence_ms / 1000.0, minimum=0.1),
        "pre_recording_buffer_duration": get_float("realtime_stt.pre_recording_buffer_duration", max(pre_roll_ms / 1000.0, 0.4), minimum=0.0),
        "min_length_of_recording": get_float("realtime_stt.min_length_of_recording", max(min_duration_ms / 1000.0, 0.35), minimum=0.0),
        "webrtc_sensitivity": get_int("realtime_stt.webrtc_sensitivity", 2, minimum=0),
        "silero_sensitivity": get_float("realtime_stt.silero_sensitivity", 0.45, minimum=0.0),
        "silero_use_onnx": get_bool("realtime_stt.silero_use_onnx", True),
        "faster_whisper_vad_filter": get_bool("realtime_stt.faster_whisper_vad_filter", False),
        "ensure_sentence_starting_uppercase": False,
        "ensure_sentence_ends_with_period": False,
        "spinner": False,
        "no_log_file": True,
        "level": logging.WARNING,
        "debug_mode": get_bool("realtime_stt.debug", False),
        "print_transcription_time": False,
        "on_recorded_chunk": on_chunk,
    }


def _input_device_index() -> int | None:
    raw = get_str("realtime_stt.input_device_index", get_str("audio.input_device", None))
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in {"", "default", "none", "null"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _write_audio(path: Path, chunks: list[bytes]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = b"".join(chunk for chunk in chunks if chunk)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(get_int("realtime_stt.sample_rate", get_int("voice.vad.sample_rate", 16000, minimum=8000), minimum=8000))
        wav.writeframes(audio)
    sample_rate = get_int("realtime_stt.sample_rate", get_int("voice.vad.sample_rate", 16000, minimum=8000), minimum=8000)
    return int(len(audio) / 2 * 1000 / sample_rate) if sample_rate and audio else 0


def _append_audio_chunk(chunks: list[bytes], chunk) -> None:
    if chunk is None:
        return
    if isinstance(chunk, bytes):
        data = chunk
    elif isinstance(chunk, bytearray):
        data = bytes(chunk)
    elif isinstance(chunk, memoryview):
        data = chunk.tobytes()
    elif hasattr(chunk, "tobytes"):
        data = chunk.tobytes()
    else:
        data = bytes(chunk)
    if data:
        chunks.append(data)


def _backend_label() -> str:
    model = get_str("realtime_stt.model", get_str("whisper.model", "small") or "small")
    device = get_str("realtime_stt.device", get_str("whisper.device", "cuda") or "cuda")
    compute_type = get_str("realtime_stt.compute_type", get_str("whisper.compute_type", "float16") or "float16")
    return f"realtime-stt {model} {device}/{compute_type}"


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
