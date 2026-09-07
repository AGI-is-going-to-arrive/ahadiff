"""Native Windows handles for safe creation of a local SQLite database.

NtCreateFile opens each component relative to its verified parent handle. The
directory handles deny write/delete sharing until SQLite has opened and checked
the file; the file handle also denies deletion. No pathname-based create is used.

API contract: https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntcreatefile
"""

from __future__ import annotations

import ctypes
import importlib
import os
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_DIRECTORY_FILE = 0x1
_FILE_NON_DIRECTORY_FILE = 0x40
_FILE_SYNCHRONOUS_IO_NONALERT = 0x20
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_READ_DATA = 0x1  # FILE_LIST_DIRECTORY for directory handles.
_FILE_WRITE_DATA = 0x2
_FILE_READ_ATTRIBUTES = 0x80
_SYNCHRONIZE = 0x00100000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OBJ_CASE_INSENSITIVE = 0x40


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint16),
        ("maximum_length", ctypes.c_uint16),
        ("buffer", ctypes.c_void_p),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("root_directory", ctypes.c_void_p),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", ctypes.c_uint32),
        ("security_descriptor", ctypes.c_void_p),
        ("security_quality_of_service", ctypes.c_void_p),
    ]


class _IoStatusBlock(ctypes.Structure):
    # The first field is an NTSTATUS/pointer union; pointer-sized storage preserves
    # its layout on both 32-bit and 64-bit Windows.
    _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", ctypes.c_uint32 * 2),
        ("last_access_time", ctypes.c_uint32 * 2),
        ("last_write_time", ctypes.c_uint32 * 2),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


class _WindowsFileApi:
    def __init__(self) -> None:
        loader: Any = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise PermissionError("safe SQLite create requires native Windows handle support")
        windows_ctypes: Any = ctypes
        self._win_error: Callable[[int], OSError] = windows_ctypes.WinError
        self._get_last_error: Callable[[], int] = windows_ctypes.get_last_error
        kernel32 = loader("kernel32", use_last_error=True)
        ntdll = loader("ntdll", use_last_error=True)
        self._create: Any = ntdll.NtCreateFile
        self._create.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint32,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self._create.restype = ctypes.c_int32
        self._status_error: Any = ntdll.RtlNtStatusToDosError
        self._status_error.argtypes = [ctypes.c_int32]
        self._status_error.restype = ctypes.c_uint32
        self._information: Any = kernel32.GetFileInformationByHandle
        self._information.argtypes = [ctypes.c_void_p, ctypes.POINTER(_FileInformation)]
        self._information.restype = ctypes.c_int32
        self._close: Any = kernel32.CloseHandle
        self._close.argtypes = [ctypes.c_void_p]
        self._close.restype = ctypes.c_int32

    def open(
        self,
        name: str,
        *,
        parent: int | None,
        directory: bool,
        create: bool = False,
    ) -> int:
        length = len(name.encode("utf-16-le"))
        if length > 65532:
            raise PermissionError("SQLite path component is too long")
        buffer = ctypes.create_unicode_buffer(name, length // 2 + 1)
        unicode_name = _UnicodeString(
            length,
            length + 2,
            ctypes.cast(buffer, ctypes.c_void_p),
        )
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            parent,
            ctypes.pointer(unicode_name),
            _OBJ_CASE_INSENSITIVE,
            None,
            None,
        )
        handle = ctypes.c_void_p()
        io_status = _IoStatusBlock()
        access = _FILE_READ_ATTRIBUTES | _FILE_READ_DATA | _SYNCHRONIZE
        sharing = _FILE_SHARE_READ
        if not directory:
            access |= _FILE_WRITE_DATA
            sharing |= _FILE_SHARE_WRITE
        options = _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
        options |= _FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT
        status = int(
            self._create(
                ctypes.byref(handle),
                access,
                ctypes.byref(attributes),
                ctypes.byref(io_status),
                None,
                _FILE_ATTRIBUTE_NORMAL,
                sharing,
                _FILE_CREATE if create else _FILE_OPEN,
                options,
                None,
                0,
            )
        )
        if status < 0:
            code = int(self._status_error(status))
            raise self._win_error(code)
        if handle.value is None:
            raise PermissionError("Windows returned no SQLite path handle")
        try:
            self._validate(handle.value, directory=directory)
        except Exception:
            self.close(handle.value)
            raise
        return handle.value

    def _validate(self, handle: int, *, directory: bool) -> None:
        info = _FileInformation()
        if not self._information(handle, ctypes.byref(info)):
            raise self._win_error(self._get_last_error())
        if info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError("refusing to open NTFS reparse point in SQLite path")
        if bool(info.attributes & _FILE_ATTRIBUTE_DIRECTORY) != directory:
            raise PermissionError("SQLite path has an unexpected file type")
        if not info.volume_serial_number or not (info.file_index_high or info.file_index_low):
            raise PermissionError("SQLite path identity unavailable")
        if not directory and info.number_of_links != 1:
            raise PermissionError("refusing hardlinked SQLite path or unknown link count")

    def close(self, handle: int) -> None:
        self._close(handle)


@dataclass
class WindowsDirectoryGuard:
    """Keep verified directory handles alive through the SQLite pathname open."""

    _api: _WindowsFileApi
    _handles: list[int]

    def hold(self, handle: int) -> None:
        self._handles.append(handle)

    def close(self) -> None:
        while self._handles:
            self._api.close(self._handles.pop())


def create_windows_sqlite_file(path: Path) -> tuple[int, WindowsDirectoryGuard]:
    """Exclusively create a file relative to locked, non-reparse ancestors.

    If another creator wins, open the existing leaf under the same guards and
    apply the same regular-file, reparse and hardlink checks. The caller owns
    both the returned fd and directory guard.
    """
    api = _WindowsFileApi()
    absolute = PureWindowsPath(str(path.absolute()))
    if (
        not absolute.is_absolute()
        or len(absolute.drive) != 2
        or not absolute.drive[0].isalpha()
        or absolute.drive[1] != ":"
        or len(absolute.parts) < 2
        or any(
            part in {".", ".."}
            or part.rstrip(" .") != part
            or PureWindowsPath(part).is_reserved()
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            for part in absolute.parts[1:]
        )
    ):
        raise PermissionError("SQLite create requires an unambiguous local Windows path")
    guard = WindowsDirectoryGuard(api, [])
    file_handle: int | None = None
    try:
        parent = api.open(f"\\??\\{absolute.anchor}", parent=None, directory=True)
        guard.hold(parent)
        for part in absolute.parts[1:-1]:
            parent = api.open(part, parent=parent, directory=True)
            guard.hold(parent)
        try:
            file_handle = api.open(absolute.name, parent=parent, directory=False, create=True)
        except FileExistsError:
            file_handle = api.open(absolute.name, parent=parent, directory=False)
        # open_osfhandle transfers ownership to the fd; it does not reopen a path.
        msvcrt = importlib.import_module("msvcrt")
        open_osfhandle = cast("Callable[[int, int], int]", msvcrt.open_osfhandle)
        fd = open_osfhandle(file_handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
        file_handle = None
        return fd, guard
    except Exception:
        if file_handle is not None:
            api.close(file_handle)
        guard.close()
        raise
