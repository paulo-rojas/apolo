from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import json
from dataclasses import replace
from pathlib import Path
from typing import Callable

from core.config import get_float, get_str
from core.logging import write_log
from core.process import hidden_subprocess_kwargs
from .audio_monitor import AudioMonitor
from .service_status import ServiceState, ServiceStatus


class ApoloManager:
    """UI-facing lifecycle boundary; real service adapters can be attached later."""

    def __init__(self, manage_backend: bool = False):
        self._running = False
        self._manage_backend = manage_backend
        self._backend_process = None
        self._voice_process = None
        self._process_log_threads: list[threading.Thread] = []
        self._audio_monitor = AudioMonitor(self._audio_level)
        self._speaker = None
        self._speech_thread = None
        self._voice_state = "Detenido"
        self._last_audio_at = 0.0
        self._listener_accepts_voice = False
        self._ptt_stop = threading.Event()
        self._ptt_thread = None
        self._listeners: dict[str, list[Callable]] = {}
        self._services = {
            "Voz": ServiceStatus("Voz", ServiceState.READY, "Listener preparado"),
            "Whisper": ServiceStatus("Whisper", ServiceState.READY, _whisper_detail()),
            "Codex": ServiceStatus("Codex", ServiceState.READY, "Disponible"),
            "Browser": ServiceStatus("Browser", ServiceState.STOPPED, "Sin conexión CDP"),
            "YouTube Music": ServiceStatus("YouTube Music", ServiceState.STOPPED, "Offline"),
        }

    def on(self, event: str, callback: Callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def _emit(self, event: str, *args) -> None:
        if event == "log_received" and len(args) >= 2:
            write_log(str(args[0]), str(args[1]))
        for callback in self._listeners.get(event, []):
            callback(*args)

    def start(self) -> None:
        from core.listener_control import listener_is_resting, resume_listener

        if self._running and listener_is_resting():
            resume_listener()
            self._listener_accepts_voice = get_str("voice.mode", "open") == "open"
            self.set_service_status("Voz", ServiceState.READY, "Listener reactivado")
            self._emit("status_changed", "Activo")
            self._emit("log_received", "SYSTEM", "Apolo reactivado")
            return
        if self._running:
            return

        resume_listener()
        self._running = True
        self._voice_state = "Activo"
        self._start_backend()
        self._start_voice_listener()
        if self._manage_backend:
            self._audio_monitor.start()
        if get_str("voice.mode", "open") == "open":
            self._listener_accepts_voice = True
        else:
            self._listener_accepts_voice = False
            self._start_push_to_talk_monitor()
        self._emit("status_changed", "Activo")
        self._emit("log_received", "SYSTEM", "Apolo iniciado")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._voice_state = "Detenido"
        self._listener_accepts_voice = False
        self._audio_monitor.stop()
        self._ptt_stop.set()
        if self._speaker is not None:
            self._speaker.stop()
        self._stop_backend()
        self._stop_voice_listener()
        self._emit("status_changed", "Detenido")
        self._emit("log_received", "SYSTEM", "Apolo detenido")

    def restart(self) -> None:
        self.stop()
        self.start()

    def get_status(self) -> str:
        return "Activo" if self._running else "Detenido"

    def get_services(self) -> list[ServiceStatus]:
        return list(self._services.values())

    def set_service_status(self, name: str, state: ServiceState, detail: str = "") -> None:
        if name not in self._services:
            raise KeyError(name)
        self._services[name] = replace(self._services[name], state=state, detail=detail)
        self._emit("service_changed", self._services[name])
        self._emit("log_received", name.upper(), f"Estado: {state.value}")

    def set_voice_state(self, state: str, level: float = 0.0) -> None:
        self._emit("status_changed", state)
        self._emit("audio_level_changed", max(0.0, min(1.0, level)))

    def _audio_level(self, level: float) -> None:
        self._emit("audio_level_changed", level)
        now = time.monotonic()
        activity_threshold = get_float("voice.monitor.activity_threshold", 0.025, minimum=0.0)
        if level >= activity_threshold:
            self._last_audio_at = now
            if self._running and self._listener_accepts_voice and self._voice_state == "Activo":
                self._voice_state = "Escuchando"
                self._emit("status_changed", self._voice_state)
        elif self._running and self._voice_state == "Escuchando" and now - self._last_audio_at >= 0.45:
            self._voice_state = "Activo"
            self._emit("status_changed", self._voice_state)

    def _start_push_to_talk_monitor(self) -> None:
        if self._ptt_thread and self._ptt_thread.is_alive():
            return
        hotkey = get_str("voice.hotkey", "ctrl+space") or "ctrl+space"
        self._ptt_stop.clear()

        def monitor():
            try:
                import keyboard
            except Exception:
                self._emit("log_received", "VOICE", "Push-to-talk no disponible")
                return
            while not self._ptt_stop.is_set():
                try:
                    keys = [key.strip() for key in hotkey.split("+") if key.strip()]
                    pressed = all(keyboard.is_pressed(key) for key in keys)
                except Exception as error:
                    self._emit("log_received", "ERROR", str(error))
                    return
                self._listener_accepts_voice = pressed
                if pressed and self._voice_state == "Activo":
                    self._voice_state = "Escuchando"
                    self._emit("status_changed", self._voice_state)
                elif not pressed and self._voice_state == "Escuchando":
                    self._voice_state = "Activo"
                    self._emit("status_changed", self._voice_state)
                self._ptt_stop.wait(0.05)

        self._ptt_thread = threading.Thread(target=monitor, name="apolo-ptt-status", daemon=True)
        self._ptt_thread.start()

    def speak(self, text: str) -> None:
        if self._speech_thread and self._speech_thread.is_alive():
            return
        from core.audio_gate import clear_listener_mute, mute_listener_for
        from voice.kokoro_tts import KokoroSpeaker

        self._speaker = self._speaker or KokoroSpeaker(self._audio_level)

        def run():
            self._emit("status_changed", "Hablando")
            self._emit("log_received", "KOKORO", text)
            try:
                mute_listener_for(_speech_mute_seconds(text))
                self._speaker.speak(text)
                self._emit("log_received", "KOKORO", "Audio reproducido")
            except Exception as error:
                self._emit("log_received", "ERROR", str(error))
                self._emit("error_received", str(error))
            finally:
                clear_listener_mute()
                self._emit("status_changed", "Activo" if self._running else "Detenido")

        self._speech_thread = threading.Thread(target=run, name="apolo-kokoro", daemon=True)
        self._speech_thread.start()

    def _start_backend(self) -> None:
        if not self._manage_backend:
            return
        if self._port_is_open(8000):
            self.set_service_status("Codex", ServiceState.READY, "Backend MCP activo")
            return
        self._backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcp.server:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        self._pipe_process_logs("MCP", self._backend_process)
        if self._wait_for_port(8000, timeout_seconds=5):
            self.set_service_status("Codex", ServiceState.READY, "Backend MCP activo")
        else:
            self.set_service_status("Codex", ServiceState.ERROR, "Backend MCP sin respuesta")

    def _stop_backend(self) -> None:
        if self._backend_process is None:
            return
        if self._backend_process.poll() is None:
            self._backend_process.terminate()
            try:
                self._backend_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._backend_process.kill()
        self._backend_process = None

    def _start_voice_listener(self) -> None:
        if not self._manage_backend or self._voice_process is not None:
            return
        root = Path(__file__).resolve().parents[1]
        mode = get_str("voice.mode", "open") or "open"
        hotkey = get_str("voice.hotkey", "ctrl+space") or "ctrl+space"
        self._voice_process = subprocess.Popen(
            _voice_listener_command("http://127.0.0.1:8000", mode, hotkey),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        self.set_service_status("Voz", ServiceState.READY, f"{mode} ({hotkey})")
        self.set_service_status("Whisper", ServiceState.READY, _whisper_detail())
        self._pipe_process_logs("VOICE", self._voice_process)

    def _stop_voice_listener(self) -> None:
        if self._voice_process is None:
            return
        if self._voice_process.poll() is None:
            self._voice_process.terminate()
            try:
                self._voice_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._voice_process.kill()
        self._voice_process = None
        self.set_service_status("Voz", ServiceState.STOPPED, "Listener detenido")

    @staticmethod
    def _port_is_open(port: int) -> bool:
        with socket.socket() as connection:
            connection.settimeout(0.15)
            return connection.connect_ex(("127.0.0.1", port)) == 0

    def _wait_for_port(self, port: int, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._port_is_open(port):
                return True
            time.sleep(0.1)
        return False

    def _pipe_process_logs(self, source: str, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return

        def read_output() -> None:
            try:
                for line in process.stdout:
                    message = line.strip()
                    if message:
                        self._handle_process_log(source, message)
            except Exception as error:
                self._emit("log_received", "ERROR", f"{source}: {error}")
            finally:
                self._handle_process_exit(source, process)

        thread = threading.Thread(target=read_output, name=f"apolo-{source.lower()}-logs", daemon=True)
        self._process_log_threads.append(thread)
        thread.start()

    def _handle_process_exit(self, source: str, process: subprocess.Popen) -> None:
        returncode = process.poll()
        if source == "VOICE" and self._running and self._voice_process is process:
            if _listener_shutdown_requested():
                self._voice_process = None
                self._shutdown_from_voice()
                return
            self._voice_process = None
            detail = f"Listener terminado ({returncode})"
            self.set_service_status("Voz", ServiceState.ERROR, detail)
            self._emit("log_received", "VOICE", f"{detail}; reiniciando")
            timer = threading.Timer(0.8, self._start_voice_listener)
            timer.daemon = True
            timer.start()
        elif source == "MCP" and self._running and self._backend_process is process:
            self._backend_process = None
            self.set_service_status("Codex", ServiceState.ERROR, f"Backend terminado ({returncode})")

    def _handle_process_log(self, source: str, message: str) -> None:
        self._emit("log_received", source, message)
        if source != "VOICE":
            return
        lowered = message.lower()
        if "preloading faster-whisper" in lowered:
            self.set_service_status("Whisper", ServiceState.READY, f"Cargando {_whisper_detail()}")
            self._emit("status_changed", "Procesando")
        elif "faster-whisper ready" in lowered:
            self.set_service_status("Whisper", ServiceState.READY, f"{_whisper_detail()} listo")
            self._emit("status_changed", "Activo")
        elif "realtime-stt ready" in lowered:
            self.set_service_status("Whisper", ServiceState.READY, "RealtimeSTT listo")
            self._emit("status_changed", "Activo")
        elif "waiting for" in lowered or "listening" in lowered:
            self._listener_accepts_voice = get_str("voice.mode", "open") == "open"
            self._emit("status_changed", "Activo")
        elif "resting" in lowered:
            self._listener_accepts_voice = False
            self.set_service_status("Voz", ServiceState.STOPPED, "Descansando")
            self._emit("status_changed", "Detenido")
        elif "shutdown requested" in lowered:
            self._listener_accepts_voice = False
            self.set_service_status("Voz", ServiceState.STOPPED, "Sesión terminada")
            self._emit("status_changed", "Detenido")
        elif "recording" in lowered:
            self._listener_accepts_voice = True
            self._emit("status_changed", "Escuchando")
        elif "transcribing" in lowered:
            self._listener_accepts_voice = False
            self._emit("status_changed", "Procesando")
        elif "heard" in lowered:
            self._listener_accepts_voice = get_str("voice.mode", "open") == "open"
            self._emit("status_changed", "Activo")
        elif "wake detected" in lowered:
            self._emit("status_changed", "Atento")
        elif "cuda unavailable" in lowered and "falling back" in lowered:
            self.set_service_status("Whisper", ServiceState.READY, "Fallback CPU activo")
        elif "cuda runtime missing" in lowered:
            self.set_service_status("Whisper", ServiceState.READY, "CPU por falta de CUDA")
        elif "unavailable" in lowered or "requiere" in lowered or "error" in lowered:
            self.set_service_status("Voz", ServiceState.ERROR, message[:90])
        else:
            self._handle_voice_json_status(message)

    def _handle_voice_json_status(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        feedback = payload.get("feedback") or payload.get("parsed", {}).get("feedback")
        if feedback == "wake":
            self._emit("status_changed", "Atento")
        elif feedback == "repeat":
            self._listener_accepts_voice = get_str("voice.mode", "open") == "open"
            self._emit("status_changed", "Atento")
        elif feedback == "processing":
            self._emit("status_changed", "Procesando")

    def _shutdown_from_voice(self) -> None:
        self._running = False
        self._voice_state = "Detenido"
        self._listener_accepts_voice = False
        self._audio_monitor.stop()
        self._ptt_stop.set()
        self._stop_backend()
        self.set_service_status("Voz", ServiceState.STOPPED, "Sesión terminada")
        self._emit("status_changed", "Detenido")
        self._emit("log_received", "SYSTEM", "Apolo apagado por voz")
        self._emit("shutdown_requested")
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(250, app.quit)
        except Exception:
            pass


def _speech_mute_seconds(text: str) -> float:
    words = len((text or "").split())
    return min(20.0, max(2.0, 0.45 * words + 1.2))


def _listener_shutdown_requested() -> bool:
    try:
        from core.listener_control import shutdown_requested

        return shutdown_requested()
    except Exception:
        return False


def _whisper_detail() -> str:
    backend = get_str("whisper.backend", "faster-whisper") or "faster-whisper"
    model = get_str("whisper.model", "medium") or "medium"
    compute = get_str("whisper.compute_type", "int8") or "int8"
    return f"{backend} {model}/{compute}"


def _voice_listener_command(server: str, mode: str, hotkey: str) -> list[str]:
    transcriber = get_str("whisper.backend", "faster-whisper") or "faster-whisper"
    return [
        sys.executable,
        "-m",
        "voice.local_listener",
        "--server",
        server,
        "--continuous",
        "--mode",
        mode,
        "--hotkey",
        hotkey,
        "--transcriber",
        transcriber,
    ]
