from __future__ import annotations

import ctypes
import math
import queue
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import win32api
import win32con
import win32gui
import win32ui

from .chamber import celsius_to_fahrenheit, fahrenheit_to_celsius
from .chamber_worker import ChamberReading, ChamberResult, ChamberWorker
from .config import LegacyConfig
from .dcps import DCPSReading
from .dcps_worker import DCPSResult, DCPSWorker
from .frequency_counter import FrequencyStats
from .frequency_worker import FrequencyCounterWorker, FrequencyResult
from .oscilloscope import scope_url_from_address
from .script_worker import ScriptEvent, ScriptWorker
from .scope_file_manager import ScopeDirectory, ScopeDirectoryEntry, scope_join_path
from .scope_file_manager_worker import ScopeFMResult, ScopeFileManagerWorker
from .scope_screenshot_worker import ScopeScreenshotResult, ScopeScreenshotWorker
from .webview2_host import WebView2Host


_ICC_PROGRESS_CLASS = 0x00000020
_TCM_FIRST = 0x1300
_TCM_GETCURSEL = _TCM_FIRST + 11
_TCM_INSERTITEMW = _TCM_FIRST + 62
_TCM_ADJUSTRECT = _TCM_FIRST + 40
_TCIF_TEXT = 0x0001
_TCN_SELCHANGE = -551
_ICC_TAB_CLASSES = 0x00000008
_WM_APP_CHAMBER_RESULT = 0x8001
_WM_APP_SCRIPT_RESULT = 0x8002
_WM_APP_DCPS_RESULT = 0x8003
_WM_APP_FREQUENCY_RESULT = 0x8004
_WM_APP_SCOPE_FM_RESULT = 0x8005
_WM_APP_SCOPE_SCREENSHOT_RESULT = 0x8006
_WM_WEBVIEW2_ENVIRONMENT_CREATED = 0x8000 + 100
_WM_WEBVIEW2_CONTROLLER_CREATED = 0x8000 + 101
_CHAMBER_TIMER = 1
_SCOPE_TIMER = 2
_SCOPE_TAB = 0
_SCOPE_FM_TAB = 4
_CHAMBER_TAB = 1
_DCPS_TAB = 2
_FREQUENCY_TAB = 3
_DIAGNOSTIC_TAB = 7
_PBM_SETPOS = 0x0402
_PBM_SETRANGE32 = 0x0406
_BM_GETCHECK = 0x00F0
_BM_SETCHECK = 0x00F1
_BST_CHECKED = 1
_BN_CLICKED = 0
_CHAMBER_CONTROL_IDS = {
    "connect": 4011,
    "temperature_units": 4012,
    "setpoint_units": 4013,
    "plan_units": 4014,
    "apply": 4015,
    "output": 4016,
    "notify": 4017,
}
_SCRIPT_CONTROL_IDS = {"run": 4021, "cancel": 4022}
_DCPS_CONTROL_IDS = {
    "connect": 4101,
    "monitor": 4102,
    "emergency_off": 4103,
    "power_up": 4104,
    "power_down": 4105,
}
_DCPS_CHANNEL_CONTROL_BASES = {
    "plan_voltage": 4200,
    "apply_voltage": 4210,
    "plan_current": 4220,
    "apply_current": 4230,
    "output": 4240,
}
_DCPS_DEFAULT_VOLTAGES = ("12", "12", "3.3", "12")
_DCPS_DEFAULT_CURRENTS = ("5", "5", "2.5", "5")
_FREQUENCY_CONTROL_IDS = {
    "connect": 4301,
    "configure": 4302,
    "reset": 4303,
    "mode": 4304,
    "initialize": 4305,
}
_SCOPE_CONTROL_IDS = {"connect": 4401, "refresh": 4402, "screenshot": 4403}
_SCOPE_FM_CONTROL_IDS = {
    "connect": 4501,
    "refresh": 4502,
    "download": 4503,
    "list": 4504,
    "upload": 4505,
}
_LB_GETCURSEL = 0x0188
_LB_ADDSTRING = 0x0180
_LB_RESETCONTENT = 0x0184
_LBN_DBLCLK = 2
_EM_SETSEL = 0x00B1
_EM_REPLACESEL = 0x00C2


class _InitCommonControlsEx(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwICC", wintypes.DWORD)]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _TabItem(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("pszText", wintypes.LPWSTR),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", wintypes.LPARAM),
    ]


class _NotifyHeader(ctypes.Structure):
    _fields_ = [
        ("hwndFrom", wintypes.HWND),
        ("idFrom", ctypes.c_size_t),
        ("code", ctypes.c_int),
    ]


_send_message = ctypes.windll.user32.SendMessageW
_send_message.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_void_p]
_send_message.restype = ctypes.c_ssize_t
_set_timer = ctypes.windll.user32.SetTimer
_set_timer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
_set_timer.restype = ctypes.c_size_t
_kill_timer = ctypes.windll.user32.KillTimer
_kill_timer.argtypes = [wintypes.HWND, ctypes.c_size_t]
_kill_timer.restype = wintypes.BOOL


class ManualTestCompanionApp:
    """Native Win32 application shell for the staged Python migration."""

    title = "ManualTestCompanion"
    tabs = (
        ("Oscilloscope", "Tektronix MSO5 control and capture"),
        ("Chamber", "Test Equity F4T thermal chamber"),
        ("DC Power Supply", "Four-channel DC power supply"),
        ("Frequency Counter", "Frequency measurement and Allan deviation"),
        ("ScopeFM", "Oscilloscope file manager"),
        ("Settings", "Application and test settings"),
        ("I2C", "I2C manual test profile"),
        ("Diagnostic", "VISA/SCPI and script diagnostics"),
    )

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path(__file__).resolve().parent.parent / "ManualTestCompanion.ini"
        self.config = LegacyConfig(self.config_path)
        self.chamber_config = LegacyConfig(self.config_path, "Chamber")
        self.dcps_config = LegacyConfig(self.config_path, "DCPS")
        self.frequency_config = LegacyConfig(self.config_path, "FC")
        self.scope_config = LegacyConfig(self.config_path, "Oscillocope")
        self.scope_fm_config = LegacyConfig(self.config_path, "Oscilloscope_FM")
        self.instance = win32api.GetModuleHandle(None)
        self.class_name = f"ManualTestCompanion.{id(self):x}"
        self.page_class_name = f"{self.class_name}.Page"
        self.window: int = 0
        self.tab: int = 0
        self.status: int = 0
        self.pages: list[int] = []
        self.placeholder_controls: dict[int, int] = {}
        self.chamber_controls: dict[str, int] = {}
        self.dcps_controls: dict[str, int] = {}
        self.frequency_controls: dict[str, int] = {}
        self.scope_controls: dict[str, int] = {}
        self.scope_fm_controls: dict[str, int] = {}
        self.diagnostic_controls: dict[str, int] = {}
        self._chamber_results: queue.SimpleQueue[ChamberResult] = queue.SimpleQueue()
        self._dcps_results: queue.SimpleQueue[DCPSResult] = queue.SimpleQueue()
        self._frequency_results: queue.SimpleQueue[FrequencyResult] = queue.SimpleQueue()
        self._script_results: queue.SimpleQueue[ScriptEvent] = queue.SimpleQueue()
        self._chamber_worker: ChamberWorker | None = None
        self._dcps_worker: DCPSWorker | None = None
        self._frequency_worker: FrequencyCounterWorker | None = None
        self._script_worker = ScriptWorker(self._publish_script_result)
        self._scope_host = WebView2Host(self._set_scope_status)
        self._scope_start_attempted = False
        self._scope_screenshot_results: queue.SimpleQueue[ScopeScreenshotResult] = (
            queue.SimpleQueue()
        )
        self._scope_screenshot_worker: ScopeScreenshotWorker | None = None
        self._scope_screenshot_busy = False
        self._scope_screenshot_path = self.scope_config.get_str(
            "screenShot",
            str(Path(__file__).resolve().parent.parent / "MSO5_Screenshot.png"),
        )
        self._scope_screenshot_settings_error = ""
        self._scope_fm_results: queue.SimpleQueue[ScopeFMResult] = queue.SimpleQueue()
        self._scope_fm_worker: ScopeFileManagerWorker | None = None
        self._scope_fm_connected = False
        self._scope_fm_busy = False
        self._scope_fm_address = self.scope_fm_config.get_str("IpAddr", "192.168.0.14")
        self._scope_fm_last_folder = self.scope_fm_config.get_str("LastFolder", "")
        self._scope_fm_identification = ""
        self._scope_fm_directory: ScopeDirectory | None = None
        self._scope_fm_entries: tuple[ScopeDirectoryEntry, ...] = ()
        self._chamber_busy = False
        self._dcps_busy = False
        self._script_running = False
        self._chamber_connected = False
        self._dcps_connected = False
        self._frequency_connected = False
        self._chamber_enabled = False
        self._chamber_reading: ChamberReading | None = None
        self._chamber_last_at_target = False
        self._chamber_address = self.chamber_config.get_str("IpAddr", "192.168.0.25")
        self._dcps_address = self.dcps_config.get_str("IpAddr", "192.168.0.16")
        self._dcps_monitor = bool(self.dcps_config.get_int("monitor", 0))
        self._dcps_channel_labels = [
            self.dcps_config.get_str(f"chlbl{channel}", default)
            for channel, default in enumerate(
                ("12V MAIN", "12V CPLD", "3.3V AUX", "12V SABR"),
                start=1,
            )
        ]
        self._frequency_address = self.frequency_config.get_str("IpAddr", "192.168.0.17")
        self._scope_address = self.scope_config.get_str("IpAddr", "192.168.0.14")
        self._frequency_target = self.frequency_config.get_str("CountRequired", "1000")
        self._frequency_refresh_interval = self.frequency_config.get_str("RefreshInterval", "2")
        self._frequency_capture_initialize = bool(
            self.frequency_config.get_int("CaptureInitialize", 0)
        )
        self._frequency_mode = "stopped"
        self._frequency_busy = False
        self._frequency_last_poll_at = 0.0
        self._frequency_last_count: tuple[int, float] | None = None
        self._frequency_stats: FrequencyStats | None = None
        self.diagnostic_config = LegacyConfig(self.config_path, "Diag")
        self._diagnostic_visa_address = self.diagnostic_config.get_str("IpAddr", "")
        self._diagnostic_modbus_host = self.diagnostic_config.get_str("ModbusIpAddr", "")
        self._chamber_temp_units_c = bool(self.chamber_config.get_int("TemperatureUnits", 1))
        self._chamber_setpoint_units_c = self._chamber_temp_units_c
        self._chamber_plan_units_c = bool(self.chamber_config.get_int("SetPointUnits", 1))
        self._chamber_notify = bool(self.chamber_config.get_int("Tnotify", 0))

    def run(self) -> int:
        self._register_window_class()
        self._create_window()
        win32gui.PumpMessages()
        return 0

    def _register_window_class(self) -> None:
        init_common_controls = _InitCommonControlsEx(
            ctypes.sizeof(_InitCommonControlsEx), _ICC_TAB_CLASSES | _ICC_PROGRESS_CLASS
        )
        if not ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(init_common_controls)):
            raise ctypes.WinError(ctypes.get_last_error())

        window_class = win32gui.WNDCLASS()
        setattr(window_class, "hInstance", self.instance)
        setattr(window_class, "lpszClassName", self.class_name)
        setattr(window_class, "lpfnWndProc", {
            win32con.WM_SIZE: self._window_proc,
            win32con.WM_NOTIFY: self._window_proc,
            win32con.WM_COMMAND: self._window_proc,
            win32con.WM_TIMER: self._window_proc,
            win32con.WM_CLOSE: self._window_proc,
            win32con.WM_DESTROY: self._window_proc,
            _WM_APP_CHAMBER_RESULT: self._window_proc,
            _WM_APP_SCRIPT_RESULT: self._window_proc,
            _WM_APP_DCPS_RESULT: self._window_proc,
            _WM_APP_FREQUENCY_RESULT: self._window_proc,
            _WM_APP_SCOPE_FM_RESULT: self._window_proc,
            _WM_WEBVIEW2_ENVIRONMENT_CREATED: self._window_proc,
            _WM_WEBVIEW2_CONTROLLER_CREATED: self._window_proc,
        })
        setattr(window_class, "hCursor", win32gui.LoadCursor(0, win32con.IDC_ARROW))
        setattr(window_class, "hbrBackground", win32con.COLOR_BTNFACE + 1)
        setattr(window_class, "style", win32con.CS_HREDRAW | win32con.CS_VREDRAW)
        win32gui.RegisterClass(window_class)

        page_class = win32gui.WNDCLASS()
        setattr(page_class, "hInstance", self.instance)
        setattr(page_class, "lpszClassName", self.page_class_name)
        setattr(page_class, "lpfnWndProc", {win32con.WM_COMMAND: self._page_proc})
        setattr(page_class, "hCursor", win32gui.LoadCursor(0, win32con.IDC_ARROW))
        setattr(page_class, "hbrBackground", win32con.COLOR_BTNFACE + 1)
        setattr(page_class, "style", win32con.CS_HREDRAW | win32con.CS_VREDRAW)
        win32gui.RegisterClass(page_class)

    def _create_window(self) -> None:
        x = self.config.get_int("wx", 60)
        y = self.config.get_int("wy", 60)
        width = max(200, self.config.get_int("ww", 800))
        height = max(200, self.config.get_int("wh", 600))
        self.window = win32gui.CreateWindowEx(
            0,
            self.class_name,
            self.title,
            win32con.WS_OVERLAPPEDWINDOW | win32con.WS_CLIPCHILDREN,
            x,
            y,
            width,
            height,
            0,
            0,
            self.instance,
            None,
        )
        self._create_controls()
        win32gui.ShowWindow(self.window, win32con.SW_SHOW)
        win32gui.UpdateWindow(self.window)
        if self.config.get_int("tab", 0) == _SCOPE_TAB:
            self._ensure_scope_webview()

    def _create_controls(self) -> None:
        self.tab = win32gui.CreateWindowEx(
            0,
            "SysTabControl32",
            "",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS,
            0,
            0,
            0,
            0,
            self.window,
            100,
            self.instance,
            None,
        )
        for index, (name, _) in enumerate(self.tabs):
            item_text = ctypes.create_unicode_buffer(name)
            item = _TabItem(mask=_TCIF_TEXT, pszText=ctypes.cast(item_text, wintypes.LPWSTR))
            result = _send_message(
                self.tab,
                _TCM_INSERTITEMW,
                index,
                ctypes.cast(ctypes.byref(item), ctypes.c_void_p),
            )
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())

        for index, (_, description) in enumerate(self.tabs):
            page_text = (
                ""
                if index
                in {
                    _SCOPE_TAB,
                    _CHAMBER_TAB,
                    _DCPS_TAB,
                    _FREQUENCY_TAB,
                    _SCOPE_FM_TAB,
                    _DIAGNOSTIC_TAB,
                }
                else f"{description}\n\nThis tab has not been ported yet."
            )
            page = win32gui.CreateWindowEx(
                0,
                self.page_class_name,
                "",
                win32con.WS_CHILD | win32con.WS_CLIPCHILDREN,
                0,
                0,
                0,
                0,
                self.window,
                200 + index,
                self.instance,
                None,
            )
            self.pages.append(page)
            if page_text:
                self.placeholder_controls[index] = self._create_chamber_control(
                    page,
                    "STATIC",
                    page_text,
                    12,
                    12,
                    500,
                    100,
                )
            if index == _SCOPE_TAB:
                self._create_scope_controls(page)
            elif index == _CHAMBER_TAB:
                self._create_chamber_controls(page)
            elif index == _DCPS_TAB:
                self._create_dcps_controls(page)
            elif index == _FREQUENCY_TAB:
                self._create_frequency_controls(page)
            elif index == _SCOPE_FM_TAB:
                self._create_scope_fm_controls(page)
            if index == _DIAGNOSTIC_TAB:
                self._create_diagnostic_controls(page)

        self.status = win32gui.CreateWindowEx(
            0,
            "STATIC",
            "Python migration in progress; Oscilloscope, ScopeFM, Chamber, DC power supply, frequency counter, and Diagnostic are available.",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT,
            8,
            0,
            0,
            24,
            self.window,
            300,
            self.instance,
            None,
        )
        selected = self.config.get_int("tab", 0)
        selected = min(max(selected, 0), len(self.tabs) - 1)
        _send_message(self.tab, _TCM_FIRST + 12, selected, None)
        self._layout_children()
        self._select_page(selected)
        if not _set_timer(self.window, _CHAMBER_TIMER, 1500, None):
            raise ctypes.WinError(ctypes.get_last_error())

    def _create_scope_controls(self, page: int) -> None:
        self._create_chamber_control(page, "STATIC", "IP address:", 10, 10, 65, 22)
        self.scope_controls["address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._scope_address,
            78,
            7,
            190,
            25,
            control_id=4400,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.scope_controls["connect"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Connect",
            276,
            6,
            80,
            27,
            control_id=_SCOPE_CONTROL_IDS["connect"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_controls["refresh"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Refresh",
            362,
            6,
            80,
            27,
            control_id=_SCOPE_CONTROL_IDS["refresh"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_controls["screenshot"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Screenshot...",
            438,
            6,
            96,
            27,
            control_id=_SCOPE_CONTROL_IDS["screenshot"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_controls["status"] = self._create_chamber_control(
            page,
            "STATIC",
            "WebView2 will start when this tab is opened.",
            542,
            10,
            260,
            22,
        )

    def _create_scope_fm_controls(self, page: int) -> None:
        self._create_chamber_control(page, "STATIC", "Scope IP:", 10, 10, 62, 22)
        self.scope_fm_controls["address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._scope_fm_address,
            76,
            7,
            165,
            25,
            control_id=4500,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.scope_fm_controls["connect"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Connect",
            249,
            6,
            80,
            27,
            control_id=_SCOPE_FM_CONTROL_IDS["connect"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_fm_controls["device"] = self._create_chamber_control(
            page, "STATIC", "Disconnected", 340, 10, 400, 22
        )
        self._create_chamber_control(page, "STATIC", "Current path:", 10, 43, 74, 22)
        self.scope_fm_controls["path"] = self._create_chamber_control(
            page,
            "EDIT",
            "",
            88,
            40,
            520,
            25,
            control_id=4506,
            extra_style=win32con.WS_BORDER | win32con.ES_READONLY | win32con.ES_AUTOHSCROLL,
        )
        self.scope_fm_controls["refresh"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Go / Refresh",
            616,
            39,
            100,
            27,
            control_id=_SCOPE_FM_CONTROL_IDS["refresh"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_fm_controls["list"] = self._create_chamber_control(
            page,
            "LISTBOX",
            "",
            10,
            74,
            700,
            300,
            control_id=_SCOPE_FM_CONTROL_IDS["list"],
            extra_style=(
                win32con.WS_BORDER
                | win32con.WS_VSCROLL
                | win32con.WS_TABSTOP
                | win32con.LBS_NOTIFY
                | win32con.LBS_HASSTRINGS
            ),
        )
        self.scope_fm_controls["download"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Download selected file",
            10,
            384,
            190,
            30,
            control_id=_SCOPE_FM_CONTROL_IDS["download"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_fm_controls["upload"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Upload file here",
            210,
            384,
            170,
            30,
            control_id=_SCOPE_FM_CONTROL_IDS["upload"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.scope_fm_controls["status"] = self._create_chamber_control(
            page, "STATIC", "Disconnected", 10, 422, 700, 22
        )
        self._update_scope_fm_controls()

    def _create_chamber_controls(self, page: int) -> None:
        self._create_chamber_control(page, "STATIC", "IP address:", 15, 20, 75, 22)
        self.chamber_controls["address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._chamber_address,
            95,
            17,
            190,
            25,
            control_id=4010,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.chamber_controls["connect"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Connect",
            295,
            16,
            95,
            27,
            control_id=_CHAMBER_CONTROL_IDS["connect"],
            extra_style=win32con.WS_TABSTOP,
        )
        self._create_chamber_control(page, "STATIC", "Device:", 15, 55, 75, 22)
        self.chamber_controls["device"] = self._create_chamber_control(
            page, "STATIC", "Not connected", 95, 55, 295, 22
        )

        self._create_chamber_control(page, "STATIC", "Temperature:", 15, 92, 75, 22)
        self.chamber_controls["temperature"] = self._create_chamber_control(
            page, "STATIC", "---", 95, 92, 90, 22
        )
        self.chamber_controls["temperature_units"] = self._create_chamber_control(
            page,
            "BUTTON",
            self._temperature_unit_label(self._chamber_temp_units_c),
            190,
            88,
            55,
            27,
            control_id=_CHAMBER_CONTROL_IDS["temperature_units"],
        )

        self._create_chamber_control(page, "STATIC", "Setpoint:", 15, 128, 75, 22)
        self.chamber_controls["setpoint"] = self._create_chamber_control(
            page, "STATIC", "---", 95, 128, 90, 22
        )
        self.chamber_controls["setpoint_units"] = self._create_chamber_control(
            page,
            "BUTTON",
            self._temperature_unit_label(self._chamber_setpoint_units_c),
            190,
            124,
            55,
            27,
            control_id=_CHAMBER_CONTROL_IDS["setpoint_units"],
        )

        self._create_chamber_control(page, "STATIC", "Plan:", 15, 164, 75, 22)
        self.chamber_controls["plan"] = self._create_chamber_control(
            page,
            "EDIT",
            self.chamber_config.get_str("SetPoint", "25"),
            95,
            160,
            90,
            25,
            control_id=4018,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.ES_RIGHT | win32con.WS_TABSTOP,
        )
        self.chamber_controls["plan_units"] = self._create_chamber_control(
            page,
            "BUTTON",
            self._temperature_unit_label(self._chamber_plan_units_c),
            190,
            160,
            55,
            27,
            control_id=_CHAMBER_CONTROL_IDS["plan_units"],
        )
        self.chamber_controls["apply"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Set temperature",
            255,
            160,
            135,
            27,
            control_id=_CHAMBER_CONTROL_IDS["apply"],
            extra_style=win32con.WS_TABSTOP,
        )

        self.chamber_controls["output"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Output Off",
            15,
            200,
            110,
            27,
            control_id=_CHAMBER_CONTROL_IDS["output"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.chamber_controls["notify"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Notify when temperature is reached",
            145,
            201,
            245,
            25,
            control_id=_CHAMBER_CONTROL_IDS["notify"],
            extra_style=0x00000003 | win32con.WS_TABSTOP,
        )
        win32gui.SendMessage(
            self.chamber_controls["notify"],
            _BM_SETCHECK,
            _BST_CHECKED if self._chamber_notify else 0,
            0,
        )

        self._create_chamber_control(page, "STATIC", "Cooling:", 15, 242, 75, 20)
        self.chamber_controls["cooling"] = self._create_chamber_control(
            page,
            "msctls_progress32",
            "",
            95,
            240,
            295,
            18,
            extra_style=0x00000001,
        )
        self._create_chamber_control(page, "STATIC", "Heating:", 15, 270, 75, 20)
        self.chamber_controls["heating"] = self._create_chamber_control(
            page,
            "msctls_progress32",
            "",
            95,
            268,
            295,
            18,
            extra_style=0x00000001,
        )
        for key in ("cooling", "heating"):
            win32gui.SendMessage(self.chamber_controls[key], _PBM_SETRANGE32, 0, 100)

    def _create_chamber_control(
        self,
        parent: int,
        class_name: str,
        text: str,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        control_id: int = 0,
        extra_style: int = 0,
    ) -> int:
        style = win32con.WS_CHILD | win32con.WS_VISIBLE | extra_style
        return win32gui.CreateWindowEx(
            0,
            class_name,
            text,
            style,
            x,
            y,
            width,
            height,
            parent,
            control_id,
            self.instance,
            None,
        )

    def _create_dcps_controls(self, page: int) -> None:
        self._create_chamber_control(page, "STATIC", "IP address:", 10, 10, 65, 22)
        self.dcps_controls["address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._dcps_address,
            78,
            7,
            190,
            25,
            control_id=4100,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.dcps_controls["connect"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Connect",
            276,
            6,
            80,
            27,
            control_id=_DCPS_CONTROL_IDS["connect"],
            extra_style=win32con.WS_TABSTOP,
        )
        self._create_chamber_control(page, "STATIC", "Device:", 370, 10, 48, 22)
        self.dcps_controls["device"] = self._create_chamber_control(
            page, "STATIC", "Not connected", 420, 10, 300, 22
        )
        self.dcps_controls["monitor"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Monitor",
            10,
            42,
            100,
            24,
            control_id=_DCPS_CONTROL_IDS["monitor"],
            extra_style=0x00000003 | win32con.WS_TABSTOP,
        )
        win32gui.SendMessage(
            self.dcps_controls["monitor"],
            _BM_SETCHECK,
            _BST_CHECKED if self._dcps_monitor else 0,
            0,
        )
        self.dcps_controls["emergency_off"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Emergency off",
            120,
            40,
            105,
            28,
            control_id=_DCPS_CONTROL_IDS["emergency_off"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.dcps_controls["power_up"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Power up",
            235,
            40,
            85,
            28,
            control_id=_DCPS_CONTROL_IDS["power_up"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.dcps_controls["power_down"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Power down",
            330,
            40,
            90,
            28,
            control_id=_DCPS_CONTROL_IDS["power_down"],
            extra_style=win32con.WS_TABSTOP,
        )

        for index in range(4):
            channel = index + 1
            prefix = f"ch{channel}_"
            self.dcps_controls[prefix + "label"] = self._create_chamber_control(
                page,
                "STATIC",
                self._dcps_channel_labels[index],
                0,
                0,
                170,
                24,
            )
            for key, label in (
                ("measured_voltage", "Measured V:"),
                ("measured_current", "Measured I:"),
                ("measured_power", "Power:"),
                ("set_voltage", "Set V:"),
                ("set_current", "Set I:"),
            ):
                self.dcps_controls[prefix + key + "_label"] = self._create_chamber_control(
                    page, "STATIC", label, 0, 0, 70, 22
                )
                self.dcps_controls[prefix + key] = self._create_chamber_control(
                    page, "STATIC", "---", 0, 0, 100, 22
                )
            self.dcps_controls[prefix + "plan_voltage_label"] = self._create_chamber_control(
                page, "STATIC", "Plan V:", 0, 0, 55, 22
            )
            self.dcps_controls[prefix + "plan_voltage"] = self._create_chamber_control(
                page,
                "EDIT",
                self.dcps_config.get_str(f"V{channel}", _DCPS_DEFAULT_VOLTAGES[index]),
                0,
                0,
                85,
                24,
                control_id=_DCPS_CHANNEL_CONTROL_BASES["plan_voltage"] + index,
                extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.ES_RIGHT | win32con.WS_TABSTOP,
            )
            self.dcps_controls[prefix + "apply_voltage"] = self._create_chamber_control(
                page,
                "BUTTON",
                "Set",
                0,
                0,
                40,
                24,
                control_id=_DCPS_CHANNEL_CONTROL_BASES["apply_voltage"] + index,
                extra_style=win32con.WS_TABSTOP,
            )
            self.dcps_controls[prefix + "plan_current_label"] = self._create_chamber_control(
                page, "STATIC", "Plan I:", 0, 0, 55, 22
            )
            self.dcps_controls[prefix + "plan_current"] = self._create_chamber_control(
                page,
                "EDIT",
                self.dcps_config.get_str(f"I{channel}", _DCPS_DEFAULT_CURRENTS[index]),
                0,
                0,
                85,
                24,
                control_id=_DCPS_CHANNEL_CONTROL_BASES["plan_current"] + index,
                extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.ES_RIGHT | win32con.WS_TABSTOP,
            )
            self.dcps_controls[prefix + "apply_current"] = self._create_chamber_control(
                page,
                "BUTTON",
                "Set",
                0,
                0,
                40,
                24,
                control_id=_DCPS_CHANNEL_CONTROL_BASES["apply_current"] + index,
                extra_style=win32con.WS_TABSTOP,
            )
            self.dcps_controls[prefix + "output"] = self._create_chamber_control(
                page,
                "BUTTON",
                "Off",
                0,
                0,
                85,
                28,
                control_id=_DCPS_CHANNEL_CONTROL_BASES["output"] + index,
                extra_style=win32con.WS_TABSTOP,
            )

    def _create_frequency_controls(self, page: int) -> None:
        self._create_chamber_control(page, "STATIC", "IP address:", 10, 10, 65, 22)
        self.frequency_controls["address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._frequency_address,
            78,
            7,
            175,
            25,
            control_id=4300,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.frequency_controls["connect"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Connect",
            260,
            6,
            80,
            27,
            control_id=_FREQUENCY_CONTROL_IDS["connect"],
            extra_style=win32con.WS_TABSTOP,
        )
        self._create_chamber_control(page, "STATIC", "Device:", 355, 10, 48, 22)
        self.frequency_controls["device"] = self._create_chamber_control(
            page, "STATIC", "Not connected", 405, 10, 310, 22
        )
        self.frequency_controls["configure"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Configure FC",
            10,
            42,
            100,
            27,
            control_id=_FREQUENCY_CONTROL_IDS["configure"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.frequency_controls["reset"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Reset stats",
            118,
            42,
            100,
            27,
            control_id=_FREQUENCY_CONTROL_IDS["reset"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.frequency_controls["mode"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Start preview",
            226,
            42,
            110,
            27,
            control_id=_FREQUENCY_CONTROL_IDS["mode"],
            extra_style=win32con.WS_TABSTOP,
        )
        self._create_chamber_control(page, "STATIC", "Capture count:", 350, 47, 80, 20)
        self.frequency_controls["target"] = self._create_chamber_control(
            page,
            "EDIT",
            self._frequency_target,
            432,
            43,
            75,
            24,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.ES_RIGHT | win32con.WS_TABSTOP,
        )
        self.frequency_controls["initialize"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Initialize on start",
            518,
            43,
            130,
            24,
            control_id=_FREQUENCY_CONTROL_IDS["initialize"],
            extra_style=0x00000003 | win32con.WS_TABSTOP,
        )
        win32gui.SendMessage(
            self.frequency_controls["initialize"],
            _BM_SETCHECK,
            _BST_CHECKED if self._frequency_capture_initialize else 0,
            0,
        )
        self._create_chamber_control(page, "STATIC", "Refresh (s):", 10, 82, 75, 22)
        self.frequency_controls["refresh_interval"] = self._create_chamber_control(
            page,
            "EDIT",
            self._frequency_refresh_interval,
            88,
            79,
            65,
            24,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.ES_RIGHT | win32con.WS_TABSTOP,
        )

        stats_labels = {
            "frequency": "Frequency:",
            "mean": "Mean:",
            "stddev": "StdDev:",
            "count": "Count:",
            "rate": "Speed:",
            "ppm": "Stability:",
            "maximum": "Max:",
            "minimum": "Min:",
            "allan": "Allan dev:",
        }
        for key, label in stats_labels.items():
            self.frequency_controls[key + "_label"] = self._create_chamber_control(
                page, "STATIC", label, 0, 0, 90, 22
            )
            self.frequency_controls[key] = self._create_chamber_control(
                page, "STATIC", "---", 0, 0, 180, 22
            )

    def _page_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == win32con.WM_COMMAND:
            return win32gui.SendMessage(
                win32gui.GetParent(hwnd),
                message,
                wparam,
                lparam,
            )
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _create_diagnostic_controls(self, page: int) -> None:
        self.diagnostic_controls["visa_label"] = self._create_chamber_control(
            page, "STATIC", "VISA/SCPI:", 10, 10, 65, 22
        )
        self.diagnostic_controls["visa_address"] = self._create_chamber_control(
            page,
            "EDIT",
            self._diagnostic_visa_address,
            78,
            7,
            280,
            25,
            control_id=4020,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.diagnostic_controls["modbus_label"] = self._create_chamber_control(
            page, "STATIC", "Modbus TCP:", 370, 10, 75, 22
        )
        self.diagnostic_controls["modbus_host"] = self._create_chamber_control(
            page,
            "EDIT",
            self._diagnostic_modbus_host,
            448,
            7,
            190,
            25,
            control_id=4024,
            extra_style=win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
        )
        self.diagnostic_controls["script_label"] = self._create_chamber_control(
            page, "STATIC", "Script:", 10, 64, 100, 20
        )
        self.diagnostic_controls["output_label"] = self._create_chamber_control(
            page, "STATIC", "Output:", 0, 64, 100, 20
        )
        self.diagnostic_controls["script"] = self._create_chamber_control(
            page,
            "EDIT",
            "",
            10,
            84,
            400,
            300,
            control_id=4025,
            extra_style=(
                win32con.WS_BORDER
                | win32con.ES_MULTILINE
                | win32con.ES_AUTOVSCROLL
                | win32con.ES_WANTRETURN
                | win32con.WS_VSCROLL
                | win32con.WS_TABSTOP
            ),
        )
        self.diagnostic_controls["output"] = self._create_chamber_control(
            page,
            "EDIT",
            "",
            420,
            84,
            260,
            300,
            control_id=4026,
            extra_style=(
                win32con.WS_BORDER
                | win32con.ES_MULTILINE
                | win32con.ES_AUTOVSCROLL
                | win32con.ES_READONLY
                | win32con.WS_VSCROLL
            ),
        )
        self.diagnostic_controls["run"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Run",
            10,
            0,
            75,
            27,
            control_id=_SCRIPT_CONTROL_IDS["run"],
            extra_style=win32con.WS_TABSTOP,
        )
        self.diagnostic_controls["cancel"] = self._create_chamber_control(
            page,
            "BUTTON",
            "Stop",
            90,
            0,
            75,
            27,
            control_id=_SCRIPT_CONTROL_IDS["cancel"],
            extra_style=win32con.WS_TABSTOP,
        )

    @staticmethod
    def _temperature_unit_label(celsius: bool) -> str:
        return "°C" if celsius else "°F"

    def _handle_command(self, wparam: int) -> bool:
        notification = (wparam >> 16) & 0xFFFF
        control_id = wparam & 0xFFFF
        if (
            control_id == _SCOPE_FM_CONTROL_IDS["list"]
            and notification == _LBN_DBLCLK
        ):
            self._activate_scope_fm_selection()
            return True
        if notification != _BN_CLICKED:
            return False
        if control_id == _SCOPE_CONTROL_IDS["connect"]:
            self._connect_scope()
        elif control_id == _SCOPE_CONTROL_IDS["refresh"]:
            self._refresh_scope()
        elif control_id == _SCOPE_CONTROL_IDS["screenshot"]:
            self._capture_scope_screenshot()
        elif control_id == _SCOPE_FM_CONTROL_IDS["connect"]:
            self._toggle_scope_fm_connection()
        elif control_id == _SCOPE_FM_CONTROL_IDS["refresh"]:
            self._refresh_scope_fm()
        elif control_id == _SCOPE_FM_CONTROL_IDS["download"]:
            self._download_scope_fm_selection()
        elif control_id == _SCOPE_FM_CONTROL_IDS["upload"]:
            self._upload_scope_fm_file()
        elif control_id == _CHAMBER_CONTROL_IDS["connect"]:
            self._connect_chamber()
        elif control_id == _CHAMBER_CONTROL_IDS["temperature_units"]:
            self._chamber_temp_units_c = not self._chamber_temp_units_c
            self._update_chamber_reading()
            self._update_unit_buttons()
        elif control_id == _CHAMBER_CONTROL_IDS["setpoint_units"]:
            self._chamber_setpoint_units_c = not self._chamber_setpoint_units_c
            self._update_chamber_reading()
            self._update_unit_buttons()
        elif control_id == _CHAMBER_CONTROL_IDS["plan_units"]:
            self._chamber_plan_units_c = not self._chamber_plan_units_c
            self._update_unit_buttons()
        elif control_id == _CHAMBER_CONTROL_IDS["apply"]:
            self._apply_chamber_setpoint()
        elif control_id == _CHAMBER_CONTROL_IDS["output"]:
            self._toggle_chamber_output()
        elif control_id == _CHAMBER_CONTROL_IDS["notify"]:
            self._chamber_notify = (
                win32gui.SendMessage(self.chamber_controls["notify"], _BM_GETCHECK, 0, 0)
                == _BST_CHECKED
            )
        elif control_id == _DCPS_CONTROL_IDS["connect"]:
            self._connect_dcps()
        elif control_id == _DCPS_CONTROL_IDS["monitor"]:
            self._dcps_monitor = (
                win32gui.SendMessage(self.dcps_controls["monitor"], _BM_GETCHECK, 0, 0)
                == _BST_CHECKED
            )
        elif control_id == _DCPS_CONTROL_IDS["emergency_off"]:
            self._submit_dcps_action(
                "Turning all power-supply outputs off...",
                lambda worker: worker.emergency_off(),
            )
        elif control_id == _DCPS_CONTROL_IDS["power_up"]:
            self._run_dcps_sequence(power_up=True)
        elif control_id == _DCPS_CONTROL_IDS["power_down"]:
            self._run_dcps_sequence(power_up=False)
        elif control_id == _FREQUENCY_CONTROL_IDS["connect"]:
            self._connect_frequency_counter()
        elif control_id == _FREQUENCY_CONTROL_IDS["configure"]:
            self._submit_frequency_command(
                "initialize",
                "Configuring the frequency counter...",
                lambda worker: worker.initialize(),
            )
        elif control_id == _FREQUENCY_CONTROL_IDS["reset"]:
            self._submit_frequency_command(
                "reset",
                "Resetting frequency-counter statistics...",
                lambda worker: worker.reset_statistics(),
            )
        elif control_id == _FREQUENCY_CONTROL_IDS["mode"]:
            self._toggle_frequency_mode()
        elif control_id == _FREQUENCY_CONTROL_IDS["initialize"]:
            self._frequency_capture_initialize = (
                win32gui.SendMessage(
                    self.frequency_controls["initialize"],
                    _BM_GETCHECK,
                    0,
                    0,
                )
                == _BST_CHECKED
            )
        elif control_id == _SCRIPT_CONTROL_IDS["run"]:
            self._run_diagnostic_script()
        elif control_id == _SCRIPT_CONTROL_IDS["cancel"]:
            self._cancel_diagnostic_script()
        else:
            for index in range(4):
                if control_id == _DCPS_CHANNEL_CONTROL_BASES["apply_voltage"] + index:
                    self._apply_dcps_plan(index + 1, voltage=True)
                    return True
                if control_id == _DCPS_CHANNEL_CONTROL_BASES["apply_current"] + index:
                    self._apply_dcps_plan(index + 1, voltage=False)
                    return True
                if control_id == _DCPS_CHANNEL_CONTROL_BASES["output"] + index:
                    self._toggle_dcps_output(index + 1)
                    return True
            return False
        return True

    def _connect_dcps(self) -> None:
        address = win32gui.GetWindowText(self.dcps_controls["address"]).strip()
        if not address:
            self._set_status("Enter a DC power-supply address before connecting.")
            return
        if self._dcps_busy:
            return
        self._dcps_address = address
        self._dcps_connected = False
        self._dcps_reading = None
        for channel in range(1, 5):
            prefix = f"ch{channel}_"
            for key in (
                "measured_voltage",
                "measured_current",
                "measured_power",
                "set_voltage",
                "set_current",
            ):
                win32gui.SetWindowText(self.dcps_controls[prefix + key], "---")
            win32gui.SetWindowText(self.dcps_controls[prefix + "output"], "--")
        self._set_dcps_busy(True)
        self._set_status(f"Connecting to DC power supply at {address}...")
        if self._dcps_worker is None:
            self._dcps_worker = DCPSWorker(self._publish_dcps_result)
        self._dcps_worker.connect(address)

    def _apply_dcps_plan(self, channel: int, *, voltage: bool) -> None:
        if not self._require_dcps_connection():
            return
        kind = "voltage" if voltage else "current"
        text = win32gui.GetWindowText(
            self.dcps_controls[f"ch{channel}_plan_{kind}"]
        ).strip()
        try:
            value = float(text)
        except ValueError:
            self._set_status(f"Invalid channel {channel} {kind}: {text!r}")
            return
        if not math.isfinite(value):
            self._set_status(f"Channel {channel} {kind} must be finite.")
            return
        if voltage:
            self._submit_dcps_action(
                f"Setting channel {channel} voltage...",
                lambda worker: worker.set_voltage(channel, value),
            )
        else:
            self._submit_dcps_action(
                f"Setting channel {channel} current limit...",
                lambda worker: worker.set_current_limit(channel, value),
            )

    def _toggle_dcps_output(self, channel: int) -> None:
        if not self._require_dcps_connection():
            return
        if self._dcps_reading is None:
            self._set_status("Read the power supply before toggling an output.")
            return
        enabled = not self._dcps_reading.channels[channel - 1].output_enabled
        self._submit_dcps_action(
            f"Turning channel {channel} {'on' if enabled else 'off'}...",
            lambda worker: worker.set_output(channel, enabled),
        )

    def _run_dcps_sequence(self, *, power_up: bool) -> None:
        if not self._require_dcps_connection() or self._dcps_worker is None:
            return
        direction = "up" if power_up else "dn"
        enabled = power_up
        steps: list[tuple[int, bool, float]] = []
        try:
            default_channels = (4, 2, 3, 1) if power_up else (1, 3, 2, 4)
            for index in range(1, 5):
                channel = int(
                    self.dcps_config.get_str(
                        f"{direction}seqch{index}",
                        str(default_channels[index - 1]),
                    )
                )
                delay = float(self.dcps_config.get_str(f"{direction}seqtm{index}", "0.5"))
                if channel not in range(5):
                    raise ValueError(f"{direction} sequence channel must be between 0 and 4")
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError(f"{direction} sequence delay must be finite and nonnegative")
                steps.append((channel, enabled, delay))
        except ValueError as error:
            self._set_status(f"Invalid DC power sequence: {error}")
            return
        action = "Powering up" if power_up else "Powering down"
        sequence = tuple(steps)
        self._submit_dcps_action(
            f"{action} using the configured channel sequence.",
            lambda worker: worker.run_sequence(sequence),
        )

    def _require_dcps_connection(self) -> bool:
        if self._dcps_busy:
            return False
        if not self._dcps_connected or self._dcps_worker is None:
            self._set_status("Connect to the DC power supply before sending commands.")
            return False
        return True

    def _submit_dcps_action(
        self,
        status: str,
        submit: Callable[[DCPSWorker], None],
    ) -> None:
        if not self._require_dcps_connection() or self._dcps_worker is None:
            return
        self._set_dcps_busy(True)
        self._set_status(status)
        submit(self._dcps_worker)

    def _set_dcps_busy(self, busy: bool) -> None:
        self._dcps_busy = busy
        for key in ("connect", "emergency_off", "power_up", "power_down"):
            if key in self.dcps_controls:
                win32gui.EnableWindow(self.dcps_controls[key], not busy)
        for index in range(4):
            prefix = f"ch{index + 1}_"
            for key in ("apply_voltage", "apply_current", "output"):
                win32gui.EnableWindow(self.dcps_controls[prefix + key], not busy)

    def _publish_dcps_result(self, result: DCPSResult) -> None:
        self._dcps_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_DCPS_RESULT, 0, 0)

    def _consume_dcps_results(self) -> None:
        while True:
            try:
                result = self._dcps_results.get_nowait()
            except queue.Empty:
                return
            self._set_dcps_busy(False)
            if result.action == "connect":
                self._dcps_connected = result.error is None
            if result.error is not None:
                if result.action == "connect":
                    win32gui.SetWindowText(self.dcps_controls["device"], "Connection failed")
                self._set_status(f"DC power supply {result.action} failed: {result.error}")
                continue
            if result.reading is None:
                self._set_status(f"DC power supply {result.action} returned no readings.")
                continue
            self._dcps_reading = result.reading
            if result.action == "connect":
                win32gui.SetWindowText(
                    self.dcps_controls["device"],
                    result.identification or "Connected",
                )
                self._set_status("Connected to DC power supply.")
            elif result.action != "refresh":
                self._set_status("DC power-supply command completed.")
            self._update_dcps_reading(result.reading)

    def _update_dcps_reading(self, reading: DCPSReading) -> None:
        for index, channel in enumerate(reading.channels, start=1):
            prefix = f"ch{index}_"
            values = {
                "measured_voltage": f"{channel.measured_voltage:.3f} V",
                "measured_current": f"{channel.measured_current * 1000:.1f} mA",
                "measured_power": f"{channel.measured_power_mw:.1f} mW",
                "set_voltage": f"{channel.voltage_setpoint:.3f} V",
                "set_current": f"{channel.current_limit:.3f} A",
            }
            for key, value in values.items():
                win32gui.SetWindowText(self.dcps_controls[prefix + key], value)
            win32gui.SetWindowText(
                self.dcps_controls[prefix + "output"],
                "On" if channel.output_enabled else "Off",
            )

    def _poll_dcps(self) -> None:
        if (
            self._dcps_connected
            and not self._dcps_busy
            and self._dcps_monitor
            and _send_message(self.tab, _TCM_GETCURSEL, 0, None) == _DCPS_TAB
            and self._dcps_worker is not None
        ):
            self._set_dcps_busy(True)
            self._dcps_worker.refresh()

    def _connect_frequency_counter(self) -> None:
        address = win32gui.GetWindowText(self.frequency_controls["address"]).strip()
        if not address:
            self._set_status("Enter a frequency-counter address before connecting.")
            return
        if self._frequency_busy:
            return
        self._frequency_address = address
        self._frequency_connected = False
        self._frequency_mode = "stopped"
        self._set_frequency_mode_button()
        self._reset_frequency_display()
        self._set_frequency_busy(True)
        self._set_status(f"Connecting to frequency counter at {address}...")
        if self._frequency_worker is None:
            self._frequency_worker = FrequencyCounterWorker(self._publish_frequency_result)
        self._frequency_worker.connect(address)

    def _submit_frequency_command(
        self,
        action: str,
        status: str,
        submit: Callable[[FrequencyCounterWorker], None],
    ) -> None:
        if self._frequency_busy:
            return
        if not self._frequency_connected or self._frequency_worker is None:
            self._set_status("Connect to the frequency counter before sending commands.")
            return
        self._set_frequency_busy(True)
        self._set_status(status)
        submit(self._frequency_worker)
        if action == "reset":
            self._reset_frequency_display()

    def _toggle_frequency_mode(self) -> None:
        if not self._frequency_connected or self._frequency_worker is None:
            self._set_status("Connect to the frequency counter before starting a measurement.")
            return
        if self._frequency_busy:
            return
        if self._frequency_mode == "capture":
            self._frequency_mode = "stopped"
            self._set_frequency_mode_button()
            self._set_status("Frequency capture stopped.")
            return
        if self._frequency_mode == "stopped":
            self._frequency_mode = "preview"
            self._set_status("Frequency preview started.")
            self._frequency_last_count = None
        else:
            try:
                target = self._get_frequency_capture_target()
                self._get_frequency_refresh_interval()
            except ValueError as error:
                self._set_status(f"Invalid frequency capture settings: {error}")
                return
            self._frequency_mode = "capture"
            self._frequency_last_count = None
            self._set_status(f"Capturing at least {target:,} frequency samples...")
            if self._frequency_capture_initialize:
                self._submit_frequency_command(
                    "initialize",
                    "Initializing the counter for capture...",
                    lambda worker: worker.initialize(),
                )
        self._frequency_last_poll_at = 0.0
        self._set_frequency_mode_button()

    def _get_frequency_capture_target(self) -> int:
        text = win32gui.GetWindowText(self.frequency_controls["target"]).strip()
        try:
            target = int(text)
        except ValueError as error:
            raise ValueError("capture count must be a positive integer") from error
        if target <= 0:
            raise ValueError("capture count must be a positive integer")
        return target

    def _get_frequency_refresh_interval(self) -> float:
        text = win32gui.GetWindowText(
            self.frequency_controls["refresh_interval"]
        ).strip()
        try:
            interval = float(text)
        except ValueError as error:
            raise ValueError("refresh interval must be a positive number of seconds") from error
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("refresh interval must be a positive finite number of seconds")
        return interval

    def _set_frequency_busy(self, busy: bool) -> None:
        self._frequency_busy = busy
        for key in ("connect", "configure", "reset", "mode"):
            if key in self.frequency_controls:
                win32gui.EnableWindow(self.frequency_controls[key], not busy)

    def _set_frequency_mode_button(self) -> None:
        labels = {
            "stopped": "Start preview",
            "preview": "Start capture",
            "capture": "Stop capture",
        }
        win32gui.SetWindowText(
            self.frequency_controls["mode"],
            labels[self._frequency_mode],
        )

    def _reset_frequency_display(self) -> None:
        self._frequency_stats = None
        self._frequency_last_count = None
        for key in (
            "frequency",
            "ppm",
            "mean",
            "maximum",
            "stddev",
            "minimum",
            "count",
            "allan",
            "rate",
        ):
            win32gui.SetWindowText(self.frequency_controls[key], "---")

    def _publish_frequency_result(self, result: FrequencyResult) -> None:
        self._frequency_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_FREQUENCY_RESULT, 0, 0)

    def _consume_frequency_results(self) -> None:
        while True:
            try:
                result = self._frequency_results.get_nowait()
            except queue.Empty:
                return
            self._set_frequency_busy(False)
            if result.action == "connect":
                self._frequency_connected = result.error is None
            if result.error is not None:
                if result.action == "connect":
                    win32gui.SetWindowText(
                        self.frequency_controls["device"],
                        "Connection failed",
                    )
                if result.action in {"monitor", "capture", "initialize"}:
                    self._frequency_mode = "stopped"
                    self._set_frequency_mode_button()
                self._set_status(f"Frequency counter {result.action} failed: {result.error}")
                continue
            if result.action == "connect":
                win32gui.SetWindowText(
                    self.frequency_controls["device"],
                    result.identification or "Connected",
                )
                self._set_status("Connected to frequency counter.")
                if self._frequency_capture_initialize:
                    self._submit_frequency_command(
                        "initialize",
                        "Initializing the frequency counter...",
                        lambda worker: worker.initialize(),
                    )
            elif result.action == "initialize":
                self._set_status("Frequency counter configured and acquisition started.")
            elif result.action == "reset":
                self._set_status("Frequency-counter statistics reset.")
            if result.count is not None:
                self._update_frequency_count(result.count)
            if result.stats is not None:
                self._update_frequency_stats(result.stats)
            if result.action == "capture" and result.capture_complete:
                self._frequency_mode = "stopped"
                self._set_frequency_mode_button()
                self._set_status(f"Frequency capture completed at {result.count:,} samples.")
            elif result.action in {"monitor", "capture"}:
                self._set_status(
                    f"Collected {result.count:,} frequency samples."
                    if result.count is not None
                    else "Frequency-counter update completed."
                )

    def _update_frequency_count(self, count: int) -> None:
        win32gui.SetWindowText(
            self.frequency_controls["count"],
            f"{count:,} samples",
        )
        now = time.monotonic()
        previous = self._frequency_last_count
        if previous is not None:
            previous_count, previous_at = previous
            elapsed = now - previous_at
            delta = count - previous_count
            if elapsed > 0 and delta >= 0:
                speed = delta / elapsed
                win32gui.SetWindowText(
                    self.frequency_controls["rate"],
                    f"{speed:.1f} samples/s",
                )
        self._frequency_last_count = (count, now)

    def _update_frequency_stats(self, stats: FrequencyStats) -> None:
        self._frequency_stats = stats
        values = {
            "frequency": f"{stats.frequency_hz:.12g} Hz",
            "mean": f"{stats.mean_hz:.12g} Hz",
            "stddev": f"{stats.standard_deviation_hz:.6g} Hz",
            "minimum": f"{stats.minimum_hz:.12g} Hz",
            "maximum": f"{stats.maximum_hz:.12g} Hz",
            "allan": f"{stats.allan_deviation_hz:.6g} Hz",
            "ppm": (
                f"{stats.stability_ppm:.6g} ppm"
                if stats.stability_ppm is not None
                else "---"
            ),
        }
        for key, value in values.items():
            win32gui.SetWindowText(self.frequency_controls[key], value)
        win32gui.SetWindowText(
            self.frequency_controls["count"],
            f"{stats.count:,} samples",
        )

    def _poll_frequency_counter(self) -> None:
        if (
            not self._frequency_connected
            or self._frequency_busy
            or self._frequency_mode == "stopped"
            or _send_message(self.tab, _TCM_GETCURSEL, 0, None) != _FREQUENCY_TAB
            or self._frequency_worker is None
        ):
            return
        try:
            interval = self._get_frequency_refresh_interval()
        except ValueError as error:
            self._set_status(f"Invalid frequency refresh interval: {error}")
            self._frequency_mode = "stopped"
            self._set_frequency_mode_button()
            return
        now = time.monotonic()
        if now - self._frequency_last_poll_at < interval:
            return
        self._frequency_last_poll_at = now
        self._set_frequency_busy(True)
        if self._frequency_mode == "capture":
            try:
                target = self._get_frequency_capture_target()
            except ValueError as error:
                self._set_frequency_busy(False)
                self._set_status(f"Invalid frequency capture count: {error}")
                self._frequency_mode = "stopped"
                self._set_frequency_mode_button()
                return
            self._frequency_worker.poll_capture(target)
        else:
            self._frequency_worker.monitor()

    def _run_diagnostic_script(self) -> None:
        if self._script_running:
            return
        source = win32gui.GetWindowText(self.diagnostic_controls["script"])
        self._diagnostic_visa_address = win32gui.GetWindowText(
            self.diagnostic_controls["visa_address"]
        ).strip()
        self._diagnostic_modbus_host = win32gui.GetWindowText(
            self.diagnostic_controls["modbus_host"]
        ).strip()
        win32gui.SetWindowText(self.diagnostic_controls["output"], "")
        self._script_running = True
        self._set_diagnostic_buttons(running=True)
        self._set_status("Starting diagnostic script...")
        try:
            self._script_worker.start(
                source,
                visa_address=self._diagnostic_visa_address,
                modbus_host=self._diagnostic_modbus_host,
            )
        except RuntimeError as error:
            self._script_running = False
            self._set_diagnostic_buttons(running=False)
            self._set_status(f"Could not start diagnostic script: {error}")

    def _cancel_diagnostic_script(self) -> None:
        if self._script_running:
            self._script_worker.cancel()
            self._set_status("Stopping diagnostic script...")

    def _set_diagnostic_buttons(self, *, running: bool) -> None:
        if self.diagnostic_controls:
            win32gui.EnableWindow(self.diagnostic_controls["run"], not running)
            win32gui.EnableWindow(self.diagnostic_controls["cancel"], running)

    def _publish_script_result(self, result: ScriptEvent) -> None:
        self._script_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_SCRIPT_RESULT, 0, 0)

    def _consume_script_results(self) -> None:
        while True:
            try:
                result = self._script_results.get_nowait()
            except queue.Empty:
                return
            if result.kind == "output":
                output = self.diagnostic_controls["output"]
                win32gui.SendMessage(output, _EM_SETSEL, -1, -1)
                win32gui.SendMessage(output, _EM_REPLACESEL, 0, result.text + "\r\n")
                continue
            if result.kind in {"completed", "cancelled", "failed"}:
                self._script_running = False
                self._set_diagnostic_buttons(running=False)
            win32gui.SendMessage(self.diagnostic_controls["output"], _EM_SETSEL, -1, -1)
            win32gui.SendMessage(
                self.diagnostic_controls["output"],
                _EM_REPLACESEL,
                0,
                result.text + "\r\n",
            )
            self._set_status(result.text)

    def _update_unit_buttons(self) -> None:
        win32gui.SetWindowText(
            self.chamber_controls["temperature_units"],
            self._temperature_unit_label(self._chamber_temp_units_c),
        )
        win32gui.SetWindowText(
            self.chamber_controls["setpoint_units"],
            self._temperature_unit_label(self._chamber_setpoint_units_c),
        )
        win32gui.SetWindowText(
            self.chamber_controls["plan_units"],
            self._temperature_unit_label(self._chamber_plan_units_c),
        )

    def _connect_chamber(self) -> None:
        address = win32gui.GetWindowText(self.chamber_controls["address"]).strip()
        host = address.split(maxsplit=1)[0] if address else ""
        if host.casefold().startswith("raw:"):
            host = host[4:]
        if not host:
            self._set_status("Enter a chamber IP address before connecting.")
            return
        if self._chamber_busy:
            return
        self._chamber_address = address
        self._chamber_connected = False
        self._chamber_set_busy(True)
        self._set_status(f"Connecting to F4T chamber at {host}...")
        if self._chamber_worker is None:
            self._chamber_worker = ChamberWorker(self._publish_chamber_result)
        self._chamber_worker.connect(host)

    def _connect_scope(self) -> None:
        address = win32gui.GetWindowText(self.scope_controls["address"]).strip()
        try:
            url = scope_url_from_address(address)
        except ValueError as error:
            self._set_scope_status(str(error))
            return
        self._scope_address = address
        self.scope_config.update({"IpAddr": address})
        if not self._scope_start_attempted:
            self._scope_start_attempted = True
            try:
                self._scope_host.initialize(
                    self.pages[_SCOPE_TAB],
                    url,
                    notify_window=self.window,
                )
                if not _set_timer(self.window, _SCOPE_TIMER, 100, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            except (OSError, RuntimeError, ValueError) as error:
                self._set_scope_status(f"WebView2 unavailable: {error}")
            return
        try:
            if self._scope_host.failed:
                self._set_scope_status("WebView2 initialization failed; restart the app after resolving the error.")
                return
            self._scope_host.navigate(url)
            if not self._scope_host.ready:
                self._set_scope_status("WebView2 is still initializing.")
        except (OSError, RuntimeError, ValueError) as error:
            self._set_scope_status(f"Could not open the oscilloscope page: {error}")

    def _refresh_scope(self) -> None:
        if self._scope_host.failed:
            self._set_scope_status("WebView2 initialization failed; restart the app after resolving the error.")
            return
        if not self._scope_host.ready:
            self._ensure_scope_webview()
            return
        try:
            self._scope_host.reload()
        except (OSError, RuntimeError) as error:
            self._set_scope_status(f"Could not refresh the oscilloscope page: {error}")

    def _capture_scope_screenshot(self) -> None:
        if self._scope_screenshot_busy:
            return
        address = win32gui.GetWindowText(self.scope_controls["address"]).strip()
        try:
            scope_url_from_address(address)
        except ValueError as error:
            self._set_scope_status(str(error))
            return

        screenshot_path = Path(self._scope_screenshot_path)
        initial_name = str(screenshot_path)
        dialog = win32ui.CreateFileDialog(
            0,
            "png",
            initial_name,
            win32con.OFN_PATHMUSTEXIST | win32con.OFN_OVERWRITEPROMPT,
            "PNG images (*.png)|*.png||",
            self.window,
        )
        if dialog.DoModal() != win32con.IDOK:
            return

        destination = Path(dialog.GetPathName())
        self._scope_screenshot_path = str(destination)
        self._scope_address = address
        try:
            self.scope_config.update(
                {"IpAddr": address, "screenShot": self._scope_screenshot_path}
            )
            self._scope_screenshot_settings_error = ""
        except OSError as error:
            self._scope_screenshot_settings_error = (
                f"Screenshot settings could not be saved to {self.config_path}: {error}"
            )

        if self._scope_screenshot_worker is None:
            self._scope_screenshot_worker = ScopeScreenshotWorker(
                self._publish_scope_screenshot_result
            )
        self._scope_screenshot_busy = True
        win32gui.EnableWindow(self.scope_controls["screenshot"], False)
        self._set_scope_status("Capturing oscilloscope screenshot...")
        self._scope_screenshot_worker.capture(address, destination)

    def _publish_scope_screenshot_result(self, result: ScopeScreenshotResult) -> None:
        self._scope_screenshot_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_SCOPE_SCREENSHOT_RESULT, 0, 0)

    def _consume_scope_screenshot_results(self) -> None:
        while True:
            try:
                result = self._scope_screenshot_results.get_nowait()
            except queue.Empty:
                return
            self._scope_screenshot_busy = False
            win32gui.EnableWindow(self.scope_controls["screenshot"], True)
            if result.error is not None:
                message = f"Oscilloscope screenshot failed: {result.error}"
            else:
                message = f"Screenshot saved to {result.path}."
            if self._scope_screenshot_settings_error:
                message = f"{message} {self._scope_screenshot_settings_error}"
            self._set_scope_status(message)

    def _ensure_scope_webview(self) -> None:
        if self._scope_start_attempted:
            return
        try:
            url = scope_url_from_address(
                win32gui.GetWindowText(self.scope_controls["address"]).strip()
            )
        except ValueError as error:
            self._set_scope_status(str(error))
            return
        self._scope_start_attempted = True
        try:
            self._scope_host.initialize(
                self.pages[_SCOPE_TAB],
                url,
                notify_window=self.window,
            )
            if not _set_timer(self.window, _SCOPE_TIMER, 100, None):
                raise ctypes.WinError(ctypes.get_last_error())
        except (OSError, RuntimeError, ValueError) as error:
            self._set_scope_status(f"WebView2 unavailable: {error}")

    def _set_scope_status(self, message: str) -> None:
        if self.scope_controls:
            win32gui.SetWindowText(self.scope_controls["status"], message)
        self._set_status(message)

    def _toggle_scope_fm_connection(self) -> None:
        if self._scope_fm_busy:
            return
        if self._scope_fm_worker is None:
            self._scope_fm_worker = ScopeFileManagerWorker(self._publish_scope_fm_result)
        self._scope_fm_busy = True
        self._update_scope_fm_controls()
        if self._scope_fm_connected:
            self._set_scope_fm_status("Disconnecting from the oscilloscope...")
            self._scope_fm_worker.disconnect()
            return
        self._scope_fm_address = win32gui.GetWindowText(
            self.scope_fm_controls["address"]
        ).strip()
        if not self._scope_fm_address:
            self._scope_fm_busy = False
            self._update_scope_fm_controls()
            self._set_scope_fm_status("Enter an oscilloscope IP address before connecting.")
            return
        self._set_scope_fm_status(f"Connecting to oscilloscope at {self._scope_fm_address}...")
        self._scope_fm_worker.connect(
            self._scope_fm_address,
            self._scope_fm_last_folder,
        )

    def _refresh_scope_fm(self) -> None:
        if not self._require_scope_fm_connection():
            return
        self._scope_fm_worker.refresh()
        self._set_scope_fm_busy("Reading the oscilloscope directory...")

    def _activate_scope_fm_selection(self) -> None:
        if not self._require_scope_fm_connection():
            return
        index = win32gui.SendMessage(
            self.scope_fm_controls["list"],
            _LB_GETCURSEL,
            0,
            0,
        )
        if index < 0:
            return
        if index == 0:
            self._scope_fm_worker.parent_directory(self._scope_fm_directory.path)
            self._set_scope_fm_busy("Opening the parent directory...")
            return
        entry = self._scope_fm_entries[index - 1]
        if entry.is_directory:
            path = scope_join_path(self._scope_fm_directory.path, entry.name.rstrip("/\\"))
            self._scope_fm_worker.change_directory(path)
            self._set_scope_fm_busy(f"Opening {entry.name}...")
            return
        self._download_scope_fm_entry(entry)

    def _download_scope_fm_selection(self) -> None:
        if not self._require_scope_fm_connection():
            return
        index = win32gui.SendMessage(self.scope_fm_controls["list"], _LB_GETCURSEL, 0, 0)
        if index <= 0 or index > len(self._scope_fm_entries):
            self._set_scope_fm_status("Select a file to download.")
            return
        entry = self._scope_fm_entries[index - 1]
        if entry.is_directory:
            self._set_scope_fm_status("Select a file, not a directory, to download.")
            return
        self._download_scope_fm_entry(entry)

    def _download_scope_fm_entry(self, entry: ScopeDirectoryEntry) -> None:
        dialog = win32ui.CreateFileDialog(
            0,
            None,
            entry.name,
            win32con.OFN_PATHMUSTEXIST | win32con.OFN_OVERWRITEPROMPT,
            "All files (*.*)|*.*||",
            self.window,
        )
        if dialog.DoModal() != win32con.IDOK:
            return
        destination = Path(dialog.GetPathName())
        self._scope_fm_worker.download(entry.name, destination)
        self._set_scope_fm_busy(f"Downloading {entry.name}...")

    def _upload_scope_fm_file(self) -> None:
        if not self._require_scope_fm_connection():
            return
        dialog = win32ui.CreateFileDialog(
            1,
            None,
            None,
            win32con.OFN_FILEMUSTEXIST | win32con.OFN_PATHMUSTEXIST,
            "All files (*.*)|*.*||",
            self.window,
        )
        if dialog.DoModal() != win32con.IDOK:
            return
        source = Path(dialog.GetPathName())
        self._scope_fm_worker.upload(source, source.name)
        self._set_scope_fm_busy(f"Uploading {source.name}...")

    def _require_scope_fm_connection(self) -> bool:
        if not self._scope_fm_connected or self._scope_fm_worker is None:
            self._set_scope_fm_status("Connect to the oscilloscope file system first.")
            return False
        if self._scope_fm_busy:
            return False
        return True

    def _set_scope_fm_busy(self, message: str) -> None:
        self._scope_fm_busy = True
        self._update_scope_fm_controls()
        self._set_scope_fm_status(message)

    def _update_scope_fm_controls(self) -> None:
        if not self.scope_fm_controls:
            return
        connected = self._scope_fm_connected
        busy = self._scope_fm_busy
        win32gui.SetWindowText(
            self.scope_fm_controls["connect"],
            "Disconnect" if connected else "Connect",
        )
        win32gui.EnableWindow(self.scope_fm_controls["connect"], not busy)
        win32gui.EnableWindow(self.scope_fm_controls["address"], not connected and not busy)
        for key in ("refresh", "download", "upload", "list"):
            win32gui.EnableWindow(self.scope_fm_controls[key], connected and not busy)

    def _set_scope_fm_status(self, message: str) -> None:
        if self.scope_fm_controls:
            win32gui.SetWindowText(self.scope_fm_controls["status"], message)
        self._set_status(message)

    def _publish_scope_fm_result(self, result: ScopeFMResult) -> None:
        self._scope_fm_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_SCOPE_FM_RESULT, 0, 0)

    def _consume_scope_fm_results(self) -> None:
        while True:
            try:
                result = self._scope_fm_results.get_nowait()
            except queue.Empty:
                return
            self._scope_fm_busy = False
            if result.error is not None:
                if result.action == "connect":
                    self._scope_fm_connected = False
                    win32gui.SetWindowText(
                        self.scope_fm_controls["device"],
                        "Connection failed",
                    )
                self._update_scope_fm_controls()
                self._set_scope_fm_status(
                    f"Oscilloscope {result.action} failed: {result.error}"
                )
                continue
            if result.action == "connect":
                self._scope_fm_connected = True
                self._scope_fm_identification = result.identification
                win32gui.SetWindowText(
                    self.scope_fm_controls["device"],
                    result.identification,
                )
                self._set_scope_fm_status(f"Connected to {result.identification}.")
            elif result.action == "disconnect":
                self._scope_fm_connected = False
                self._scope_fm_directory = None
                self._scope_fm_entries = ()
                win32gui.SetWindowText(self.scope_fm_controls["device"], "Disconnected")
                win32gui.SetWindowText(self.scope_fm_controls["path"], "")
                win32gui.SendMessage(
                    self.scope_fm_controls["list"],
                    _LB_RESETCONTENT,
                    0,
                    0,
                )
                self._set_scope_fm_status("Disconnected from oscilloscope.")
            elif result.action == "download":
                self._set_scope_fm_status(f"Downloaded to {result.local_path}.")
            elif result.action == "upload":
                self._set_scope_fm_status("File uploaded to the oscilloscope.")
            elif result.action not in {"refresh", "change_directory", "parent_directory"}:
                self._set_scope_fm_status(f"Oscilloscope {result.action} completed.")
            if result.directory is not None:
                self._scope_fm_directory = result.directory
                self._scope_fm_entries = result.directory.entries
                self._scope_fm_last_folder = result.directory.path
                self._render_scope_fm_directory(result.directory)
                settings_saved = True
                try:
                    self._save_scope_fm_settings()
                except OSError as error:
                    settings_saved = False
                    self._set_scope_fm_status(
                        f"Directory loaded, but settings could not be saved to "
                        f"{self.config_path}: {error}"
                    )
                if (
                    settings_saved
                    and result.action in {"refresh", "change_directory", "parent_directory"}
                ):
                    self._set_scope_fm_status(f"Directory updated: {result.directory.path}")
            self._update_scope_fm_controls()

    def _render_scope_fm_directory(self, directory: ScopeDirectory) -> None:
        listbox = self.scope_fm_controls["list"]
        win32gui.SetWindowText(self.scope_fm_controls["path"], directory.path)
        win32gui.SendMessage(listbox, _LB_RESETCONTENT, 0, 0)
        win32gui.SendMessage(listbox, _LB_ADDSTRING, 0, "[..] Parent directory")
        for entry in directory.entries:
            prefix = "[DIR] " if entry.is_directory else "[FILE] "
            win32gui.SendMessage(listbox, _LB_ADDSTRING, 0, prefix + entry.name)

    def _save_scope_fm_settings(self) -> None:
        if self.scope_fm_controls:
            self._scope_fm_address = win32gui.GetWindowText(
                self.scope_fm_controls["address"]
            ).strip()
        self.scope_fm_config.update(
            {
                "IpAddr": self._scope_fm_address,
                "LastFolder": self._scope_fm_last_folder,
            }
        )

    def _apply_chamber_setpoint(self) -> None:
        if not self._require_chamber_connection():
            return
        text = win32gui.GetWindowText(self.chamber_controls["plan"]).strip()
        try:
            temperature = float(text)
        except ValueError:
            self._set_status(f"Invalid setpoint: {text!r}")
            return
        if not math.isfinite(temperature):
            self._set_status("Setpoint must be a finite number.")
            return
        if not self._chamber_plan_units_c:
            temperature = fahrenheit_to_celsius(temperature)
        self._submit_chamber_action(
            lambda worker: worker.set_setpoint(temperature),
            "Setting chamber temperature...",
        )

    def _toggle_chamber_output(self) -> None:
        if not self._require_chamber_connection():
            return
        self._submit_chamber_action(
            lambda worker: worker.set_enabled(not self._chamber_enabled),
            "Changing chamber output state...",
        )

    def _require_chamber_connection(self) -> bool:
        if self._chamber_busy:
            return False
        if not self._chamber_connected or self._chamber_worker is None:
            self._set_status("Connect to the chamber before sending commands.")
            return False
        return True

    def _submit_chamber_action(
        self,
        submit: Callable[[ChamberWorker], None],
        status: str,
    ) -> None:
        if not self._require_chamber_connection() or self._chamber_worker is None:
            return
        self._chamber_set_busy(True)
        self._set_status(status)
        submit(self._chamber_worker)

    def _poll_chamber(self) -> None:
        if (
            self._chamber_connected
            and not self._chamber_busy
            and _send_message(self.tab, _TCM_GETCURSEL, 0, None) == _CHAMBER_TAB
            and self._chamber_worker is not None
        ):
            self._chamber_set_busy(True)
            self._chamber_worker.refresh()

    def _publish_chamber_result(self, result: ChamberResult) -> None:
        self._chamber_results.put(result)
        if self.window and win32gui.IsWindow(self.window):
            win32gui.PostMessage(self.window, _WM_APP_CHAMBER_RESULT, 0, 0)

    def _consume_chamber_results(self) -> None:
        while True:
            try:
                result = self._chamber_results.get_nowait()
            except queue.Empty:
                return
            self._chamber_set_busy(False)
            if result.action == "connect":
                self._chamber_connected = result.error is None
                self._chamber_last_at_target = False
            if result.error is not None:
                message = f"Chamber {result.action} failed: {result.error}"
                win32gui.SetWindowText(
                    self.chamber_controls["device"],
                    "Connection failed" if result.action == "connect" else "Communication error",
                )
                self._set_status(message)
                continue
            if result.reading is None:
                self._set_status(f"Chamber {result.action} returned no reading.")
                continue
            if result.action == "connect":
                host = self._chamber_address.split(maxsplit=1)[0].removeprefix("raw:")
                win32gui.SetWindowText(
                    self.chamber_controls["device"],
                    f"Connected to {host}",
                )
                self._set_status(f"Connected to F4T chamber at {host}.")
            elif result.action != "refresh":
                self._set_status("Chamber command completed.")
            self._chamber_reading = result.reading
            self._chamber_enabled = result.reading.enabled
            self._update_chamber_reading()
            self._update_chamber_outputs(result.reading)
            self._notify_if_at_target(result.reading)

    def _update_chamber_reading(self) -> None:
        reading = self._chamber_reading
        if reading is None:
            return
        temperature = reading.temperature_c
        if not self._chamber_temp_units_c:
            temperature = celsius_to_fahrenheit(temperature)
        setpoint = reading.setpoint_c
        if not self._chamber_setpoint_units_c:
            setpoint = celsius_to_fahrenheit(setpoint)
        win32gui.SetWindowText(self.chamber_controls["temperature"], f"{temperature:.1f}")
        win32gui.SetWindowText(self.chamber_controls["setpoint"], f"{setpoint:.1f}")

    def _update_chamber_outputs(self, reading: ChamberReading) -> None:
        win32gui.SetWindowText(
            self.chamber_controls["output"],
            "Output On" if reading.enabled else "Output Off",
        )
        win32gui.SendMessage(
            self.chamber_controls["cooling"],
            _PBM_SETPOS,
            _percent_position(reading.cooling_percent),
            0,
        )
        win32gui.SendMessage(
            self.chamber_controls["heating"],
            _PBM_SETPOS,
            _percent_position(reading.heating_percent),
            0,
        )

    def _notify_if_at_target(self, reading: ChamberReading) -> None:
        at_target = abs(reading.temperature_c - reading.setpoint_c) <= 0.5
        if self._chamber_notify and at_target and not self._chamber_last_at_target:
            win32gui.MessageBox(
                self.window,
                f"Temperature setpoint reached.\nTemperature: {reading.temperature_c:.1f} °C\n"
                f"Setpoint: {reading.setpoint_c:.1f} °C",
                "Thermal chamber",
                win32con.MB_OK | win32con.MB_ICONINFORMATION,
            )
        self._chamber_last_at_target = at_target

    def _chamber_set_busy(self, busy: bool) -> None:
        self._chamber_busy = busy
        for key in ("connect", "apply", "output"):
            if key in self.chamber_controls:
                win32gui.EnableWindow(self.chamber_controls[key], not busy)

    def _save_chamber_settings(self) -> None:
        if not self.chamber_controls:
            return
        self._chamber_address = win32gui.GetWindowText(self.chamber_controls["address"]).strip()
        plan = win32gui.GetWindowText(self.chamber_controls["plan"]).strip()
        self.chamber_config.update(
            {
                "IpAddr": self._chamber_address,
                "TemperatureUnits": int(self._chamber_temp_units_c),
                "SetPoint": plan,
                "SetPointUnits": int(self._chamber_plan_units_c),
                "Tnotify": int(self._chamber_notify),
            }
        )

    def _set_status(self, message: str) -> None:
        if self.status:
            win32gui.SetWindowText(self.status, message)

    def _layout_children(self) -> None:
        if not self.tab:
            return
        client = win32gui.GetClientRect(self.window)
        width = client[2] - client[0]
        height = client[3] - client[1]
        status_height = 24
        win32gui.MoveWindow(self.tab, 0, 0, width, max(0, height - status_height), True)
        page_rect = _Rect(0, 0, width, max(0, height - status_height))
        _send_message(
            self.tab,
            _TCM_ADJUSTRECT,
            0,
            ctypes.cast(ctypes.byref(page_rect), ctypes.c_void_p),
        )
        for index, page in enumerate(self.pages):
            page_width = max(0, page_rect.right - page_rect.left - 24)
            page_height = max(0, page_rect.bottom - page_rect.top - 20)
            win32gui.MoveWindow(
                page,
                page_rect.left + 12,
                page_rect.top + 10,
                page_width,
                page_height,
                True,
            )
            placeholder = self.placeholder_controls.get(index)
            if placeholder is not None:
                win32gui.MoveWindow(
                    placeholder,
                    12,
                    12,
                    max(0, page_width - 24),
                    max(0, page_height - 24),
                    True,
                )
        self._layout_scope_controls()
        self._layout_scope_fm_controls()
        self._layout_diagnostic_controls()
        self._layout_dcps_controls()
        self._layout_frequency_controls()
        win32gui.MoveWindow(self.status, 8, height - status_height, max(0, width - 16), status_height, True)

    def _layout_frequency_controls(self) -> None:
        if not self.frequency_controls:
            return
        page = self.pages[_FREQUENCY_TAB]
        client = win32gui.GetClientRect(page)
        width = max(0, client[2] - client[0])
        win32gui.MoveWindow(self.frequency_controls["address"], 78, 7, 165, 25, True)
        win32gui.MoveWindow(self.frequency_controls["connect"], 250, 6, 80, 27, True)
        win32gui.MoveWindow(
            self.frequency_controls["device"],
            405,
            10,
            max(0, width - 415),
            22,
            True,
        )
        win32gui.MoveWindow(self.frequency_controls["configure"], 10, 42, 100, 27, True)
        win32gui.MoveWindow(self.frequency_controls["reset"], 118, 42, 100, 27, True)
        win32gui.MoveWindow(self.frequency_controls["mode"], 226, 42, 110, 27, True)
        win32gui.MoveWindow(self.frequency_controls["target"], 432, 43, 75, 24, True)
        win32gui.MoveWindow(self.frequency_controls["initialize"], 518, 43, 130, 24, True)
        win32gui.MoveWindow(self.frequency_controls["refresh_interval"], 88, 79, 65, 24, True)

        left_x = 10
        right_x = max(300, width // 2)
        value_width = max(0, width // 2 - 120)
        rows = {
            "frequency": (left_x, 126),
            "mean": (left_x, 160),
            "stddev": (left_x, 194),
            "count": (left_x, 228),
            "rate": (left_x, 262),
            "ppm": (right_x, 126),
            "maximum": (right_x, 160),
            "minimum": (right_x, 194),
            "allan": (right_x, 228),
        }
        for key, (x, y) in rows.items():
            win32gui.MoveWindow(
                self.frequency_controls[key + "_label"],
                x,
                y,
                85,
                22,
                True,
            )
            win32gui.MoveWindow(
                self.frequency_controls[key],
                x + 90,
                y,
                value_width,
                22,
                True,
            )

    def _layout_scope_controls(self) -> None:
        if not self.scope_controls:
            return
        page = self.pages[_SCOPE_TAB]
        client = win32gui.GetClientRect(page)
        width = max(0, client[2] - client[0])
        height = max(0, client[3] - client[1])
        win32gui.MoveWindow(self.scope_controls["address"], 78, 7, 180, 25, True)
        win32gui.MoveWindow(self.scope_controls["connect"], 266, 6, 80, 27, True)
        win32gui.MoveWindow(self.scope_controls["refresh"], 352, 6, 80, 27, True)
        win32gui.MoveWindow(self.scope_controls["screenshot"], 438, 6, 96, 27, True)
        win32gui.MoveWindow(
            self.scope_controls["status"],
            542,
            10,
            max(0, width - 552),
            22,
            True,
        )
        try:
            self._scope_host.set_bounds(0, 40, width, max(0, height - 40))
        except OSError as error:
            self._set_scope_status(f"Could not resize the embedded browser: {error}")

    def _layout_scope_fm_controls(self) -> None:
        if not self.scope_fm_controls:
            return
        page = self.pages[_SCOPE_FM_TAB]
        client = win32gui.GetClientRect(page)
        width = max(0, client[2] - client[0])
        height = max(0, client[3] - client[1])
        win32gui.MoveWindow(self.scope_fm_controls["address"], 76, 7, 165, 25, True)
        win32gui.MoveWindow(self.scope_fm_controls["connect"], 249, 6, 80, 27, True)
        win32gui.MoveWindow(
            self.scope_fm_controls["device"],
            340,
            10,
            max(0, width - 350),
            22,
            True,
        )
        path_width = max(80, width - 218)
        win32gui.MoveWindow(self.scope_fm_controls["path"], 88, 40, path_width, 25, True)
        refresh_x = 96 + path_width
        win32gui.MoveWindow(self.scope_fm_controls["refresh"], refresh_x, 39, 100, 27, True)
        list_y = 74
        footer_y = max(list_y, height - 58)
        win32gui.MoveWindow(
            self.scope_fm_controls["list"],
            10,
            list_y,
            max(0, width - 20),
            max(0, footer_y - list_y - 8),
            True,
        )
        win32gui.MoveWindow(
            self.scope_fm_controls["download"],
            10,
            footer_y,
            190,
            30,
            True,
        )
        win32gui.MoveWindow(
            self.scope_fm_controls["upload"],
            210,
            footer_y,
            170,
            30,
            True,
        )
        win32gui.MoveWindow(
            self.scope_fm_controls["status"],
            10,
            height - 24,
            max(0, width - 20),
            22,
            True,
        )

    def _layout_dcps_controls(self) -> None:
        if not self.dcps_controls:
            return
        page = self.pages[_DCPS_TAB]
        client = win32gui.GetClientRect(page)
        width = max(0, client[2] - client[0])
        margin = 10
        win32gui.MoveWindow(self.dcps_controls["address"], 78, 7, 180, 25, True)
        win32gui.MoveWindow(self.dcps_controls["connect"], 266, 6, 80, 27, True)
        win32gui.MoveWindow(self.dcps_controls["device"], 420, 10, max(0, width - 430), 22, True)
        win32gui.MoveWindow(self.dcps_controls["emergency_off"], 120, 40, 105, 28, True)
        win32gui.MoveWindow(self.dcps_controls["power_up"], 235, 40, 85, 28, True)
        win32gui.MoveWindow(self.dcps_controls["power_down"], 330, 40, 90, 28, True)

        gap = 8
        column_width = max(0, (width - 2 * margin - 3 * gap) // 4)
        row_y = {
            "measured_voltage": 116,
            "measured_current": 142,
            "measured_power": 168,
            "set_voltage": 206,
            "set_current": 232,
        }
        for index in range(4):
            prefix = f"ch{index + 1}_"
            x = margin + index * (column_width + gap)
            win32gui.MoveWindow(self.dcps_controls[prefix + "label"], x, 82, column_width, 24, True)
            for key, y in row_y.items():
                win32gui.MoveWindow(
                    self.dcps_controls[prefix + key + "_label"],
                    x,
                    y,
                    68,
                    22,
                    True,
                )
                win32gui.MoveWindow(
                    self.dcps_controls[prefix + key],
                    x + 70,
                    y,
                    max(0, column_width - 72),
                    22,
                    True,
                )
            for key, y in (("plan_voltage", 278), ("plan_current", 312)):
                self._move_dcps_plan_row(prefix, key, x, y, column_width)
            win32gui.MoveWindow(
                self.dcps_controls[prefix + "output"],
                x + max(0, (column_width - 85) // 2),
                352,
                min(85, column_width),
                28,
                True,
            )

    def _move_dcps_plan_row(
        self,
        prefix: str,
        key: str,
        x: int,
        y: int,
        column_width: int,
    ) -> None:
        label_width = 52
        button_width = min(40, column_width)
        edit_x = x + label_width
        edit_width = max(0, column_width - label_width - button_width - 4)
        win32gui.MoveWindow(
            self.dcps_controls[prefix + key + "_label"],
            x,
            y,
            label_width,
            22,
            True,
        )
        win32gui.MoveWindow(
            self.dcps_controls[prefix + key],
            edit_x,
            y - 1,
            edit_width,
            24,
            True,
        )
        win32gui.MoveWindow(
            self.dcps_controls[prefix + "apply_" + key.removeprefix("plan_")],
            edit_x + edit_width + 4,
            y - 1,
            button_width,
            24,
            True,
        )

    def _layout_diagnostic_controls(self) -> None:
        if not self.diagnostic_controls:
            return
        page = self.pages[_DIAGNOSTIC_TAB]
        client = win32gui.GetClientRect(page)
        width = max(0, client[2] - client[0])
        height = max(0, client[3] - client[1])
        margin = 10
        visa_label_width = 65
        modbus_label_width = 75
        button_width = 75
        gap = 8
        address_width = max(
            80,
            (width - 2 * margin - visa_label_width - modbus_label_width - 2 * button_width - 4 * gap)
            // 2,
        )
        visa_edit_x = margin + visa_label_width + 3
        modbus_label_x = visa_edit_x + address_width + gap
        modbus_edit_x = modbus_label_x + modbus_label_width
        win32gui.MoveWindow(self.diagnostic_controls["visa_address"], visa_edit_x, 7, address_width, 25, True)
        win32gui.MoveWindow(
            self.diagnostic_controls["modbus_host"],
            modbus_edit_x,
            7,
            max(80, width - margin - modbus_edit_x),
            25,
            True,
        )
        content_y = 84
        content_height = max(0, height - content_y - margin)
        script_width = max(0, width // 2 - 15)
        win32gui.MoveWindow(
            self.diagnostic_controls["visa_label"],
            margin,
            10,
            65,
            22,
            True,
        )
        win32gui.MoveWindow(
            self.diagnostic_controls["modbus_label"],
            modbus_label_x,
            10,
            modbus_label_width,
            22,
            True,
        )
        win32gui.MoveWindow(
            self.diagnostic_controls["script"],
            margin,
            content_y,
            script_width,
            content_height,
            True,
        )
        output_x = width // 2 + 5
        win32gui.MoveWindow(
            self.diagnostic_controls["output"],
            output_x,
            content_y,
            max(0, width - output_x - margin),
            content_height,
            True,
        )
        win32gui.MoveWindow(self.diagnostic_controls["script_label"], margin, 62, 100, 20, True)
        win32gui.MoveWindow(
            self.diagnostic_controls["output_label"],
            output_x,
            62,
            100,
            20,
            True,
        )
        win32gui.MoveWindow(self.diagnostic_controls["run"], margin, 34, button_width, 25, True)
        win32gui.MoveWindow(
            self.diagnostic_controls["cancel"],
            margin + button_width + gap,
            34,
            button_width,
            25,
            True,
        )

    def _select_page(self, index: int) -> None:
        for page_index, page in enumerate(self.pages):
            win32gui.ShowWindow(page, win32con.SW_SHOW if page_index == index else win32con.SW_HIDE)
        try:
            self._scope_host.set_visible(index == _SCOPE_TAB)
        except OSError as error:
            self._set_scope_status(f"Could not update embedded browser visibility: {error}")
        if index == _SCOPE_TAB:
            self._ensure_scope_webview()

    def _save_window_state(self) -> None:
        show_command = win32gui.GetWindowPlacement(self.window)[1]
        values = {
            "tab": max(0, _send_message(self.tab, _TCM_GETCURSEL, 0, None)),
        }
        if not win32gui.IsIconic(self.window) and show_command != win32con.SW_SHOWMAXIMIZED:
            left, top, right, bottom = win32gui.GetWindowRect(self.window)
            values.update(
                {
                    "wx": left,
                    "wy": top,
                    "ww": right - left,
                    "wh": bottom - top,
                }
            )
        self.config.update(values)
        self._save_chamber_settings()
        self._save_dcps_settings()
        self._save_frequency_settings()
        self._save_scope_settings()
        self._save_scope_fm_settings()
        self._save_diagnostic_settings()

    def _save_scope_settings(self) -> None:
        if not self.scope_controls:
            return
        self._scope_address = win32gui.GetWindowText(
            self.scope_controls["address"]
        ).strip()
        self.scope_config.update(
            {
                "IpAddr": self._scope_address,
                "screenShot": self._scope_screenshot_path,
            }
        )

    def _save_dcps_settings(self) -> None:
        if not self.dcps_controls:
            return
        self._dcps_address = win32gui.GetWindowText(self.dcps_controls["address"]).strip()
        values: dict[str, str | int] = {
            "IpAddr": self._dcps_address,
            "monitor": int(
                win32gui.SendMessage(self.dcps_controls["monitor"], _BM_GETCHECK, 0, 0)
                == _BST_CHECKED
            ),
        }
        for channel in range(1, 5):
            prefix = f"ch{channel}_"
            values[f"V{channel}"] = win32gui.GetWindowText(
                self.dcps_controls[prefix + "plan_voltage"]
            ).strip()
            values[f"I{channel}"] = win32gui.GetWindowText(
                self.dcps_controls[prefix + "plan_current"]
            ).strip()
            values[f"chlbl{channel}"] = win32gui.GetWindowText(
                self.dcps_controls[prefix + "label"]
            ).strip()
        self.dcps_config.update(values)

    def _save_frequency_settings(self) -> None:
        if not self.frequency_controls:
            return
        self._frequency_address = win32gui.GetWindowText(
            self.frequency_controls["address"]
        ).strip()
        self.frequency_config.update(
            {
                "IpAddr": self._frequency_address,
                "CountRequired": win32gui.GetWindowText(
                    self.frequency_controls["target"]
                ).strip(),
                "RefreshInterval": win32gui.GetWindowText(
                    self.frequency_controls["refresh_interval"]
                ).strip(),
                "CaptureInitialize": int(
                    win32gui.SendMessage(
                        self.frequency_controls["initialize"],
                        _BM_GETCHECK,
                        0,
                        0,
                    )
                    == _BST_CHECKED
                ),
            }
        )

    def _save_diagnostic_settings(self) -> None:
        if not self.diagnostic_controls:
            return
        self._diagnostic_visa_address = win32gui.GetWindowText(
            self.diagnostic_controls["visa_address"]
        ).strip()
        self._diagnostic_modbus_host = win32gui.GetWindowText(
            self.diagnostic_controls["modbus_host"]
        ).strip()
        self.diagnostic_config.update(
            {
                "IpAddr": self._diagnostic_visa_address,
                "ModbusIpAddr": self._diagnostic_modbus_host,
            }
        )

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == win32con.WM_SIZE:
            self._layout_children()
            return 0
        if self._scope_host.handle_message(message, wparam):
            if self._scope_host.ready or self._scope_host.failed:
                _kill_timer(hwnd, _SCOPE_TIMER)
            return 0
        if message == win32con.WM_COMMAND and self._handle_command(wparam):
            return 0
        if message == win32con.WM_TIMER and wparam == _CHAMBER_TIMER:
            self._poll_chamber()
            self._poll_dcps()
            self._poll_frequency_counter()
            return 0
        if message == win32con.WM_TIMER and wparam == _SCOPE_TIMER:
            self._scope_host.poll()
            if self._scope_host.ready or self._scope_host.failed:
                _kill_timer(hwnd, _SCOPE_TIMER)
            return 0
        if message == _WM_APP_CHAMBER_RESULT:
            self._consume_chamber_results()
            return 0
        if message == _WM_APP_SCRIPT_RESULT:
            self._consume_script_results()
            return 0
        if message == _WM_APP_DCPS_RESULT:
            self._consume_dcps_results()
            return 0
        if message == _WM_APP_FREQUENCY_RESULT:
            self._consume_frequency_results()
            return 0
        if message == _WM_APP_SCOPE_FM_RESULT:
            self._consume_scope_fm_results()
            return 0
        if message == _WM_APP_SCOPE_SCREENSHOT_RESULT:
            self._consume_scope_screenshot_results()
            return 0
        if message == win32con.WM_NOTIFY and lparam:
            notification = ctypes.cast(lparam, ctypes.POINTER(_NotifyHeader)).contents
            if notification.hwndFrom == self.tab and notification.code == _TCN_SELCHANGE:
                selected = max(0, _send_message(self.tab, _TCM_GETCURSEL, 0, None))
                self._select_page(selected)
                return 0
        if message == win32con.WM_CLOSE:
            try:
                self._save_window_state()
            except OSError as error:
                win32gui.MessageBox(
                    hwnd,
                    f"Could not save settings to {self.config_path}:\n{error}",
                    self.title,
                    win32con.MB_ICONERROR | win32con.MB_OK,
                )
                return 0
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == win32con.WM_DESTROY:
            _kill_timer(hwnd, _CHAMBER_TIMER)
            _kill_timer(hwnd, _SCOPE_TIMER)
            self._scope_host.close()
            if self._scope_screenshot_worker is not None:
                self._scope_screenshot_worker.close()
            if self._scope_fm_worker is not None:
                self._scope_fm_worker.close()
            if self._chamber_worker is not None:
                self._chamber_worker.close()
            if self._dcps_worker is not None:
                self._dcps_worker.close()
            if self._frequency_worker is not None:
                self._frequency_worker.close()
            self._script_worker.cancel()
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


def _percent_position(value: float) -> int:
    if not math.isfinite(value):
        return 0
    return min(100, max(0, round(value)))


def main() -> int:
    return ManualTestCompanionApp().run()
