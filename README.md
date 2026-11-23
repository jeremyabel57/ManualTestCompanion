This code run in AutoIt https://www.autoitscript.com/site/

Chamber_Control controls the Test Equity F4T Thermal Chamber, giving readings of the current temperature and controlling the target temperature setpoint.

DC_Power_Supply controls the Keysight N67... DC Power supply with 4 output channels

FrequencyCounter controls an Agilent Frequency counter with a specific script to have it measure channel 1 for a given number of cycles and calculate Allan Deviation

Oscilloscope_Tek_MSO5 gives a control window into the MSO5 series Tektronics oscilloscope (using the web interface on the scope). It also has a screen capture function

All of these use VISA/SCPI commands to talk to the equipment over the network. The Chamber control uses ModBusTCP as I was having trouble using SCPI commands to control the chamber.

Each of these has a field to enter the IP address of the target device. Next to it is a search button that will search the 192.168.0.x subnet for devices, and give you a selection list.


Manual Test Station Companion

Provides a GUI to control
  MSO5 Oscilloscope via VISA/SCPI
  Test Equity F4T Thermal Chamber via modbustcp
  Agilent DC Power Supply via VISA/SCPI
  Agilent Frequency Counter via VISA/SCPI

Each instrument has a script execution queue so they can be given independent tasks while also queueing the tasks, so they do not attempt to run at the same time confusing the instrument.
A master queue not associated with an instrument can be used to run a script and control all devices as needed (not fully implemented yet).

The VISA/SCPI/Modbus script queue can process conditional flow control statements as well as scpi/modbus requests.

Still very much and "evidently so" a work in progress.  :)

Framework for semi-automated testing - Test Tab template
  Profile ini file lists measurement symbols and signals
    gui tab populated with signals and measurements to be taken
  measurement file with two parts
    scpi commands to set up scope for the measurement
    scpi commands to collect data from the scope and record it into a spreadsheet
    internal variables can be used to set text and other captions in the scope screen
    screen shot can also be taken and saved to an output folder based on the test
  picture and caption files for each measurement to highlight each measurement
    in the timing diagram
Settings tab
  list of common variables to identify device under test
  chamber temperatures list to be tested
  
Goals:
  I2C, SPI, SMBus, Clocks, and other validation tests to be mostly automated.
  
Future goals:
  convert to python using win32 gui elements, or maybe switch to more modern but standard windows gui elements that follow windows themes and color schemes
  
  convert to c++ for full compilation and ~5-50x speed improvement

Python migration (in progress)
------------------------------

The Python application is being introduced alongside the AutoIt version so the
existing instrument workflows remain available during the port. It uses native
Windows controls through pywin32 and reads the existing `ManualTestCompanion.ini`.

Launch the initial application shell from the repository root. The launcher
checks for missing dependencies and installs them from `requirements.txt` using
the current Python interpreter:

    python -m manual_test_companion

You can still install dependencies manually if preferred:

    python -m pip install -r requirements.txt

VXI-11 instrument connections also require a VISA backend installed on Windows;
raw TCP SCPI connections do not use that backend.

The current Python milestone provides the native tabbed window and persists its
position, size, and selected tab without rewriting unrelated legacy INI settings.
It also includes FIFO/deque and program-counter queue models, a tested Modbus TCP
register client, an F4T chamber protocol model for both legacy register maps,
a SCPI session for raw sockets or the installed VISA backend, and a synchronous
script runner for conditionals, loops, variable expressions, SCPI commands,
Modbus reads/writes, logging, cancellation, and Python `eval`/`exec` directives.
Python code can access script variables plus the `visa` and `modbus` sessions.
`exec` supports either a single Python statement or an `exec`/`endexec` block.
These directives run with normal Python builtins and process privileges; only
use trusted scripts. The Diagnostic tab now includes a native script editor,
VISA/SCPI and Modbus TCP address fields, run/stop controls, and an output pane.
Scripts run on a worker thread so instrument I/O does not block the window;
leave an address blank when that script does not use the corresponding session.
Address settings are saved to the legacy INI. Binary transfers and multi-
instrument selection are not supported; unsupported directives fail explicitly.

The Oscilloscope tab now provides native IP address, Connect, Refresh, and
screenshot controls, and embeds the installed Microsoft Edge WebView2 Runtime
in the tab. It uses the architecture-matched WebView2 loader and callback
helper included with the legacy project, navigates to the Tektronix interface,
and persists the address and screenshot path in the legacy `[Oscillocope]` INI
section. Screenshot capture runs on a worker thread and saves the instrument's
PNG response atomically. The WebView2 Runtime must be installed on the machine.

The Chamber tab has native Win32 controls for F4T connection, temperature
polling, setpoint and output control, unit selection, heat/cool indicators, and
setpoint notifications. Modbus I/O runs on a worker thread, and chamber
preferences are saved back to the legacy INI file.

The DC Power Supply tab now provides four-channel measurements and setpoints,
individual output control, emergency all-off, and the configured power-up/down
sequences. SCPI traffic runs on a worker thread; address, plans, labels, and
monitor preference are saved to the legacy INI. Screenshot capture and subnet
discovery are not yet ported.

The Frequency Counter tab now supports connection, counter configuration,
statistics reset, live preview, and sample-count capture. It displays the
frequency, mean, standard deviation, minimum, maximum, Allan deviation, and
stability in ppm. VISA operations run on a worker thread, and address, capture
count, refresh interval, and initialization preference are saved to the legacy
INI. Screenshot capture, data export, and subnet discovery remain pending.

The ScopeFM tab now connects to the oscilloscope, browses its remote directory,
restores the last path, navigates into folders or to the parent directory, and
downloads/uploads files using IEEE 488.2 binary blocks. VISA and file transfers
run on a worker thread, and the address and last folder are saved in the legacy
`[Oscilloscope_FM]` section.

For browser content inside a Python Win32 tab, the intended route is still
Microsoft Edge WebView2: create its controller with the tab's child HWND and use
the installed WebView2 Runtime. This preserves the existing embedded-browser
behavior without bundling a separate Chromium engine. `pywebview` is a higher
level option when its own browser window is acceptable; it also uses WebView2
on Windows.

The Python application remains a partial port. Settings and I2C workflows, as
well as device discovery, script file dialogs, and remaining screenshot/profile
features, still need to be ported before Python can replace the AutoIt app.
  