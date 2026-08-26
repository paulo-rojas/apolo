import argparse
import atexit
from datetime import datetime
import json
import os
import queue
import shutil
import subprocess
import wave
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from core.audio_gate import listener_is_muted
from core.config import PROJECT_ROOT, get_bool, get_float, get_int, get_str
from core.listener_control import listener_is_resting, shutdown_requested
from core.logging import write_log
from core.memory_files import memory_dir
from .microphone import MicrophoneNotAvailable, record_utterance_to_wav
from .providers import create_speech_to_text_provider, wav_path_for_voice_command
from .vad import VadConfig
from .audio_devices import selected_device
from .wake_word import strip_wake_word


class RealtimeSttTimeout(RuntimeError):
    pass


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
    parser.add_argument("--dictate", action="store_true", help="Transcribe speech without wake word or command routing.")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--silence-ms", type=int, default=None)
    parser.add_argument("--block-ms", type=int, default=None)
    parser.add_argument("--mode", choices=("open", "push_to_talk"), default=None)
    parser.add_argument("--hotkey", default=None)
    parser.add_argument("--transcriber", choices=("faster-whisper", "whisper-cpp", "realtime-stt", "realtimestt"), default=None)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    if args.dictate:
        os.environ["APOLO_VOICE_DICTATION"] = "1"

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
    use_realtime_stt = _is_realtime_stt_backend(transcriber_name)
    fallback_transcriber_name = get_str("realtime_stt.fallback_backend", "faster-whisper") or "faster-whisper"
    transcriber = None if use_realtime_stt else create_speech_to_text_provider(transcriber_name)
    realtime_session = RealtimeSttSession(wav_path, args.language) if use_realtime_stt and args.continuous else None
    if realtime_session is not None:
        atexit.register(realtime_session.close)
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
            started_at = time.monotonic()
            if use_realtime_stt:
                try:
                    if realtime_session is None or not realtime_session.ready:
                        print("voice listener: preparing realtime-stt", flush=True)
                    result = (
                        realtime_session.listen()
                        if realtime_session is not None
                        else _listen_with_realtime_stt(wav_path, args.language)
                    )
                    transcript = result["text"]
                    duration_ms = int(result.get("duration_ms", 0))
                    elapsed_ms = int(result.get("elapsed_ms", int((time.monotonic() - started_at) * 1000)))
                    backend_label = str(result.get("backend") or "realtime-stt")
                except RealtimeSttTimeout as error:
                    print(f"voice listener: {error}; no fallback recording attempted", flush=True)
                    write_log("VOICE", f"realtime-stt timeout: {error}")
                    if args.continuous:
                        continue
                    break
                except Exception as error:
                    print(f"voice listener: realtime-stt failed; falling back to {fallback_transcriber_name}: {error}", flush=True)
                    write_log("VOICE", f"realtime-stt failed; fallback={fallback_transcriber_name}: {error}")
                    transcriber = create_speech_to_text_provider(fallback_transcriber_name)
                    transcript, duration_ms, elapsed_ms, backend_label = _record_and_transcribe_legacy(
                        transcriber,
                        wav_path,
                        language=args.language,
                        timeout_seconds=transcribe_timeout,
                        vad_config=vad_config,
                        stop_when=stop_when,
                        start_immediately=start_immediately,
                    )
            else:
                transcript, duration_ms, elapsed_ms, backend_label = _record_and_transcribe_legacy(
                    transcriber,
                    wav_path,
                    language=args.language,
                    timeout_seconds=transcribe_timeout,
                    vad_config=vad_config,
                    stop_when=stop_when,
                    start_immediately=start_immediately,
                )
            if listener_is_muted():
                print("voice listener: discarded self-audio", flush=True)
                continue
            print(f"voice listener: heard {transcript!r} in {elapsed_ms}ms using {backend_label}", flush=True)
            if _looks_like_prompt_echo(transcript):
                print("voice listener: discarded prompt echo", flush=True)
                continue
            if _wake_detected(transcript):
                print("voice listener: wake detected", flush=True)
            if args.dictate:
                response_text = json.dumps(
                    {"ok": True, "kind": "dictation", "text": transcript, "duration_ms": duration_ms},
                    ensure_ascii=False,
                )
                print(response_text, flush=True)
                continue
            if args.dry_run:
                response_text = json.dumps(
                    _interpret_dry_run(transcript, duration_ms),
                    ensure_ascii=False,
                )
                print(response_text, flush=True)
                _maybe_save_training_sample(
                    wav_path,
                    transcript=transcript,
                    response_text=response_text,
                    duration_ms=duration_ms,
                    elapsed_ms=elapsed_ms,
                    backend_label=backend_label,
                )
            else:
                payload = json.dumps({"text": transcript, "duration_ms": duration_ms, "dry_run": args.dry_run}).encode("utf-8")
                request = urllib.request.Request(
                    f"{args.server.rstrip('/')}/voice-command",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    response_text = response.read().decode("utf-8")
                    print(response_text)
            _maybe_save_training_sample(
                wav_path,
                transcript=transcript,
                response_text=response_text,
                duration_ms=duration_ms,
                elapsed_ms=elapsed_ms,
                backend_label=backend_label,
            )
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
    if realtime_session is not None:
        realtime_session.close()


def _interpret_dry_run(transcript: str, duration_ms: int) -> dict:
    from core.state import State
    from voice.gateway import VoiceGateway

    return VoiceGateway(State()).handle_transcript(
        transcript,
        duration_ms=duration_ms,
    )


def _hotkey_is_pressed(keyboard, hotkey: str) -> bool:
    keys = [key.strip() for key in hotkey.split("+") if key.strip()]
    if not keys:
        return False
    return all(keyboard.is_pressed(key) for key in keys)


def _is_realtime_stt_backend(name: str) -> bool:
    return str(name or "").strip().lower() in {"realtime-stt", "realtimestt", "realtime_stt"}


def _record_and_transcribe_legacy(
    transcriber,
    wav_path: Path,
    *,
    language: str,
    timeout_seconds: int,
    vad_config: VadConfig,
    stop_when=None,
    start_immediately: bool = False,
) -> tuple[str, int, int, str]:
    record_utterance_to_wav(
        str(wav_path),
        sample_rate=vad_config.sample_rate,
        vad_config=vad_config,
        stop_when=stop_when,
        start_immediately=start_immediately,
    )
    duration_ms = _wav_duration_ms(wav_path)
    print(f"voice listener: transcribing {duration_ms}ms", flush=True)
    started_at = time.monotonic()
    transcript = _transcribe_with_timeout(transcriber, wav_path, language, timeout_seconds)
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    backend_label = getattr(transcriber, "backend_label", "unknown")
    return transcript, duration_ms, elapsed_ms, backend_label


def _listen_with_realtime_stt(wav_path: Path, language: str) -> dict:
    timeout_seconds = get_int(
        "realtime_stt.timeout_seconds",
        get_int("voice.vad.max_utterance_ms", 8000, minimum=500) // 1000
        + get_int("whisper.transcribe_timeout_seconds", 12, minimum=2)
        + 5,
        env="APOLO_REALTIMESTT_TIMEOUT_SECONDS",
        minimum=3,
    )
    command = _realtime_stt_command(wav_path, language)
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines: list[str] = []
    reader = threading.Thread(
        target=_read_realtime_stt_output,
        args=(process, output_lines),
        daemon=True,
    )
    reader.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_realtime_process(process)
        reader.join(timeout=1)
        raise RealtimeSttTimeout(
            f"realtime-stt timed out after {timeout_seconds}s; no final phrase was detected"
        ) from error
    except KeyboardInterrupt:
        _terminate_realtime_process(process)
        reader.join(timeout=1)
        print("voice listener: stopped", flush=True)
        raise
    reader.join(timeout=1)
    result = _parse_realtime_stt_result("\n".join(output_lines))
    if returncode != 0 or not result.get("ok"):
        detail = result.get("error") or "\n".join(output_lines).strip() or f"exit {returncode}"
        raise RuntimeError(detail)
    return result


def _terminate_realtime_process(process) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _read_realtime_stt_output(process, output_lines: list[str]) -> None:
    if process.stdout is None:
        return
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        output_lines.append(line)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "partial":
            print(f"voice listener: partial: {event.get('text', '')}", flush=True)
        elif isinstance(event, dict) and event.get("event") == "ready":
            print("voice listener: realtime-stt ready; speak now", flush=True)


class RealtimeSttSession:
    def __init__(self, wav_path: Path, language: str):
        self.wav_path = wav_path
        self.language = language
        self.timeout_seconds = _realtime_stt_timeout_seconds()
        self.process = None
        self.events: queue.Queue[dict] = queue.Queue()
        self.reader = None
        self.ready = False

    def listen(self) -> dict:
        self._ensure_started()
        if not self.ready:
            self._wait_until_ready()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.restart()
                raise RealtimeSttTimeout(
                    f"realtime-stt timed out after {self.timeout_seconds}s; no final phrase was detected"
                )
            try:
                event = self.events.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    self.ready = False
                    raise RuntimeError(f"realtime-stt exited with code {self.process.returncode}")
                continue
            if event.get("event") in {"ready", "partial"}:
                continue
            if event.get("ok"):
                return event
            raise RuntimeError(event.get("error") or "realtime-stt failed")

    def restart(self) -> None:
        self.close()
        self._ensure_started()

    def close(self) -> None:
        if self.process is not None:
            _terminate_realtime_process(self.process)
        if self.reader is not None:
            self.reader.join(timeout=1)
        self.process = None
        self.reader = None
        self.ready = False
        self.events = queue.Queue()

    def _ensure_started(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.ready = False
        self.process = subprocess.Popen(
            _realtime_stt_command(self.wav_path, self.language, loop=True),
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while not self.ready:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.restart()
                raise RealtimeSttTimeout(
                    f"realtime-stt timed out after {self.timeout_seconds}s before it became ready"
                )
            try:
                event = self.events.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    raise RuntimeError(f"realtime-stt exited with code {self.process.returncode}")
                continue
            if event.get("event") == "ready":
                self.ready = True
                continue
            if not event.get("ok", True):
                raise RuntimeError(event.get("error") or "realtime-stt failed")

    def _read_output(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        for raw_line in self.process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line, flush=True)
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "partial":
                print(f"voice listener: partial: {event.get('text', '')}", flush=True)
            elif event.get("event") == "ready":
                print("voice listener: realtime-stt ready; speak now", flush=True)
            self.events.put(event)


def _realtime_stt_timeout_seconds() -> int:
    return get_int(
        "realtime_stt.timeout_seconds",
        get_int("voice.vad.max_utterance_ms", 8000, minimum=500) // 1000
        + get_int("whisper.transcribe_timeout_seconds", 12, minimum=2)
        + 5,
        env="APOLO_REALTIMESTT_TIMEOUT_SECONDS",
        minimum=3,
    )


def _realtime_stt_command(wav_path: Path, language: str, loop: bool = False) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "voice.realtime_stt_worker",
        "--output",
        str(wav_path),
        "--language",
        language or "es",
    ]
    if loop:
        command.append("--loop")
    return command


def _parse_realtime_stt_result(stdout: str) -> dict:
    for line in reversed(str(stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise RuntimeError("realtime-stt produced no JSON result")


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


def _maybe_save_training_sample(
    wav_path: Path,
    *,
    transcript: str,
    response_text: str,
    duration_ms: int,
    elapsed_ms: int,
    backend_label: str,
) -> None:
    try:
        response = json.loads(response_text or "{}")
    except json.JSONDecodeError:
        response = {"raw": response_text}
    if not _should_save_training_sample(transcript, response):
        return

    try:
        target_dir = _training_samples_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        base_name = f"{timestamp}-{_training_kind(response)}"
        audio_path = target_dir / f"{base_name}.wav"
        meta_path = target_dir / f"{base_name}.json"
        if get_bool("voice.training.save_audio", True):
            shutil.copy2(wav_path, audio_path)
        metadata = {
            "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "transcript": transcript,
            "durationMs": duration_ms,
            "transcribeMs": elapsed_ms,
            "backend": backend_label,
            "response": response,
            "audio": str(audio_path) if audio_path.exists() else None,
        }
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_log("VOICE_TRAIN", f"saved sample {meta_path.name} transcript={transcript!r}")
    except Exception as error:
        write_log("VOICE_TRAIN", f"could not save sample: {error}")


def _should_save_training_sample(transcript: str, response: dict) -> bool:
    if not get_bool("voice.training.enabled", True):
        return False
    if not str(transcript or "").strip():
        return False
    if get_bool("voice.training.save_all", False):
        return True
    kind = str(response.get("kind") or response.get("parsed", {}).get("kind") or "")
    if kind in {"repeat", "error"}:
        return True
    if response.get("ok") is False:
        return True
    return bool(get_bool("voice.training.save_wake_commands", True) and _wake_detected(transcript))


def _training_kind(response: dict) -> str:
    kind = str(response.get("kind") or response.get("parsed", {}).get("kind") or "sample").lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in kind).strip("-")
    return cleaned or "sample"


def _training_samples_dir() -> Path:
    configured = get_str("voice.training.dir", None)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else memory_dir() / path
    return memory_dir() / "voice_samples"


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
        import numpy as np
        import sounddevice as sd
    except Exception as error:
        print(f"voice listener: audio diagnostics unavailable: {error}", flush=True)
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

    try:
        sample_rate = get_int("voice.vad.sample_rate", 16000, minimum=8000)
        block_ms = get_int("voice.vad.block_ms", 40, minimum=10)
        block_size = int(sample_rate * block_ms / 1000)
        readings = []
        print("voice listener: measuring mic level for 3s; stay quiet, then say Apolo once", flush=True)
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=block_size,
            device=selected_device("input"),
        ) as stream:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                block, _ = stream.read(block_size)
                readings.append(float(np.sqrt(np.mean((block.astype("float32") / 32768.0) ** 2))))
        if readings:
            p10, p50, p95, peak = np.percentile(readings, [10, 50, 95, 100])
            current = get_float("voice.vad.threshold", 0.015, env="APOLO_VOICE_VAD_THRESHOLD", minimum=0.0)
            recommended = max(0.006, min(0.05, float(p95) * 1.6))
            print(
                "voice listener: mic rms "
                f"p10={p10:.4f} median={p50:.4f} p95={p95:.4f} peak={peak:.4f} "
                f"current_threshold={current:.4f} suggested_threshold={recommended:.4f}",
                flush=True,
            )
    except Exception as error:
        print(f"voice listener: mic level check failed: {error}", flush=True)

    if transcriber_name == "faster-whisper":
        try:
            transcriber._ensure_model()
        except Exception as error:
            print(f"voice listener: faster-whisper unavailable: {error}", flush=True)
        else:
            print("voice listener: faster-whisper ready", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("voice listener: stopped", flush=True)
