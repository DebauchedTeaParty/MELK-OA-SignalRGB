"""
MELK-OA Bluetooth bridge: emulates a Nanoleaf device so SignalRGB can control
one or more MELK-OA strips/panels over the network. Bridge receives colors via
REST/UDP and forwards to all configured MELK-OA devices via BLE.
"""

import asyncio
import json
import os
import queue
import sys
import socket
import struct
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

import melk_ble

# Fixed token so user doesn't need to hold device button
NANOLEAF_TOKEN = "melkoa1"
# Accept "null" so cached devices with key null still get 200 (fix validation Status: 0)
VALID_TOKENS = (NANOLEAF_TOKEN, "null")
HTTP_PORT = 16021
UDP_PORT = 60222
MAX_FPS = 30  # Throttle BLE updates

app = Flask(__name__)
CORS(app)


@app.before_request
def log_request():
    # Log all API requests so we see what SignalRGB calls (helps debug validation / effects)
    if request.path.startswith("/api/"):
        if request.method in ("PUT", "POST"):
            body = ""
            if request.get_data():
                try:
                    body = request.get_json(silent=True) or request.get_data()[:200]
                    body = str(body)[:300]
                except Exception:
                    body = "(binary)"
            print(f"[HTTP] {request.method} {request.path} -> body: {body[:200] if body else '(none)'}")
        else:
            print(f"[HTTP] {request.method} {request.path}")


@app.errorhandler(404)
def not_found(e):
    # Avoid 404 for API paths so validation doesn't see "invalid"; return 200 + minimal JSON
    if request.path.startswith("/api/"):
        return jsonify({"name": "Nanoleaf Canvas", "model": "NL22"}), 200, {"Content-Type": "application/json"}
    return e


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "internal", "name": "Nanoleaf Canvas"}), 200, {"Content-Type": "application/json"}
    return e

# Shared state
color_queue = queue.Queue(maxsize=2)  # Drop old frames if slow
effect_command_queue = queue.Queue(maxsize=1)  # (mode_id, speed) to set device effect
mac_addresses = []  # list of MACs to control (all get same color/effect)
ble_ready = threading.Event()
ble_error = [None]  # list so worker can set, main can read
streaming_active = False  # True after SignalRGB enables extControl v2
# Current device effect (mode_id 0–255, speed 0–255); set via PUT /api/v1/<token>/device/effect
effect_mode_id = 0
effect_speed = 128
# Keep zeroconf service alive globally
_zeroconf_service = None
# GUI and control state
_paused = False  # Pause color updates
_server_running = False  # Flask server status
_udp_count = [0]  # UDP packet counter for GUI
_should_restart = False  # Flag to restart bridge
_should_stop = False  # Flag to stop bridge
_flask_app = None  # Flask app instance for control

# Log throttling for console output (set to 0 to disable per-packet logs)
LOG_UDP_EVERY = 0    # We show UDP packet count in the GUI instead of raw packets
LOG_BLE_EVERY = 0
ble_send_count = [0]  # list so worker can mutate
LOG_UDP_RAW_FIRST = 50  # Log first N UDP packets in full (any length) to debug "no UDP" issue


def load_device_list():
    """Load MAC list from melk_config.json or env MELK_MAC_ADDRESSES. Returns list or None to scan."""
    # Env: comma-separated MACs (e.g. MELK_MAC_ADDRESSES=AA:BB:...,CC:DD:...)
    env_macs = os.environ.get("MELK_MAC_ADDRESSES", "").strip()
    if env_macs:
        addrs = [a.strip().upper() for a in env_macs.split(",") if a.strip()]
        if addrs:
            return addrs
    # File: next to exe when frozen, else next to this script
    if getattr(sys, "frozen", False):
        config_dir = Path(sys.executable).resolve().parent
    else:
        config_dir = Path(__file__).resolve().parent
    config_path = config_dir / "melk_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            addrs = data.get("mac_addresses")  # list of MAC strings
            if isinstance(addrs, list) and addrs:
                return [str(a).strip().upper() for a in addrs if a]
        except Exception:
            pass
    return None  # None = scan for all MELK-OA


def run_ble_worker():
    """Background thread: load or scan devices, turn on, then send colors to all MELK-OA."""
    global mac_addresses
    try:
        import melk_tray
        melk_tray.set_status(ble_status="Starting")
    except:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        configured = load_device_list()
        if configured:
            mac_addresses = configured
            print(f"[BLE] Using {len(mac_addresses)} device(s) from config: {mac_addresses}")
        else:
            devices = loop.run_until_complete(melk_ble.scan_for_melk_oa(timeout=12.0))
            if not devices:
                ble_error[0] = "No MELK-OA device found. Ensure strips/panels are on and in range."
                ble_ready.set()
                return
            mac_addresses = [d.address for d in devices]
            print(f"[BLE] Found {len(mac_addresses)} MELK-OA device(s): {mac_addresses}")
        # Turn on all (optional; requires btledstrip)
        try:
            loop.run_until_complete(melk_ble.turn_on_all(mac_addresses))
            print("[BLE] Turn-on sent to all devices (btledstrip).")
        except Exception as e:
            if "btledstrip" in str(e).lower():
                print("[BLE] btledstrip not installed — devices won't auto turn-on. Turn on manually or: pip install btledstrip")
            else:
                print(f"[BLE] turn_on error: {e}")
        time.sleep(1.0)
        ble_ready.set()
        # Send color loop (throttled); also handle effect commands
        last_send = 0
        while not _should_stop:
            # Handle effect/mode change (optimized: check queue without blocking)
            try:
                mode_id, speed = effect_command_queue.get_nowait()
                try:
                    loop.run_until_complete(melk_ble.send_mode_all(mac_addresses, mode_id))
                    loop.run_until_complete(melk_ble.send_mode_speed_all(mac_addresses, speed))
                    # Don't log effect changes to keep console clean (GUI shows status)
                except Exception as e:
                    print(f"[BLE] send_mode error: {e}")
            except queue.Empty:
                pass
            # Get color from queue (with timeout to allow _should_stop check)
            try:
                (r, g, b) = color_queue.get(timeout=0.5)
            except queue.Empty:
                if _should_stop:
                    break
                continue
            # Throttle to MAX_FPS
            now = time.monotonic()
            if now - last_send < 1.0 / MAX_FPS:
                continue
            last_send = now
            # Only send if not paused
            if not _paused:
                try:
                    loop.run_until_complete(melk_ble.send_color_all(mac_addresses, r, g, b))
                    ble_send_count[0] += 1
                    if LOG_BLE_EVERY and (ble_send_count[0] <= 3 or ble_send_count[0] % LOG_BLE_EVERY == 0):
                        print(f"[BLE] sent color #{ble_send_count[0]} RGB({r},{g},{b}) -> {len(mac_addresses)} device(s)")
                except Exception as e:
                    print(f"[BLE] send_color error: {e}")
    except Exception as e:
        ble_error[0] = str(e)
        ble_ready.set()
        print(f"[BLE] Worker error: {e}")
    finally:
        loop.close()


def run_udp_server():
    """Listen for Nanoleaf extControl UDP on 60222; push first panel RGB to queue."""
    global _udp_count
    try:
        import melk_tray
        melk_tray.set_status(udp_status="Starting")
    except:
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[UDP] Listening on 0.0.0.0:{UDP_PORT}")
    _udp_count[0] = 0
    try:
        import melk_tray
        melk_tray.set_status(udp_status="Receiving", udp_receiving=True)
    except:
        pass
    last_packet_time = time.time()
    try:
        while not _should_stop:
            try:
                # Set timeout to allow checking _should_stop
                sock.settimeout(1.0)
                data, addr = sock.recvfrom(1024)
                _udp_count[0] += 1
                last_packet_time = time.time()
                # For EXE use, avoid printing raw packets; GUI shows UDP count
                if len(data) < 8:
                    # Ignore short packets silently; GUI still sees total count
                    continue
                # Nanoleaf extControl: v2 (SignalRGB) = [0, nPanels, panelId_hi, panelId_lo, r, g, b, w, time, ...] per panel (8 bytes each)
                # v1 or legacy = [nPanels, panelId, reserved, r, g, b, w, time] (7 bytes per panel) or version 0x01/0x02 header
                off = 0
                n = 0
                if data[0] == 0 and len(data) >= 2:
                    # SignalRGB SendColorsv2: packet[0]=0, packet[1]=lightCount, then 8 bytes per panel
                    off = 2
                    n = data[1]
                elif data[0] in (0x01, 0x02):
                    off = 2
                    n = data[1] if len(data) > 1 else 0
                else:
                    off = 1
                    n = data[0]
                if n == 0 or off + 7 > len(data):
                    # Can't parse packet; skip without noisy logging
                    continue
                r = data[off + 2]
                g = data[off + 3]
                b = data[off + 4]
                # Only queue if not paused
                if not _paused:
                    if color_queue.full():
                        try:
                            color_queue.get_nowait()
                        except queue.Empty:
                            pass
                    color_queue.put((r, g, b))
                # Optionally log aggregated UDP info (disabled by default)
                if LOG_UDP_EVERY and (_udp_count[0] % LOG_UDP_EVERY == 0):
                    print(f"[UDP] received {_udp_count[0]} packets so far")
            except socket.timeout:
                # Check if we should stop or if UDP is still receiving (timeout is normal)
                if time.time() - last_packet_time > 5.0:
                    # No packets for 5 seconds - update GUI
                    pass
                continue
    except Exception as e:
        print(f"[UDP] error: {e}")


# Stable device id so SignalRGB cache/link has a defined key (fixes "Adding undefined to IP Cache")
DEVICE_ID = "melkoa-bridge-1"

# --- Nanoleaf REST API (minimal for SignalRGB) ---
# Return JSON with 200 so validation (State 4) passes; avoid 404/5xx = "invalid call"

@app.route("/api/v1/", methods=["GET"])
@app.route("/api/v1", methods=["GET"])
def api_root():
    # Root without token - some clients validate by GET here; must return 200 + valid body
    return jsonify({
        "name": "Nanoleaf Canvas",
        "model": "NL22",
        "firmwareVersion": "3.2.0",
        "id": DEVICE_ID,
        "serialNo": DEVICE_ID,
        "serialNumber": DEVICE_ID,
        "manufacturer": "Nanoleaf",
    }), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/new", methods=["POST", "GET"])
def api_new():
    """Return token (no physical button required). SignalRGB uses this to link."""
    return jsonify({"auth_token": NANOLEAF_TOKEN, "token": NANOLEAF_TOKEN}), 200, {"Content-Type": "application/json"}


def _check_token(token):
    if token not in VALID_TOKENS:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route("/api/v1/<token>/", methods=["GET"])
@app.route("/api/v1/<token>", methods=["GET"])
def api_device_info(token):
    err = _check_token(token)
    if err:
        return err
    # Full device info; include booleans/nested state SignalRGB editor may expect
    return jsonify({
        "name": "Nanoleaf Canvas",
        "model": "NL22",
        "firmwareVersion": "3.2.0",
        "id": DEVICE_ID,
        "serialNo": DEVICE_ID,
        "serialNumber": DEVICE_ID,
        "state": {
            "on": {"value": True},
            "brightness": {"value": 100},
            "hue": {"value": 0},
            "sat": {"value": 0},
        },
        "effects": {
            "select": "*ExtControl*" if streaming_active else "Solid",
            "list": ["Solid", "*ExtControl*"],
            "effectsList": ["Solid", "*ExtControl*"],  # SignalRGB extension uses this
        },
        "panelLayout": {
            "layout": {
                "numPanels": 1,
                "sideLength": 100,
                "positionData": [{"panelId": 1, "x": 0, "y": 0, "o": 0, "shapeType": 0}],
            }
        },
    }), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/<token>/state", methods=["GET"])
@app.route("/api/v1/<token>/state/", methods=["GET"])
def api_state(token):
    err = _check_token(token)
    if err:
        return err
    return jsonify({
        "on": {"value": True},
        "brightness": {"value": 100},
        "hue": {"value": 0},
        "sat": {"value": 0},
    }), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/<token>/effects/effect", methods=["GET"])
@app.route("/api/v1/<token>/effects/effect/", methods=["GET"])
def api_effect_current(token):
    err = _check_token(token)
    if err:
        return err
    name = "*ExtControl*" if streaming_active else "Solid"
    return jsonify({"effectName": name}), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/<token>/effects/select", methods=["GET"])
@app.route("/api/v1/<token>/effects/select/", methods=["GET"])
def api_effects_select(token):
    """Current effect name; SignalRGB extension calls this (GetCurrentEffect)."""
    err = _check_token(token)
    if err:
        return err
    value = "*ExtControl*" if streaming_active else "Solid"
    return jsonify({"value": value}), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/<token>/panelLayout", methods=["GET"])
@app.route("/api/v1/<token>/panelLayout/", methods=["GET"])
def api_panel_layout_root(token):
    err = _check_token(token)
    if err:
        return err
    return jsonify({
        "layout": {
            "numPanels": 1,
            "sideLength": 100,
            "positionData": [{"panelId": 1, "x": 0, "y": 0, "o": 0, "shapeType": 0}],
        }
    }), 200, {"Content-Type": "application/json"}


@app.route("/api/v1/<token>/panelLayout/layout", methods=["GET"])
def api_panel_layout(token):
    err = _check_token(token)
    if err:
        return err
    # Single "panel" so SignalRGB sends one color
    return jsonify({
        "numPanels": 1,
        "sideLength": 100,
        "positionData": [
            {"panelId": 1, "x": 0, "y": 0, "o": 0, "shapeType": 0}
        ]
    })


@app.route("/api/v1/<token>/effects/", methods=["PUT"])
@app.route("/api/v1/<token>/effects", methods=["PUT"])
def api_effects(token):
    err = _check_token(token)
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    # SignalRGB SetCurrentEffect sends {"select": effectName}; extension expects 204
    if "select" in body and "write" not in body:
        return Response(status=204)
    write = body.get("write") or body
    anim_type = write.get("animType")
    if anim_type == "extControl" and write.get("extControlVersion") == "v2":
        global streaming_active
        streaming_active = True
        print("[HTTP] extControl v2 enabled (streaming) -> expect UDP on port 60222")
        print("       If you never see [UDP] lines: allow Windows Firewall inbound UDP 60222 for Python.")
        # SignalRGB extension only sets streamOpen when status === 204 (see StartStreamV2 in Nanoleaf.js)
        return Response(status=204)
    # Static / animData: e.g. "1 1 1 R G B 0 1" or "1 1 1 0 0 255 0 1" -> use R,G,B
    anim_data = write.get("animData") or ""
    if anim_data and " " in anim_data:
        parts = anim_data.split()
        if len(parts) >= 6:
            try:
                r = int(parts[3]) & 0xFF
                g = int(parts[4]) & 0xFF
                b = int(parts[5]) & 0xFF
                if color_queue.full():
                    try:
                        color_queue.get_nowait()
                    except queue.Empty:
                        pass
                color_queue.put((r, g, b))
                print(f"[HTTP] effect animData -> RGB({r},{g},{b}) queued")
            except (ValueError, IndexError):
                pass
    # Also accept direct color in write (some clients send different shape)
    for key in ("r", "red", "hue"):
        if key in write and isinstance(write.get(key), (int, float)):
            try:
                r = int(write.get("r", write.get("red", 0))) & 0xFF
                g = int(write.get("g", write.get("green", 0))) & 0xFF
                b = int(write.get("b", write.get("blue", 0))) & 0xFF
                if color_queue.full():
                    try:
                        color_queue.get_nowait()
                    except queue.Empty:
                        pass
                color_queue.put((r, g, b))
                print(f"[HTTP] effect color -> RGB({r},{g},{b}) queued")
                break
            except (ValueError, TypeError):
                pass
    return jsonify({})


@app.route("/api/v1/<token>/state/brightness", methods=["GET", "PUT"])
def api_state_brightness(token):
    err = _check_token(token)
    if err:
        return err
    if request.method == "PUT":
        # SignalRGB extension expects 204 for SetBrightness (Nanoleaf.js)
        return Response(status=204)
    return jsonify({"value": 100})


@app.route("/api/v1/<token>/state/on", methods=["GET", "PUT"])
def api_state_on(token):
    err = _check_token(token)
    if err:
        return err
    return jsonify({"value": True})


@app.route("/api/v1/<token>/device/effect", methods=["GET", "PUT"])
def api_device_effect(token):
    """Get or set device effect (mode_id 0–255, speed 0–255). Device runs built-in effect with per-panel colours."""
    global effect_mode_id, effect_speed
    err = _check_token(token)
    if err:
        return err
    if request.method == "PUT":
        body = request.get_json(force=True, silent=True) or {}
        mode_id = body.get("mode_id")
        speed = body.get("speed")
        if mode_id is not None:
            effect_mode_id = max(0, min(255, int(mode_id)))
        if speed is not None:
            effect_speed = max(0, min(255, int(speed)))
        try:
            effect_command_queue.put_nowait((effect_mode_id, effect_speed))
        except queue.Full:
            try:
                effect_command_queue.get_nowait()
            except queue.Empty:
                pass
            effect_command_queue.put_nowait((effect_mode_id, effect_speed))
        return jsonify({"mode_id": effect_mode_id, "speed": effect_speed}), 200
    return jsonify({"mode_id": effect_mode_id, "speed": effect_speed}), 200


def main(start_gui: bool = True):
    global _should_stop, _should_restart, _paused, _server_running, _flask_app
    
    # Ensure we're in the script directory for config file lookups
    script_dir = Path(__file__).resolve().parent
    if Path.cwd() != script_dir:
        os.chdir(script_dir)
        print(f"[INFO] Changed working directory to: {script_dir}")
    
    # Initialize tray (and optionally GUI) - must be done early and kept alive
    tray_icon_path = None
    try:
        import melk_tray
        icon_path = script_dir / "icons" / "rgb.png"
        if icon_path.exists():
            tray_icon_path = icon_path
        else:
            # Try to find icon in executable directory
            if getattr(sys, 'frozen', False):
                exe_dir = Path(sys.executable).parent
                icon_path = exe_dir / "icons" / "rgb.png"
                if icon_path.exists():
                    tray_icon_path = icon_path
        
        # Initialize status as "Starting" for all components
        melk_tray.set_status(
            running=True, 
            server_running=False,  # Will be "Starting" then True
            server_status="Starting",
            udp_receiving=False, 
            udp_status="Starting",
            udp_count=0, 
            ble_ready=False,
            ble_status="Starting",
            devices=[], 
            local_ip="127.0.0.1", 
            http_port=HTTP_PORT
        )
        
        def on_pause():
            global _paused
            _paused = not _paused
            print(f"[GUI] {'Paused' if _paused else 'Resumed'} color updates")
        
        def on_restart():
            global _should_restart
            _should_restart = True
            print("[GUI] Restart requested")
            # Flask will be stopped by the main loop checking _should_restart
        
        def on_stop():
            """Handle exit from GUI or tray: stop workers, close tray and exit process."""
            global _should_stop
            _should_stop = True
            print("[GUI] Exit requested")
            # Stop tray icon
            try:
                melk_tray.stop_tray()
            except Exception:
                pass
            # Close GUI window if it exists
            try:
                import melk_gui
                import tkinter as tk
                gui = melk_gui.get_gui_instance()
                if gui and hasattr(gui, "root"):
                    try:
                        if gui.root.winfo_exists():
                            gui.root.after(0, lambda: (gui.root.quit(), gui.root.destroy()))
                    except (RuntimeError, tk.TclError):
                        # Mainloop already exited, just destroy
                        try:
                            gui.root.destroy()
                        except:
                            pass
            except Exception:
                pass
            # GUI quit will cause start_melk_bridge.py to exit via os._exit(0)
        
        melk_tray.set_callbacks(restart=on_restart, stop=on_stop, pause=on_pause)
        
        # Start tray in a separate thread (non-daemon to keep app alive)
        tray_thread = melk_tray.start_tray_thread(tray_icon_path)
        if tray_thread:
            print("[GUI] System tray thread started")
            # Wait a moment to ensure it initializes
            time.sleep(1)
            if not melk_tray.is_tray_running():
                print("[GUI] WARNING: System tray thread started but icon not running")
        else:
            print("[GUI] WARNING: Failed to start system tray thread")
    except ImportError as e:
        print(f"[GUI] System tray not available (pystray/pillow not installed): {e}")
    except Exception as e:
        print(f"[GUI] Error starting system tray: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 60)
    print("MelkoLeaf Bridge")
    print("Ready for SignalRGB.")
    print("=" * 60)
    print(f"[INFO] Script directory: {script_dir}")
    print(f"[INFO] Working directory: {Path.cwd()}")
    
    # Main loop - allows restart
    while not _should_stop:
        _should_restart = False
        # Don't reset _should_stop here - it's set by on_stop callback
        
        # Start BLE worker
        t_ble = threading.Thread(target=run_ble_worker, daemon=True)
        t_ble.start()
        # Start UDP server
        t_udp = threading.Thread(target=run_udp_server, daemon=True)
        t_udp.start()
        # Wait for BLE to be ready (or error)
        ble_ready.wait(timeout=15)
        if ble_error[0]:
            print(f"[!] BLE: {ble_error[0]}")
            print("    Bridge will still run; add device in SignalRGB and try streaming.")
            try:
                import melk_tray
                melk_tray.set_status(ble_ready=False, ble_status="Not ready", devices=[])
            except:
                pass
        else:
            print(f"[BLE] Ready. Device(s): {mac_addresses}")
            try:
                import melk_tray
                melk_tray.set_status(ble_ready=True, ble_status="Ready", devices=mac_addresses.copy())
            except:
                pass
        
        # Local IP for discovery and manual add
        local_ip = "127.0.0.1"
        try:
            # Try to get the actual network interface IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Connect to external IP to determine which interface is used
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            print(f"[INFO] Detected local IP: {local_ip}")
        except Exception as e:
            print(f"[WARN] Could not detect local IP automatically: {e}")
            print(f"[WARN] Using fallback IP: {local_ip}")
            print(f"[WARN] SignalRGB may need manual IP entry: {local_ip}")
            # Try alternative method: get hostname IP
            try:
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                if local_ip and local_ip != "127.0.0.1":
                    print(f"[INFO] Using hostname IP: {local_ip}")
            except Exception:
                pass
        
        # Zeroconf: advertise as ONE Nanoleaf device only (avoid duplicate entries)
        global _zeroconf_service
        try:
            from zeroconf import ServiceInfo, Zeroconf
            _zeroconf_service = Zeroconf()
            addr_bytes = [socket.inet_aton(local_ip)]
            # id so SignalRGB has a defined cache key (fixes "Adding undefined to IP Cache")
            props = {"path": "/api/v1/", "md": "NL22", "id": DEVICE_ID}
            info = ServiceInfo(
                "_nanoleafapi._tcp.local.",
                "Nanoleaf Canvas._nanoleafapi._tcp.local.",
                port=HTTP_PORT,
                properties=props,
                server="melkoa.local.",
                addresses=addr_bytes,
            )
            _zeroconf_service.register_service(info)
            print(f"[mDNS] Advertising as Nanoleaf at {local_ip}:{HTTP_PORT} (single device).")
            # Register cleanup handler to unregister service on exit
            import atexit
            def cleanup_zeroconf():
                global _zeroconf_service
                if _zeroconf_service:
                    try:
                        _zeroconf_service.unregister_service(info)
                        _zeroconf_service.close()
                    except Exception:
                        pass
            atexit.register(cleanup_zeroconf)
        except Exception as e:
            print(f"[mDNS] Not used: {e}")
            import traceback
            print(f"[mDNS] Error details: {traceback.format_exc()}")
        
        print("=" * 60)
        print(f"[HTTP] Starting Flask server on 0.0.0.0:{HTTP_PORT}...")
        print(f"[HTTP] Server will be accessible at http://{local_ip}:{HTTP_PORT}")
        
        # Update GUI status
        try:
            import melk_tray
            melk_tray.set_status(server_running=True, server_status="Running", local_ip=local_ip, http_port=HTTP_PORT)
        except:
            pass
        
        _server_running = True
        _flask_app = app
        
        # Status update thread for GUI
        def update_gui_status():
            try:
                import melk_tray
                while not _should_stop and not _should_restart:
                    # Check if UDP is receiving (packets in last 5 seconds)
                    udp_receiving = _udp_count[0] > 0
                    melk_tray.set_status(
                        server_running=_server_running,
                        udp_receiving=udp_receiving,
                        udp_count=_udp_count[0],
                        paused=_paused,
                        devices=mac_addresses.copy() if mac_addresses else []
                    )
                    time.sleep(1)
            except:
                pass
        
        status_thread = threading.Thread(target=update_gui_status, daemon=True)
        status_thread.start()
        
        # Ensure system tray is running - check periodically
        def check_tray_alive():
            try:
                import melk_tray
                while not _should_stop and not _should_restart:
                    if not melk_tray.is_tray_running():
                        print("[GUI] System tray not running, attempting to restart...")
                        melk_tray.start_tray_thread(tray_icon_path)
                    time.sleep(5)  # Check every 5 seconds
            except Exception as e:
                print(f"[GUI] Error in tray monitor: {e}")
        
        tray_monitor_thread = threading.Thread(target=check_tray_alive, daemon=True)
        tray_monitor_thread.start()
        
        try:
            # Run Flask in a way that can be stopped
            from werkzeug.serving import make_server
            server = make_server("0.0.0.0", HTTP_PORT, app, threaded=True)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            
            # Wait for shutdown signal - keep main thread alive
            while not _should_stop and not _should_restart:
                time.sleep(0.5)
            
            server.shutdown()
            server_thread.join(timeout=2)
        except OSError as e:
            if "Address already in use" in str(e) or "Only one usage of each socket address" in str(e):
                print(f"[ERROR] Port {HTTP_PORT} is already in use. Another instance may be running.")
                print(f"[ERROR] Close other instances or change HTTP_PORT in the code.")
            else:
                print(f"[ERROR] Failed to start Flask server: {e}")
            _server_running = False
            if not _should_restart:
                raise
        except (KeyboardInterrupt, SystemExit):
            _server_running = False
            _should_stop = True
            break
        finally:
            _server_running = False
            _flask_app = None
        
        if _should_restart:
            print("[INFO] Restarting bridge...")
            time.sleep(1)
            continue
        else:
            break
    
    # Cleanup
    try:
        import melk_tray
        melk_tray.set_status(running=False)
        melk_tray.stop_tray()
    except:
        pass
    print("[INFO] Bridge stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
        sys.exit(0)
    except Exception as e:
        import traceback
        error_msg = f"[ERROR] Fatal error: {e}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        # Log to file
        try:
            log_file = Path(__file__).parent / "error.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Error occurred\n")
                f.write(f"{error_msg}\n")
                f.write(f"{'='*60}\n")
        except Exception:
            pass
        # Keep console open on error
        try:
            input("\nPress Enter to exit...")
        except:
            pass
        sys.exit(1)
