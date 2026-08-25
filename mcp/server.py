import asyncio
import contextvars
import queue
import threading
import traceback
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="apolo MCP")


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
                loop.call_soon_threadsafe(future.set_exception, e)
            else:
                loop.call_soon_threadsafe(future.set_result, result)

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
            except Exception as e:
                raise RuntimeError(f"No browser implementation available: {e}")

    def call(self, method: str, args: Dict[str, Any]):
        self._ensure()
        fn = getattr(self._impl, method, None)
        if fn is None:
            raise AttributeError(f"Browser has no method {method}")
        return fn(**args)

    def snapshot_state(self):
        if self._impl is None:
            return None
        snapshot = getattr(self._impl, "snapshot_state", None)
        if snapshot is None:
            return None
        return snapshot()


browser = BrowserProxy()


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
            args["query_or_candidate"] = args.pop("query")
        fn = getattr(self._impl, method, None)
        if fn is None:
            raise AttributeError(f"YouTube Music has no method {method}")
        return fn(**args)


music = MusicProxy(browser)


async def run_agent_call(fn, *args, **kwargs):
    return await agent_worker.call(fn, *args, **kwargs)


async def execute_tool(tool: str, args: Dict[str, Any]):
    if tool.startswith("browser."):
        method = tool.split(".", 1)[1]
        return await run_agent_call(browser.call, method, args)

    if tool.startswith("youtube_music."):
        method = tool.split(".", 1)[1]
        return await run_agent_call(music.call, method, args)

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
        if parsed.get("kind") in {"ignore", "session"}:
            return parsed
        if req.dry_run:
            return {"ok": True, "heard": req.text, "parsed": parsed}
        if parsed.get("kind") == "codex":
            return await handle_codex_path(req.text, parsed)
        result = await execute_tool(parsed["tool"], parsed.get("args", {}))
        return {"ok": True, "heard": req.text, "parsed": parsed, "result": result}
    except Exception as e:
        return error_response(e)


async def handle_codex_path(heard: str, parsed: Dict[str, Any]):
    from core.codex_bridge import CodexBridge, CodexBridgeDisabled, codex_auto_execute_tools

    context = await collect_codex_context()
    try:
        codex_result = await run_agent_call(CodexBridge().run, parsed.get("command", heard), context)
    except CodexBridgeDisabled:
        return {"ok": True, "heard": heard, "parsed": parsed, "needs_codex": True}

    response = {"ok": True, "heard": heard, "parsed": parsed, "codex": codex_result}
    codex_parsed = codex_result.get("parsed", {})
    if (
        codex_auto_execute_tools()
        and codex_parsed.get("kind") == "mcp"
        and codex_parsed.get("tool")
    ):
        response["result"] = await execute_tool(
            codex_parsed["tool"],
            codex_parsed.get("args", {}),
        )
    return response


async def collect_codex_context() -> Dict[str, Any]:
    from core.state import State

    state = State()
    context: Dict[str, Any] = {
        "lastTranscript": state.get("lastTranscript"),
        "lastCommand": state.get("lastCommand"),
        "voiceSession": state.get("voiceSession"),
        "lastMusicSearch": state.get("lastMusicSearch"),
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
    if e.__class__.__name__ in {"BrowserProfileInUse", "BrowserCdpUnavailable"}:
        return {"ok": False, "error": str(e)}
    tb = traceback.format_exc()
    return {"ok": False, "error": str(e), "trace": tb}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
