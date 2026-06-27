#!/usr/bin/env python3
"""
Claude Code LED Status Driver
-----------------------------------------
Invoked by Claude Code hooks. Looks up a Claude state name in STATE_MAP and
sends the corresponding animation command to the ESP8266 over USB-serial.

The firmware is generic (it knows only animation + color + speed + brightness,
not Claude states). All Claude-specific mapping lives in STATE_MAP below --
edit the dict to change a state's visual without reflashing firmware.

Setup:
    pip3 install pyserial

Usage:
    # Hook mode (state name) - used by claude_settings_hooks_example.json:
    python3 led_driver.py thinking
    python3 led_driver.py idle --quiet

    # Raw mode (direct animation, for testing/custom use):
    python3 led_driver.py --raw breathe --rgb 0,50,220 --period 3500
    python3 led_driver.py --raw solid --rgb 0,0,255 --brightness 30
    python3 led_driver.py --raw off

The port is auto-detected by scanning USB-serial devices; if it cannot be
found, set the CLAUDE_LED_PORT environment variable or pass --port.
"""

import argparse
import glob
import os
import sys
import time

try:
    import serial
except ImportError:
    serial = None

RESET_WAIT_SECONDS = 0.5
BAUD_RATE = 115200

# state -> (animation, (r, g, b), period_ms, brightness_pct)
# Edit freely to retune a state's visual without touching firmware. Brightness
# is a percentage scaled below the firmware's MAX_BRIGHTNESS USB-safety ceiling.
STATE_MAP = {
    "idle":     ("breathe", (0, 50, 220),    3500, 100),
    "thinking": ("scanner", (90, 0, 170),    1600, 100),
    "tool":     ("breathe", (255, 128, 0),   1500, 100),
    "waiting":  ("breathe", (200, 200, 200), 2500,  60),
    "success":  ("fill",    (0, 220, 0),     3500, 100),
    "error":    ("blink",   (180, 0, 0),      300, 100),
    "off":      ("off",     (0, 0, 0),          0,   0),
}

ANIMATIONS = {"solid", "breathe", "blink", "scanner", "fill", "off"}
ANIMATIONS_REQUIRING_PERIOD = {"breathe", "blink", "scanner", "fill"}


def find_esp8266_port() -> str | None:
    candidates = []
    for pattern in ("/dev/cu.wchusbserial*", "/dev/cu.usbserial-*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.usbmodem*"):
        candidates.extend(glob.glob(pattern))
    candidates.extend(glob.glob("/dev/ttyUSB*"))
    candidates.extend(glob.glob("/dev/ttyACM*"))
    return candidates[0] if candidates else None


def parse_rgb(s: str) -> tuple[int, int, int]:
    """Accept 'r,g,b' (e.g. '0,50,220') or a single value for grayscale."""
    parts = s.split(",")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"invalid --rgb value {s!r} (expected integers)")
    if len(nums) == 1:
        v = max(0, min(255, nums[0]))
        return (v, v, v)
    if len(nums) == 3:
        return (max(0, min(255, nums[0])),
                max(0, min(255, nums[1])),
                max(0, min(255, nums[2])))
    raise ValueError(f"--rgb expects 1 or 3 values, got {len(nums)}")


def build_state_command(state: str) -> str:
    anim, (r, g, b), period, pct = STATE_MAP[state]
    if anim == "off":
        return "off"
    return f"{anim} {r} {g} {b} {period} {pct}"


def build_raw_command(anim: str, rgb: tuple[int, int, int] | None,
                      period: int | None, pct: int) -> str:
    if anim == "off":
        return "off"
    if rgb is None:
        raise ValueError(f"--rgb required for animation {anim!r}")
    r, g, b = rgb
    if anim in ANIMATIONS_REQUIRING_PERIOD and period is None:
        raise ValueError(f"--period required for animation {anim!r}")
    pct = max(0, min(100, pct))
    if anim == "solid":
        return f"solid {r} {g} {b} {pct}"
    return f"{anim} {r} {g} {b} {period} {pct}"


def send_command(cmd: str, port: str | None, quiet: bool = False) -> bool:
    if serial is None:
        if not quiet:
            print("pyserial is not installed. Install it with: pip3 install pyserial", file=sys.stderr)
        return False

    resolved_port = port or os.environ.get("CLAUDE_LED_PORT") or find_esp8266_port()
    if not resolved_port:
        if not quiet:
            print("ESP8266 serial port not found; LED state not updated (skipping silently).",
                  file=sys.stderr)
        return False

    try:
        with serial.Serial(resolved_port, BAUD_RATE, timeout=1) as ser:
            time.sleep(RESET_WAIT_SECONDS)  # ESP8266 ready-wait after reset
            ser.write((cmd + "\n").encode("utf-8"))
            ser.flush()
        return True
    except (serial.SerialException, OSError) as e:
        if not quiet:
            print(f"Serial port error ({resolved_port}): {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Claude Code LED status driver")
    parser.add_argument("name", help="State name, or animation name when --raw is set")
    parser.add_argument("--raw", action="store_true",
                        help="Treat 'name' as a raw animation (solid/breathe/blink/scanner/fill/off)")
    parser.add_argument("--rgb", default=None,
                        help="Color as 'r,g,b' (e.g. 0,50,220) or a single value for grayscale")
    parser.add_argument("--period", type=int, default=None,
                        help="Animation period in ms (required for breathe/blink/scanner/fill)")
    parser.add_argument("--brightness", type=int, default=100,
                        help="Brightness 0-100 (default 100, scaled below firmware MAX_BRIGHTNESS)")
    parser.add_argument("--port", default=None,
                        help="Serial port path (e.g. /dev/cu.usbserial-1410)")
    parser.add_argument("--quiet", action="store_true",
                        help="Stay silent if the LED is missing or fails (do not interrupt Claude Code)")
    args = parser.parse_args()

    if args.raw:
        if args.name not in ANIMATIONS:
            print(f"Unknown animation: {args.name}. Valid: {sorted(ANIMATIONS)}", file=sys.stderr)
            sys.exit(0)
        try:
            rgb = parse_rgb(args.rgb) if args.rgb is not None else None
            cmd = build_raw_command(args.name, rgb, args.period, args.brightness)
        except ValueError as e:
            if not args.quiet:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(0)
    else:
        if args.name not in STATE_MAP:
            print(f"Unknown state: {args.name}. Valid: {sorted(STATE_MAP.keys())}", file=sys.stderr)
            sys.exit(0)
        cmd = build_state_command(args.name)

    send_command(cmd, args.port, quiet=args.quiet)
    sys.exit(0)


if __name__ == "__main__":
    main()
