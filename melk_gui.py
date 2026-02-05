"""
Modern Material Design 3 GUI for MelkoLeaf.
Compact design that fits on screen without resizing.
"""

import threading
import time
import sys
import io
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext

# Try to import ttkbootstrap for modern Material Design 3 styling
try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    TTKBOOTSTRAP_AVAILABLE = True
except ImportError:
    # Fallback to standard ttk if ttkbootstrap not available
    from tkinter import ttk
    TTKBOOTSTRAP_AVAILABLE = False
    print("[GUI] ttkbootstrap not available. Install with: pip install ttkbootstrap")
    print("[GUI] Falling back to standard ttk styling")

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("[GUI] pystray/Pillow not available. Install with: pip install pystray pillow")

# Global reference to GUI instance
_gui_instance = None

# Material Design 3 Color Palette (2026)
MATERIAL_COLORS = {
    "primary": "#6750A4",
    "primary_variant": "#7E57C2",
    "secondary": "#625B71",
    "tertiary": "#7D5260",
    "surface": "#FFFBFE",
    "surface_dark": "#1C1B1F",
    "surface_variant": "#E7E0EC",
    "background": "#FFFBFE",
    "background_dark": "#1C1B1F",
    "on_primary": "#FFFFFF",
    "on_surface": "#1C1B1F",
    "on_surface_dark": "#E6E1E5",
    "outline": "#79747E",
    "success": "#4CAF50",
    "warning": "#FF9800",
    "error": "#B3261E",
    "info": "#2196F3",
}

# Import status from tray module - will be set up at runtime
def get_status_from_tray():
    """Get status from melk_tray module."""
    try:
        import melk_tray
        return melk_tray.get_status()
    except:
        return {
            "running": False,
            "paused": False,
            "devices": [],
            "server_running": False,
            "udp_receiving": False,
            "udp_count": 0,
            "ble_ready": False,
            "local_ip": "127.0.0.1",
            "http_port": 16021,
        }


class CompactStatusRow(ttk.Frame):
    """Compact status row with label and badge."""
    def __init__(self, parent, label_text, **kwargs):
        super().__init__(parent, **kwargs)
        
        # Label
        self.label = tk.Label(
            self,
            text=label_text + ":",
            font=("Segoe UI", 9),
            fg=MATERIAL_COLORS["on_surface_dark"] if TTKBOOTSTRAP_AVAILABLE else "#E6E1E5",
            bg=MATERIAL_COLORS["background_dark"] if TTKBOOTSTRAP_AVAILABLE else "#1C1B1F",
            width=12,
            anchor="w"
        )
        self.label.pack(side=tk.LEFT, padx=(0, 8))
        
        # Badge - set initial background
        default_bg = MATERIAL_COLORS["surface_variant"] if TTKBOOTSTRAP_AVAILABLE else "#2B2B2B"
        default_fg = MATERIAL_COLORS["on_surface"] if TTKBOOTSTRAP_AVAILABLE else "#E6E1E5"
        self.badge = tk.Label(
            self,
            text="...",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            relief=tk.FLAT,
            borderwidth=0,
            bg=default_bg,
            fg=default_fg
        )
        self.badge.pack(side=tk.LEFT)
    
    def set_status(self, status, text):
        """Update badge with status color."""
        colors = {
            "success": (MATERIAL_COLORS["success"], "#FFFFFF"),
            "warning": (MATERIAL_COLORS["warning"], "#FFFFFF"),
            "error": (MATERIAL_COLORS["error"], "#FFFFFF"),
            "info": (MATERIAL_COLORS["info"], "#FFFFFF"),
            "default": (MATERIAL_COLORS["surface_variant"], MATERIAL_COLORS["on_surface"]),
        }
        bg, fg = colors.get(status, colors["default"])
        self.badge.config(text=text, bg=bg, fg=fg)


class MelkBridgeGUI:
    def __init__(self, root):
        global _gui_instance
        try:
            print("[GUI] Initializing compact MelkBridgeGUI...")
            _gui_instance = self
            self.root = root
            
            # Apply Material Design 3 theme
            if TTKBOOTSTRAP_AVAILABLE:
                self.style = ttk.Style(theme="darkly")
                self._apply_material_theme()
            else:
                self.style = ttk.Style()
                self._apply_fallback_theme()
            
            self.root.title("MelkoLeaf")
            # Compact window size - fits on most screens
            self.root.geometry("550x500")
            self.root.resizable(False, False)  # Fixed size
            
            # Set background color
            bg_color = MATERIAL_COLORS["background_dark"] if TTKBOOTSTRAP_AVAILABLE else "#1C1B1F"
            self.root.configure(bg=bg_color)
            
            print("[GUI] Window properties set")
            
            # Try to set icon
            try:
                icon_path = Path(__file__).parent / "icons" / "rgb.png"
                if not icon_path.exists() and getattr(sys, 'frozen', False):
                    icon_path = Path(sys.executable).parent / "icons" / "rgb.png"
                if icon_path.exists():
                    img = Image.open(icon_path)
                    img = img.resize((32, 32), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.root.iconphoto(False, photo)
            except Exception as e:
                print(f"[GUI] Could not set icon: {e}")
            
            # Variables
            self.startup_var = tk.BooleanVar()
            self.startup_var.set(self.is_startup_enabled())
            
            # Create UI
            print("[GUI] Creating compact widgets...")
            self.create_widgets()
            print("[GUI] Widgets created")
            
            # Start update loop
            print("[GUI] Starting update loop...")
            self.update_status()
            
            # Handle window close
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            
            # Ensure window is visible on startup
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.update()
            
            print("[GUI] GUI initialization complete")
        except Exception as e:
            print(f"[GUI] Error initializing GUI: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _apply_material_theme(self):
        """Apply Material Design 3 color scheme."""
        try:
            self.style.configure("Title.TLabel",
                               font=("Segoe UI", 18, "bold"),
                               foreground=MATERIAL_COLORS["on_surface_dark"],
                               background=MATERIAL_COLORS["background_dark"])
            
            self.style.configure("Primary.TButton",
                               font=("Segoe UI", 9),
                               padding=(16, 8))
            
            self.style.configure("Secondary.TButton",
                               font=("Segoe UI", 9),
                               padding=(12, 6))
            
            self.style.configure("TNotebook",
                               background=MATERIAL_COLORS["background_dark"],
                               borderwidth=0)
            
            self.style.configure("TNotebook.Tab",
                               padding=(16, 8),
                               font=("Segoe UI", 9))
        except Exception as e:
            print(f"[GUI] Error applying theme: {e}")
    
    def _apply_fallback_theme(self):
        """Apply fallback theme when ttkbootstrap is not available."""
        try:
            self.style.configure("Title.TLabel",
                               font=("Segoe UI", 18, "bold"),
                               foreground="#FFFFFF",
                               background="#1C1B1F")
        except:
            pass
    
    def create_widgets(self):
        # Main container with minimal padding
        main_container = ttk.Frame(self.root, padding=10)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Compact header
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        title_label = ttk.Label(
            header_frame,
            text="MelkoLeaf",
            style="Title.TLabel" if TTKBOOTSTRAP_AVAILABLE else "TLabel"
        )
        title_label.pack(anchor="w")
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Status tab
        status_tab = ttk.Frame(notebook, padding=10)
        notebook.add(status_tab, text="Status")
        
        # Compact status section using grid
        self._create_compact_status(status_tab)
        
        # Compact controls
        self._create_compact_controls(status_tab)
        
        # Log/Console tab
        log_tab = ttk.Frame(notebook, padding=10)
        notebook.add(log_tab, text="Console")
        
        self._create_compact_console(log_tab)
        
        # Setup log capture
        self.setup_log_capture()
    
    def _create_compact_status(self, parent):
        """Create compact status display using grid layout."""
        # Status frame (no padding kwarg for maximum Tk compatibility)
        status_frame = ttk.LabelFrame(parent, text="Status")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8), padx=4, ipadx=4, ipady=4)
        
        # Use grid for compact layout
        # Row 0: Server
        self.server_row = CompactStatusRow(status_frame, "Server")
        self.server_row.grid(row=0, column=0, sticky="ew", pady=4, padx=4)
        
        # Row 1: UDP
        self.udp_row = CompactStatusRow(status_frame, "UDP")
        self.udp_row.grid(row=1, column=0, sticky="ew", pady=4, padx=4)
        
        # Row 2: BLE
        self.ble_row = CompactStatusRow(status_frame, "BLE")
        self.ble_row.grid(row=2, column=0, sticky="ew", pady=4, padx=4)
        
        # Row 3: Devices
        self.devices_row = CompactStatusRow(status_frame, "Devices")
        self.devices_row.grid(row=3, column=0, sticky="ew", pady=4, padx=4)
        
        # Row 4: Network
        self.network_row = CompactStatusRow(status_frame, "Network")
        self.network_row.grid(row=4, column=0, sticky="ew", pady=4, padx=4)
        
        # Configure grid weights
        status_frame.grid_columnconfigure(0, weight=1)
    
    def _create_compact_controls(self, parent):
        """Create compact controls section."""
        # Controls frame (no padding kwarg for maximum Tk compatibility)
        controls_frame = ttk.LabelFrame(parent, text="Controls")
        controls_frame.pack(fill=tk.X, pady=(0, 8), padx=4, ipadx=4, ipady=4)
        
        # Buttons in a row
        button_frame = ttk.Frame(controls_frame)
        button_frame.pack(fill=tk.X)
        
        if TTKBOOTSTRAP_AVAILABLE:
            self.pause_button = ttk.Button(
                button_frame,
                text="⏸ Pause",
                command=self.toggle_pause,
                style="Primary.TButton",
                bootstyle="primary",
                width=12
            )
            self.pause_button.pack(side=tk.LEFT, padx=(0, 6))
            
            restart_button = ttk.Button(
                button_frame,
                text="🔄 Restart",
                command=self.restart_bridge,
                style="Secondary.TButton",
                bootstyle="secondary",
                width=12
            )
            restart_button.pack(side=tk.LEFT, padx=(0, 6))
            
            exit_button = ttk.Button(
                button_frame,
                text="❌ Exit",
                command=self.stop_bridge,
                style="Secondary.TButton",
                bootstyle="danger",
                width=12
            )
            exit_button.pack(side=tk.LEFT)
        else:
            self.pause_button = ttk.Button(
                button_frame,
                text="Pause",
                command=self.toggle_pause,
                width=12
            )
            self.pause_button.pack(side=tk.LEFT, padx=(0, 6))
            
            restart_button = ttk.Button(
                button_frame,
                text="Restart",
                command=self.restart_bridge,
                width=12
            )
            restart_button.pack(side=tk.LEFT, padx=(0, 6))
            
            exit_button = ttk.Button(
                button_frame,
                text="Exit",
                command=self.stop_bridge,
                width=12
            )
            exit_button.pack(side=tk.LEFT)
        
        # Settings row
        settings_frame = ttk.Frame(parent)
        settings_frame.pack(fill=tk.X)
        
        startup_check = ttk.Checkbutton(
            settings_frame,
            text="Start with Windows",
            variable=self.startup_var,
            command=self.toggle_startup
        )
        startup_check.pack(side=tk.LEFT)
        
        if TTKBOOTSTRAP_AVAILABLE:
            minimize_button = ttk.Button(
                settings_frame,
                text="Minimize to Tray",
                command=self.minimize_to_tray,
                style="Secondary.TButton",
                bootstyle="secondary",
                width=15
            )
        else:
            minimize_button = ttk.Button(
                settings_frame,
                text="Minimize to Tray",
                command=self.minimize_to_tray,
                width=15
            )
        minimize_button.pack(side=tk.RIGHT)
    
    def _create_compact_console(self, parent):
        """Create compact console output section."""
        # Console header
        console_header = ttk.Frame(parent)
        console_header.pack(fill=tk.X, pady=(0, 6))
        
        console_title = ttk.Label(
            console_header,
            text="Console Output",
            font=("Segoe UI", 10, "bold")
        )
        console_title.pack(side=tk.LEFT)
        
        if TTKBOOTSTRAP_AVAILABLE:
            clear_button = ttk.Button(
                console_header,
                text="Clear",
                command=self.clear_log,
                style="Secondary.TButton",
                bootstyle="secondary",
                width=10
            )
        else:
            clear_button = ttk.Button(
                console_header,
                text="Clear",
                command=self.clear_log,
                width=10
            )
        clear_button.pack(side=tk.RIGHT)
        
        # Console text area
        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            width=60,
            height=20,
            font=("Consolas", 9),
            bg="#1E1E1E",
            fg="#D4D4D4",
            insertbackground="#D4D4D4",
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=8
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
    
    def update_status(self):
        """Update status labels with compact badges."""
        try:
            status = get_status_from_tray()
            
            # Server status
            server_status_text = status.get("server_status", "Stopped")
            if server_status_text == "Running":
                self.server_row.set_status("success", "✓ Running")
            elif server_status_text == "Starting":
                self.server_row.set_status("info", "⟳ Starting...")
            else:
                self.server_row.set_status("error", "✗ Stopped")
            
            # UDP status
            udp_status_text = status.get("udp_status", "Stopped")
            udp_count = status.get("udp_count", 0)
            if udp_status_text == "Receiving":
                self.udp_row.set_status("success", f"✓ {udp_count:,} packets")
            elif udp_status_text == "Starting":
                self.udp_row.set_status("info", "⟳ Starting...")
            else:
                self.udp_row.set_status("error", f"✗ {udp_count:,} packets")
            
            # BLE status
            ble_status_text = status.get("ble_status", "Stopped")
            if ble_status_text == "Ready":
                self.ble_row.set_status("success", "✓ Ready")
            elif ble_status_text == "Starting":
                self.ble_row.set_status("info", "⟳ Scanning...")
            elif ble_status_text == "Not ready":
                self.ble_row.set_status("warning", "⚠ Not Ready")
            else:
                self.ble_row.set_status("error", "✗ Stopped")
            
            # Devices
            devices = status.get("devices", [])
            if devices:
                if len(devices) <= 2:
                    devices_text = f"{len(devices)} device(s)"
                else:
                    devices_text = f"{len(devices)} device(s)"
                self.devices_row.set_status("success", devices_text)
            else:
                self.devices_row.set_status("error", "None")
            
            # Network
            ip = status.get("local_ip", "Unknown")
            port = status.get("http_port", 16021)
            self.network_row.set_status("info", f"{ip}:{port}")
            
            # Update pause button
            paused = status.get("paused", False)
            if paused:
                self.pause_button.config(text="▶ Resume")
            else:
                self.pause_button.config(text="⏸ Pause")
            
        except Exception as e:
            print(f"[GUI] Error updating status: {e}")
        
        # Schedule next update
        self.root.after(1000, self.update_status)
    
    def toggle_pause(self):
        """Toggle pause/resume."""
        try:
            import melk_tray
            if melk_tray._pause_callback:
                melk_tray._pause_callback()
        except:
            pass
    
    def restart_bridge(self):
        """Restart the bridge."""
        if messagebox.askyesno("Restart", "Restart the bridge?"):
            try:
                import melk_tray
                if melk_tray._restart_callback:
                    melk_tray._restart_callback()
            except:
                pass
    
    def stop_bridge(self):
        """Exit the bridge."""
        if messagebox.askyesno("Exit", "Exit MelkoLeaf? This will close the application."):
            try:
                import melk_tray
                if melk_tray._stop_callback:
                    melk_tray._stop_callback()
            except:
                pass
            self.root.quit()
            self.root.destroy()
    
    def minimize_to_tray(self):
        """Minimize window to system tray."""
        self.root.withdraw()
        try:
            import melk_tray
            print("[GUI] Window minimized to tray. Right-click the system tray icon to restore.")
        except:
            pass
    
    def restore_from_tray(self):
        """Restore window from system tray."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    def on_closing(self):
        """Handle window close - minimize to tray instead of closing."""
        self.minimize_to_tray()
    
    def setup_log_capture(self):
        """Setup log capture to display in text box."""
        import logging
        
        class TextHandler:
            def __init__(self, text_widget, original_stdout, original_stderr):
                self.text_widget = text_widget
                self.original_stdout = original_stdout
                self.original_stderr = original_stderr
                self.buffer = ""
            
            def write(self, message):
                if self.original_stdout:
                    self.original_stdout.write(message)
                    self.original_stdout.flush()
                self.buffer += message
                try:
                    self.text_widget.after(0, self._update_text)
                except RuntimeError:
                    pass
                except Exception:
                    pass
            
            def _update_text(self):
                if self.buffer:
                    try:
                        if self.text_widget.winfo_exists():
                            self.text_widget.insert(tk.END, self.buffer)
                            self.text_widget.see(tk.END)
                            content = self.text_widget.get("1.0", tk.END)
                            if len(content) > 50000:
                                self.text_widget.delete("1.0", "5000.0")
                    except (RuntimeError, tk.TclError):
                        pass
                    except Exception:
                        pass
                    self.buffer = ""
            
            def flush(self):
                if self.original_stdout:
                    self.original_stdout.flush()
        
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        self.log_handler = TextHandler(self.log_text, self.original_stdout, self.original_stderr)
        
        sys.stdout = self.log_handler
        sys.stderr = self.log_handler
        
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                stream = getattr(handler, "stream", None)
                if stream is None or not hasattr(stream, "write"):
                    root_logger.removeHandler(handler)
        
        class LoggingTextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
            
            def emit(self, record):
                try:
                    msg = self.format(record) + '\n'
                    self.text_widget.after(0, lambda: self._append_text(msg))
                except (RuntimeError, tk.TclError):
                    pass
                except Exception:
                    pass
            
            def _append_text(self, msg):
                try:
                    self.log_text.insert(tk.END, msg)
                    self.log_text.see(tk.END)
                    content = self.log_text.get("1.0", tk.END)
                    if len(content) > 50000:
                        self.log_text.delete("1.0", "5000.0")
                except:
                    pass
        
        logging_handler = LoggingTextHandler(self.log_text)
        logging_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(logging_handler)
    
    def clear_log(self):
        """Clear the log text box."""
        self.log_text.delete("1.0", tk.END)
    
    def is_startup_enabled(self):
        """Check if app is in Windows startup."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ
            )
            try:
                winreg.QueryValueEx(key, "MelkoLeaf")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except:
            return False
    
    def toggle_startup(self):
        """Add/remove from Windows startup."""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            
            if self.startup_var.get():
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    key_path,
                    0, winreg.KEY_WRITE
                )
                exe_path = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
                winreg.SetValueEx(key, "MelkoLeaf", 0, winreg.REG_SZ, exe_path)
                winreg.CloseKey(key)
                messagebox.showinfo("Startup", "Added to Windows startup")
            else:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    key_path,
                    0, winreg.KEY_WRITE
                )
                try:
                    winreg.DeleteValue(key, "MelkoLeaf")
                    messagebox.showinfo("Startup", "Removed from Windows startup")
                except FileNotFoundError:
                    pass
                winreg.CloseKey(key)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update startup: {e}")


def show_gui():
    """Show the GUI window."""
    global _gui_instance
    try:
        print("[GUI] show_gui() called")
        if _gui_instance and hasattr(_gui_instance, 'root'):
            try:
                if _gui_instance.root.winfo_exists():
                    print("[GUI] Window exists, showing it")
                    _gui_instance.root.deiconify()
                    _gui_instance.root.lift()
                    _gui_instance.root.focus_force()
                    _gui_instance.root.update()
                    return
            except (tk.TclError, RuntimeError):
                # Window was destroyed, create new one
                _gui_instance = None
        
        print("[GUI] Creating new GUI window...")
        if TTKBOOTSTRAP_AVAILABLE:
            root = ttk.Window(themename="darkly")
        else:
            root = tk.Tk()
        print("[GUI] Tk root created")
        
        try:
            app = MelkBridgeGUI(root)
            print("[GUI] MelkBridgeGUI instance created")
            
            root.deiconify()
            root.lift()
            root.focus_force()
            root.update()
            print("[GUI] Window shown and focused")
            
            print("[GUI] Starting mainloop...")
            root.mainloop()
            print("[GUI] Mainloop exited")
        except Exception as e:
            print(f"[GUI] Error creating GUI: {e}")
            import traceback
            traceback.print_exc()
            # Try to destroy root if it exists
            try:
                root.destroy()
            except:
                pass
            raise
    except Exception as e:
        print(f"[GUI] Error in show_gui(): {e}")
        import traceback
        traceback.print_exc()
        raise


def get_gui_instance():
    """Get the current GUI instance."""
    return _gui_instance


if __name__ == "__main__":
    show_gui()
