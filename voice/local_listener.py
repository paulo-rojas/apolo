import argparse
import json
import os
import wave
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from core.audio_gate import listener_is_muted
from core.config import get_float, get_int, get_str
from core.listener_control import listener_is_resting, shutdown_requested
from .microphone import MicrophoneNotAvailable, record_utterance_to_wav
from .providers import create_speech_to_text_provider, wav_path_for_voice_command
from .vad import VadConfig
from .audio_devices import selected_device
from .wake_word import strip_wake_word


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Record one voice command and send it to Apolo.")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--language", default=get_str("whisper.language", "es"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--silence-ms", type=int, default=None)
    parser.add_argument("--block-ms", type=int, default=None)
    parser.add_argument("--mode", choices=("open", "push_to_talk"), default=None)
    parser.add_argument("--hotkey", default=None)
    parser.add_argument("--transcriber", choices=("faster-whisper", "whisper-cpp"), default=None)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    wav_path = wav_path_for_voice_command(tempfile.gettempdir())
    vad_config = VadConfig(
        sample_rate=get_int("voice.vad.sample_rate", 16000),
        threshold=args.threshold if args.threshold is not None else get_float("voice.vad.threshold", 0.015, env="APOLO_VOICE_VAD_THRESHOLD", minimum=0.0),
        block_ms=args.block_ms if args.block_ms is not None else get_int("voice.vad.block_ms", 40, env="APOLO_VOICE_VAD_BLOCK_MS", minimum=10),
        silence_ms=args.silence_ms if args.silence_ms is not None else get_int("voice.vad.silence_ms", 700, env="APOLO_VOICE_VAD_SILENCE_MS", minimum=100),
        max_utterance_ms=get_int("voice.vad.max_utterance_ms", 8000, minimum=500),
        pre_roll_ms=get_int("voice.vad.pre_roll_ms", 240, env="APOLO_VOICE_VAD_PRE_ROLL_MS", minimum=0),
    )
    mode = args.mode or get_str("voice.mode", "open")
    transcriber_name = args.transcriber or get_str("whisper.backend", "faster-whisper")
    transcribe_timeout = get_int("whisper.transcribe_timeout_seconds", 12, env="APOLO_WHISPER_TRANSCRIBE_TIMEOUT_SECONDS", minimum=2)
    transcriber = create_speech_to_text_provider(transcriber_name)
    print(f"voice listener: starting mode={mode} transcriber={transcriber_name} block_ms={vad_config.block_ms} transcribe_timeout={transcribe_timeout}s", flush=True)
    if args.diagnose:
        _diagnose_audio(transcriber_name, transcriber)
        return
    if transcriber_name == "faster-whisper" and get_str("whisper.preload", "true").lower() in {"1", "true", "yes", "on"}:
        print("voice listener: preloading faster-whisper model", flush=True)
        transcriber._ensure_model()
        print(f"voice listener: faster-whisper ready ({transcriber.backend_label})", flush=True)
    hotkey = args.hotkey or get_str("voice.hotkey", "ctrl+space")
    keyboard = None
    if mode == "push_to_talk":
        try:
            import keyboard as keyboard_module
            keyboard = keyboard_module
        except Exception as error:
            raise RuntimeError("El modo push_to_talk requiere el paquete keyboard") from error
    resting_announced = False
    while True:
        try:
            if shutdown_requested():
                print("voice listener: shutdown requested", flush=True)
                return
            if listener_is_resting():
                if not resting_announced:
                    print("voice listener: resting", flush=True)
                    resting_announced = True
                threading.Event().wait(1)
                continue
            resting_announced = False
            if listener_is_muted():
                print("voice listener: muted while Apolo speaks", flush=True)
                threading.Event().wait(0.25)
                continue
            stop_when = None
            start_immediately = False
            if keyboard is not None:
                print(f"voice listener: waiting for {hotkey}", flush=True)
                keyboard.wait(hotkey)
                print("voice listener: recording", flush=True)
                stop_when = lambda: _hotkey_is_pressed(keyboard, hotkey)
                start_immediately = True
            else:
                print("voice listener: listening", flush=True)
            record_utterance_to_wav(
                str(wav_path),
                sample_rate=vad_config.sample_rate,
                vad_config=vad_config,
                stop_when=stop_when,
                start_immediately=start_immediately,
            )
            if listener_is_muted():
                print("voice listener: discarded self-audio", flush=True)
                continue
            duration_ms = _wav_duration_ms(wav_path)
            print(f"voice listener: transcribing {duration_ms}ms", flush=True)
            started_at = time.monotonic()
            transcript = _transcribe_with_timeout(transcriber, wav_path, args.language, transcribe_timeout)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            backend_label = getattr(transcriber, "backend_label", transcriber_name)
            print(f"voice listener: heard {transcript!r} in {elapsed_ms}ms using {backend_label}", flush=True)
            if _looks_like_prompt_echo(transcript):
                print("voice listener: discarded prompt echo", flush=True)
                continue
            if _wake_detected(transcript):
                print("voice listener: wake detected", flush=True)
            payload = json.dumps({"text": transcript, "duration_ms": duration_ms, "dry_run": args.dry_run}).encode("utf-8")
            request = urllib.request.Request(
                f"{args.server.rstrip('/')}/voice-command",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                print(response.read().decode("utf-8"))
        except MicrophoneNotAvailable as error:
            if not args.continuous:
                raise
            print(f"voice listener: {error}", file=sys.stderr)
            threading.Event().wait(1)
        except Exception as error:
            if not args.continuous:
                raise
            print(f"voice listener: {error}", file=sys.stderr)
            threading.Event().wait(1)
        if not args.continuous:
            break


def _hotkey_is_pressed(keyboard, hotkey: str) -> bool:
    keys = [key.strip() for key in hotkey.split("+") if key.strip()]
    if not keys:
        return False
    return all(keyboard.is_pressed(key) for key in keys)


def _wake_detected(transcript: str) -> bool:
    try:
        return strip_wake_word(transcript).detected
    except Exception:
        return False


def _looks_like_prompt_echo(transcript: str) -> bool:
    normalized = " ".join(str(transcript or "").strip().lower().split())
    if not normalized:
        return False
    prompt_fragments = (
        "el usuario suele empezar",
        "frases cortas en español",
        "comandos pon reproduce pausa",
        "conexion con codex",
    )
    return any(fragment in normalized for fragment in prompt_fragments)


def _wav_duration_ms(wav_path: Path) -> int:
    with wave.open(str(wav_path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
    return int(frames * 1000 / rate) if rate else 0


def _transcribe_with_timeout(transcriber, wav_path: Path, language: str, timeout_seconds: int) -> str:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(transcriber.transcribe_file, str(wav_path), language=language)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError:
            print(f"voice listener: transcription timed out after {timeout_seconds}s; restarting listener", flush=True)
            os._exit(124)


def _diagnose_audio(transcriber_name: str, transcriber) -> None:
    try:
        import sounddevice as sd
    except Exception as error:
        print(f"voice listener: sounddevice unavailable: {error}", flush=True)
        return

    try:
        default_input = sd.query_devices(kind="input")
        print(f"voice listener: default input={default_input.get('name', 'unknown')}", flush=True)
        configured_input = selected_device("input")
        if configured_input is not None:
            device = sd.query_devices(configured_input, kind="input")
            print(f"voice listener: configured input={device.get('name', configured_input)}", flush=True)
    except Exception as error:
        print(f"voice listener: default input unavailable: {error}", flush=True)

    if transcriber_name == "faster-whisper":
        try:
            transcriber._ensure_model()
        except Exception as error:
            print(f"voice listener: faster-whisper unavailable: {error}", flush=True)
        else:
            print("voice listener: faster-whisper ready", flush=True)


if __name__ == "__main__":
    main()
