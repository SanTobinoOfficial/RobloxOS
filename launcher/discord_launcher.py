#!/usr/bin/env python3
"""
RobloxOS – Discord smart launcher
Detects second monitor via xrandr and positions Discord accordingly.
"""

import subprocess
import re
import sys


def get_monitors() -> list[dict]:
    """Parse xrandr output and return list of connected monitors with geometry."""
    try:
        out = subprocess.check_output(["xrandr", "--query"], text=True)
    except FileNotFoundError:
        print("[discord_launcher] xrandr not found", file=sys.stderr)
        return []

    monitors = []
    # Match lines like: HDMI-1 connected 1920x1080+1920+0 ...
    pattern = re.compile(
        r"^(\S+)\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(out):
        monitors.append({
            "name":   m.group(1),
            "width":  int(m.group(2)),
            "height": int(m.group(3)),
            "x":      int(m.group(4)),
            "y":      int(m.group(5)),
        })
    return monitors


def launch_discord(monitors: list[dict]):
    base_cmd = ["flatpak", "run", "com.discordapp.Discord"]

    if len(monitors) >= 2:
        # ── Two monitors: open Discord fullscreen on the second one ──────────
        # "Second" = the monitor that is NOT at x=0 (i.e. not the primary)
        secondary = next((m for m in monitors if m["x"] != 0), monitors[1])
        print(
            f"[discord_launcher] Second monitor detected: {secondary['name']} "
            f"{secondary['width']}x{secondary['height']}+{secondary['x']}+{secondary['y']}"
        )

        # Discord itself doesn't take --geometry, so we launch it then move the
        # window with wmctrl after a short delay.
        subprocess.Popen(
            base_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for Discord window to appear, then move + maximise it
        _move_window_to_monitor("discord", secondary)

    else:
        # ── Single monitor: small overlay in top-right corner ─────────────────
        primary = monitors[0] if monitors else {"width": 1920, "height": 1080}
        win_w, win_h = 420, 680
        margin = 20
        x = primary["x"] + primary["width"] - win_w - margin
        y = primary.get("y", 0) + margin

        print(
            f"[discord_launcher] Single monitor – overlay at {x},{y} size {win_w}x{win_h}"
        )

        subprocess.Popen(
            base_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _move_window_overlay("discord", x, y, win_w, win_h)


def _move_window_to_monitor(window_name: str, monitor: dict, retries: int = 15):
    """Wait for the window and move it fullscreen to the given monitor."""
    import time

    for attempt in range(retries):
        time.sleep(2)
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True, text=True
        )
        win_id = _find_window_id(result.stdout, window_name)
        if win_id:
            # Remove decorations / maximise flags first
            subprocess.run(["wmctrl", "-ir", win_id, "-b", "remove,maximized_vert,maximized_horz"])
            # Move and resize to fill secondary monitor
            geo = f"0,{monitor['x']},{monitor['y']},{monitor['width']},{monitor['height']}"
            subprocess.run(["wmctrl", "-ir", win_id, "-e", geo])
            subprocess.run(["wmctrl", "-ir", win_id, "-b", "add,maximized_vert,maximized_horz"])
            print(f"[discord_launcher] Window moved to secondary monitor (attempt {attempt+1})")
            return
        print(f"[discord_launcher] Waiting for Discord window… ({attempt+1}/{retries})")

    print("[discord_launcher] Could not find Discord window after retries", file=sys.stderr)


def _move_window_overlay(window_name: str, x: int, y: int, w: int, h: int, retries: int = 15):
    """Wait for the window and position it as a small overlay."""
    import time

    for attempt in range(retries):
        time.sleep(2)
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True, text=True
        )
        win_id = _find_window_id(result.stdout, window_name)
        if win_id:
            subprocess.run(["wmctrl", "-ir", win_id, "-b", "remove,maximized_vert,maximized_horz"])
            geo = f"0,{x},{y},{w},{h}"
            subprocess.run(["wmctrl", "-ir", win_id, "-e", geo])
            # Keep it always-on-top so it floats above the game
            subprocess.run(["wmctrl", "-ir", win_id, "-b", "add,above"])
            print(f"[discord_launcher] Overlay positioned (attempt {attempt+1})")
            return
        print(f"[discord_launcher] Waiting for Discord window… ({attempt+1}/{retries})")

    print("[discord_launcher] Could not find Discord window after retries", file=sys.stderr)


def _find_window_id(wmctrl_output: str, keyword: str) -> str | None:
    """Return the hex window ID for the first window whose title contains keyword."""
    for line in wmctrl_output.splitlines():
        if keyword.lower() in line.lower():
            return line.split()[0]
    return None


if __name__ == "__main__":
    monitors = get_monitors()
    if not monitors:
        # Fallback: just launch Discord without positioning
        subprocess.Popen(
            ["flatpak", "run", "com.discordapp.Discord"],
            start_new_session=True,
        )
        sys.exit(0)

    launch_discord(monitors)
