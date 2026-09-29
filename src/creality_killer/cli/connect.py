"""`ck connect HOST` - work out how (and whether) we can talk to the printer."""
from __future__ import annotations

import asyncio
import sys

from creality_killer import config
from creality_killer.core.moonraker import AuthError, MoonrakerClient, MoonrakerError

# port -> what we expect there on a K1C. Only 7125 is required.
PROBES = {
    7125: "Moonraker API (required)",
    4408: "Fluidd (stock UI)",
    80: "Creality web UI",
    22: "SSH (off unless enabled in printer settings)",
    8080: "MJPEG camera (common on K1 series, unverified)",
}


async def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    return True


async def run(host: str, port: int = 7125) -> int:
    print(f"Probing {host} ...")
    results = await asyncio.gather(*(_port_open(host, p) for p in PROBES))
    for (p, desc), ok in zip(PROBES.items(), results):
        print(f"  {'open  ' if ok else 'closed'} {p:<5} {desc}")
    if not results[0]:
        print("\nMoonraker port is closed. Check the IP, that the printer is on the same LAN,"
              "\nand try `curl http://%s:4408` to see whether Fluidd answers at all." % host)
        return 1

    client = MoonrakerClient(host, port)
    try:
        info = await client.server_info()
        print(f"\nMoonraker {info.get('moonraker_version')}  klippy_state={info.get('klippy_state')}")
        pinfo = await client.printer_info()
        print(f"Klipper {pinfo.get('software_version')}  host={pinfo.get('hostname')}  state={pinfo.get('state')}")
        files = await client.list_files()
        print(f"{len(files)} G-code files on the printer")
        try:
            cams = await client.webcams()
            for c in cams:
                print(f"camera '{c.get('name')}': stream={c.get('stream_url')} snapshot={c.get('snapshot_url')}")
            if not cams:
                print("no webcams registered with Moonraker (camera URL will need to be set by hand)")
        except MoonrakerError as e:
            print(f"webcam list unavailable: {e}")
    except AuthError as e:
        print(f"\n{e}")
        return 2
    except MoonrakerError as e:
        print(f"\nAPI error: {e}")
        return 3
    finally:
        await client.aclose()
    config.save(host=host)
    print(f"\nOK - saved host to {config.CONFIG_PATH}")
    return 0


def main(host: str, port: int = 7125) -> int:
    return asyncio.run(run(host, port))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
