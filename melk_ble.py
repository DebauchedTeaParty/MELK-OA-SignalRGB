"""
Shared BLE logic for MELK-OA strip.
- Turn on: btledstrip.
- Set color: 7E 00 05 03 [R] [G] [B] 00 EF via BleakClient.
"""

import asyncio
from bleak import BleakScanner, BleakClient
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice

try:
    from btledstrip import BTLedStrip, MELKController
    BT_LED_STRIP_AVAILABLE = True
except ImportError:
    BT_LED_STRIP_AVAILABLE = False

WRITE_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"


def cmd_color_7e(r: int, g: int, b: int) -> bytes:
    """Build 7E set-color packet. r, g, b in 0–255."""
    return bytes([0x7E, 0x00, 0x05, 0x03, r & 0xFF, g & 0xFF, b & 0xFF, 0x00, 0xEF])


def cmd_mode_7e(mode_id: int) -> bytes:
    """Build 7E effect/mode select packet (from Magic Lantern app changeMode). mode_id = effect ID 0–255."""
    return bytes([0x7E, 0x05, 0x03, mode_id & 0xFF, 0x06, 0xFF, 0xFF, 0x00, 0xEF])


def cmd_mode_speed_7e(speed: int) -> bytes:
    """Build 7E mode speed packet (from app changeModeSpeed). speed 0–255."""
    return bytes([0x7E, 0x04, 0x02, speed & 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])


def _find_write_char(client):
    fallback = None
    for service in client.services:
        for char in service.characteristics:
            if str(char.uuid).upper() == WRITE_UUID.upper():
                return char
            if fallback is None and ("write" in char.properties or "write-without-response" in char.properties):
                fallback = char
    return fallback


async def scan_for_melk_oa(timeout=10.0):
    """Scan for MELK-OA devices. Returns list of BLEDevice."""
    devices = []
    def callback(device: BLEDevice, ad: AdvertisementData):
        name = ad.local_name or device.name or ""
        if "MELK-OA" in name.upper() or "MELK" in name.upper():
            if not any(d.address == device.address for d in devices):
                devices.append(device)
    scanner = BleakScanner(callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return devices


async def turn_on_and_brightness(mac: str):
    """Turn strip on and set brightness 100% via btledstrip."""
    if not BT_LED_STRIP_AVAILABLE:
        raise RuntimeError("btledstrip required for turn-on. pip install btledstrip")
    controller = MELKController()
    async with BTLedStrip(controller, mac) as led_strip:
        await led_strip.exec.turn_on()
        await asyncio.sleep(0.2)
        await led_strip.exec.brightness(percentage=100)
        await asyncio.sleep(0.2)


async def send_color(mac: str, r: int, g: int, b: int):
    """Send 7E color packet to strip via BLE. Connects, writes, disconnects."""
    client = BleakClient(mac)
    await client.connect()
    if not client.is_connected:
        return
    write_char = _find_write_char(client)
    if write_char:
        await client.write_gatt_char(write_char, cmd_color_7e(r, g, b), response=False)
    await client.disconnect()


async def send_mode(mac: str, mode_id: int):
    """Select device effect/mode by ID (0–255). Packet: 7E 05 03 <mode_id> 06 FF FF 00 EF."""
    client = BleakClient(mac)
    await client.connect()
    if not client.is_connected:
        return
    write_char = _find_write_char(client)
    if write_char:
        await client.write_gatt_char(write_char, cmd_mode_7e(mode_id), response=False)
    await client.disconnect()


async def send_mode_speed(mac: str, speed: int):
    """Set effect/mode speed (0–255). Packet: 7E 04 02 <speed> FF FF FF 00 EF."""
    client = BleakClient(mac)
    await client.connect()
    if not client.is_connected:
        return
    write_char = _find_write_char(client)
    if write_char:
        await client.write_gatt_char(write_char, cmd_mode_speed_7e(speed), response=False)
    await client.disconnect()


async def ensure_on_and_send_color(mac: str, r: int, g: int, b: int):
    """Send color only (strip should already be on from initial turn_on)."""
    await send_color(mac, r, g, b)


# --- Multi-device: run same command on all MACs in parallel ---

async def turn_on_all(mac_list: list) -> None:
    """Turn on and set brightness for all strips. Skips devices that fail."""
    if not mac_list:
        return
    async def one(mac):
        try:
            await turn_on_and_brightness(mac)
        except Exception:
            pass  # skip if btledstrip missing or device unreachable
    await asyncio.gather(*[one(m) for m in mac_list], return_exceptions=True)


async def send_color_all(mac_list: list, r: int, g: int, b: int) -> None:
    """Send same color to all devices in parallel."""
    if not mac_list:
        return
    await asyncio.gather(
        *[send_color(mac, r, g, b) for mac in mac_list],
        return_exceptions=True
    )


async def send_mode_all(mac_list: list, mode_id: int) -> None:
    """Set effect/mode on all devices in parallel."""
    if not mac_list:
        return
    await asyncio.gather(
        *[send_mode(mac, mode_id) for mac in mac_list],
        return_exceptions=True
    )


async def send_mode_speed_all(mac_list: list, speed: int) -> None:
    """Set effect speed on all devices in parallel."""
    if not mac_list:
        return
    await asyncio.gather(
        *[send_mode_speed(mac, speed) for mac in mac_list],
        return_exceptions=True
    )
