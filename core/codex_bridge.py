import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import PROJECT_ROOT, get_bool, get_int, get_str
from core.process import hidden_subprocess_kwargs


class CodexBridgeDisabled(RuntimeError):
    pass


class CodexBridgeError(RuntimeError):
    pass


class CodexQuotaExceeded(CodexBridgeError):
    pass


class CodexBridge:
    def __init__(self):
        self.enabled = get_bool("codex.enabled", False, env="APOLO_CODEX_ENABLED")
        self.executable = resolve_codex_executable(
            get_str("codex.executable", "codex", env="APOLO_CODEX_EXE")
        )
        self.model = get_str("codex.model", None, env="APOLO_CODEX_MODEL")
        self.timeout_seconds = get_int(
            "codex.timeout_seconds", 30, env="APOLO_CODEX_TIMEOUT_SECONDS", minimum=1
        )
        self.sandbox = _config_choice(
            get_str("codex.sandbox", "read-only", env="APOLO_CODEX_SANDBOX"),
            "read-only",
            {"read-only", "workspace-write", "danger-full-access"},
        )
        self.approval = _config_choice(
            get_str("codex.approval", "never", env="APOLO_CODEX_APPROVAL"),
            "never",
            {"never", "on-request", "on-failure", "untrusted"},
        )
        self.cwd = get_str("codex.cwd", str(PROJECT_ROOT), env="APOLO_CODEX_CWD")
        self.agent_prompt_path = get_str("codex.agent_prompt_path", "agents/apolo_codex.md")

    def run(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise CodexBridgeDisabled("Codex bridge is disabled")

        prompt = build_codex_prompt(command, context or {}, load_agent_prompt(self.agent_prompt_path))
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as f:
            output_path = Path(f.name)

        cmd = [self.executable]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend(
            [
                "--sandbox",
                self.sandbox,
                "--ask-for-approval",
                self.approval,
                "exec",
                "--cd",
                self.cwd,
                "--output-last-message",
                str(output_path),
                "-",
            ]
        )

        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                **hidden_subprocess_kwargs(),
            )
            final = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        finally:
            output_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            if "usage limit" in message.lower() or "quota" in message.lower():
                raise CodexQuotaExceeded(message)
            raise CodexBridgeError(message)

        parsed = _parse_json_object(final)
        return {
            "ok": True,
            "command": command,
            "raw": final,
            "parsed": parsed,
            "stdout": completed.stdout.strip(),
        }

    def test_connection(self) -> dict[str, Any]:
        """Check that the configured Codex CLI is installed without using a prompt."""
        completed = subprocess.run(
            [self.executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(self.timeout_seconds, 10),
            check=False,
            **hidden_subprocess_kwargs(),
        )
        output = (completed.stdout or completed.stderr).strip()
        if completed.returncode != 0:
            raise CodexBridgeError(output or "Codex CLI no respondió")
        return {"ok": True, "version": output}


def build_codex_prompt(command: str, context: Dict[str, Any], agent_prompt: str = "") -> str:
    payload = {
        "command": command,
        "context": context,
        "allowed_tools": [
            "browser.open",
            "browser.find",
            "browser.click",
            "browser.type",
            "browser.scroll",
            "browser.back",
            "browser.get_state",
            "browser.dom_snapshot",
            "browser.dom_click",
            "browser.smart_click",
            "browser.dom_type",
            "browser.dom_press",
            "web.open",
            "web.search_google",
            "web.remember",
            "system.open_app",
            "system.close_app",
            "system.remember_app",
            "youtube_music.play",
            "youtube_music.search",
            "youtube_music.esa_no",
            "youtube_music.play_last_search_index",
            "youtube_music.get_current_track",
            "memory.remember",
            "memory.add_voice_correction",
        ],
    }
    return (
        "Eres el cerebro de Apolo. Recibes una instruccion transcrita y contexto local. "
        "No ejecutes comandos del sistema. Solo puedes editar memoria mediante herramientas memory.*. "
        "Devuelve SOLO JSON valido. "
        "No pidas ni propongas browser.get_state como paso preparatorio: usa solo el "
        "contexto recibido. Propón herramientas MCP solo cuando la instruccion del "
        "usuario solicite una accion concreta. Para controlar paginas web de forma "
        "general, prefiere browser.dom_snapshot, browser.smart_click, browser.dom_type "
        "y browser.dom_press antes que depender de integraciones especificas. "
        "Para abrir sitios o busquedas simples, prefiere web.open o web.search_google "
        "porque usan el navegador predeterminado sin CDP. "
        "Para abrir o cerrar aplicaciones del sistema, usa system.open_app o "
        "system.close_app; Apolo aprendera alias exitosos en memoria. "
        "Si puedes resolverlo con una herramienta MCP permitida, responde "
        "{\"kind\":\"mcp\",\"tool\":\"nombre\",\"args\":{...},\"confidence\":0.0-1.0}. "
        "Si falta informacion, responde {\"kind\":\"ask_user\",\"question\":\"...\"}. "
        "Si solo debes contestar, responde {\"kind\":\"answer\",\"text\":\"...\"}. "
        "Si no es seguro, responde {\"kind\":\"ignore\",\"reason\":\"...\"}.\n\n"
        f"{_agent_prompt_block(agent_prompt)}"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def load_agent_prompt(configured: Optional[str]) -> str:
    if not configured:
        return ""
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _agent_prompt_block(agent_prompt: str) -> str:
    if not agent_prompt:
        return ""
    return f"Instrucciones persistentes del agente Apolo:\n{agent_prompt}\n\n"


def resolve_codex_executable(configured: Optional[str]) -> str:
    configured = configured or "codex"
    path = Path(configured)
    if path.is_file():
        return str(path)

    resolved = shutil.which(configured)
    if resolved:
        return resolved

    for candidate in (f"{configured}.cmd", f"{configured}.exe", f"{configured}.ps1"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    return configured


def _config_choice(value: Optional[str], default: str, allowed: set[str]) -> str:
    normalized = (value or "").strip()
    if normalized in allowed:
        return normalized
    return default


def _parse_json_object(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise CodexBridgeError("Codex did not return JSON")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise CodexBridgeError("Codex JSON response must be an object")
    return data


def codex_auto_execute_tools() -> bool:
    return get_bool("codex.auto_execute_tools", False, env="APOLO_CODEX_AUTO_EXECUTE_TOOLS")
