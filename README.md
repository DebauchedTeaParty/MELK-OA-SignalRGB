## MelkoLeaf – MELK-OA Nanoleaf Bridge for SignalRGB

MelkoLeaf is a Python-based bridge that makes cheap **MELK-OA LED panels and strips** work with **SignalRGB** by emulating a **Nanoleaf** device.  
It speaks Nanoleaf on the network side and the MELK-OA “7E protocol” over Bluetooth Low Energy on the device side.

This repository contains both the **source bridge script** and a **modern GUI + tray EXE** for Windows, including an obfuscated build to reduce AV false-positives.

> The story and technical background are described in detail in the blog post  
> **“Building a Bridge: Making Cheap LED Panels Work with SignalRGB”** – see [the article](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/).

### MelkoLeaf GUI (EXE)

![MelkoLeaf GUI]([https://debauchedtea.party/img/qffzbzom/](https://debauchedtea.party/wp-content/uploads/2026/02/melko.png))

The EXE version runs in the background with a compact Material Design–inspired GUI and a system tray icon for quick control.

### Lights in Action

Short demo of the bridge driving MELK-OA panels via SignalRGB:  
[YouTube Short – MelkoLeaf + SignalRGB](https://youtube.com/shorts/tn5hn16_tJM?si=odGw8A4gB9eRlKyw)

---

## Features

- **Nanoleaf emulation for SignalRGB**
  - Emulates the Nanoleaf HTTP API using Flask
  - Implements the UDP “extControl v2” streaming protocol on port `60222`
  - Auto-discoverable via mDNS/zeroconf as a Nanoleaf Canvas

- **MELK-OA device support over BLE**
  - Scans for nearby MELK-OA devices with `bleak`
  - Uses the **7E protocol** to send colors and basic commands
  - Optional auto power-on via `btledstrip` (if installed)
  - Supports multiple panels/strips in sync (all same color)

- **Compact modern GUI (MelkoLeaf)**
  - Material Design 3–style dark UI using `ttkbootstrap`
  - Status tab showing:
    - Server status (Starting / Running / Stopped)
    - UDP status and total packet count
    - BLE status
    - Connected devices
    - Bridge IP and port
  - Controls:
    - **Pause / Resume** streaming to devices
    - **Restart** bridge
    - **Exit** (full shutdown, no orphan processes)
    - “Start with Windows” toggle (uses Windows registry)
  - Console tab showing live log output (Flask, UDP, BLE, errors)
  - Minimizes to **system tray** (via `pystray`) with tray menu:
    - Show Window
    - Pause / Resume
    - Restart
    - Exit
    - Live status items (server, UDP, BLE, devices, IP)

- **CLI / headless mode**
  - Can be run as a simple console bridge without the GUI
  - Same latency optimisations and throttling are shared between CLI and GUI modes

- **Obfuscated Windows EXE build**
  - Uses **PyArmor** to obfuscate Python sources
  - Packs everything with **PyInstaller** into a single `MelkoLeaf.exe`
  - Hides the console window in normal use
  - Why did I do this? It seems to be a common problem that python packaged as an exe creates AV false positives, this solves that issue. The app now only has 2 false positives on VirusTotal

---

## How It Works (High Level)

1. **Device Discovery (BLE)**
   - At startup, the bridge scans for MELK-OA devices using `bleak` or reads a configured device list from `melk_config.json` / `MELK_MAC_ADDRESSES`.
   - Optionally sends a “turn on + 100% brightness” sequence using `btledstrip`.

2. **Nanoleaf Emulation (HTTP + mDNS)**
   - A Flask server exposes a minimal Nanoleaf-style API on port `16021`.
   - mDNS/zeroconf advertises the bridge as a Nanoleaf Canvas so SignalRGB auto-discovers it.
   - HTTP routes satisfy what SignalRGB expects (`/api/v1/`, `/state`, `/effects`, etc.).

3. **Color Streaming (UDP)**
   - A UDP listener on `0.0.0.0:60222` receives Nanoleaf extControl v2 packets from SignalRGB.
   - The first “panel” color (or aggregate color) is extracted and pushed into a queue.
   - The bridge throttles to **30 FPS** and drops stale frames to keep latency low.

4. **BLE Forwarding (7E Protocol)**
   - A dedicated BLE worker thread reads from the color queue.
   - For each new color, it sends the 7E color packet to **all** configured MELK-OA devices in parallel using `bleak`.
   - All panels show the same color at the same time (hardware limitation).

5. **GUI + Tray (EXE)**
   - On Windows, `start_melk_bridge.py` starts the bridge logic in a background thread and launches the Tk/ttkbootstrap GUI on the main thread.
   - The GUI and tray read status from `melk_tray` and update indicators in real time.
   - Exiting from the GUI or tray cleanly stops UDP, BLE, HTTP, and the process.

For a more narrative explanation, see the original blog post:  
[Building a Bridge: Making Cheap LED Panels Work with SignalRGB](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/).

---

## Requirements

### Hardware

- MELK-OA LED panels or strips
- Windows PC with **Bluetooth** support
- [SignalRGB](https://www.signalrgb.com/) installed

### Software (source / dev setup)

- Python **3.12+** (3.14 also tested)
- Recommended to use a virtualenv

Python dependencies (see `requirements.txt`):

- Core bridge:
  - `bleak`
  - `btledstrip`
  - `flask`
  - `flask-cors`
  - `zeroconf`
- GUI + tray:
  - `ttkbootstrap`
  - `pystray`
  - `pillow`
- Windows integration:
  - `pywin32`
- Build / obfuscation (optional):
  - `pyinstaller`
  - `pyarmor`

Install dependencies for development:

```bash
pip install -r requirements.txt
```

---

## Running from Source (CLI / Dev)

### Simple CLI bridge (no GUI)

```bash
python melk_bridge.py
```

This:

- Scans for MELK-OA devices
- Starts the Flask Nanoleaf API on port `16021`
- Listens for UDP streaming on port `60222`

Use this mode when debugging or running headless (e.g. on a Linux box with Bluetooth).

### GUI + Tray (development)

On Windows, run:

```bash
python start_melk_bridge.py
```

This:

- Starts the bridge (BLE, UDP, HTTP, mDNS) in a background thread
- Launches the compact MelkoLeaf GUI on the main thread
- Shows a tray icon (`rgb.png`) in the notification area

If you see a console window in dev mode, that’s expected; the final EXE hides it.

---

## Using the Windows EXE

After building (see **Building the EXE** below) you’ll have:

- `dist/MelkoLeaf.exe`

Running `MelkoLeaf.exe` will:

- Change into the correct working directory for configs/logs
- Start the bridge
- Show the MelkoLeaf GUI window and a tray icon

### GUI Overview

- **Status tab**
  - Server – “Starting” → “Running” or “Stopped”
  - UDP – “Starting” → “Receiving (N packets)” or “Stopped (N packets)”
  - BLE – “Starting” / “Ready” / “Not Ready”
  - Devices – number of connected MELK-OA devices
  - Network – IP and port the bridge is advertising

- **Controls**
  - **Pause / Resume** – stop/resume applying UDP colors to the devices
  - **Restart** – restart the bridge components
  - **Exit** – fully closes GUI, tray, and bridge (no leftover processes)
  - **Start with Windows** – registers/unregisters MelkoLeaf in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  - **Minimize to Tray** – hides the window but keeps the tray icon active

- **Console tab**
  - Shows logs from Flask, UDP, BLE, and the bridge
  - Auto-scrolls and trims old log content to avoid memory bloat
  - “Clear” button to reset the log view

The tray menu mirrors key controls (Pause/Resume, Restart, Exit) and shows live status.

---

## SignalRGB Setup

1. **Start MelkoLeaf**
   - Run either `python start_melk_bridge.py` (dev) or `MelkoLeaf.exe` (EXE).
   - Wait for the GUI status to show:
     - Server: Running
     - UDP: Receiving (once an effect is running)
     - BLE: Ready

2. **Add the device in SignalRGB**
   - Open SignalRGB
   - Go to **Add Device → Nanoleaf**
   - The bridge should appear automatically via mDNS as a Nanoleaf Canvas


3. **Start an effect**
   - Pick any effect in SignalRGB; the panels/strips will follow in real time.

> Note: All connected MELK-OA devices show the same color. Individual panel control is not possible with this hardware, as explained in the [blog post](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/).

---

## Configuration

### Selecting specific devices

By default, the bridge scans for all nearby MELK-OA devices. To restrict it to specific MAC addresses, create a `melk_config.json` file next to the executable/script:

```json
{
  "mac_addresses": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
}
```

Alternatively, use the environment variable:

```bash
# PowerShell
$env:MELK_MAC_ADDRESSES="AA:BB:CC:DD:EE:FF,11:22:33:44:55:66"

# Bash
export MELK_MAC_ADDRESSES="AA:BB:CC:DD:EE:FF,11:22:33:44:55:66"
```

### Logs

When launched via `start_melk_bridge.py` or the EXE, logs are written to:

- `melk_bridge.log` – general info and errors
- `error.log` – fatal errors and stack traces

These are especially useful if the EXE fails to start the GUI or bridge.

---

## Building the Obfuscated EXE

1. **Install build dependencies**

```bash
pip install -r requirements.txt
```

2. **Run the build script (Windows)**

You can use either:

```bash
python build.py
```

or the convenience batch file:

```bash
build.bat
```

This will:

- Clean previous build artifacts
- Obfuscate selected modules with **PyArmor**
- Generate a PyInstaller `.spec` file with the correct paths and hidden imports
- Build `MelkoLeaf.exe` into the `dist` directory

3. **Run the EXE**

```text
dist\MelkoLeaf.exe
```

> The build is configured to **hide the console window** in normal use. During development you can temporarily enable the console via `build.py` if you want to see stdout/stderr.

---

## Limitations

- **Single-color output across devices**  
  MELK-OA hardware does not support addressing panels individually over BLE in this mode. All connected strips/panels receive the same color.

- **Windows-focused GUI EXE**  
  The GUI + tray EXE is currently designed and tested for Windows. The core bridge logic (`melk_bridge.py`) is portable and can be used on other platforms (with BLE + Python 3.12+).

- **Bluetooth bandwidth**  
  The bridge throttles updates to ~30 FPS. Sending faster than this provides no visual benefit and can cause latency or dropped frames.

---

## FAQ

- **Can I run this on Linux or macOS?**  
  Yes, for CLI/headless use. The core bridge (`melk_bridge.py`) should work anywhere `bleak` and Bluetooth are supported. The Windows-specific pieces are the tray integration and startup (registry) logic.

- **Why are effects / per-panel effects removed?**  
  To keep the bridge focused and reliable for SignalRGB usage. Device-side effects still exist in the hardware but are not exposed through this bridge. This matches the design explained in the [blog post](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/).

- **Why obfuscate the code?**  
  Obfuscation with PyArmor helps reduce false-positive flags from antivirus engines when distributing a standalone EXE and adds a mild layer of code protection.

---

## Credits & License

- Based on reverse engineering of MELK-OA panels and the work described in the blog post  
  [Building a Bridge: Making Cheap LED Panels Work with SignalRGB](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/).
- Uses the excellent libraries:
  - [Bleak](https://bleak.readthedocs.io/)
  - `btledstrip`
  - Flask / Flask-CORS
  - `zeroconf`
  - `ttkbootstrap`
  - `pystray` and `Pillow`
  - PyInstaller and PyArmor

This project is provided as-is for personal and educational use. It is not affiliated with Nanoleaf, SignalRGB, or MELK-OA.


