"""Local HTTP bridge that lets sandboxed code call MCP tools securely."""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any, Dict, Sequence, TypedDict

from aiohttp import web


LOGGER = logging.getLogger(__name__)


class ToolBridgeSession(TypedDict):
    """Metadata returned to sandboxes so they can reach the bridge."""

    endpoint: str
    token: str


class MCPToolBridge:
    """Hosts an HTTP endpoint that proxies requests to MCP tools."""

    def __init__(self, tools: Sequence[Any] | None = None) -> None:
        self._tools: Dict[str, Any] = {}
        self.update_tools(tools or [])
        self._app = web.Application()
        self._app.router.add_post("/call", self._handle_call)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._base_url: str | None = None
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def update_tools(self, tools: Sequence[Any]) -> None:
        """Refresh the internal mapping of tool name -> callable."""

        mapping: Dict[str, Any] = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if not isinstance(name, str) or not name:
                continue
            mapping[name] = tool
        self._tools = mapping

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        sockets = getattr(self._site._server, "sockets", None)  # type: ignore[attr-defined]
        if not sockets:
            raise RuntimeError("Failed to start MCP tool bridge; no sockets bound")
        port = sockets[0].getsockname()[1]
        self._base_url = f"http://127.0.0.1:{port}/call"
        LOGGER.info("MCP tool bridge listening on %s", self._base_url)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._base_url = None
        self._sessions.clear()

    async def create_session(self, *, timeout: int = 120) -> ToolBridgeSession:
        if self._base_url is None:
            raise RuntimeError("Tool bridge has not been started")
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "expires": time.time() + timeout,
            "timeout": timeout,
        }
        return {"endpoint": self._base_url, "token": token}

    def invalidate_session(self, token: str) -> None:
        self._sessions.pop(token, None)

    async def _handle_call(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

        token = payload.get("token")
        name = payload.get("name")
        params = payload.get("params") or {}

        if not isinstance(token, str) or token not in self._sessions:
            return web.json_response({"success": False, "error": "Invalid token"}, status=403)

        session = self._sessions[token]
        if session["expires"] < time.time():
            self._sessions.pop(token, None)
            return web.json_response({"success": False, "error": "Session expired"}, status=403)

        tool = self._tools.get(str(name))
        if tool is None:
            return web.json_response(
                {"success": False, "error": f"Unknown tool: {name}"},
                status=404,
            )

        try:
            handler = getattr(tool, "acall", None)
            if callable(handler):
                result = handler(**params)
            else:
                result = tool(**params)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:  # pragma: no cover - depends on tool implementation
            LOGGER.exception("Tool %s failed", name)
            return web.json_response(
                {"success": False, "error": str(exc)},
                status=500,
            )

        session["expires"] = time.time() + session["timeout"]
        return web.json_response({"success": True, "result": result})


__all__ = ["MCPToolBridge", "ToolBridgeSession"]
