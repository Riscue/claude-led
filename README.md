# claude-led

A hardware status indicator that mirrors Claude Code's state on an LED strip. A WS2812B strip is driven by a Wemos D1 Mini (ESP8266) over USB-serial. Multiple parallel Claude sessions are merged onto a **single strip by priority** — if one session errors, the error pattern wins even if the others are still thinking.

## What it does

Each Claude Code state maps to a strip animation:

| State | Animation | Color |
|-------|-----------|-------|
| `idle` | slow breathe | blue |
| `thinking` | scanner (sweeping dot) | purple |
| `tool` | breathe | orange |
| `waiting` (input requested) | dim breathe | white/grey |
| `success` | fill (top-to-bottom) | green |
| `error` | fast blink | red |
| `off` | dark | — |

When three Claude sessions run in parallel, the **most urgent wins**: `error` > `waiting` > `thinking` > `tool` > `success` > `idle`.

## Topology / data flow

```
Claude Code  ──hooks──►  led (CLI)  ──Unix socket──►  led_daemon  ──USB-serial──►  D1 Mini  ──WS2812B──►  LED
                          │                            │
                          │ STATE <sid> <pri> <wire>   │ sessions: { sid → (priority, wire) }
                          │ CLEAR  <sid>               │ transient: { wire, expires_at }
                          │ TRANSIENT <ttl> <wire>     │ → picks highest-priority live entry and forwards it
```

- `led_cli.py` (CLI): resolves the state from a JSON profile, sends it to the daemon
- `led_daemon.py` (background): tracks every live session, forwards the highest-priority one to the firmware
- Firmware (ESP8266): renders the incoming animation command and knows nothing else

## Installation

**Requirement:** `pip3 install pyserial`

```bash
./scripts/install.sh install
```

This command:
- Copies the Python files to `~/.claude-led/`
- Creates the `~/.local/bin/led` symlink (must be on `$PATH`; if not, the script prints what to add to your shell rc)
- macOS: writes a launchd plist (`RunAtLoad` + `KeepAlive`) → auto-starts at login
- Linux: writes a systemd --user unit (`enable --now`) → auto-starts at login
- Starts the daemon immediately

To remove:
```bash
./scripts/install.sh uninstall
```

**No sudo required** — entirely user-level.

## Claude Code hooks example

Add to `~/.claude/settings.json` (see `examples/claude_settings_hooks_example.json`):

```json
{
  "hooks": {
    "SessionStart":   [{ "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.idle" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.thinking" }] }],
    "PreToolUse":     [{ "matcher": "*", "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.tool" }] }],
    "PostToolUseFailure": [{ "matcher": "*", "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.error" }] }],
    "Notification":   [{ "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.waiting" }] }],
    "Stop":           [{ "hooks": [{ "type": "command",
      "command": "led --quiet --session $CLAUDE_SESSION_ID --state claude.success" }] }],
    "SessionEnd":     [{ "hooks": [{ "type": "command",
      "command": "led --quiet --end-session $CLAUDE_SESSION_ID" }] }]
  }
}
```

Every hook calls `led` with `--session $CLAUDE_SESSION_ID` → the daemon tracks that session as live. SessionEnd cleans it up.

## State profile (JSON)

`~/.claude-led/states/claude.json` — edit colors, animations, and priorities here. No reinstall needed; the change takes effect on the next hook fire.

```json
{
  "idle":     { "animation": "breathe", "rgb": [0,50,220],     "period": 3500, "brightness": 100, "priority": 10 },
  "thinking": { "animation": "scanner", "rgb": [90,0,170],     "period": 1600, "brightness": 100, "priority": 60 },
  "tool":     { "animation": "breathe", "rgb": [255,128,0],    "period": 1500, "brightness": 100, "priority": 50 },
  "waiting":  { "animation": "breathe", "rgb": [200,200,200],  "period": 2500, "brightness": 60,  "priority": 80 },
  "success":  { "animation": "fill",    "rgb": [0,220,0],      "period": 3500, "brightness": 100, "priority": 30 },
  "error":    { "animation": "blink",   "rgb": [180,0,0],      "period": 300,  "brightness": 100, "priority": 100 },
  "off":      { "animation": "off" }
}
```

| Field | Description |
|-------|-------------|
| `animation` | `solid`, `breathe`, `blink`, `scanner`, `fill`, `converge`, `strobe`, `level`, `off` |
| `rgb` | `[R, G, B]` 0-255 |
| `period` | Animation speed in ms (lower = faster) |
| `brightness` | 0-100 (firmware enforces a USB-power ceiling) |
| `priority` | Aggregation order — higher number wins |

To add a new state, drop a new key into the JSON and invoke it with `led --state claude.<new_key>`.

## Trigger usage

You can also fire `led` manually outside of Claude Code hooks:

```bash
# No session — brief flash (default 3s), then reverts to aggregate
led --state claude.error

# Custom duration
led --state claude.success --ttl 5000

# Manual session (testing outside Claude Code)
led --session manual1 --state claude.thinking
led --end-session manual1

# Raw animation — no profile lookup
led --raw strobe --rgb 255,0,0 --rgb2 0,0,255 --period 200
led --raw blink --rgb 255,255,0 --period 100

# Default-profile shorthand (`led <key>` == `--state default.<key>`)
led off

# Daemon bypass for debug (pays the 0.5s reset wait)
led --direct --state claude.idle
```

Three modes:
- `--session <sid>` → **STATE** (joins the aggregate, persistent)
- `--end-session <sid>` → **CLEAR** (removes the session)
- (neither) → **TRANSIENT** (3s flash, then reverts)

## How aggregation works

The daemon holds a dictionary: `session_id → (priority, wire_line)`. On every hook fire and on each 1-second accept-timeout tick, it picks the highest-priority live entry and forwards it to the firmware.

Rules:
1. **Highest priority wins** — `error` (100) > `thinking` (60) > `idle` (10)
2. **Ties broken by recency** — last write wins within a priority tier
3. **While a TRANSIENT is live (TTL not expired)** it overrides the aggregate
4. **With no live sessions** the daemon emits `off`

Example scenarios:

| Session A | Session B | LED shows |
|-----------|-----------|-----------|
| thinking | — | purple scanner |
| thinking | idle | purple scanner (60 > 10) |
| thinking | error | red blink (100 > 60) |
| thinking | (SessionEnd) | purple scanner (B removed) |
| (SessionEnd) | — | off |

**Caveats:**
- A crashed session that doesn't fire SessionEnd leaves stale state until the daemon restarts (accepted trade-off).
- A daemon restart drops all in-memory state — sessions rebuild as hooks fire again.

## Installed file layout

```
~/.claude-led/
├── led_cli.py             # CLI (called by hooks)
├── led_daemon.py          # daemon (stateful aggregator)
├── protocol.py            # shared constants
├── states/
│   ├── claude.json        # Claude Code state map
│   └── default.json       # ad-hoc states (on, off)
├── led.sock               # Unix socket (runtime)
├── daemon.pid             # PID (runtime)
└── daemon.log             # logs (runtime)

~/.local/bin/led           # → ~/.claude-led/led_cli.py

~/Library/LaunchAgents/tr.riscue.claude-led.plist       # macOS (auto-start)
~/.config/systemd/user/tr.riscue.claude-led.service     # Linux (auto-start)
```

Daemon log: `~/.claude-led/daemon.log` — watch with `tail -f`.

Daemon control:
- **macOS:** `launchctl list tr.riscue.claude-led` / `launchctl kickstart -k gui/$(id -u)/tr.riscue.claude-led`
- **Linux:** `systemctl --user status tr.riscue.claude-led` / `systemctl --user restart tr.riscue.claude-led`

## Hardware

- **Wemos D1 Mini** (ESP8266) with a CH340 USB-serial chip
- **WS2812B LED strip** — 8 LEDs (more requires external power; USB can't supply it)
- **D4 pin** (GPIO2) → strip data
- Single USB cable, no external power

Firmware upload (first install or firmware update):
```bash
scripts/upload.sh    # requires PlatformIO
```

## Tests

```bash
python3 -m unittest discover -s tests    # 55 tests, ~0.02s
```

Hardware animation smoke test:
```bash
scripts/test.sh    # cycles through every animation
```
