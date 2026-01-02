"""WebSocket bridge that streams gacha pull payloads to the browser overlay.

The overlay HTML (media/gacha/gacha_overlay/index.html) connects to this server
via WebSocket and receives structured payloads that instruct it to animate the
latest set of pulls. This decouples the gacha animation pipeline from OBS
scene manipulation so the browser source can render the animation itself.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from asyncio import AbstractServer
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from tools import debug_print


class GachaOverlayBridge:
    """Small WebSocket server that multiplexes gacha payloads to browsers."""

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 17890
    DEFAULT_PATH = "/gacha"

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        path: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        self.host = (host or self.DEFAULT_HOST).strip() or self.DEFAULT_HOST
        self.port = int(port or self.DEFAULT_PORT)
        normalized_path = (path or self.DEFAULT_PATH).strip() or self.DEFAULT_PATH
        self.path = normalized_path if normalized_path.startswith("/") else f"/{normalized_path}"
        token = (auth_token or "").strip()
        self.auth_token = token or None

        self._server: AbstractServer | None = None
        self._clients: set[WebSocketServerProtocol] = set()
        self._client_state: dict[WebSocketServerProtocol, dict[str, Any]] = {}
        self._startup_lock = asyncio.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._server is not None

    @property
    def connected_clients(self) -> int:
        return len(self._clients)

    async def ensure_started(self) -> None:
        if self.is_running:
            return
        async with self._startup_lock:
            if self.is_running:
                return
            try:
                self._server = await serve(
                    self._handle_client,
                    self.host,
                    self.port,
                    ping_interval=20,
                    ping_timeout=20,
                    max_queue=64,
                )
                self._running = True
                debug_print(
                    "GachaOverlay",
                    f"Listening for overlay clients on ws://{self.host}:{self.port}{self.path}",
                )
            except Exception as exc:  # pragma: no cover - startup errors are logged for visibility
                debug_print("GachaOverlay", f"Unable to start overlay bridge: {exc}")
                self._server = None
                self._running = False
                raise

    async def shutdown(self) -> None:
        if not self._server:
            return
        debug_print("GachaOverlay", "Shutting down overlay bridge.")
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self._running = False
        await asyncio.gather(*[self._safe_close(ws) for ws in list(self._clients)], return_exceptions=True)
        self._clients.clear()
        self._client_state.clear()

    async def send_gacha_pulls(
        self,
        user_id: str,
        total_pulls: int,
        pulls: list[dict[str, Any]],
        display_name: str = "",
        set_name: str = "",
    ) -> bool:
        """Broadcast the latest pulls to all connected overlay clients."""
        payload = {
            "type": "gacha_pulls",
            "payload": {
                "userId": user_id,
                "totalPulls": total_pulls,
                "pulls": pulls,
                "timestamp": time.time(),
                "displayName": display_name,
                "setName": set_name
            },
        }
        return await self._broadcast(payload)

    async def send_clear(self) -> bool:
        """Instruct connected overlays to clear their stage."""
        return await self._broadcast({"type": "clear"})

    async def _broadcast(self, envelope: dict[str, Any]) -> bool:
        await self.ensure_started()
        if not self._clients:
            debug_print("GachaOverlay", "No overlay clients are connected; skipping broadcast.")
            return False
        recipients = [
            ws for ws in self._clients if self._client_state.get(ws, {}).get("authenticated", True)
        ]
        if not recipients:
            debug_print("GachaOverlay", "Overlay clients connected, but none authenticated.")
            return False
        message = json.dumps(envelope)
        delivered = 0
        stale: list[WebSocketServerProtocol] = []
        for ws in recipients:
            try:
                await ws.send(message)
                delivered += 1
            except Exception as exc:
                debug_print("GachaOverlay", f"Failed to deliver message to an overlay client: {exc}")
                stale.append(ws)
        for ws in stale:
            await self._safe_close(ws)
        if delivered == 0:
            debug_print("GachaOverlay", "Overlay broadcast failed; no clients accepted the payload.")
            return False
        return True

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        if self.path and websocket.path != self.path:
            await websocket.close(code=1008, reason="Invalid overlay path")
            return
        state = {"authenticated": self.auth_token is None, "connected_at": time.time()}
        self._clients.add(websocket)
        self._client_state[websocket] = state
        debug_print("GachaOverlay", f"Overlay client connected from {self._peer_label(websocket)}")
        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "version": 1,
                        "requiresAuth": bool(self.auth_token),
                    }
                )
            )
            async for message in websocket:
                await self._handle_client_message(websocket, message, state)
        except ConnectionClosed:
            pass
        except Exception as exc:
            debug_print("GachaOverlay", f"Overlay client handler error: {exc}")
        finally:
            self._clients.discard(websocket)
            self._client_state.pop(websocket, None)
            debug_print("GachaOverlay", f"Overlay client disconnected: {self._peer_label(websocket)}")

    async def _handle_client_message(
        self,
        websocket: WebSocketServerProtocol,
        message: str,
        state: dict[str, Any],
    ) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            debug_print("GachaOverlay", "Received malformed JSON from overlay client.")
            return
        msg_type = payload.get("type")
        if msg_type == "ready":
            await self._handle_ready(websocket, payload, state)
        elif msg_type == "ping":
            await self._safe_send(websocket, {"type": "pong", "ts": payload.get("ts")})
        elif msg_type == "pong":
            state["last_pong"] = time.time()
        # Other message types are ignored for now.

    async def _handle_ready(
        self,
        websocket: WebSocketServerProtocol,
        payload: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        if state.get("authenticated"):
            return
        if self.auth_token:
            provided = (payload.get("token") or "").strip()
            if provided != self.auth_token:
                await self._safe_send(websocket, {"type": "error", "code": "unauthorized"})
                await websocket.close(code=4003, reason="Invalid token")
                return
        state["authenticated"] = True
        await self._safe_send(websocket, {"type": "ready_ack"})
        debug_print("GachaOverlay", f"Overlay client authenticated: {self._peer_label(websocket)}")

    async def _safe_send(self, websocket: WebSocketServerProtocol, payload: dict[str, Any]) -> None:
        try:
            await websocket.send(json.dumps(payload))
        except Exception:
            pass

    async def _safe_close(self, websocket: WebSocketServerProtocol) -> None:
        try:
            await websocket.close()
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            self._client_state.pop(websocket, None)

    @staticmethod
    def _peer_label(websocket: WebSocketServerProtocol) -> str:
        peer = websocket.remote_address
        if not peer:
            return "unknown"
        host, *rest = peer
        if rest:
            return f"{host}:{rest[0]}"
        return str(host)


__all__ = ["GachaOverlayBridge"]
