# Mac Control — CLI Script (English)

Terminal Python script for controlling macOS via typed commands: open/close apps, volume, brightness, lock screen, sleep display, and more.

## Requirements

- macOS 12.0 or later
- Python 3 (pre-installed on macOS)

## Run

```bash
cd script
python3 mac_control.py
```

## Commands

| Command | Description |
|---|---|
| `open <app>` | Open application |
| `close <app>` | Close application |
| `volume <0-100>` | Set volume |
| `volume up\|down [step]` | Adjust volume (default step: 10) |
| `brightness <0-100>` | Set display brightness |
| `brightness up\|down [step]` | Adjust brightness (default step: 10) |
| `mute` / `unmute` | Toggle audio output |
| `lock` | Lock screen |
| `sleep` | Sleep display |
| `list` | List all indexed applications |
| `refresh` | Rebuild app index |
| `permissions` | Check / request macOS permissions |
| `help` | Show all commands |
| `exit` | Quit the script |

## Fuzzy matching

App names and command keywords are matched with fuzzy search — typos and partial names are tolerated (e.g. `open safri` will open Safari).

## Permissions

Some actions require macOS system permissions:

- **Accessibility** — needed for simulated key events (volume/brightness keys, lock screen fallback)
- **Automation → System Events** — needed for AppleScript-based actions

Run `permissions` to trigger the system permission request dialog.
