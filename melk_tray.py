"""
System tray GUI for MelkoLeaf.
Provides minimal interface with status display and controls.
"""

import threading
import time
from pathlib import Path
import sys

try:
    import pystray
    from PIL import Image, ImageDraw
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("[GUI] pystray/Pillow not available. Install with: pip install pystray pillow")

# Global status variables (set by bridge)
_status = {
    "running": False,
    "paused": False,
    "devices": [],
    "server_running": False,
    "server_status": "Stopped",  # "Starting", "Running", "Stopped"
    "udp_receiving": False,
    "udp_status": "Stopped",  # "Starting", "Receiving", "Stopped"
    "udp_count": 0,
    "ble_ready": False,
    "ble_status": "Stopped",  # "Starting", "Ready", "Not ready", "Stopped"
    "local_ip": "127.0.0.1",
    "http_port": 16021,
}

_icon = None
_tray_thread = None
_restart_callback = None
_stop_callback = None
_pause_callback = None


def set_status(**kwargs):
    """Update status values."""
    _status.update(kwargs)


def get_status():
    """Get current status."""
    return _status.copy()


def set_callbacks(restart=None, stop=None, pause=None):
    """Set callback functions for menu actions."""
    global _restart_callback, _stop_callback, _pause_callback
    _restart_callback = restart
    _stop_callback = stop
    _pause_callback = pause


def create_icon_image():
    """Create or load icon image for system tray."""
    # Try to load rgb.png from icons folder
    script_dir = Path(__file__).resolve().parent
    icon_path = script_dir / "icons" / "rgb.png"
    
    if icon_path.exists():
        try:
            img = Image.open(icon_path)
            # Resize to standard system tray size (typically 16x16 or 32x32)
            img = img.resize((32, 32), Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            print(f"[GUI] Could not load icon from {icon_path}: {e}")
    
    # Fallback: create a simple colored icon
    img = Image.new('RGB', (32, 32), color=(255, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 24, 24], fill=(0, 255, 0))
    return img


def create_menu():
    """Create system tray menu with status and controls."""
    # Status section
    status_items = []
    
    # Show/Hide Window option (if GUI is available)
    try:
        import melk_gui
        # Check if there's a GUI window that can be restored
        show_hide_text = "Show Window"  # Will be updated if window is visible
        status_items.append(pystray.MenuItem(show_hide_text, on_show_window_clicked))
        # Separator - pystray uses Menu.SEPARATOR
        try:
            status_items.append(pystray.Menu.SEPARATOR)
        except AttributeError:
            # Fallback if SEPARATOR doesn't exist
            status_items.append(pystray.MenuItem("─" * 20, None, enabled=False))
    except:
        pass
    
    # Server status
    server_status_text = _status.get("server_status", "Stopped")
    if server_status_text == "Running":
        server_display = "✓ Running"
    elif server_status_text == "Starting":
        server_display = "⟳ Starting"
    else:
        server_display = "✗ Stopped"
    status_items.append(pystray.MenuItem(f"Server: {server_display}", None, enabled=False))
    
    # UDP status
    udp_status_text = _status.get("udp_status", "Stopped")
    udp_count = _status.get("udp_count", 0)
    if udp_status_text == "Receiving":
        udp_display = f"✓ Receiving ({udp_count})"
    elif udp_status_text == "Starting":
        udp_display = "⟳ Starting"
    else:
        udp_display = f"✗ Stopped ({udp_count})"
    status_items.append(pystray.MenuItem(f"UDP: {udp_display}", None, enabled=False))
    
    # BLE status
    ble_status_text = _status.get("ble_status", "Stopped")
    if ble_status_text == "Ready":
        ble_display = "✓ Ready"
    elif ble_status_text == "Starting":
        ble_display = "⟳ Starting"
    elif ble_status_text == "Not ready":
        ble_display = "✗ Not ready"
    else:
        ble_display = "✗ Stopped"
    status_items.append(pystray.MenuItem(f"BLE: {ble_display}", None, enabled=False))
    
    # Devices
    device_count = len(_status["devices"])
    if device_count > 0:
        devices_text = f"Devices: {device_count}"
        if device_count <= 3:
            devices_text += f" ({', '.join(_status['devices'][:3])})"
        else:
            devices_text += f" ({', '.join(_status['devices'][:2])}...)"
        status_items.append(pystray.MenuItem(devices_text, None, enabled=False))
    else:
        status_items.append(pystray.MenuItem("Devices: None", None, enabled=False))
    
    # IP info
    status_items.append(pystray.MenuItem(f"IP: {_status['local_ip']}:{_status['http_port']}", None, enabled=False))
    
    # Separator - pystray uses Menu.SEPARATOR
    try:
        status_items.append(pystray.Menu.SEPARATOR)
    except AttributeError:
        # Fallback if SEPARATOR doesn't exist
        status_items.append(pystray.MenuItem("─" * 20, None, enabled=False))
    
    # Control section
    control_items = []
    
    # Pause/Resume
    pause_text = "Resume" if _status["paused"] else "Pause"
    control_items.append(pystray.MenuItem(pause_text, on_pause_clicked))
    
    # Restart
    control_items.append(pystray.MenuItem("Restart", on_restart_clicked))
    
    # Exit/Quit
    control_items.append(pystray.MenuItem("Exit", on_stop_clicked))
    
    # Combine menu items
    menu_items = status_items + control_items
    
    return pystray.Menu(*menu_items)


def on_show_window_clicked(icon, item):
    """Handle show/hide window click."""
    try:
        import melk_gui
        import tkinter as tk
        # Try to find the root window
        root = tk._default_root
        if root and root.winfo_exists():
            try:
                if root.winfo_viewable():
                    # Window is visible, hide it
                    root.withdraw()
                else:
                    # Window is hidden, show it
                    root.deiconify()
                    root.lift()
                    root.focus_force()
            except:
                # Window might be destroyed, try to get GUI instance
                gui = melk_gui.get_gui_instance()
                if gui and gui.root.winfo_exists():
                    gui.root.deiconify()
                    gui.root.lift()
                    gui.root.focus_force()
        else:
            # No window exists, create one
            import threading
            def show_window():
                melk_gui.show_gui()
            thread = threading.Thread(target=show_window, daemon=True)
            thread.start()
    except Exception as e:
        print(f"[GUI] Error showing window: {e}")
        import traceback
        traceback.print_exc()


def on_pause_clicked(icon, item):
    """Handle pause/resume click."""
    if _pause_callback:
        _pause_callback()


def on_restart_clicked(icon, item):
    """Handle restart click."""
    if _restart_callback:
        _restart_callback()


def on_stop_clicked(icon, item):
    """Handle stop click."""
    if _stop_callback:
        _stop_callback()


def update_menu_periodically(icon):
    """Periodically update menu to refresh status."""
    while _status.get("running", True):
        try:
            icon.menu = create_menu()
            time.sleep(2)  # Update every 2 seconds
        except Exception:
            break


def run_tray(icon_path=None):
    """Start the system tray icon."""
    if not PILLOW_AVAILABLE:
        print("[GUI] System tray not available. Install pystray and pillow.")
        return None
    
    global _icon
    
    try:
        print("[GUI] Initializing system tray icon...")
        
        # Create icon image
        if icon_path and Path(icon_path).exists():
            try:
                img = Image.open(icon_path)
                img = img.resize((32, 32), Image.Resampling.LANCZOS)
                print(f"[GUI] Loaded icon from {icon_path}")
            except Exception as e:
                print(f"[GUI] Could not load icon from {icon_path}: {e}")
                img = create_icon_image()
        else:
            print("[GUI] Using fallback icon")
            img = create_icon_image()
        
        # Create menu
        menu = create_menu()
        print("[GUI] Created system tray menu")
        
        # Create icon with double-click handler to show window
        def on_icon_clicked(icon, item):
            """Handle icon double-click - show window."""
            on_show_window_clicked(icon, None)
        
        _icon = pystray.Icon("MelkoLeaf", img, "MelkoLeaf", menu)
        # Set default action to show window on double-click
        _icon.default_action = on_icon_clicked
        print("[GUI] Created system tray icon object")
        
        # Start update thread
        update_thread = threading.Thread(target=update_menu_periodically, args=(_icon,), daemon=True)
        update_thread.start()
        print("[GUI] Started menu update thread")
        
        print("[GUI] Starting system tray icon (this will block)...")
        print("[GUI] TIP: Look for the icon in the Windows notification area (system tray)")
        print("[GUI] TIP: Right-click the icon to see the menu, or double-click to show window")
        # Run icon (blocks until stopped)
        _icon.run()
        print("[GUI] System tray icon stopped")
        
    except Exception as e:
        print(f"[GUI] Error starting system tray: {e}")
        import traceback
        traceback.print_exc()
        return None


def stop_tray():
    """Stop the system tray icon."""
    global _icon
    if _icon:
        try:
            _icon.stop()
        except Exception:
            pass
        _icon = None


def start_tray_thread(icon_path=None):
    """Start system tray in a separate thread."""
    global _tray_thread, _icon
    if not PILLOW_AVAILABLE:
        print("[GUI] pystray/Pillow not available")
        return None
    
    if _tray_thread and _tray_thread.is_alive():
        print("[GUI] System tray thread already running")
        return _tray_thread
    
    def tray_worker():
        try:
            print("[GUI] Tray worker thread started")
            run_tray(icon_path)
        except Exception as e:
            print(f"[GUI] Tray worker error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("[GUI] Tray worker thread exiting")
    
    print("[GUI] Creating system tray thread...")
    _tray_thread = threading.Thread(target=tray_worker, daemon=False, name="SystemTrayThread")  # Non-daemon so it keeps app alive
    _tray_thread.start()
    print(f"[GUI] System tray thread started (alive: {_tray_thread.is_alive()})")
    # Give it a moment to start
    time.sleep(1)
    return _tray_thread


def is_tray_running():
    """Check if system tray is running."""
    global _icon, _tray_thread
    return _icon is not None and _tray_thread is not None and _tray_thread.is_alive()


if __name__ == "__main__":
    # Test the tray
    set_status(
        running=True,
        server_running=True,
        udp_receiving=True,
        udp_count=1234,
        ble_ready=True,
        devices=["AA:BB:CC:DD:EE:FF"],
        local_ip="192.168.1.100",
    )
    run_tray()

