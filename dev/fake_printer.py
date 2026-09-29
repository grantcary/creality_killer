"""Fake Moonraker for developing without the printer.

    python dev/fake_printer.py            # serves on :7125
    ck gui 127.0.0.1

Serves generated test models and simulates a print when POST /printer/print/start is hit.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from urllib.parse import parse_qs, unquote, urlparse

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response


def make_model(kind: str) -> str:
    out = ["G90", "M83", "G28"]
    e = 0.0
    z = 0.0
    for layer in range(1, 121):
        z = layer * 0.2
        out += [";LAYER_CHANGE", f";Z:{z:.2f}"]
        if kind == "vase":
            r = 25 + 12 * math.sin(z / 6)
        else:
            r = 30
        out.append(";TYPE:Outer wall")
        for i in range(0, 73):
            a = math.radians(i * 5)
            x, y = 110 + r * math.cos(a), 110 + r * math.sin(a)
            if i == 0:
                out.append(f"G1 X{x:.3f} Y{y:.3f} Z{z:.2f} F6000")
            else:
                out.append(f"G1 X{x:.3f} Y{y:.3f} E0.04")
        out.append(";TYPE:Inner wall")
        for i in range(0, 73):
            a = math.radians(i * 5)
            x, y = 110 + (r - 0.45) * math.cos(a), 110 + (r - 0.45) * math.sin(a)
            out.append(f"G1 X{x:.3f} Y{y:.3f} E0.04" if i else f"G0 X{x:.3f} Y{y:.3f}")
        if kind != "vase" and layer % 2:
            out.append(";TYPE:Sparse infill")
            for k in range(-4, 5):
                xx = 110 + k * 5
                h = math.sqrt(max(r * r - (k * 5) ** 2, 0)) - 1
                out += [f"G0 X{xx} Y{110 - h:.2f}", f"G1 X{xx} Y{110 + h:.2f} E0.12"]
    return "\n".join(out) + "\n"


MODELS = {"tower.gcode": make_model("tower"), "vase.gcode": make_model("vase")}
START = time.time() - 3600
state = {"print_stats": {"state": "standby", "filename": "", "print_duration": 0.0},
         "virtual_sdcard": {"progress": 0.0, "file_position": 0},
         "extruder": {"temperature": 24.0, "target": 0.0}, "heater_bed": {"temperature": 23.0, "target": 0.0},
         "temperature_sensor chamber": {"temperature": 26.0}, "toolhead": {"position": [0, 0, 0, 0]}}
clients = set()


def json_resp(obj, status=200):
    body = json.dumps(obj).encode()
    return Response(status, "OK", Headers({"Content-Type": "application/json", "Content-Length": str(len(body))}), body)


def http(connection, request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    u = urlparse(request.path)
    q = parse_qs(u.query)
    p = unquote(u.path)
    if p == "/server/info":
        return json_resp({"result": {"klippy_state": "ready", "moonraker_version": "fake"}})
    if p == "/printer/info":
        return json_resp({"result": {"state": "ready", "software_version": "fake", "hostname": "fake-k1c"}})
    if p == "/server/files/list":
        return json_resp({"result": [{"path": n, "modified": START + i * 60, "size": len(g)}
                                     for i, (n, g) in enumerate(MODELS.items())]})
    if p == "/server/files/metadata":
        n = q["filename"][0]
        return json_resp({"result": {"size": len(MODELS[n]), "modified": START, "estimated_time": 5400 if "tower" in n else 3100}})
    if p.startswith("/server/files/gcodes/"):
        body = MODELS[p.removeprefix("/server/files/gcodes/")].encode()
        return Response(200, "OK", Headers({"Content-Length": str(len(body))}), body)
    if p == "/server/webcams/list":
        return json_resp({"result": {"webcams": []}})
    if p == "/printer/print/start":
        asyncio.get_running_loop().create_task(simulate(q["filename"][0]))
        return json_resp({"result": "ok"})
    return json_resp({"error": "nf"}, 404)


async def broadcast(delta):
    msg = json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [delta, time.time()]})
    for ws in list(clients):
        try:
            await ws.send(msg)
        except Exception:
            clients.discard(ws)


async def simulate(name):
    size = len(MODELS[name])
    ps = state["print_stats"]
    ps.update(state="printing", filename=name, print_duration=0.0)
    await broadcast({"print_stats": dict(ps), "extruder": {"target": 220.0}, "heater_bed": {"target": 60.0}})
    steps = 300
    for i in range(1, steps + 1):
        await asyncio.sleep(0.2)
        frac = i / steps
        d = {"print_stats": {"print_duration": frac * 600}, "virtual_sdcard": {"progress": frac, "file_position": int(frac * size)},
             "extruder": {"temperature": 219.0 + math.sin(i)}, "heater_bed": {"temperature": 59.5}}
        for k, v in d.items():
            state.setdefault(k, {}).update(v)
        await broadcast(d)
    ps["state"] = "complete"
    await broadcast({"print_stats": {"state": "complete"}, "extruder": {"target": 0.0}, "heater_bed": {"target": 0.0}})


async def ws_handler(ws):
    clients.add(ws)
    try:
        async for raw in ws:
            m = json.loads(raw)
            method = m["method"]
            if method == "printer.objects.list":
                res = {"objects": list(state) + ["gcode_macro X"]}
            elif method == "printer.objects.subscribe":
                res = {"status": state, "eventtime": time.time()}
            else:
                res = "ok"
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}))
    finally:
        clients.discard(ws)


async def main(port=7125):
    async with serve(ws_handler, "127.0.0.1", port, process_request=http, max_size=None):
        print(f"fake Moonraker on :{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
