#!/usr/bin/env python3
"""
Start the MELK-OA Bluetooth bridge.
Bridge emulates a Nanoleaf device so SignalRGB can control the strip.
Run: python start_melk_bridge.py
"""

from melk_bridge import main

if __name__ == "__main__":
    main()
