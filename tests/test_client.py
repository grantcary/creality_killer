import asyncio
import json

import httpx
import pytest
import websockets

from creality_killer.core.moonraker import AuthError, MoonrakerClient
from creality_killer.core.state import PrinterState


def make_client(handler):
    return MoonrakerClient("printer.local", transport=httpx.MockTransport(handler))


async def test_list_and_download_urls():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url)
        if req.url.path == "/server/files/list":
            return httpx.Response(200, json={"result": [{"path": "a b.gcode", "size": 3}]})
        return httpx.Response(200, content=b"G28")

    c = make_client(handler)
    assert (await c.list_files())[0]["path"] == "a b.gcode"
    assert await c.download("sub dir/a b.gcode") == b"G28"
    assert seen[1].raw_path == b"/server/files/gcodes/sub%20dir/a%20b.gcode"
    assert await c.download_thumbnail("sub dir/a.gcode", ".thumbs/a-300x300.png") == b"G28"
    assert seen[2].raw_path == b"/server/files/gcodes/sub%20dir/.thumbs/a-300x300.png"


async def test_403_is_auth_error():
    c = make_client(lambda r: httpx.Response(403))
    with pytest.raises(AuthError):
        await c.server_info()


async def test_upload_sends_multipart():
    def handler(req: httpx.Request):
        assert req.url.path == "/server/files/upload"
        assert b'name="file"; filename="x.gcode"' in req.content
        assert b'name="root"' in req.content
        return httpx.Response(201, json={"result": {"item": {"path": "x.gcode"}}})

    assert (await make_client(handler).upload("x.gcode", b"G28"))["item"]["path"] == "x.gcode"


async def test_websocket_subscribe_and_deltas():
    async def server(ws):
        async for raw in ws:
            m = json.loads(raw)
            if m["method"] == "printer.objects.list":
                res = {"objects": ["extruder", "gcode_macro X", "temperature_sensor chamber"]}
            elif m["method"] == "printer.objects.subscribe":
                assert set(m["params"]["objects"]) == {"extruder", "temperature_sensor chamber"}
                res = {"status": {"extruder": {"temperature": 25.0, "target": 0.0}}}
            else:
                res = "ok"
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}))
            if m["method"] == "printer.objects.subscribe":
                await ws.send(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update",
                                          "params": [{"extruder": {"temperature": 30.0}}, 1.0]}))

    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        client = MoonrakerClient("127.0.0.1", port)
        state, conn = PrinterState(), []
        got_delta = asyncio.Event()

        def on_status(d):
            state.apply(d)
            if state.temp("extruder") == (30.0, 0.0):
                got_delta.set()

        task = asyncio.create_task(client.subscribe_forever(on_status, conn.append))
        await asyncio.wait_for(got_delta.wait(), 5)
        task.cancel()
        assert "connected" in conn
        await client.aclose()


def test_state_merge_and_helpers():
    s = PrinterState()
    s.apply({"print_stats": {"state": "printing", "filename": "a.gcode", "print_duration": 100.0},
             "virtual_sdcard": {"progress": 0.25, "file_position": 500},
             "temperature_sensor chamber": {"temperature": 31.0}})
    s.apply({"virtual_sdcard": {"progress": 0.5}})
    assert s.is_printing and s.progress == 0.5 and s.file_position == 500
    assert s.eta_seconds == pytest.approx(100.0)
    assert s.extra_sensors() == {"chamber": (31.0, 0.0)}
