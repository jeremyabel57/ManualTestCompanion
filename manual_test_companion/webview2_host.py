from __future__ import annotations

import ctypes
import os
import struct
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable


_WM_WEBVIEW2_ENVIRONMENT_CREATED = 0x8000 + 100
_WM_WEBVIEW2_CONTROLLER_CREATED = 0x8000 + 101
_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = -2147417850
_HRESULT = ctypes.c_long
_STDMETHOD = ctypes.WINFUNCTYPE


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def _vtable_method(interface: int, index: int) -> int:
    vtable = ctypes.cast(
        interface,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    address = vtable[index]
    if not address:
        raise OSError(f"WebView2 COM method at vtable index {index} is missing")
    return int(address)


class WebView2Host:
    """Host WebView2 in an existing native window using the bundled helper DLL."""

    def __init__(self, status_callback: Callable[[str], None]) -> None:
        self._status_callback = status_callback
        self._base_directory = Path(__file__).resolve().parent.parent / "webview2" / "bin"
        self._loader: ctypes.WinDLL | None = None
        self._helper: ctypes.WinDLL | None = None
        self._environment = 0
        self._controller = 0
        self._webview = 0
        self._page_window = 0
        self._notify_window = 0
        self._pending_url = ""
        self._bounds = (0, 0, 0, 0)
        self._visible = False
        self._initialized = False
        self._com_initialized = False
        self._failed = False
        self._started_at = 0.0

    @property
    def ready(self) -> bool:
        return bool(self._webview)

    @property
    def failed(self) -> bool:
        return self._failed

    def initialize(
        self,
        page_window: int,
        initial_url: str,
        *,
        notify_window: int | None = None,
    ) -> None:
        if self._initialized:
            self.navigate(initial_url)
            return
        self._initialized = True
        self._started_at = time.monotonic()
        self._page_window = page_window
        self._notify_window = notify_window or page_window
        self._pending_url = initial_url

        result = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        if result == _RPC_E_CHANGED_MODE:
            raise RuntimeError("WebView2 requires the GUI thread to use COM apartment-threaded mode.")
        if result not in (_S_OK, _S_FALSE):
            raise OSError(result, "Could not initialize COM for WebView2.")
        self._com_initialized = True

        architecture = "x64" if struct.calcsize("P") == 8 else "x86"
        loader_path = self._base_directory / f"WebView2Loader_{architecture}.dll"
        helper_path = self._base_directory / f"WebView2Helper_{architecture}.dll"
        if not loader_path.is_file() or not helper_path.is_file():
            raise FileNotFoundError(
                f"WebView2 binaries for {architecture} are missing from {self._base_directory}."
            )

        self._loader = ctypes.WinDLL(str(loader_path))
        self._helper = ctypes.WinDLL(str(helper_path))
        self._configure_helper()

        user_data_directory = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        ) / "ManualTestCompanion" / "WebView2"
        user_data_directory.mkdir(parents=True, exist_ok=True)

        create_environment = self._loader.CreateCoreWebView2EnvironmentWithOptions
        create_environment.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        create_environment.restype = _HRESULT
        handler = self._helper.WV2Helper_CreateEnvironmentHandler(self._notify_window)
        if not handler:
            raise RuntimeError("The WebView2 environment callback could not be created.")
        result = create_environment("", str(user_data_directory), None, handler)
        if result < 0:
            raise OSError(result, "WebView2 environment creation could not be started.")
        self._status_callback("Starting the embedded Edge WebView2 runtime...")

    def handle_message(self, message: int, wparam: int) -> bool:
        if message == _WM_WEBVIEW2_ENVIRONMENT_CREATED:
            if self._environment:
                return True
            try:
                self._handle_environment_created(_HRESULT(wparam).value)
            except (OSError, RuntimeError) as error:
                self._fail(f"WebView2 setup failed: {error}")
            return True
        if message == _WM_WEBVIEW2_CONTROLLER_CREATED:
            if self._controller:
                return True
            try:
                self._handle_controller_created(_HRESULT(wparam).value)
            except (OSError, RuntimeError) as error:
                self._fail(f"WebView2 setup failed: {error}")
            return True
        return False

    def poll(self) -> None:
        if self._helper is None or self._failed or self.ready:
            return
        try:
            if not self._environment and self._helper.WV2Helper_GetEnvironment():
                self._handle_environment_created(_S_OK)
            if not self._controller and self._helper.WV2Helper_GetController():
                self._handle_controller_created(_S_OK)
        except (OSError, RuntimeError) as error:
            self._fail(f"WebView2 setup failed: {error}")
        if not self._failed and time.monotonic() - self._started_at > 15:
            self._fail("WebView2 initialization timed out.")

    def navigate(self, url: str) -> None:
        self._pending_url = url
        if self._webview:
            method = _STDMETHOD(_HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)(
                _vtable_method(self._webview, 5)
            )
            result = method(self._webview, url)
            if result < 0:
                raise OSError(result, f"WebView2 could not navigate to {url}.")
            self._status_callback(f"Opening {url}")

    def reload(self) -> None:
        if not self._webview:
            raise RuntimeError("The embedded browser is not ready yet.")
        method = _STDMETHOD(_HRESULT, ctypes.c_void_p)(
            _vtable_method(self._webview, 31)
        )
        result = method(self._webview)
        if result < 0:
            raise OSError(result, "WebView2 could not reload the current page.")

    def set_bounds(self, left: int, top: int, width: int, height: int) -> None:
        self._bounds = (left, top, width, height)
        if not self._controller:
            return
        self._apply_bounds()

    def _apply_bounds(self) -> None:
        assert self._controller
        left, top, width, height = self._bounds
        bounds = _Rect(left, top, left + max(0, width), top + max(0, height))
        method = _STDMETHOD(_HRESULT, ctypes.c_void_p, ctypes.POINTER(_Rect))(
            _vtable_method(self._controller, 6)
        )
        result = method(self._controller, ctypes.byref(bounds))
        if result < 0:
            raise OSError(result, "WebView2 could not update its bounds.")

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        if not self._controller:
            return
        method = _STDMETHOD(_HRESULT, ctypes.c_void_p, wintypes.BOOL)(
            _vtable_method(self._controller, 4)
        )
        result = method(self._controller, visible)
        if result < 0:
            raise OSError(result, "WebView2 visibility could not be updated.")

    def close(self) -> None:
        try:
            if self._controller:
                method = _STDMETHOD(_HRESULT, ctypes.c_void_p)(
                    _vtable_method(self._controller, 24)
                )
                result = method(self._controller)
                if result < 0:
                    self._status_callback(
                        f"WebView2 controller close failed (HRESULT 0x{-result:08X})."
                    )
        except OSError as error:
            self._status_callback(f"WebView2 controller close failed: {error}")
        finally:
            self._controller = 0
            if self._helper is not None:
                self._helper.WV2Helper_Cleanup()
                self._helper = None
            if self._com_initialized:
                ctypes.windll.ole32.CoUninitialize()
                self._com_initialized = False
            self._webview = 0
            self._environment = 0

    def _configure_helper(self) -> None:
        assert self._helper is not None
        self._helper.WV2Helper_Initialize.argtypes = [wintypes.HWND]
        self._helper.WV2Helper_Initialize.restype = wintypes.BOOL
        self._helper.WV2Helper_CreateEnvironmentHandler.argtypes = [wintypes.HWND]
        self._helper.WV2Helper_CreateEnvironmentHandler.restype = ctypes.c_void_p
        self._helper.WV2Helper_CreateControllerHandler.argtypes = [wintypes.HWND]
        self._helper.WV2Helper_CreateControllerHandler.restype = ctypes.c_void_p
        self._helper.WV2Helper_GetEnvironment.restype = ctypes.c_void_p
        self._helper.WV2Helper_GetController.restype = ctypes.c_void_p
        self._helper.WV2Helper_GetWebView2.restype = ctypes.c_void_p
        self._helper.WV2Helper_Cleanup.restype = None
        if not self._helper.WV2Helper_Initialize(self._notify_window):
            raise RuntimeError("The WebView2 callback helper could not be initialized.")

    def _handle_environment_created(self, result: int) -> None:
        if result < 0:
            self._fail(
                f"WebView2 runtime initialization failed (HRESULT 0x{-result:08X})."
            )
            return
        assert self._helper is not None
        self._environment = self._helper.WV2Helper_GetEnvironment()
        if not self._environment:
            self._fail("WebView2 did not return an environment interface.")
            return
        handler = self._helper.WV2Helper_CreateControllerHandler(self._notify_window)
        if not handler:
            self._fail("The WebView2 controller callback could not be created.")
            return
        method = _STDMETHOD(
            _HRESULT,
            ctypes.c_void_p,
            wintypes.HWND,
            ctypes.c_void_p,
        )(_vtable_method(self._environment, 3))
        result = method(self._environment, self._page_window, handler)
        if result < 0:
            self._fail(
                f"WebView2 controller creation could not be started (HRESULT 0x{-result:08X})."
            )

    def _handle_controller_created(self, result: int) -> None:
        if result < 0:
            self._fail(
                f"WebView2 controller creation failed (HRESULT 0x{-result:08X})."
            )
            return
        assert self._helper is not None
        self._controller = self._helper.WV2Helper_GetController()
        self._webview = self._helper.WV2Helper_GetWebView2()
        if not self._controller or not self._webview:
            self._controller = 0
            self._webview = 0
            self._fail("WebView2 did not return its controller and browser interfaces.")
            return
        self._apply_bounds()
        self.set_visible(self._visible)
        if self._pending_url:
            self.navigate(self._pending_url)
        self._status_callback("Embedded Edge WebView2 is ready.")

    def _fail(self, message: str) -> None:
        self._failed = True
        self._status_callback(message)
