# MELK-OA Nanoleaf Bridge for SignalRGB

A bridge application that makes affordable MELK-OA LED panels and strips work with SignalRGB by emulating Nanoleaf devices. This project allows you to use budget-friendly RGB lighting with SignalRGB's premium ecosystem.

Note: I have tested this on two sets of panels and a set of strip lights and over two machines with no issues, however, another tester found that the Nanoleaf bridge was setup correctly but the lights set to colours outside of their theme. I have been unable to replicate this and as such am unsure on how to fix it. If you run into this issue please let me know. In future versions of the executable I intend to add some sort of logging so that i can work out any problems like this if they arise. I have also been able to reduce latency in the app and colour changes have been able to roughly keep up now upto a shift speed of around 50-60. I'll be pushing that version live over the coming days and will remove this message once I have done it.

## Overview

SignalRGB doesn't natively support MELK-OA devices, but it does support Nanoleaf panels. This bridge acts as a translator: SignalRGB thinks it's talking to a Nanoleaf device, but the bridge translates those commands into the 7E protocol that MELK-OA devices understand over Bluetooth Low Energy (BLE).

## Features

- **New .exe version available in releases to remove the need for the setup steps below
- **Automatic Device Discovery**: Automatically scans for and connects to nearby MELK-OA devices
- **Multi-Device Support**: Control multiple MELK-OA panels/strips simultaneously (all synchronized)
- **Real-time Color Streaming**: Receives color updates from SignalRGB via UDP and forwards them to your devices
- **Zero Configuration**: Works out of the box - just run and connect
- **mDNS Discovery**: Advertises itself as a Nanoleaf device for easy auto-detection in SignalRGB

## Requirements

- **Hardware**:
  - MELK-OA LED panels or strips
  - A computer with Bluetooth support
  - SignalRGB installed

- **Software**:
  - Python 3.12 or higher

## Installation

1. **Clone or download this repository**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
## Usage

### Basic Setup

1. **Power on your MELK-OA panels/strips** and ensure they're in Bluetooth range

2. **Start the bridge**:
   ```bash
   python start_melk_bridge.py
   ```
   Or directly:
   ```bash
   python melk_bridge.py
   ```

3. **Add device in SignalRGB**:
   - Open SignalRGB
   - Go to **Add Device** → **Nanoleaf** (or search for "Nanoleaf")
   - If auto-discovery worked, the device should appear automatically

4. **Start an effect in SignalRGB** - your MELK-OA panels should now sync with the colors!

### Configuration (Optional)

#### Using Specific Devices

By default, the bridge scans for all nearby MELK-OA devices. To use specific devices only, create a `melk_config.json` file in the same directory as the bridge:

```json
{
  "mac_addresses": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
}
```

Replace the MAC addresses with your actual device addresses (shown in the bridge console when it discovers devices).

#### Environment Variable Alternative

You can also set device MAC addresses via environment variable:

```bash
# Windows PowerShell
$env:MELK_MAC_ADDRESSES="AA:BB:CC:DD:EE:FF,11:22:33:44:55:66"

# Linux/macOS
export MELK_MAC_ADDRESSES="AA:BB:CC:DD:EE:FF,11:22:33:44:55:66"
```

## How It Works

1. **Device Discovery**: The bridge scans for MELK-OA devices using Bluetooth Low Energy (BLE)
2. **Nanoleaf Emulation**: A Flask web server emulates the Nanoleaf REST API that SignalRGB expects
3. **Color Streaming**: SignalRGB sends color data via UDP (port 60222) using the Nanoleaf extControl protocol
4. **Protocol Translation**: The bridge translates Nanoleaf commands into the 7E protocol format that MELK-OA devices understand
5. **Bluetooth Communication**: Colors are sent to all connected MELK-OA devices simultaneously via BLE

## Limitations

**Individual Panel Control**: Unlike real Nanoleaf panels, MELK-OA devices cannot be individually controlled. All panels/strips connected to the bridge will display the same color at the same time. This is a hardware limitation - the devices don't have unique addresses and all listen to the same Bluetooth signal.

This means:
- ✅ All panels are perfectly synchronized
- ✅ Great for ambient lighting that reacts to games/music
- ❌ Cannot create multi-colored flowing patterns across panels
- ❌ Each panel cannot be a different color

For most use cases, this is perfectly fine and still provides an excellent RGB experience at a fraction of the cost of premium lighting.

## Troubleshooting

### No Devices Found

- Ensure your MELK-OA panels are powered on
- Make sure Bluetooth is enabled on your computer
- Check that devices are within Bluetooth range
- Try running the bridge with administrator/root privileges

### No UDP Packets Received

- **Windows Firewall**: Allow Python to receive incoming UDP connections on port 60222
- Check the bridge console for `[UDP]` messages - if you don't see any, SignalRGB may not be sending data
- Ensure SignalRGB has the device added and an effect is running

### Devices Don't Turn On Automatically

- Install `btledstrip` (see Installation section)
- You may need to manually power on your devices the first time
- Check that the bridge console shows `[BLE] Turn-on sent to all devices`

### SignalRGB Can't Find the Device

- Check that your computer's local IP is correct
- Ensure port 16021 is not blocked by firewall
- Try manually adding the device with the IP address shown in the bridge console

## Technical Details

### Protocol Information

The MELK-OA devices use the "7E protocol" (named after the first byte in each command):

- **Color Command**: `7E 00 05 03 [R] [G] [B] 00 EF`
- **Mode/Effect Command**: `7E 05 03 [mode_id] 06 FF FF 00 EF`
- **Speed Command**: `7E 04 02 [speed] FF FF FF 00 EF`

### API Endpoints

The bridge implements a minimal Nanoleaf REST API:

- `GET /api/v1/` - Device information
- `POST /api/v1/new` - Authentication token
- `GET /api/v1/<token>/` - Device state
- `PUT /api/v1/<token>/effects` - Set effect/color
- UDP port 60222 - Real-time color streaming (extControl v2)

### Performance

- Color updates are throttled to 30 FPS to match Bluetooth bandwidth limitations
- The bridge uses a queue system to drop old frames if updates arrive faster than they can be sent
- All device operations run in parallel for optimal performance

## Credits

This project was inspired by the need to make affordable RGB lighting work with SignalRGB. The reverse engineering of the MELK-OA protocol was done by analyzing the Magic Lantern Android app.

Special thanks to:
- The [LED BLE Home Assistant project](https://www.home-assistant.io/integrations/led_ble/) for protocol insights
- The SignalRGB team for their Nanoleaf integration documentation
- The open-source community for tools like Bleak and Flask

## License

This project is provided as-is for educational and personal use.

## Related Links

- [Original Blog Post](https://debauchedtea.party/2026/01/30/building-a-bridge-making-cheap-led-panels-work-with-signalrgb/)
- [SignalRGB](https://www.signalrgb.com/)
- [Bleak Documentation](https://bleak.readthedocs.io/)

## Contributing

Contributions are welcome! If you have improvements, bug fixes, or new features, please feel free to submit a pull request.

## Disclaimer

This project is not affiliated with Nanoleaf, SignalRGB, or MELK-OA. It is an independent bridge solution created to make affordable lighting work with premium RGB software.

