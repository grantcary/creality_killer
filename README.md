# creality_killer

Replacement desktop GUI (PySide6) and terminal client for the Creality K1C. It talks to the printer's
Klipper **Moonraker** API ([docs](https://moonraker.readthedocs.io/en/latest/external_api/introduction/)) on port 7125.

## Setup

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[gui,tui,dev]'
ck connect <printer-ip>     # probes ports, checks the API, saves the address
ck gui                      # desktop app
```

`ck connect` is the first thing to run: it reports which ports answer, the Moonraker/Klipper versions,
the file count and any camera Moonraker knows about. A 401/403 means this machine's IP is missing from
`trusted_clients` in Moonraker's `[authorization]` config.

## Layout

- `src/creality_killer/core` - Moonraker client, printer state, G-code toolpath parser, local queue (no Qt).
- `src/creality_killer/gui` - left: model library (drag to the viewport to queue); centre: orbiting 3D
  preview (ghosted model + solid current layer while printing); right: status, temperatures, camera, queue.
- `dev/fake_printer.py` - fake Moonraker with test models and a simulated print, for working without the printer.

Starting, pausing or cancelling a print always needs an explicit click (start and cancel ask for confirmation).
The queue never starts a job by itself.

## Development

```sh
pytest
python dev/fake_printer.py &   # then: ck gui 127.0.0.1
```
