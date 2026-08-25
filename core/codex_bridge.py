import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import PROJECT_ROOT, get_bool, get_int, get_str


class CodexBridgeDisabled(RuntimeError):
    pass


class CodexBridgeError(RuntimeError):
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
        self.sandbox = get_str("codex.sandbox", "read-only", env="APOLO_CODEX_SANDBOX")
        self.approval = get_str("codex.approval", "never", env="APOLO_CODEX_APPROVAL")
        self.cwd = get_str("codex.cwd", str(PROJECT_ROOT), env="APOLO_CODEX_CWD")

    def run(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise CodexBridgeDisabled("Codex bridge is disabled")

        prompt = build_codex_prompt(command, context or {})
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as f:
            output_path = Path(f.name)

        cmd = [
            self.executable,
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
        if self.model:
            cmd[2:2] = ["--model", self.model]

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
            )
            final = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        finally:
            output_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            raise CodexBridgeError(completed.stderr.strip() or completed.stdout.strip())

        parsed = _parse_json_object(final)
        return {
            "ok": True,
            "command": command,
            "raw": final,
            "parsed": parsed,
            "stdout": completed.stdout.strip(),
        }


def build_codex_prompt(command: str, context: Dict[str, Any]) -> str:
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
            "youtube_music.play",
            "youtube_music.search",
            "youtube_music.esa_no",
            "youtube_music.play_last_search_index",
            "youtube_music.get_current_track",
        ],
    }
    return (
        "Eres el cerebro de Apolo. Recibes una instruccion transcrita y contexto local. "
        "No ejecutes comandos del sistema ni edites archivos. Devuelve SOLO JSON valido. "
        "No pidas ni propongas browser.get_state como paso preparatorio: usa solo el "
        "contexto recibido. Propón herramientas MCP solo cuando la instruccion del "
        "usuario solicite una accion concreta. "
        "Si puedes resolverlo con una herramienta MCP permitida, responde "
        "{\"kind\":\"mcp\",\"tool\":\"nombre\",\"args\":{...},\"confidence\":0.0-1.0}. "
        "Si falta informacion, responde {\"kind\":\"ask_user\",\"question\":\"...\"}. "
        "Si solo debes contestar, responde {\"kind\":\"answer\",\"text\":\"...\"}. "
        "Si no es seguro, responde {\"kind\":\"ignore\",\"reason\":\"...\"}.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


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
