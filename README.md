﻿﻿﻿﻿﻿﻿﻿﻿# Voicemeeter Remote Control Listener

A Python application that intercepts media keys (volume up/down/mute) and redirects them to control Voicemeeter audio strips and buses.

## Features

- Captures volume up/down/mute media keys and redirects them to Voicemeeter
- Provides a REST API for external control via HTTP requests
- Automatically reconnects to Voicemeeter if connection is lost
- Supports targeting any strip or bus in Voicemeeter
- Works with Voicemeeter Basic, Banana, and Potato

## Requirements

- Python 3.6+
- [Voicemeeter](https://vb-audio.com/Voicemeeter/) installed and running
- Python packages:
  - voicemeeterlib
  - pynput
  - flask

## Installation

1. Clone this repository or download the source code
2. Install required packages using the requirements.txt file:

```bash
pip install -r requirements.txt
```

Or install packages individually:

```bash
pip install voicemeeterlib pynput flask
```

## Usage

Run the script with administrator privileges for key suppression functionality:

```bash
python main.py
```

### Running at Startup

#### Using Windows Task Scheduler (Recommended)

1. Open Task Scheduler (search for it in the Start menu)
2. Click "Create Basic Task..."
3. Enter a name (e.g., "Voicemeeter Listener") and description
4. Select "When I log on" as the trigger
5. Select "Start a program" as the action
6. Browse to your Python**w** executable (e.g., `C:\Python39\pythonw.exe`) - **not** python.exe
7. Add the full path to main.py as an argument (e.g., `C:\Path\To\voicemeeter-listener\main.py`)

**Note:** Using `pythonw.exe` instead of `python.exe` is important because:
- `pythonw.exe` runs without a console window, making it ideal for background applications
- It prevents a command prompt window from appearing on your desktop at startup
- The script will still run and log to files, but won't show a visible window
- If you use `python.exe`, a console window will remain open as long as the script runs

8. In the summary page, check "Open the Properties dialog for this task when I click Finish"
9. Click Finish
10. In the Properties dialog:
    - Check "Run with highest privileges" (required for key suppression)
    - Under the "Conditions" tab, uncheck "Start the task only if the computer is on AC power"
    - Under the "Settings" tab, you can configure additional options
    - Click OK to save

**Adding a Start Delay:**

It's often helpful to add a delay before starting the script to ensure Voicemeeter and other audio services are fully loaded. To do this:

1. After creating the task, right-click on it and select "Properties"
2. Go to the "Triggers" tab
3. Select the logon trigger and click "Edit"
4. Check the box for "Delay task for" and set a delay (e.g., 30 seconds or 1 minute)
5. Click OK to save the changes

Alternatively, you can create a batch file with a delay command:

```batch
@echo off
timeout /t 30 /nobreak
cd /d C:\Path\To\voicemeeter-listener
"C:\Path\To\Python\pythonw.exe" main.py
```

#### Alternative Methods

**Startup Folder:**

Create a batch file (e.g., `start_voicemeeter_listener.bat`) with the following content:

```batch
@echo off
cd /d C:\Path\To\voicemeeter-listener
"C:\Path\To\Python\pythonw.exe" main.py
```

Place this batch file in your startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).

### Configuration

Edit the following variables in `main.py` to customize behavior:

```python
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
```

### REST API

The application provides a simple REST API for external control:

- Get current target: `GET http://127.0.0.1:5000/get_target`
- Set target: `GET http://127.0.0.1:5000/set_target/strip/0` or `GET http://127.0.0.1:5000/set_target/bus/0`

### Integration with Bitfocus Companion

This script works well with [Bitfocus Companion](https://bitfocus.io/companion) to create custom control surfaces for Voicemeeter:

1. **Setting up HTTP Requests in Companion:**
   - Add a new button in your Companion interface
   - Configure the button to send an HTTP GET request
   - Use the URL format: `http://127.0.0.1:5000/set_target/strip/0` (change strip/bus and index as needed)
   - No authentication or custom headers are required

2. **Creating a Control Surface:**
   - Create buttons for different strips and buses
   - Add visual feedback by using different colors or text for active targets
   - You can use the `/get_target` endpoint to check the current state

3. **Example Button Configuration:**
   - **Button for Strip 0:** HTTP GET to `http://127.0.0.1:5000/set_target/strip/0`
   - **Button for Bus 1:** HTTP GET to `http://127.0.0.1:5000/set_target/bus/1`
   - **Status Check:** HTTP GET to `http://127.0.0.1:5000/get_target` (use with feedback)

Once configured, you can use your Stream Deck or other control surface to instantly switch which Voicemeeter strip/bus the media keys control.

## How It Works

1. The script connects to Voicemeeter using the voicemeeterlib API
2. It intercepts media key presses using pynput
3. When a media key is pressed, it redirects the action to the currently targeted Voicemeeter strip or bus
4. The Flask server provides an API for external applications to control the target

## Troubleshooting

- **Keys not being intercepted**: Make sure you're running the script as administrator
- **Cannot connect to Voicemeeter**: Ensure Voicemeeter is running before starting the script
- **Flask server fails to start**: Check if another application is using port 5000

## License

[MIT License](LICENSE)

## Acknowledgements

- [VB-Audio](https://vb-audio.com/) for Voicemeeter
- [voicemeeterlib](https://github.com/chvolkmann/voicemeeter-api-python) for the Python API
