# Claude Code LED Status Indicator

A hardware indicator that turns a WS2812B LED strip into a status display for
Claude Code (idle / thinking / running a tool / waiting for input / success / error).

## Architecture

```
Claude Code --hooks--> led_driver.py --USB-serial--> Wemos D1 Mini --WS2812B data line--> WS2812B strip
```

- **No Wi-Fi.** The D1 Mini's wireless feature is never used — USB-serial only.
- **Single cable.** Power and data both go through the same USB cable; no external power supply needed.
- Brightness is capped in firmware (USB port safety); each command can additionally dim below that ceiling via a `bright_pct` parameter.

## Hardware requirements

| Part                                                     | Note                                                   |
|----------------------------------------------------------|--------------------------------------------------------|
| WS2812B addressable LED strip                            | Any WS2812B / NeoPixel strip, stick, or ring works     |
| Wemos D1 Mini (ESP8266, CH340 or CP2104 USB-serial chip) | Clone or original both work                            |
| USB data cable (micro-USB)                               | A charge-only cable will NOT work — it must carry data |
| 3 wires (~10 cm): 5V, GND, DIN                           | From the strip connector to the D1 Mini                |
| Multimeter                                               | For pin verification — CRITICAL                        |

> A NodeMCU or any other ESP8266 board also works instead of the Wemos D1 Mini, but the pin mapping will differ.

## Folders

- `firmware/platformio.ini` — PlatformIO configuration (board + library versions pinned)
- `firmware/src/main.cpp` — Firmware flashed onto the D1 Mini
- `driver/led_driver.py` — Python script running on the host, invoked by hooks
- `driver/claude_settings_hooks_example.json` — Example Claude Code hook configuration

## Setup sequence

### 1) Verifying the strip pinout (MOST CRITICAL STEP)

Identify the three connections at the input end of your WS2812B strip: 5V (VCC),
GND, and DIN (data input). Most strips are labeled, but verify with a multimeter
before wiring — do not guess. Wiring 5V and GND backwards will permanently kill
the LED chips. Convention is typically red=5V, black=GND, white or yellow=data,
but always confirm your strip's own color coding.

### 2) Flashing the firmware (PlatformIO)

- If PlatformIO is not installed: `pip3 install platformio` (or `brew install platformio`)
- Plug the D1 Mini in via USB
- From the project root: `cd firmware && pio run -t upload`
    - Dependencies (`espressif8266@4.2.1` platform, `Adafruit NeoPixel@1.15.5` library)
      are downloaded automatically; versions are pinned in `platformio.ini`.

> We avoid the Arduino IDE — its manual setup steps cause reproducibility issues.
> PlatformIO installs everything with a single command.

### 3) Wiring

```
D1 Mini "5V"  -> Strip 5V
D1 Mini "G"   -> Strip GND
D1 Mini "D4"  -> Strip DIN (data)
```

### 4) Host-side driver

```bash
pip3 install pyserial
python3 driver/led_driver.py idle   # test — LEDs should slowly breathe blue
```

For ad-hoc testing without involving the state mapping:

```bash
python3 driver/led_driver.py --raw breathe --rgb 0,50,220 --period 3500
python3 driver/led_driver.py --raw solid --rgb 0,0,255 --brightness 30
```

### 5) Wiring up Claude Code hooks

Append the contents of `claude_settings_hooks_example.json` to `~/.claude/settings.json`,
and update the paths to point to your `led_driver.py` location.

## State colors

The driver maps each Claude Code state to an animation via `STATE_MAP` in
`driver/led_driver.py`. Defaults:

| State      | Animation | Color (RGB)  | Period | Brightness |
|------------|-----------|--------------|--------|------------|
| `idle`     | breathe   | 0, 50, 220   | 3500ms | 100%       |
| `thinking` | scanner   | 90, 0, 170   | 1600ms | 100%       |
| `tool`     | breathe   | 255, 128, 0  | 900ms  | 100%       |
| `waiting`  | breathe   | 200, 200, 200 | 2500ms | 60%        |
| `success`  | fill      | 0, 220, 0    | 1600ms | 100%       |
| `error`    | blink     | 180, 0, 0    | 300ms  | 100%       |
| `off`      | off       | —            | —      | —          |

## Wire protocol

The firmware is generic — it does not know about Claude Code, only the
animation commands below. Each is a single ASCII line, lowercase, newline-
terminated, at 115200 baud. `bright_pct` is optional (default 100) and scales
below the firmware's `MAX_BRIGHTNESS` USB-safety ceiling.

```
solid   r g b [bright_pct]              all LEDs steady
breathe r g b period_ms [bright_pct]    black -> color, sin-based pulse
blink   r g b period_ms [bright_pct]    period/2 on + period/2 off
scanner r g b period_ms [bright_pct]    dot sweeps back and forth
fill    r g b period_ms [bright_pct]    LEDs light one-by-one, then hold
off
```

RGB is decimal 0-255 per channel. Period is in milliseconds (clamped to >= 50
in firmware). Unknown animations and malformed lines are silently ignored.

## Customizing the visuals

Edit `STATE_MAP` in `driver/led_driver.py` to retune any state's animation,
color, period, or brightness — **no firmware reflash required**. Each entry is
a 4-tuple: `(animation, (r, g, b), period_ms, brightness_pct)`.

```python
# Dim the error blink to 70% and slow it down:
"error": ("blink", (180, 0, 0), 500, 70),

# Make idle a calm green instead of blue:
"idle": ("breathe", (0, 180, 80), 4000, 80),
```

For one-off testing from the shell, bypass `STATE_MAP` with `--raw`:

```bash
python3 driver/led_driver.py --raw scanner --rgb 200,0,255 --period 1200 --brightness 50
```

## Claude Code hooks → state mapping

| Hook (Claude Code event) | Command    | When it fires                            |
|--------------------------|------------|------------------------------------------|
| `SessionStart`           | `idle`     | When Claude Code opens                   |
| `UserPromptSubmit`       | `thinking` | When you send a message                  |
| `PreToolUse`             | `tool`     | Before a tool (Read/Bash/...) is invoked |
| `PostToolUse`            | `thinking` | After a tool finishes                    |
| `PostToolUseFailure`     | `error`    | On a tool failure                        |
| `Notification`           | `waiting`  | When Claude Code shows a notification    |
| `Stop`                   | `success`  | When Claude Code finishes its response   |
| `SessionEnd`             | `off`      | When the session closes                  |

> The hook commands reference the `$CLAUDE_LED_PROJECT_FOLDER` environment variable
> (no hardcoded paths). Export it in your shell rc (`~/.zshrc` / `~/.bashrc`) before
> launching Claude Code:
>
> ```bash
> export CLAUDE_LED_PROJECT_FOLDER=/absolute/path/to/claude-led
> ```
>
> Alternatively, replace every `$CLAUDE_LED_PROJECT_FOLDER` occurrence in the hook
> config with the absolute path to this project.

## Notes / limitations

- `led_driver.py` always exits with code 0 even if the LED hardware is missing or not found,
  so it never disrupts the Claude Code flow.

> All states are persistent — the effect continues until a new hook/command arrives.
> There is no automatic return to blue (state changes as the user sends new commands).

- **LEDs are not lighting up.** List serial ports with `ls /dev/cu.*`. If there is no
  `cu.wchusbserial*` entry, either the USB cable is not carrying data or the CH340 driver
  is missing (install the macOS driver from wch.cn).
- **Port found but LEDs still not lighting up.** Re-verify the strip pins with a multimeter.
  If you swap 5V and GND, the WS2812B chips will die permanently.
- **When a hook fires, the LEDs briefly turn off and then back on.** This is normal: the
  ESP8266 resets on every serial port open, which is why the driver waits 0.5 s after
  opening the port before sending the command. If multiple hooks fire back-to-back you may
  see a brief flash.
- **"pyserial not installed" warning.** Run `pip3 install pyserial`. The hook config example
  calls the driver with `--quiet`, so this warning is hidden in the hook flow; it only
  appears when running manually.
- **Wrong port is being selected.** If multiple USB-serial devices are plugged in, set the
  `CLAUDE_LED_PORT` environment variable or pass `--port /dev/cu.usbserial-XXXX`.

---

## License

MIT © [Riscue](https://github.com/riscue)
