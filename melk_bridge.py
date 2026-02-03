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

# Log every N-th UDP/BLE event to see if data flows (set 0 to disable)
LOG_UDP_EVERY = 30
LOG_BLE_EVERY = 30
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
        while True:
            # Handle effect/mode change
            try:
                mode_id, speed = effect_command_queue.get_nowait()
                try:
                    loop.run_until_complete(melk_ble.send_mode_all(mac_addresses, mode_id))
                    loop.run_until_complete(melk_ble.send_mode_speed_all(mac_addresses, speed))
                    print(f"[BLE] effect mode_id={mode_id} speed={speed} -> {len(mac_addresses)} device(s)")
                except Exception as e:
                    print(f"[BLE] send_mode error: {e}")
            except queue.Empty:
                pass
            try:
                (r, g, b) = color_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            now = time.monotonic()
            if now - last_send < 1.0 / MAX_FPS:
                continue
            last_send = now
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[UDP] Listening on 0.0.0.0:{UDP_PORT} (Nanoleaf streaming). Allow firewall inbound UDP {UDP_PORT} if no packets arrive.")
    udp_count = [0]  # list so we mutate in closure
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            udp_count[0] += 1
            # Log first N packets in full so we can see if SignalRGB sends anything and in what format
            if udp_count[0] <= LOG_UDP_RAW_FIRST:
                print(f"[UDP] #{udp_count[0]} from {addr}: len={len(data)} hex={data.hex()}")
            if len(data) < 8:
                if udp_count[0] > LOG_UDP_RAW_FIRST or udp_count[0] % 100 == 0:
                    print(f"[UDP] short packet #{udp_count[0]} from {addr} len={len(data)} (need >=8)")
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
                if udp_count[0] <= LOG_UDP_RAW_FIRST:
                    print(f"[UDP] unparsed #{udp_count[0]} n={n} off={off} len={len(data)}")
                continue
            r = data[off + 2]
            g = data[off + 3]
            b = data[off + 4]
            if color_queue.full():
                try:
                    color_queue.get_nowait()
                except queue.Empty:
                    pass
            color_queue.put((r, g, b))
            if LOG_UDP_EVERY and (udp_count[0] <= 3 or udp_count[0] % LOG_UDP_EVERY == 0):
                print(f"[UDP] #{udp_count[0]} from {addr}: len={len(data)} first={data[:min(12, len(data))].hex()} -> RGB({r},{g},{b})")
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


def main():
    print("=" * 60)
    print("MELK-OA Bridge (Nanoleaf emulation)")
    print("SignalRGB can add this as a Nanoleaf device by IP.")
    print("=" * 60)
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
    else:
        print(f"[BLE] Ready. Device(s): {mac_addresses}")
    # Local IP for discovery and manual add
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    # Zeroconf: advertise as ONE Nanoleaf device only (avoid duplicate entries)
    _zeroconf = None
    try:
        from zeroconf import ServiceInfo, Zeroconf
        _zeroconf = Zeroconf()
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
        _zeroconf.register_service(info)
        print(f"[mDNS] Advertising as Nanoleaf at {local_ip}:{HTTP_PORT} (single device).")
    except Exception as e:
        print(f"[mDNS] Not used: {e}")
    print()
    print("If SignalRGB did not auto-discover:")
    print("  1. Add Device → Nanoleaf (or search for 'Nanoleaf')")
    print("  2. Enter IP:", local_ip)
    print("  3. Port:", HTTP_PORT)
    print("  4. Token:", NANOLEAF_TOKEN)
    print()
    print("Then start an effect; the strip should follow.")
    print()
    print("Multiple devices: all discovered MELK-OA panels/strips are controlled together.")
    print("  To pin specific MACs, create melk_config.json: {\"mac_addresses\": [\"AA:BB:...\", ...]}")
    print("Device effects (per-panel colours): PUT /api/v1/<token>/device/effect")
    print("  body: {\"mode_id\": 0-255, \"speed\": 0-255}  (same IDs as Magic Lantern app)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
