#!/usr/bin/env python3
import difflib
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

APP_DIRS = [
    Path("/Applications"),
    Path("/System/Applications"),
    Path.home() / "Applications",
]

KNOWN_ACTIONS = [
    "open",
    "close",
    "volume",
    "brightness",
    "mute",
    "unmute",
    "lock",
    "sleep",
    "permissions",
    "help",
    "list",
    "refresh",
    "exit",
    "quit",
]

BRIGHTNESS_DOWN_KEY = 144
BRIGHTNESS_UP_KEY = 145
VOLUME_UP_KEY = 72
VOLUME_DOWN_KEY = 73
VOLUME_MUTE_KEY = 74
MEDIA_STEPS = 16


@dataclass
class CommandParseResult:
    action: Optional[str]
    target: Optional[str]
    value: Optional[int]
    corrected_from: Optional[str] = None


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


class AppIndex:
    def __init__(self) -> None:
        self.apps_by_display_name: Dict[str, str] = {}
        self.normalized_to_display: Dict[str, str] = {}

    def refresh(self) -> None:
        self.apps_by_display_name.clear()
        self.normalized_to_display.clear()
        for base_dir in APP_DIRS:
            if not base_dir.exists():
                continue
            for root, dirs, _ in os.walk(base_dir):
                app_dirs = [d for d in dirs if d.endswith(".app")]
                for app_dir in app_dirs:
                    app_path = Path(root) / app_dir
                    display_name = app_path.stem
                    if display_name not in self.apps_by_display_name:
                        self.apps_by_display_name[display_name] = str(app_path)
                        self.normalized_to_display[normalize_text(display_name)] = display_name
                dirs[:] = [d for d in dirs if not d.endswith(".app")]

    def find_best_match(self, raw_name: str, cutoff: float = 0.5) -> Optional[str]:
        if not raw_name:
            return None
        cleaned = raw_name.strip()
        if cleaned in self.apps_by_display_name:
            return cleaned
        normalized = normalize_text(cleaned)
        if normalized in self.normalized_to_display:
            return self.normalized_to_display[normalized]
        if not normalized:
            return None
        candidates = list(self.normalized_to_display.keys())
        best = difflib.get_close_matches(normalized, candidates, n=1, cutoff=cutoff)
        return self.normalized_to_display[best[0]] if best else None

    def app_path(self, display_name: str) -> Optional[str]:
        return self.apps_by_display_name.get(display_name)

    def list_names(self) -> List[str]:
        return sorted(self.apps_by_display_name.keys(), key=lambda s: s.lower())


def run_cmd(cmd: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip()
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err or f"Command failed: {shlex.join(cmd)}"
    except Exception as exc:
        return False, str(exc)


def parse_action(raw_action: str) -> Tuple[Optional[str], Optional[str]]:
    action = raw_action.strip().lower()
    if action in KNOWN_ACTIONS:
        return action, None
    best = difflib.get_close_matches(action, KNOWN_ACTIONS, n=1, cutoff=0.6)
    return (best[0], action) if best else (None, action)


def parse_input(line: str) -> CommandParseResult:
    line = line.strip()
    if not line:
        return CommandParseResult(action=None, target=None, value=None)

    parts = line.split()
    action, corrected_from = parse_action(parts[0])
    if not action:
        return CommandParseResult(action=None, target=None, value=None, corrected_from=corrected_from)

    no_target = {"exit", "quit", "help", "list", "refresh", "permissions", "mute", "unmute", "lock", "sleep"}
    if action in no_target:
        return CommandParseResult(action=action, target=None, value=None, corrected_from=corrected_from)

    if action in ("volume", "brightness"):
        if len(parts) < 2:
            return CommandParseResult(action=action, target=None, value=None, corrected_from=corrected_from)
        mode = parts[1].lower()
        if mode in ("up", "down"):
            step = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 10
            return CommandParseResult(action=action, target=mode, value=step, corrected_from=corrected_from)
        try:
            value = int(parts[1])
            return CommandParseResult(action=action, target="set", value=value, corrected_from=corrected_from)
        except ValueError:
            return CommandParseResult(action=action, target=None, value=None, corrected_from=corrected_from)

    target = " ".join(parts[1:]).strip() if len(parts) > 1 else None
    return CommandParseResult(action=action, target=target, value=None, corrected_from=corrected_from)


def open_app(app_path: str) -> Tuple[bool, str]:
    return run_cmd(["/usr/bin/open", app_path])


def close_app(app_name: str) -> Tuple[bool, str]:
    ok, out = run_cmd(["/usr/bin/osascript", "-e", f'tell application "{app_name}" to quit'])
    return (True, out) if ok else run_cmd(["/usr/bin/killall", app_name])


def press_key_code(key_code: int, times: int = 1) -> Tuple[bool, str]:
    times = max(1, min(50, times))
    script = (
        'tell application "System Events"\n'
        f"  repeat {times} times\n"
        f"    key code {key_code}\n"
        "  end repeat\n"
        "end tell"
    )
    return run_cmd(["/usr/bin/osascript", "-e", script])


def set_volume_absolute(value: int) -> Tuple[bool, str]:
    clamped = max(0, min(100, value))
    ok, msg = run_cmd(["/usr/bin/osascript", "-e", f"set volume output volume {clamped}"])
    if ok:
        return True, msg
    target_steps = round((clamped / 100) * MEDIA_STEPS)
    down_ok, down_msg = press_key_code(VOLUME_DOWN_KEY, MEDIA_STEPS)
    if not down_ok:
        return False, down_msg
    return (True, "") if target_steps == 0 else press_key_code(VOLUME_UP_KEY, target_steps)


def change_volume(direction: str, step_percent: int) -> Tuple[bool, str]:
    steps = max(1, round(max(1, step_percent) / (100 / MEDIA_STEPS)))
    key = VOLUME_UP_KEY if direction == "up" else VOLUME_DOWN_KEY
    return press_key_code(key, steps)


def get_mute_state() -> Tuple[bool, Optional[bool], str]:
    ok, msg = run_cmd(["/usr/bin/osascript", "-e", "output muted of (get volume settings)"])
    if not ok:
        return False, None, msg
    normalized = msg.strip().lower()
    if normalized == "true":
        return True, True, ""
    if normalized == "false":
        return True, False, ""
    return False, None, f"Unexpected mute state: {msg}"


def set_mute(muted: bool) -> Tuple[bool, str]:
    state_ok, current_muted, state_msg = get_mute_state()
    if state_ok and current_muted == muted:
        return True, ""

    state = "true" if muted else "false"
    direct_ok, direct_msg = run_cmd(["/usr/bin/osascript", "-e", f"set volume output muted {state}"])
    if direct_ok:
        return True, direct_msg

    toggle_ok, toggle_msg = press_key_code(VOLUME_MUTE_KEY, 1)
    if not toggle_ok:
        return False, direct_msg or toggle_msg or state_msg

    verify_ok, verify_muted, verify_msg = get_mute_state()
    if verify_ok and verify_muted == muted:
        return True, toggle_msg

    return False, verify_msg or state_msg or "Unable to confirm mute state."


def set_brightness_absolute(value: int) -> Tuple[bool, str]:
    clamped = max(0, min(100, value))
    target_steps = round((clamped / 100) * MEDIA_STEPS)
    down_ok, down_msg = press_key_code(BRIGHTNESS_DOWN_KEY, MEDIA_STEPS)
    if not down_ok:
        return False, down_msg
    return (True, "") if target_steps == 0 else press_key_code(BRIGHTNESS_UP_KEY, target_steps)


def change_brightness(direction: str, step_percent: int) -> Tuple[bool, str]:
    steps = max(1, round(max(1, step_percent) / (100 / MEDIA_STEPS)))
    key = BRIGHTNESS_UP_KEY if direction == "up" else BRIGHTNESS_DOWN_KEY
    return press_key_code(key, steps)


def request_permissions() -> List[str]:
    lines: List[str] = []
    run_cmd(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
    ok, msg = run_cmd(["/usr/bin/osascript", "-e", 'tell application "System Events" to get name of first process'])
    if ok:
        lines.append("✓ Automation access for System Events looks good.")
    else:
        if "-1743" in msg or "not authorized" in msg.lower() or "not permitted" in msg.lower():
            lines.append("→ macOS asked for Automation permission (System Events).")
        else:
            lines.append("→ Opened Privacy settings. Grant Accessibility and Automation permissions.")
    lines.append("Then run the command again.")
    return lines


def lock_screen() -> Tuple[bool, str]:
    loginwindow = "/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow"
    if Path(loginwindow).exists():
        ok, msg = run_cmd([loginwindow, "-LockScreen"])
        if ok and "usage" not in msg.lower():
            return True, msg
    legacy = "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession"
    if Path(legacy).exists():
        ok, msg = run_cmd([legacy, "-suspend"])
        if ok:
            return True, msg
    return run_cmd([
        "/usr/bin/osascript",
        "-e",
        'tell application "System Events" to key code 12 using {control down, command down}',
    ])


def sleep_display() -> Tuple[bool, str]:
    return run_cmd(["/usr/bin/pmset", "displaysleepnow"])


def help_lines() -> List[str]:
    return [
        "open <app>               open application",
        "close <app>              close application",
        "volume <0-100>           set volume",
        "volume up [step]         increase volume",
        "volume down [step]       decrease volume",
        "mute / unmute            toggle audio",
        "brightness <0-100>       set brightness",
        "brightness up [step]     increase brightness",
        "brightness down [step]   decrease brightness",
        "lock                     lock screen",
        "sleep                    sleep display",
        "permissions              open/check permissions",
        "list                     show all apps",
        "refresh                  rebuild app index",
        "help                     show this help",
        "exit                     quit",
    ]


def execute_command(line: str, app_index: AppIndex) -> Tuple[List[str], bool]:
    parsed = parse_input(line)
    output: List[str] = []

    if not parsed.action:
        if parsed.corrected_from:
            output.append(f'✗ Command not recognized: "{parsed.corrected_from}". Try: help')
        return output, False

    if parsed.corrected_from:
        output.append(f"→ Recognized as: {parsed.action}")

    if parsed.action in ("exit", "quit"):
        output.append("Exit.")
        return output, True
    if parsed.action == "help":
        output.extend(help_lines())
        return output, False
    if parsed.action == "list":
        names = app_index.list_names()
        output.extend(names if names else ["No applications indexed."])
        return output, False
    if parsed.action == "refresh":
        output.append("→ Refreshing index...")
        app_index.refresh()
        output.append(f"✓ Done. {len(app_index.apps_by_display_name)} applications found.")
        return output, False
    if parsed.action == "permissions":
        output.extend(request_permissions())
        return output, False

    if parsed.action in ("volume", "brightness"):
        if parsed.target is None or parsed.value is None:
            output.append(f"! Usage: {parsed.action} <0-100> or {parsed.action} up/down [step]")
            return output, False
        if parsed.action == "volume":
            ok, msg = (
                set_volume_absolute(parsed.value)
                if parsed.target == "set"
                else change_volume(parsed.target, parsed.value)
            )
            output.append(f"✓ Volume {'set' if parsed.target == 'set' else parsed.target}." if ok else f"✗ {msg}")
        else:
            ok, msg = (
                set_brightness_absolute(parsed.value)
                if parsed.target == "set"
                else change_brightness(parsed.target, parsed.value)
            )
            output.append(f"✓ Brightness {'set' if parsed.target == 'set' else parsed.target}." if ok else f"✗ {msg}")
        return output, False

    if parsed.action == "mute":
        ok, msg = set_mute(True)
        output.append("✓ Output muted." if ok else f"✗ {msg}")
        return output, False
    if parsed.action == "unmute":
        ok, msg = set_mute(False)
        output.append("✓ Output unmuted." if ok else f"✗ {msg}")
        return output, False
    if parsed.action == "lock":
        ok, msg = lock_screen()
        output.append("✓ Screen locked." if ok else f"✗ {msg}")
        return output, False
    if parsed.action == "sleep":
        ok, msg = sleep_display()
        output.append("✓ Display sleep sent." if ok else f"✗ {msg}")
        return output, False

    if parsed.action in ("open", "close"):
        if not parsed.target:
            output.append(f"! Usage: {parsed.action} <app>")
            return output, False
        matched = app_index.find_best_match(parsed.target)
        if not matched:
            output.append(f'✗ Application not found: "{parsed.target}"')
            return output, False
        if normalize_text(parsed.target) != normalize_text(matched):
            output.append(f"→ Recognized as: {matched}")
        if parsed.action == "open":
            app_path = app_index.app_path(matched)
            if not app_path:
                output.append(f"✗ Cannot resolve path for {matched}.")
                return output, False
            ok, msg = open_app(app_path)
            output.append(f"✓ Opened: {matched}" if ok else f"✗ {msg}")
        else:
            ok, msg = close_app(matched)
            output.append(f"✓ Closed: {matched}" if ok else f"✗ {msg}")
        return output, False

    return output, False


def main() -> int:
    print("Mac Control CLI")
    print("Scanning installed applications...")
    app_index = AppIndex()
    app_index.refresh()
    print(f"Indexed apps: {len(app_index.apps_by_display_name)}")
    print("Type 'help' to show commands.")

    while True:
        try:
            line = input("\ncmd> ")
        except (EOFError, KeyboardInterrupt):
            print("\nExit.")
            return 0

        output, should_exit = execute_command(line, app_index)
        for row in output:
            print(row)
        if should_exit:
            return 0


if __name__ == "__main__":
    sys.exit(main())
