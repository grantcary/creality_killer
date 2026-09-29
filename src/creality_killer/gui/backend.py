"""Runs the asyncio Moonraker client on its own thread and bridges results to Qt signals."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal

from creality_killer.core.gcode import Toolpath, parse_gcode
from creality_killer.core.moonraker import MoonrakerClient


class Backend(QObject):
    status = Signal(dict)  # status delta
    connection = Signal(str)  # connecting / connected / disconnected
    event = Signal(str, list)  # raw Moonraker notification
    _done = Signal(object, object, object)  # callback, value, exception

    def __init__(self, host: str, port: int = 7125) -> None:
        super().__init__()
        self.client = MoonrakerClient(host, port)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="moonraker", daemon=True)
        self._done.connect(self._deliver)

    def start(self) -> None:
        self._thread.start()
        asyncio.run_coroutine_threadsafe(
            self.client.subscribe_forever(
                self.status.emit, self.connection.emit, lambda m, p: self.event.emit(m, list(p))
            ),
            self._loop,
        )

    def stop(self) -> None:
        if self._thread.is_alive():
            asyncio.run_coroutine_threadsafe(self.client.aclose(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(
        self,
        coro: Coroutine[Any, Any, Any],
        ok: Callable[[Any], None] | None = None,
        err: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run `coro` on the backend loop; `ok`/`err` run on the Qt thread."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def finished(f):
            exc = f.exception()
            self._done.emit(err if exc else ok, None if exc else f.result(), exc)

        fut.add_done_callback(finished)

    def _deliver(self, cb, value, exc) -> None:
        if cb is None:
            return
        cb(exc if exc is not None else value)

    # ---- composite operations
    async def load_toolpath(self, path: str) -> tuple[str, Toolpath]:
        data = await self.client.download(path)
        # parsing is CPU-bound python: keep it off the websocket loop
        tp = await asyncio.get_running_loop().run_in_executor(None, parse_gcode, data)
        return path, tp

    async def load_card(self, path: str) -> tuple[str, dict, bytes | None]:
        """Metadata plus the smallest embedded thumbnail >= 100px, if any."""
        meta = await self.client.file_metadata(path)
        thumbs = sorted(meta.get("thumbnails") or [], key=lambda t: t.get("width", 0))
        pick = next((t for t in thumbs if t.get("width", 0) >= 100), thumbs[-1] if thumbs else None)
        img = None
        if pick:
            img = await self.client.download_thumbnail(path, pick["relative_path"])
        return path, meta, img
