import asyncio
import contextvars
import queue
import threading
import time
import traceback
from typing import Any, Dict

from core.config import get_float, get_int
from core.tool_contract import validate_structured_tool_args
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="apolov2 MCP")


class AgentWorker:
    def __init__(self):
        self._tasks = queue.Queue()
        self._thread = threading.Thread(
            target=lambda: contextvars.Context().run(self._run),
            name="apolo-agent",
            daemon=True,
        )
        self._thread.start()

    def _run(self):
        while True:
            loop, future, fn, args, kwargs = self._tasks.get()
            try:
                result = contextvars.Context().run(fn, *args, **kwargs)
            except Exception as e:
                loop.call_soon_threadsafe(self._complete_future, future, None, e)
            else:
                loop.call_soon_threadsafe(self._complete_future, future, result, None)

    @staticmethod
    def _complete_future(future, result=None, exception=None):
        if future.cancelled():
            return
        if exception is not None:
            future.set_exception(exception)
            return
        future.set_result(result)

    async def call(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._tasks.put((loop, future, fn, args, kwargs))
        return await future


agent_worker = AgentWorker()


class CallRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


class VoiceCommandRequest(BaseModel):
    text: str
    confidence: float | None = None
    duration_ms: int | None = None
    dry_run: bool = False


class BrowserProxy:
    def __init__(self):
        self._impl = None

    def _ensure(self):
        if self._impl is None:
            try:
                from mcp.browser.playwright_driver import PlaywrightBrowser

                self._impl = PlaywrightBrowser()
                if getattr(self._impl, "cdp_endpoint", None):
                    from mcp.browser.cdp_manager import ensure_cdp

                    ensure_cdp(close_existing=False)
                try:
                    self._impl._ensure_started()
                except Exception as error:
                    if error.__class__.__name__ != "BrowserCdpUnavailable":
                        raise
                    from core.config import PROJECT_ROOT

                    self._impl = PlaywrightBrowser(
                        user_data_dir=str(PROJECT_ROOT / "runtime" / "browser-profile"),
                        force_launch=True,
                    )
                    self._impl._ensure_started()
            except Exception as e:
                raise RuntimeError(f"No browser implementation available: {e}")

    def call(self, method: str, args: Dict[str, Any]):
        self._ensure()
        fn = getattr(self._impl, method, None)
        if fn is None:
            raise AttributeError(f"Browser has no method {method}")
        tab_context = getattr(self._impl, "using_tab", None)
        if tab_context and method in {
            "open",
            "find",
            "click",
            "type",
            "dom_snapshot",
            "dom_click",
            "smart_click",
            "dom_type",
            "dom_press",
            "scroll",
            "back",
            "screenshot",
        }:
            with tab_context(create_url="about:blank", restore=True, remember_key="browser"):
                return fn(**args)
        return fn(**args)

    def snapshot_state(self):
        if self._impl is None:
            return None
        snapshot = getattr(self._impl, "snapshot_state", None)
        if snapshot is None:
            return None
        return snapshot()


browser = BrowserProxy()
kokoro_speaker = None


class MusicProxy:
    def __init__(self, browser_proxy: BrowserProxy):
        self._impl = None
        self._browser_proxy = browser_proxy

    def _ensure(self):
        if self._impl is None:
            from core.state import State
            from mcp.youtube_music.player import YouTubeMusic

            self._browser_proxy._ensure()
            self._impl = YouTubeMusic(self._browser_proxy._impl, state=State())

    def call(self, method: str, args: Dict[str, Any]):
        self._ensure()
        if method == "play" and "query" in args and "query_or_candidate" not in args:
            args = dict(args)
            query = str(args.pop("query") or "").strip()
            artist = str(args.pop("artist", "") or "").strip()
            album = str(args.pop("album", "") or "").strip()
            args.pop("platform", None)
            parts = [query, artist, album]
            args["query_or_candidate"] = " ".join(part for part in parts if part)
        fn = getattr(self._impl, method, None)
        if fn is None:
            raise AttributeError(f"YouTube Music has no method {method}")
        tab_context = getattr(self._browser_proxy._impl, "using_tab", None)
        if tab_context is None:
            return fn(**args)
        with tab_context(
            url_contains="music.youtube.com",
            create_url="https://music.youtube.com",
            restore=True,
            remember_key="youtube_music",
        ):
            return fn(**args)


music = MusicProxy(browser)


async def run_agent_call(fn, *args, **kwargs):
    return await agent_worker.call(fn, *args, **kwargs)


async def speak_response(text: str) -> None:
    global kokoro_speaker
    from core.audio_gate import clear_listener_mute, mute_listener_for
    from voice.kokoro_tts import KokoroSpeaker

    kokoro_speaker = kokoro_speaker or KokoroSpeaker()
    try:
        mute_listener_for(_speech_mute_seconds(text))
        await run_agent_call(kokoro_speaker.speak, text)
    except Exception as error:
        print(f"Kokoro response error: {error}", flush=True)
    finally:
        clear_listener_mute()


def schedule_speech(text: str) -> None:
    from core.audio_gate import mute_listener_for

    mute_listener_for(_speech_mute_seconds(text))
    asyncio.create_task(speak_response(text))


def _speech_mute_seconds(text: str) -> float:
    words = len((text or "").split())
    return min(20.0, max(2.0, 0.45 * words + 1.2))


def _computer_audio_guard_seconds() -> float:
    return get_float("voice.computer_audio_guard_seconds", 3600.0, minimum=0.0)


def _update_computer_audio_guard(parsed: Dict[str, Any]) -> None:
    from core.audio_gate import clear_computer_audio, mark_computer_audio_for

    tool = str(parsed.get("tool") or "")
    if tool == "youtube_music.pause":
        clear_computer_audio()
        return
    if tool in {
        "youtube_music.play",
        "youtube_music.resume",
        "youtube_music.next",
        "youtube_music.previous",
        "youtube_music.esa_no",
        "youtube_music.play_last_search_index",
    }:
        mark_computer_audio_for(_computer_audio_guard_seconds())


async def execute_tool(tool: str, args: Dict[str, Any]):
    validate_structured_tool_args(tool, args)

    if tool == "web.open":
        from core.web_shortcuts import open_web_target

        return await run_agent_call(open_web_target, args.get("target", ""))

    if tool == "web.search_google":
        from core.web_shortcuts import search_google

        return await run_agent_call(search_google, args.get("query", ""))

    if tool == "web.remember":
        from core.web_shortcuts import remember_web_shortcut

        return await run_agent_call(
            remember_web_shortcut,
            args.get("alias", ""),
            args.get("url", ""),
            args.get("label"),
        )

    if tool == "system.open_app":
        from core.system_apps import open_system_app

        return await run_agent_call(open_system_app, _tool_app_name(args))

    if tool == "system.close_app":
        from core.system_apps import close_system_app

        return await run_agent_call(close_system_app, _tool_app_name(args))

    if tool == "system.set_volume":
        from core.system_volume import set_system_volume

        return await asyncio.wait_for(
            run_agent_call(
                set_system_volume,
                args.get("level"),
                args.get("direction"),
                args.get("step") or get_int("system.volume_step", 5, minimum=1),
            ),
            timeout=get_int("actions.timeout_seconds", 5, minimum=1),
        )

    if tool == "system.remember_app":
        from core.system_apps import remember_system_app

        return await run_agent_call(
            remember_system_app,
            args.get("alias", ""),
            args.get("launch", {}),
            args.get("label"),
        )

    if tool == "memory.remember":
        if not _memory_write_allowed():
            raise HTTPException(status_code=403, detail="Memory writes are disabled")
        from core.memory_files import remember_note

        return await run_agent_call(remember_note, args.get("text", ""), args.get("source", "codex"))

    if tool == "memory.add_voice_correction":
        if not _memory_write_allowed():
            raise HTTPException(status_code=403, detail="Memory writes are disabled")
        from core.memory_files import add_voice_correction

        return await run_agent_call(add_voice_correction, args.get("heard", ""), args.get("normalized", ""))

    if tool.startswith("browser."):
        method = tool.split(".", 1)[1]
        if method == "ensure_cdp":
            from mcp.browser.cdp_manager import ensure_cdp

            result = await run_agent_call(
                ensure_cdp,
                close_existing=bool(args.get("close_existing", False)),
            )
            await run_agent_call(browser._ensure)
            return result
        return await run_agent_call(browser.call, method, args)

    if tool.startswith("youtube_music."):
        method = tool.split(".", 1)[1]
        return await asyncio.wait_for(
            run_agent_call(music.call, method, args),
            timeout=get_int("music.action_timeout_seconds", 45, minimum=1),
        )

    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


@app.get("/voice", response_class=HTMLResponse)
async def voice_page():
    from mcp.voice_page import VOICE_PAGE_HTML

    return VOICE_PAGE_HTML


@app.post("/voice-command")
async def voice_command(req: VoiceCommandRequest):
    try:
        from core.state import State
        from voice.gateway import VoiceGateway

        parsed = VoiceGateway(State()).handle_transcript(
            req.text,
            confidence=req.confidence,
            duration_ms=req.duration_ms,
        )
        if parsed.get("kind") == "repeat":
            response_text = repeat_response_text(parsed)
            if not req.dry_run:
                schedule_speech(response_text)
            return {**parsed, "response": response_text}
        if parsed.get("kind") in {"ignore", "session"}:
            return parsed
        if req.dry_run:
            return {"ok": True, "heard": req.text, "parsed": parsed}
        if parsed.get("kind") == "local":
            return await handle_local_path(req.text, parsed)
        if parsed.get("kind") == "memory":
            return await handle_memory_path(req.text, parsed)
        if parsed.get("kind") == "status":
            return await handle_status_path(req.text, parsed)
        if parsed.get("kind") == "codex":
            return await handle_codex_path(req.text, parsed)
        return await handle_tool_path(req.text, parsed)
    except Exception as e:
        return error_response(e)


async def handle_codex_path(heard: str, parsed: Dict[str, Any]):
    from core.codex_bridge import CodexBridge, CodexBridgeDisabled, CodexQuotaExceeded, codex_auto_execute_tools
    from core.memory_files import cached_repetitive_answer, maybe_remember_repetitive_answer
    from core.state import State
    from voice.normalize import normalize_text

    command = parsed.get("command", heard)
    normalized_command = normalize_text(command)
    if normalized_command in {"me escuchas", "me oyes", "estas ahi"}:
        response_text = "Sí, te escucho."
        schedule_speech(response_text)
        return {"ok": True, "heard": heard, "parsed": parsed, "response": response_text}

    cached = cached_repetitive_answer(command)
    if cached:
        response_text = cached.get("answer", "")
        if response_text:
            schedule_speech(response_text)
            return {
                "ok": True,
                "heard": heard,
                "parsed": parsed,
                "memory": {"kind": "repetitive_answer", **cached},
                "response": response_text,
            }

    context = await collect_codex_context()
    started_at = time.monotonic()
    try:
        announce_codex_handoff()
        codex_result = await run_agent_call(CodexBridge().run, command, context)
    except CodexBridgeDisabled:
        return {"ok": True, "heard": heard, "parsed": parsed, "needs_codex": True}
    except CodexQuotaExceeded:
        response_text = "Codex ha agotado su cuota. La conexión funciona, pero no puede procesar más consultas ahora."
        schedule_speech(response_text)
        return {"ok": False, "heard": heard, "parsed": parsed, "codex_error": "quota_exceeded", "response": response_text}

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    route_entry = remember_codex_route(State(), command, codex_result, elapsed_ms)
    repetitive_memory = maybe_remember_repetitive_answer(command, codex_result, route_entry)
    response = {"ok": True, "heard": heard, "parsed": parsed, "codex": codex_result}
    if repetitive_memory.get("saved"):
        response["memory"] = {"kind": "repetitive_answer_saved", **repetitive_memory}
    codex_parsed = codex_result.get("parsed", {})
    if _codex_did_not_understand(codex_parsed):
        response_text = "No entendí la instrucción."
        schedule_speech(response_text)
        response["response"] = response_text
        return response
    response_text = codex_parsed.get("text") or codex_parsed.get("question")
    if response_text:
        schedule_speech(response_text)
        response["response"] = response_text
    should_auto_execute = codex_auto_execute_tools() or str(codex_parsed.get("tool", "")).startswith("memory.")
    if should_auto_execute and codex_parsed.get("kind") == "mcp" and codex_parsed.get("tool"):
        try:
            response["result"] = await execute_tool(
                codex_parsed["tool"],
                codex_parsed.get("args", {}),
            )
            _update_computer_audio_guard(
                {"tool": codex_parsed.get("tool"), "args": codex_parsed.get("args", {})}
            )
        except Exception as error:
            response_text = tool_error_feedback(
                {"tool": codex_parsed.get("tool"), "args": codex_parsed.get("args", {})},
                error,
            )
            if not response_text:
                raise
            schedule_speech(response_text)
            response["result"] = {"ok": False, "error": str(error)}
            response["feedback"] = "repeat"
            response["response"] = response_text
    return response


def announce_codex_handoff() -> str:
    response_text = "Voy a consultarlo con Codex."
    schedule_speech(response_text)
    return response_text


async def handle_tool_path(heard: str, parsed: Dict[str, Any]):
    try:
        execution = await execute_goal(parsed) if parsed.get("goal") else None
        result = execution["result"] if execution else await execute_tool(parsed["tool"], parsed.get("args", {}))
        _update_computer_audio_guard(parsed)
        response = {"ok": True, "heard": heard, "parsed": parsed, "result": result}
        if execution:
            response["execution"] = execution
            if not execution.get("verified", True):
                response_text = tool_result_feedback(parsed, result)
                if response_text:
                    schedule_speech(response_text)
                    response["feedback"] = "unavailable"
                    response["response"] = response_text
        response_text = tool_success_feedback(parsed, result) if not response.get("response") else ""
        if response_text:
            schedule_speech(response_text)
            response["response"] = response_text
        return response
    except Exception as error:
        response_text = tool_error_feedback(parsed, error)
        if not response_text:
            raise
        schedule_speech(response_text)
        return {
            "ok": True,
            "kind": "feedback",
            "heard": heard,
            "parsed": parsed,
            "result": {"ok": False, "error": str(error)},
            "feedback": "repeat",
            "response": response_text,
        }


async def execute_goal(parsed: Dict[str, Any]) -> Dict[str, Any]:
    goal = parsed.get("goal") or {}
    actions = goal.get("actions") or []
    max_actions = _goal_limit(goal, "max_actions", default=5, minimum=1)
    max_replans = _goal_limit(goal, "max_replans", default=1, minimum=0)
    observations = []
    last_result: Dict[str, Any] = {}
    if len(actions) > max_actions:
        return _goal_failed(
            goal,
            observations,
            {"ok": False, "error": "goal exceeds max_actions"},
            "definitive",
            max_replans,
        )
    for index, action in enumerate(actions):
        tool = str(action.get("tool") or "")
        args = resolve_action_args(action, observations)
        try:
            result = await execute_tool(tool, args)
        except Exception as error:
            result = {"ok": False, "error": str(error), "error_type": error.__class__.__name__}
        observation = observe_action(index, action, result, goal.get("observe", "tool_result"))
        observations.append(observation)
        last_result = result if isinstance(result, dict) else {"ok": True, "value": result}
        if not verify_observation(observation, action, goal):
            return _goal_failed(goal, observations, last_result, failure_type(last_result), max_replans)
    return {
        "ok": True,
        "goal": goal.get("objective", ""),
        "observations": observations,
        "verified": True,
        "replan_required": False,
        "replan": "none",
        "replan_attempts": 0,
        "max_replans": max_replans,
        "status": "finished",
        "result": last_result,
    }


def resolve_action_args(action: Dict[str, Any], observations: list[Dict[str, Any]]) -> Dict[str, Any]:
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    return {key: resolve_action_value(value, observations) for key, value in args.items()}


def resolve_action_value(value: Any, observations: list[Dict[str, Any]]) -> Any:
    if not isinstance(value, dict) or set(value) != {"from_observation"}:
        return value
    selector = value.get("from_observation")
    if not isinstance(selector, dict):
        return ""
    index = int(selector.get("index", -1))
    path = str(selector.get("path", "result")).split(".")
    if index < 0 or index >= len(observations):
        return ""
    current: Any = observations[index]
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return current


def observe_action(index: int, action: Dict[str, Any], result: Any, goal_observer: str = "tool_result") -> Dict[str, Any]:
    observer = str(action.get("observe") or goal_observer or "tool_result")
    observe = OBSERVERS.get(observer, observe_tool_result)
    observation = {
        "index": index,
        "tool": action.get("tool", ""),
        "observer": observer,
        "result": result,
    }
    observation.update(observe(result, action))
    return observation


def verify_observation(observation: Dict[str, Any], action: Dict[str, Any] | None = None, goal: Dict[str, Any] | None = None) -> bool:
    verifier_name = str((action or {}).get("verify") or (goal or {}).get("verify") or "tool_result_ok")
    verifier = VERIFIERS.get(verifier_name, verify_tool_result)
    return verifier(observation)


def observe_tool_result(result: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": tool_result_ok(result)}


def verify_tool_result(observation: Dict[str, Any]) -> bool:
    return bool(observation.get("ok"))


def verify_web_opened(observation: Dict[str, Any]) -> bool:
    result = observation.get("result")
    return isinstance(result, dict) and result.get("ok") is not False and bool(result.get("url"))


def verify_music_action(observation: Dict[str, Any]) -> bool:
    result = observation.get("result")
    if isinstance(result, dict) and result.get("playing") is False:
        return False
    return tool_result_ok(result)


def tool_result_ok(result: Any) -> bool:
    if isinstance(result, dict) and result.get("ok") is False:
        return False
    return True


def failure_type(result: Dict[str, Any]) -> str:
    error = str(result.get("error") or "").lower()
    if "empty" in error or "required" in error or "missing" in error:
        return "insufficient_info"
    if result.get("error_type") in {"HTTPException", "ToolContractError"}:
        return "definitive"
    return "recoverable"


def _goal_failed(
    goal: Dict[str, Any],
    observations: list[Dict[str, Any]],
    result: Dict[str, Any],
    kind: str,
    max_replans: int,
) -> Dict[str, Any]:
    can_replan = kind in {"recoverable", "insufficient_info"} and max_replans > 0
    return {
        "ok": False,
        "goal": goal.get("objective", ""),
        "observations": observations,
        "verified": False,
        "replan_required": can_replan,
        "failure": {"type": kind, "action": len(observations) - 1 if observations else None},
        "replan": goal.get("replan") or "ask_or_escalate_on_failed_verification",
        "replan_attempts": 0,
        "max_replans": max_replans,
        "status": "replan_required" if can_replan else "failed",
        "result": result,
    }


def _goal_limit(goal: Dict[str, Any], key: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(goal.get(key, default)))
    except (TypeError, ValueError):
        return default


OBSERVERS = {
    "tool_result": observe_tool_result,
}

VERIFIERS = {
    "tool_result_ok": verify_tool_result,
    "web_opened": verify_web_opened,
    "music_action_ok": verify_music_action,
}


async def handle_memory_path(heard: str, parsed: Dict[str, Any]):
    result = await execute_tool("memory.remember", parsed.get("args", {}))
    response_text = "Lo recordé."
    schedule_speech(response_text)
    return {"ok": True, "heard": heard, "parsed": parsed, "result": result, "response": response_text}


async def handle_status_path(heard: str, parsed: Dict[str, Any]):
    if parsed.get("command") == "codex":
        from core.codex_bridge import CodexBridge, CodexBridgeError

        try:
            result = await run_agent_call(CodexBridge().test_connection)
            response_text = f"Sí, Codex está disponible: {result['version']}."
            ok = True
        except CodexBridgeError as error:
            response_text = f"No tengo conexión usable con Codex: {error}"
            ok = False
        schedule_speech(response_text)
        return {"ok": ok, "heard": heard, "parsed": parsed, "response": response_text}
    response_text = "No logro revisar ese estado todavía."
    schedule_speech(response_text)
    return {"ok": False, "heard": heard, "parsed": parsed, "response": response_text}


async def handle_local_path(heard: str, parsed: Dict[str, Any]):
    from datetime import datetime
    from core.listener_control import request_shutdown, rest_listener

    now = datetime.now().astimezone()
    if parsed.get("command") == "time":
        response_text = _format_spoken_time(now)
    elif parsed.get("command") == "date":
        response_text = _format_spoken_date(now)
    elif parsed.get("command") == "assistant_status":
        response_text = "Estoy bien, te escucho."
    elif parsed.get("command") == "rest":
        response_text = "Nos vemos luego"
        rest_listener()
    elif parsed.get("command") == "shutdown":
        response_text = "Nos vemos luego"
        request_shutdown()
    else:
        response_text = "Eso puedo responderlo localmente, pero todavía no tengo esa respuesta preparada."
    schedule_speech(response_text)
    return {"ok": True, "heard": heard, "parsed": parsed, "response": response_text}


async def collect_codex_context() -> Dict[str, Any]:
    from core.state import State
    from core.memory_files import read_memory_context

    state = State()
    context: Dict[str, Any] = {
        "lastTranscript": state.get("lastTranscript"),
        "lastCommand": state.get("lastCommand"),
        "voiceSession": state.get("voiceSession"),
        "lastMusicSearch": state.get("lastMusicSearch"),
        "memory": read_memory_context(),
    }
    browser_state = browser.snapshot_state()
    if browser_state:
        context["browserState"] = browser_state
    return context


@app.post("/call")
async def call(req: CallRequest):
    try:
        if not req.tool:
            raise HTTPException(status_code=400, detail="tool is required")

        result = await execute_tool(req.tool, req.args)
        return {"ok": True, "result": result}
    except Exception as e:
        return error_response(e)


def error_response(e: Exception) -> Dict[str, Any]:
    if isinstance(e, TimeoutError):
        return {"ok": False, "error": "tool timed out"}
    if e.__class__.__name__ in {"BrowserProfileInUse", "BrowserCdpUnavailable"}:
        return {"ok": False, "error": str(e)}
    tb = traceback.format_exc()
    return {"ok": False, "error": str(e), "trace": tb}


def repeat_response_text(parsed: Dict[str, Any]) -> str:
    reason = parsed.get("reason")
    if reason == "command not understood":
        return "Te escuché, pero no entendí el comando."
    return "No logro entenderte."


def tool_error_feedback(parsed: Dict[str, Any], error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError) and str(parsed.get("tool") or "").startswith("youtube_music."):
        return "YouTube Music tardó demasiado en responder. Reinténtalo en unos segundos."
    if error.__class__.__name__ == "SystemVolumeUnavailable":
        return volume_unavailable_feedback(parsed, str(error))
    if error.__class__.__name__ != "SystemAppNotFound":
        return ""
    tool = parsed.get("tool")
    name = _tool_app_name(parsed.get("args", {}))
    if tool == "system.open_app":
        if name:
            return f"No encontré la aplicación {name}."
        return "No entendí qué aplicación quieres abrir."
    if tool == "system.close_app":
        if name:
            return f"No encontré abierta la aplicación {name}."
        return "No entendí qué aplicación quieres cerrar."
    return ""


def tool_result_feedback(parsed: Dict[str, Any], result: Dict[str, Any]) -> str:
    if not isinstance(result, dict) or result.get("ok") is not False:
        return ""
    if result.get("error_type") == "SystemVolumeUnavailable":
        return volume_unavailable_feedback(parsed, str(result.get("error") or ""))
    return ""


def tool_success_feedback(parsed: Dict[str, Any], result: Dict[str, Any]) -> str:
    if not isinstance(result, dict) or result.get("ok") is False:
        return ""
    tool = parsed.get("tool")
    if tool == "browser.ensure_cdp":
        if result.get("status") == "already_available":
            return "El navegador ya se encuentra abierto."
        return "Navegador listo."
    return ""


def volume_unavailable_feedback(parsed: Dict[str, Any], error: str) -> str:
    if parsed.get("tool") != "system.set_volume":
        return ""
    if "exact volume" in error:
        return "No puedo fijar un volumen exacto todavía. Puedo subirlo o bajarlo por pasos."
    return "No pude cambiar el volumen."


def _tool_app_name(args: Dict[str, Any]) -> str:
    return str(args.get("name") or args.get("app") or args.get("application") or "").strip()


def _codex_did_not_understand(codex_parsed: Dict[str, Any]) -> bool:
    kind = codex_parsed.get("kind")
    if not kind:
        return True
    if kind == "ignore":
        return True
    if kind == "ask_user" and not codex_parsed.get("question"):
        return True
    return False


def _memory_write_allowed() -> bool:
    from core.config import get_bool

    return get_bool("memory.allow_codex_write", True)


def _format_spoken_time(now) -> str:
    hour = now.hour
    minute = now.minute
    suffix = "a. m." if hour < 12 else "p. m."
    spoken_hour = hour % 12 or 12
    if minute == 0:
        return f"Son las {spoken_hour} en punto {suffix}"
    return f"Son las {spoken_hour}:{minute:02d} {suffix}"


def _format_spoken_date(now) -> str:
    weekdays = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return f"Hoy es {weekdays[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}."


def remember_codex_route(state, command: str, codex_result: Dict[str, Any], elapsed_ms: int) -> Dict[str, Any]:
    from core.memory_files import record_learned_route
    from voice.normalize import normalize_text

    normalized = normalize_text(command)
    if not normalized:
        return {}
    learned = state.get("learnedCodexRoutes", {})
    entry = learned.get(normalized, {"count": 0})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["lastElapsedMs"] = elapsed_ms
    entry["lastKind"] = codex_result.get("parsed", {}).get("kind")
    entry["lastText"] = codex_result.get("parsed", {}).get("text")
    learned[normalized] = entry
    state.set("learnedCodexRoutes", learned)
    file_entry = record_learned_route(command, codex_result, elapsed_ms)
    return file_entry or entry


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
