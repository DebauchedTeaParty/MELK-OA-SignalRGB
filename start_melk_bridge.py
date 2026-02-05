#!/usr/bin/env python3
"""
Start the MELK-OA Bluetooth bridge.
Bridge emulates a Nanoleaf device so SignalRGB can control the strip.
Run: python start_melk_bridge.py
"""

import sys
import traceback
import threading
from pathlib import Path

# When running as executable, add the executable directory to path
# This helps find obfuscated modules if they're in the same directory
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    exe_dir = Path(sys.executable).parent
    if str(exe_dir) not in sys.path:
        sys.path.insert(0, str(exe_dir))
    # Also check for _internal directory (PyInstaller onefile mode)
    internal_dir = exe_dir / "_internal"
    if internal_dir.exists() and str(internal_dir) not in sys.path:
        sys.path.insert(0, str(internal_dir))
else:
    # Running as script - add script directory to path
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

def setup_logging():
    """Setup logging to file for when console is hidden."""
    log_file = Path(__file__).parent / "melk_bridge.log"
    if getattr(sys, 'frozen', False):
        log_file = Path(sys.executable).parent / "melk_bridge.log"
    
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stderr)  # Also log to stderr if available
        ]
    )
    return logging.getLogger(__name__)

def log_error(error_msg):
    """Log error to file and print to console."""
    log_file = Path(__file__).parent / "error.log"
    if getattr(sys, 'frozen', False):
        log_file = Path(sys.executable).parent / "error.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Error occurred\n")
            f.write(f"{error_msg}\n")
            f.write(f"{'='*60}\n")
    except Exception:
        pass
    print(error_msg, file=sys.stderr)

if __name__ == "__main__":
    # Setup logging
    logger = setup_logging()
    logger.info("Starting MELK-OA Bridge...")

    try:
        # Import here so logging is configured first
        import melk_bridge
        import melk_gui

        # Start the bridge (Flask/UDP/BLE/tray) in a background thread
        def bridge_worker():
            try:
                logger.info("Starting bridge worker (no GUI in this thread)...")
                melk_bridge.main(start_gui=False)
            except KeyboardInterrupt:
                logger.info("Bridge worker interrupted by user")
            except Exception as e:
                error_msg = f"[ERROR] Bridge worker fatal error: {e}\n{traceback.format_exc()}"
                logger.error(error_msg)
                log_error(error_msg)

        # Store bridge thread reference for cleanup
        # Make it daemon so it dies when main thread exits
        bridge_thread = threading.Thread(target=bridge_worker, daemon=True, name="BridgeWorker")
        bridge_thread.start()
        logger.info("Bridge worker thread started (daemon)")

        # Start the GUI on the main thread so Tkinter is happy
        logger.info("Launching GUI window (MelkoLeaf)...")
        try:
            melk_gui.show_gui()
        except Exception as e:
            # Capture any GUI startup/runtime errors in the log file so we can debug EXE issues
            error_msg = f"[ERROR] GUI fatal error: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            log_error(error_msg)
        finally:
            # Ensure we exit when GUI closes or on GUI error
            logger.info("GUI window closed, exiting application")
            # Signal bridge to stop
            try:
                import melk_bridge
                melk_bridge._should_stop = True
            except:
                pass
            # Stop tray if it exists
            try:
                import melk_tray
                melk_tray.stop_tray()
            except:
                pass
            # Force immediate exit - don't wait for threads
            import os
            os._exit(0)

    except ImportError as e:
        # Fallback: if GUI modules aren't available, run bridge normally
        logger.warning("GUI not available due to ImportError: %s", e)
        logger.warning("Running bridge without GUI")
        try:
            from melk_bridge import main
            main()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            sys.exit(0)
        except Exception as e:
            error_msg = f"[ERROR] Fatal error: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            log_error(error_msg)
            sys.exit(1)
    except Exception as e:
        error_msg = f"[ERROR] Fatal error during startup: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        log_error(error_msg)
        sys.exit(1)
