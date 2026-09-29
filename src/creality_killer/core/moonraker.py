"""Async client for the Moonraker API (REST + WebSocket JSON-RPC).

Docs: https://moonraker.readthedocs.io/en/latest/external_api/introduction/
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import websockets

log = logging.getLogger(__name__)

DEFAULT_PORT = 7125

# Objects we always want when the printer exposes them. Any heater_generic /
# temperature_* object is added dynamically (the K1C's chamber sensor name is
# not something we can assume).
WANTED_OBJECTS = (
    "print_stats",
    "virtual_sdcard",
    "display_status",
    "toolhead",
    "gcode_move",
    "extruder",
    "heater_bed",
    "fan",
    "webhooks",
    "idle_timeout",
)
DYNAMIC_PREFIXES = ("heater_generic ", "temperature_sensor ", "temperature_fan ", "fan_generic ")


class MoonrakerError(Exception):
    pass


class AuthError(MoonrakerError):
    """401/403 - usually the client IP is missing from trusted_clients."""


def _quote_path(path: str) -> str:
    return quote(path, safe="/")


class MoonrakerClient:
    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/websocket"
        headers = {"X-Api-Key": api_key} if api_key else {}
        self._http = httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._ws: Any = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ REST
    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise MoonrakerError(f"{method} {path}: {e!r}") from e
        if r.status_code in (401, 403):
            raise AuthError(
                f"{r.status_code} from Moonraker - add this machine's IP to "
                "[authorization] trusted_clients or supply an API key"
            )
        if r.status_code >= 400:
            raise MoonrakerError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
        return r

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        r = await self._request(method, path, **kw)
        return r.json().get("result")

    async def server_info(self) -> dict:
        return await self._json("GET", "/server/info")

    async def printer_info(self) -> dict:
        return await self._json("GET", "/printer/info")

    async def list_objects(self) -> list[str]:
        return (await self._json("GET", "/printer/objects/list"))["objects"]

    async def query_objects(self, objects: dict[str, list[str] | None]) -> dict:
        params = "&".join(
            k.replace(" ", "%20") + ("=" + ",".join(v) if v else "") for k, v in objects.items()
        )
        return (await self._json("GET", f"/printer/objects/query?{params}"))["status"]

    async def list_files(self, root: str = "gcodes") -> list[dict]:
        """Files in `root`; each has path, modified, size."""
        return await self._json("GET", "/server/files/list", params={"root": root})

    async def file_metadata(self, filename: str) -> dict:
        return await self._json("GET", "/server/files/metadata", params={"filename": filename})

    async def download(self, path: str, root: str = "gcodes") -> bytes:
        r = await self._request("GET", f"/server/files/{root}/{_quote_path(path)}")
        return r.content

    async def download_thumbnail(self, gcode_path: str, relative_path: str) -> bytes:
        parent = gcode_path.rsplit("/", 1)[0] + "/" if "/" in gcode_path else ""
        return await self.download(parent + relative_path)

    async def upload(self, name: str, data: bytes | Path, root: str = "gcodes") -> dict:
        payload = data.read_bytes() if isinstance(data, Path) else data
        files = {"file": (name, payload, "application/octet-stream")}
        return await self._json("POST", "/server/files/upload", files=files, data={"root": root})

    async def delete_file(self, path: str, root: str = "gcodes") -> dict:
        return await self._json("DELETE", f"/server/files/{root}/{_quote_path(path)}")

    async def webcams(self) -> list[dict]:
        return (await self._json("GET", "/server/webcams/list"))["webcams"]

    def resolve_webcam_url(self, url: str) -> str:
        """Webcam URLs are often relative ('/webcam/?action=stream') or on another port."""
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("/"):
            # relative to whatever served the UI - fall back to the printer host
            return f"http://{self.host}{url}"
        return url

    # Print control. Only ever called from an explicit user action.
    async def start_print(self, filename: str) -> None:
        await self._request("POST", "/printer/print/start", params={"filename": filename})

    async def pause_print(self) -> None:
        await self._request("POST", "/printer/print/pause")

    async def resume_print(self) -> None:
        await self._request("POST", "/printer/print/resume")

    async def cancel_print(self) -> None:
        await self._request("POST", "/printer/print/cancel")

    # ------------------------------------------------------------- WebSocket
    async def _rpc(self, method: str, params: dict | None = None, timeout: float = 10.0) -> Any:
        rid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        msg = {"jsonrpc": "2.0", "method": method, "id": rid}
        if params is not None:
            msg["params"] = params
        await self._ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    async def subscribe_forever(
        self,
        on_status: Callable[[dict], None],
        on_connection: Callable[[str], None] | None = None,
        on_event: Callable[[str, list], None] | None = None,
    ) -> None:
        """Connect, subscribe, and stream status deltas; reconnect with backoff."""
        delay = 1.0
        while True:
            try:
                if on_connection:
                    on_connection("connecting")
                async with websockets.connect(self.ws_url, max_size=None) as ws:
                    self._ws = ws
                    reader = asyncio.create_task(self._read_loop(ws, on_status, on_event))
                    try:
                        await self._rpc(
                            "server.connection.identify",
                            {
                                "client_name": "creality_killer",
                                "version": "0.1.0",
                                "type": "desktop",
                                "url": "https://github.com/grantcary/creality_killer",
                            },
                        )
                        available = (await self._rpc("printer.objects.list"))["objects"]
                        wanted = {
                            o: None
                            for o in available
                            if o in WANTED_OBJECTS or o.startswith(DYNAMIC_PREFIXES)
                        }
                        result = await self._rpc("printer.objects.subscribe", {"objects": wanted})
                        on_status(result["status"])
                        if on_connection:
                            on_connection("connected")
                        delay = 1.0
                        await reader
                    finally:
                        reader.cancel()
                        self._ws = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep the link alive on anything
                log.warning("websocket dropped: %r", e)
            if on_connection:
                on_connection("disconnected")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)

    async def _read_loop(self, ws: Any, on_status: Callable, on_event: Callable | None) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self._pending:
                fut = self._pending[msg["id"]]
                if "error" in msg:
                    fut.set_exception(MoonrakerError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result"))
            elif msg.get("method") == "notify_status_update":
                on_status(msg["params"][0])
            elif on_event and "method" in msg:
                on_event(msg["method"], msg.get("params", []))


AsyncCallback = Callable[..., Awaitable[Any]]
