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
    parser.add_argument("--loop", action="store_true", help="Keep the recorder alive and emit one JSON result per utterance.")
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
            **_recorder_kwargs(
                args.language,
                lambda chunk: _append_audio_chunk(chunks, chunk),
                lambda text: _print_partial(text),
            )
        )
        _print_result({"event": "ready"})
        while True:
            chunks.clear()
            utterance_started_at = time.monotonic()
            text = str(recorder.text() or "").strip()
            duration_ms = _write_audio(Path(args.output), chunks)
            _print_result(
                {
                    "ok": True,
                    "text": text,
                    "duration_ms": duration_ms,
                    "elapsed_ms": int((time.monotonic() - utterance_started_at) * 1000),
                    "backend": _backend_label(),
                    "audio": str(Path(args.output)),
                }
            )
            if not args.loop:
                break
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


def _recorder_kwargs(language: str, on_chunk, on_partial) -> dict[str, Any]:
    vad_silence_ms = get_int("voice.vad.silence_ms", 700, minimum=100)
    pre_roll_ms = get_int("voice.vad.pre_roll_ms", 240, minimum=0)
    min_duration_ms = get_int("voice.min_duration_ms", 250, minimum=0)
    silero_backend = get_str("realtime_stt.silero_backend", "auto", env="APOLO_REALTIMESTT_SILERO_BACKEND") or "auto"
    dictation = get_bool("voice.dictation", False, env="APOLO_VOICE_DICTATION")
    return {
        "transcription_engine": get_str("realtime_stt.engine", "faster_whisper") or "faster_whisper",
        "model": get_str("realtime_stt.model", get_str("whisper.model", "small") or "small", env="APOLO_REALTIMESTT_MODEL"),
        "language": language,
        "device": get_str("realtime_stt.device", get_str("whisper.device", "cuda") or "cuda", env="APOLO_REALTIMESTT_DEVICE"),
        "compute_type": get_str(
            "realtime_stt.compute_type",
            get_str("whisper.compute_type", "float16") or "float16",
            env="APOLO_REALTIMESTT_COMPUTE_TYPE",
        ),
        "beam_size": get_int("realtime_stt.beam_size", get_int("whisper.beam_size", 3, minimum=1), minimum=1),
        "initial_prompt": None if dictation else get_str("realtime_stt.prompt", get_str("whisper.prompt", None)),
        "input_device_index": _input_device_index(),
        "sample_rate": get_int("realtime_stt.sample_rate", get_int("voice.vad.sample_rate", 16000, minimum=8000), minimum=8000),
        "post_speech_silence_duration": get_float("realtime_stt.post_speech_silence_duration", vad_silence_ms / 1000.0, minimum=0.1),
        "pre_recording_buffer_duration": get_float("realtime_stt.pre_recording_buffer_duration", max(pre_roll_ms / 1000.0, 0.4), minimum=0.0),
        "min_length_of_recording": get_float("realtime_stt.min_length_of_recording", max(min_duration_ms / 1000.0, 0.35), minimum=0.0),
        "min_gap_between_recordings": get_float("realtime_stt.min_gap_between_recordings", 0.2, minimum=0.0),
        "webrtc_sensitivity": get_int("realtime_stt.webrtc_sensitivity", 2, minimum=0),
        "silero_sensitivity": get_float("realtime_stt.silero_sensitivity", 0.45, minimum=0.0),
        "silero_deactivity_detection": get_bool("realtime_stt.silero_deactivity_detection", True),
        "deactivity_silence_confirmation_duration": get_float(
            "realtime_stt.deactivity_silence_confirmation_duration",
            0.16,
            minimum=0.0,
        ),
        "silero_use_onnx": None
        if str(silero_backend).strip().lower() == "auto"
        else _optional_bool("realtime_stt.silero_use_onnx", "APOLO_REALTIMESTT_SILERO_USE_ONNX"),
        "silero_backend": silero_backend,
        "silero_onnx_model_path": get_str(
            "realtime_stt.silero_onnx_model_path",
            None,
            env="APOLO_REALTIMESTT_SILERO_ONNX_MODEL_PATH",
        ),
        "faster_whisper_vad_filter": get_bool("realtime_stt.faster_whisper_vad_filter", False),
        "enable_realtime_transcription": True,
        "realtime_model_type": get_str("realtime_stt.realtime_model_type", "tiny") or "tiny",
        "realtime_processing_pause": get_float("realtime_stt.realtime_processing_pause", 0.1, minimum=0.0),
        "early_transcription_on_silence": get_float("realtime_stt.early_transcription_on_silence", 0.0, minimum=0.0),
        "on_realtime_transcription_update": on_partial,
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


def _optional_bool(path: str, env: str) -> bool | None:
    raw = get_str(path, None, env=env)
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in {"", "default", "auto", "none", "null"}:
        return None
    return value in {"1", "true", "yes", "y", "on"}


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
    model = get_str("realtime_stt.model", get_str("whisper.model", "small") or "small", env="APOLO_REALTIMESTT_MODEL")
    device = get_str("realtime_stt.device", get_str("whisper.device", "cuda") or "cuda", env="APOLO_REALTIMESTT_DEVICE")
    compute_type = get_str(
        "realtime_stt.compute_type",
        get_str("whisper.compute_type", "float16") or "float16",
        env="APOLO_REALTIMESTT_COMPUTE_TYPE",
    )
    return f"realtime-stt {model} {device}/{compute_type}"


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False), flush=True)


def _print_partial(text: str) -> None:
    text = str(text or "").strip()
    if text:
        _print_result({"event": "partial", "text": text})


if __name__ == "__main__":
    raise SystemExit(main())
