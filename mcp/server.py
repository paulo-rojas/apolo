from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import traceback
from typing import Any, Dict

app = FastAPI(title="apolo MCP")


class CallRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


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


browser = BrowserProxy()


@app.post("/call")
async def call(req: CallRequest):
    try:
        if not req.tool:
            raise HTTPException(status_code=400, detail="tool is required")

        if req.tool.startswith("browser."):
            method = req.tool.split(".", 1)[1]
            result = browser.call(method, req.args)
            return {"ok": True, "result": result}

        raise HTTPException(status_code=400, detail=f"Unknown tool: {req.tool}")
    except Exception as e:
        tb = traceback.format_exc()
        return {"ok": False, "error": str(e), "trace": tb}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
