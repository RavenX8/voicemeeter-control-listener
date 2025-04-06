"""Voicemeeter Remote Control Listener

This script provides a bridge between media keys (volume up/down/mute) and Voicemeeter audio controls.
It intercepts media key presses and redirects them to control specific Voicemeeter strips or buses.

Features:
- Captures volume up/down/mute media keys and redirects them to Voicemeeter
- Provides a REST API for external control via HTTP requests
- Automatically reconnects to Voicemeeter if connection is lost
- Supports targeting any strip or bus in Voicemeeter

Requires:
- voicemeeter-api
- pynput
- flask

Run as administrator for key suppression functionality.
"""

import time
import logging
import threading
from pynput import keyboard
import voicemeeterlib  # From voicemeeter-api package
from flask import Flask, jsonify, request

# --- Configuration ---
# Target type: 'strip' (input) or 'bus' (output)
INITIAL_TARGET_TYPE = 'strip'
# Index of the initial target (zero-based)
INITIAL_TARGET_STRIP_INDEX = 5
# Amount to change gain with each volume key press (in dB)
GAIN_STEP = 1.0
# Voicemeeter version: 'basic', 'banana', or 'potato'
VOICEMEETER_KIND = 'potato'
# Network settings for the REST API
FLASK_HOST = '127.0.0.1'  # Listen only on the local machine
FLASK_PORT = 5000         # Port for external applications to connect to

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
target_type = INITIAL_TARGET_TYPE
target_index = INITIAL_TARGET_STRIP_INDEX
vmr = None  # Voicemeeter Remote API instance
app = Flask(__name__)  # Flask web server instance
flask_thread = None    # Thread for running the Flask server

def connect_voicemeeter():
    """Connect to Voicemeeter and validate the initial target.

    Returns:
        bool: True if connection and validation successful, False otherwise.
    """
    global vmr, target_mute_states, target_type, target_index
    try:
        # Initialize the Voicemeeter Remote API with appropriate flags
        vmr = voicemeeterlib.api(VOICEMEETER_KIND, sync=True, pdirty=True, mdirty=True, ldirty=True)
        vmr.login()
        logging.info(f"Connected to Voicemeeter {VOICEMEETER_KIND.capitalize()}")

        try:
            # Validate that the configured target exists
            if target_type == 'strip':
                _ = vmr.strip[target_index].label
            elif target_type == 'bus':
                # Buses might not have labels, so check gain as proxy for existence
                _ = vmr.bus[target_index].gain
            else:
                raise ValueError(f"Invalid target type: {target_type}. Must be 'strip' or 'bus'.")

            logging.info(f"Initial target: {target_type}[{target_index}]")
            return True

        except (IndexError, AttributeError, ValueError) as e:
            logging.error(
                f"Initial target {target_type}[{target_index}] is invalid or inaccessible: {e}. Check config.")
            vmr.logout()
            vmr = None
            return False
        except Exception as e:
            logging.error(f"Error during initial connection/state read: {e}", exc_info=True)
            if vmr:
                vmr.logout()
            vmr = None
            return False
    except Exception as e:
        logging.error(f"Could not connect to Voicemeeter: {e}")
        logging.error("Is Voicemeeter running and API enabled?")
        vmr = None
        return False

def set_target_strip(index: int):
    """Set the target strip index for volume control.

    Args:
        index: The zero-based index of the strip to target

    Returns:
        tuple: (success, message) where success is a boolean and message is a string
    """
    global target_type, target_index, vmr

    if vmr and vmr.gui.launched:
        try:
            # Validate the strip index exists
            _ = vmr.strip[index].label

            old_index = target_index
            target_index = index
            strip_name = vmr.strip[target_index].label or 'Untitled'
            logging.info(f"Target strip changed from {old_index} to: {target_index} ({strip_name})")

            return True, f"Target strip set to {index}"
        except IndexError:
            msg = f"Cannot set target strip: Index {index} is out of range for {VOICEMEETER_KIND}."
            logging.warning(msg)
            return False, msg
        except Exception as e:
            msg = f"Error accessing strip {index}: {e}"
            logging.error(msg)
            return False, msg
    else:
        # Allow setting index even if disconnected, will apply on reconnect
        target_index = index
        msg = f"Voicemeeter not connected. Target strip set to {index} (will apply on reconnect)."
        logging.warning(msg)
        # Return True because the variable was set, even if not applied yet
        return True, msg


def change_gain(delta: float):
    """Changes the gain of the currently targeted strip or bus.

    Args:
        delta: The amount to change the gain by in decibels (positive or negative)
    """
    global target_type, target_index, vmr

    if not (vmr and vmr.gui.launched):
        logging.warning("Gain change failed: Voicemeeter GUI not launched.")
        return

    param_name = f"{target_type}[{target_index}].gain"
    try:
        # Read current gain value
        time.sleep(0.04)  # Small delay before read to ensure stability
        current_gain = vmr.get(param_name)
        if current_gain is None:
            logging.error(f"Failed to read current gain for '{param_name}'.")
            return
        logging.debug(f"Current gain for '{param_name}': {current_gain:.1f} dB")

        # Calculate new gain value with limits
        new_gain = round(current_gain + delta, 1)
        new_gain = max(-60.0, min(12.0, new_gain))  # Clamp to Voicemeeter's range

        # Set the new gain value
        vmr.set(param_name, new_gain)
        logging.info(f"{param_name} gain set to: {new_gain:.1f} dB")

        # Verify the change was applied correctly
        time.sleep(0.05)  # Small delay to allow change to take effect
        final_gain = vmr.get(param_name)
        if final_gain is not None and abs(final_gain - new_gain) < 0.1:
            logging.debug(f"Verified {param_name} gain is now {final_gain:.1f} dB")
        else:
            logging.warning(f"Verification failed for {param_name} gain! Expected {new_gain:.1f}, read {final_gain}")

    except Exception as e:
        logging.error(f"Error changing gain for '{param_name}': {e}", exc_info=True)

def toggle_mute():
    """Toggles mute state for the currently targeted strip or bus.

    Reads the current mute state, inverts it, and applies the new state.
    Verifies the change was applied correctly.
    """
    global target_type, target_index, vmr

    if not (vmr and vmr.gui.launched):
        logging.warning("Mute toggle failed: Voicemeeter GUI not launched.")
        return

    param_name = f"{target_type}[{target_index}].mute"
    try:
        # Read current mute state
        time.sleep(0.04)  # Small delay before read to ensure stability
        current_mute_float = vmr.get(param_name)
        if current_mute_float is None:
            logging.error(f"Failed to read parameter '{param_name}'.")
            return

        # Convert float value to boolean (0.0 = unmuted, 1.0 = muted)
        current_mute_state = bool(round(current_mute_float))
        logging.debug(f"Current mute state for '{param_name}': {current_mute_state}")

        # Invert the mute state
        new_mute_state = not current_mute_state
        new_mute_value = 1 if new_mute_state else 0

        # Set the new mute state
        vmr.set(param_name, new_mute_value)

        # Verify the change was applied correctly
        time.sleep(0.05)  # Small delay to allow change to take effect
        final_mute_float = vmr.get(param_name)
        if final_mute_float is None:
            logging.warning(f"Verification read failed for '{param_name}'.")
            return

        final_mute_state = bool(round(final_mute_float))
        status = "MUTED" if final_mute_state else "UNMUTED"

        if final_mute_state == new_mute_state:
            logging.info(f"{param_name} successfully set to {status}")
        else:
            logging.warning(f"Verification mismatch for {param_name}! Expected {new_mute_state}, read {final_mute_state}")

    except Exception as e:
        logging.error(f"Error toggling mute for '{param_name}': {e}", exc_info=True)

# --- Keyboard Listener Callback ---

def on_press(key):
    """Callback function for key presses.

    Intercepts media keys (volume up/down/mute) and redirects them to control
    the currently targeted Voicemeeter strip or bus.

    Args:
        key: The key that was pressed, from pynput.keyboard

    Returns:
        bool: True to allow the key to be processed by other applications,
              False to suppress it
    """
    global target_type, target_index, listener

    logging.debug(f"Key press detected: {key}")

    # Pass through all keys if Voicemeeter isn't running
    if not (vmr and vmr.gui.launched):
        logging.debug("Voicemeeter not running, allowing key pass-through")
        return True

    should_suppress = False

    try:
        target_key_detected = False

        # Handle media keys using Key enum constants
        if key == keyboard.Key.media_volume_up:
            logging.debug(f"Volume Up key detected. Target: {target_type}[{target_index}]")
            target_key_detected = True
            change_gain(GAIN_STEP)
            should_suppress = True

        elif key == keyboard.Key.media_volume_down:
            logging.debug(f"Volume Down key detected. Target: {target_type}[{target_index}]")
            target_key_detected = True
            change_gain(-GAIN_STEP)
            should_suppress = True

        elif key == keyboard.Key.media_volume_mute:
            logging.debug(f"Mute key detected. Target: {target_type}[{target_index}]")
            target_key_detected = True
            toggle_mute()
            should_suppress = True

        # Fallback to virtual key codes for systems where Key enum doesn't work
        elif hasattr(key, 'vk') and key.vk is not None:
            if key.vk == 0xAF:  # Volume Up VK code
                logging.debug(f"Volume Up VK code detected. Target: {target_type}[{target_index}]")
                target_key_detected = True
                change_gain(GAIN_STEP)
                should_suppress = True

            elif key.vk == 0xAE:  # Volume Down VK code
                logging.debug(f"Volume Down VK code detected. Target: {target_type}[{target_index}]")
                target_key_detected = True
                change_gain(-GAIN_STEP)
                should_suppress = True

            elif key.vk == 0xAD:  # Mute VK code
                logging.debug(f"Mute VK code detected. Target: {target_type}[{target_index}]")
                target_key_detected = True
                toggle_mute()
                should_suppress = True

        # Allow all other keys to pass through
        if not target_key_detected:
            should_suppress = False

    except Exception as e:
        logging.error(f"Error processing key {key}: {e}", exc_info=True)
        should_suppress = False

    # Set the suppress flag and return
    listener._suppress = should_suppress
    if should_suppress:
        logging.debug(f"Suppressing key: {key}")
    return True

# --- Flask HTTP Server Routes ---

@app.route('/set_target/<string:ttype>/<int:index>', methods=['GET'])
def handle_set_target(ttype: str, index: int):
    """API endpoint to set the target type and index.

    Args:
        ttype: The target type ('strip' or 'bus')
        index: The zero-based index of the target

    Returns:
        JSON response with status and target information
    """
    global target_type, target_index, vmr

    logging.info(f"Received request to set target to: {ttype}[{index}]")

    # Validate target type
    ttype = ttype.lower()
    if ttype not in ('strip', 'bus'):
        msg = f"Invalid target type: '{ttype}'. Must be 'strip' or 'bus'."
        logging.error(msg)
        return jsonify({"status": "error", "message": msg}), 400

    # Validate index if Voicemeeter is running
    vm_ready = vmr and vmr.gui.launched
    if vm_ready:
        try:
            if ttype == 'strip':
                _ = vmr.strip[index].label  # Verify strip exists
            elif ttype == 'bus':
                _ = vmr.bus[index].gain     # Verify bus exists
            logging.debug(f"Index {index} is valid for type '{ttype}'")
        except (IndexError, AttributeError):
            msg = f"Index {index} is out of range for '{ttype}' in Voicemeeter {VOICEMEETER_KIND}"
            logging.error(msg)
            return jsonify({
                "status": "error",
                "message": msg,
                "requested_type": ttype,
                "requested_index": index
            }), 400
        except Exception as e:
            msg = f"Error validating index {index} for type '{ttype}': {e}"
            logging.error(msg)
            return jsonify({"status": "error", "message": msg}), 500

    # Update the target
    old_type, old_index = target_type, target_index
    target_type = ttype
    target_index = index
    logging.info(f"Target changed from {old_type}[{old_index}] to: {target_type}[{target_index}]")

    return jsonify({
        "status": "success",
        "message": f"Target set to {target_type}[{target_index}]",
        "target_type": target_type,
        "target_index": target_index
    }), 200

@app.route('/get_target', methods=['GET'])
def handle_get_target():
    """API endpoint to query the current target type and index.

    Returns:
        JSON response with the current target information and status
    """
    global target_type, target_index

    label = "Unknown"
    vm_ready = vmr and vmr.gui.launched

    if vm_ready:
        try:
            if target_type == 'strip':
                label = vmr.strip[target_index].label or 'Untitled Strip'
            elif target_type == 'bus':
                # Buses typically don't have labels, use a generic name
                label = f"Bus {target_index}"
                # Verify the bus exists
                _ = vmr.bus[target_index].gain
        except Exception as e:
            label = f"Error: {e}"

    logging.info(f"Received request to get target. Current: {target_type}[{target_index}]")

    return jsonify({
        "status": "success",
        "target_type": target_type,
        "target_index": target_index,
        "target_label": label,
        "voicemeeter_running": vm_ready
    }), 200


# --- Flask Server Thread ---

def run_flask():
    """Runs the Flask server in a separate thread.

    This function is intended to be run in a daemon thread.
    It starts the Flask web server to listen for API requests.
    """
    global app
    try:
        # Reduce Flask's own logging to warnings and errors only
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.WARNING)

        # Start the Flask server
        # Note: Use '0.0.0.0' instead of '127.0.0.1' to allow external connections
        app.run(host=FLASK_HOST, port=FLASK_PORT)
    except OSError as e:
        logging.error(f"Flask server failed to start: {e}")
        logging.error(f"Is port {FLASK_PORT} already in use?")
    except Exception as e:
        logging.error(f"Flask server encountered an error: {e}")

# --- Windows Event Filter ---

def win32_event_filter(msg, data):
    """Low-level Windows event filter for keyboard events.

    This function is called by the pynput keyboard listener for each key event
    on Windows platforms. It allows for direct suppression of media keys at the
    Windows message level.

    Args:
        msg: The Windows message type
        data: The key data containing vkCode and other information

    Returns:
        bool: Always returns True to continue processing
    """
    global listener

    try:
        # Reset suppression flag
        listener._suppress = False

        # Check for media keys by their virtual key codes
        if data.vkCode in (0xAF, 0xAE, 0xAD):  # Volume Up, Down, Mute
            logging.debug(f"Win32 filter suppressing key code: {data.vkCode}")
            listener._suppress = True

        return True
    except Exception as e:
        logging.error(f"Error in win32_event_filter: {e}")
        return True  # Always continue processing

# --- Main Execution ---

if __name__ == "__main__":
    # Initialize Voicemeeter connection
    vmr = None

    # Initial connection attempt
    if not connect_voicemeeter():
        logging.warning("Initial Voicemeeter connection failed. Will retry in the main loop.")

    # Start Flask API server in a background thread
    logging.info(f"Starting Flask API server on http://{FLASK_HOST}:{FLASK_PORT}")
    logging.info(f"API endpoints: http://{FLASK_HOST}:{FLASK_PORT}/get_target and /set_target/strip/0")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Initialize and start the keyboard listener
    listener = keyboard.Listener(
        on_press=on_press,
        win32_event_filter=win32_event_filter,
        suppress=False
    )

    logging.info("Starting keyboard listener...")
    logging.info(f"Initial target: {target_type}[{target_index}]")
    logging.info("Press Volume Up/Down/Mute keys to control the targeted Voicemeeter strip/bus.")
    logging.info("Run this script as Administrator for key suppression functionality.")

    listener.start()

    # --- Main Loop ---
    try:
        loop_count = 0

        while True:
            loop_count += 1
            vm_ready = False

            # Check Voicemeeter status
            if vmr:
                try:
                    if vmr.gui.launched:
                        vm_ready = True
                    elif loop_count % 10 == 1:  # Log less frequently
                        logging.warning("Voicemeeter GUI not detected. Waiting...")
                except Exception as e:
                    logging.error(f"Error checking Voicemeeter status: {e}. Resetting connection.")
                    vmr = None  # Reset connection

            # Reconnect to Voicemeeter if needed
            if not vm_ready:
                if loop_count % 5 == 1:  # Try reconnecting every 5 seconds
                    logging.info("Attempting to connect to Voicemeeter...")
                    if connect_voicemeeter():
                        logging.info(f"Voicemeeter connected. Target: {target_type}[{target_index}]")
                    else:
                        time.sleep(5)  # Wait longer after failed connection attempt
                else:
                    time.sleep(1)  # Short wait between checks
                continue  # Skip the rest of this iteration

            # Check that background threads are still running
            if not flask_thread.is_alive():
                logging.error("Flask server thread has stopped. Exiting.")
                break

            if loop_count % 10 == 0 and not listener.is_alive():
                logging.error("Keyboard listener thread has stopped. Exiting.")
                break

            # Main loop delay
            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("Ctrl+C detected. Shutting down...")
    except Exception as e:
        logging.error(f"Unhandled exception in main loop: {e}", exc_info=True)
    finally:
        # Clean up resources
        if listener and listener.is_alive():
            logging.info("Stopping keyboard listener...")
            listener.stop()
            listener.join()
            logging.info("Keyboard listener stopped.")

        # Flask thread is a daemon thread and will exit automatically

        if vmr:
            try:
                logging.info("Logging out from Voicemeeter...")
                vmr.logout()
                logging.info("Voicemeeter logout successful.")
            except Exception as e:
                logging.warning(f"Voicemeeter logout failed: {e}")

        logging.info("Script terminated.")

