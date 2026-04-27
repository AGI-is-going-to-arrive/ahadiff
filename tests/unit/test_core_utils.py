"""Tests for core.json_util and core.sqlite_util."""

from __future__ import annotations

import json
import sqlite3
from pathlib import PureWindowsPath
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import ahadiff.core.sqlite_util as sqlite_util_module
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.sqlite_util import reject_symlink_path, safe_sqlite_connect

if TYPE_CHECKING:
    from pathlib import Path


class TestSafeJsonLoads:
    def test_valid_json(self) -> None:
        assert safe_json_loads('{"x": 1}') == {"x": 1}

    def test_valid_json_list(self) -> None:
        assert safe_json_loads("[1, 2, 3]") == [1, 2, 3]

    def test_valid_json_string(self) -> None:
        assert safe_json_loads('"hello"') == "hello"

    def test_valid_json_bytes(self) -> None:
        assert safe_json_loads(b'{"x": 1}') == {"x": 1}

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"x": NaN}')

    def test_rejects_infinity(self) -> None:
        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"x": Infinity}')

    def test_rejects_negative_infinity(self) -> None:
        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"x": -Infinity}')

    def test_rejects_nested_nan(self) -> None:
        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"a": {"b": NaN}}')

    def test_rejects_overflow_float(self) -> None:
        with pytest.raises(ValueError, match="Non-finite JSON number"):
            safe_json_loads('{"x": 1e309}')

    def test_empty_string_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads("")

    def test_none_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            safe_json_loads(None)  # type: ignore[arg-type]

    def test_parse_constant_kwarg_stripped(self) -> None:
        def parse_constant(_constant: str) -> float:
            return 0.0

        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"x": NaN}', parse_constant=parse_constant)

    def test_cls_kwarg_stripped(self) -> None:
        class BadDecoder(json.JSONDecoder):
            def __init__(self, **kw: Any) -> None:
                kw.pop("parse_constant", None)
                super().__init__(**kw)

        with pytest.raises(ValueError, match="Disallowed JSON constant"):
            safe_json_loads('{"x": NaN}', cls=BadDecoder)

    def test_allows_object_hook(self) -> None:
        def object_hook(value: dict[str, int]) -> list[tuple[str, int]]:
            return sorted(value.items())

        result = safe_json_loads(
            '{"x": 1}',
            object_hook=object_hook,
        )
        assert result == [("x", 1)]


class TestSafeSqliteConnect:
    def test_creates_new_db(self, tmp_path: Path) -> None:
        db = tmp_path / "new.db"
        conn = safe_sqlite_connect(db)
        conn.execute("CREATE TABLE t(x)")
        conn.close()
        assert db.exists()

    def test_opens_existing_db(self, tmp_path: Path) -> None:
        db = tmp_path / "exist.db"
        conn = safe_sqlite_connect(db)
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.execute("INSERT INTO t VALUES(42)")
        conn.commit()
        conn.close()

        conn2 = safe_sqlite_connect(db)
        row = conn2.execute("SELECT x FROM t").fetchone()
        assert row is not None
        assert row[0] == 42
        conn2.close()

    def test_read_only_existing(self, tmp_path: Path) -> None:
        db = tmp_path / "ro.db"
        conn = safe_sqlite_connect(db)
        conn.execute("CREATE TABLE t(x)")
        conn.close()

        conn2 = safe_sqlite_connect(db, read_only=True)
        with pytest.raises(sqlite3.OperationalError):
            conn2.execute("CREATE TABLE t2(y)")
        conn2.close()

    def test_read_only_nonexistent(self, tmp_path: Path) -> None:
        db = tmp_path / "noexist.db"
        with pytest.raises(sqlite3.OperationalError):
            safe_sqlite_connect(db, read_only=True)

    def test_rejects_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / "real.db"
        real.touch()
        link = tmp_path / "link.db"
        link.symlink_to(real)
        with pytest.raises(PermissionError, match="symlink"):
            safe_sqlite_connect(link)

    def test_rejects_dangling_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.db"
        link = tmp_path / "dangling.db"
        link.symlink_to(target)
        with pytest.raises(PermissionError, match="symlink"):
            safe_sqlite_connect(link)

    def test_rejects_existing_db_swapped_to_symlink_during_connect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "victim.db"
        shadow = tmp_path / "shadow.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE t(x)")
        with sqlite3.connect(shadow) as connection:
            connection.execute("CREATE TABLE t(x)")
        original_connect = sqlite_util_module.sqlite3.connect
        swapped = False

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal swapped
            if database == str(db) and not swapped:
                swapped = True
                db.unlink()
                try:
                    db.symlink_to(shadow)
                except OSError as exc:
                    pytest.skip(f"symlink creation unavailable: {exc}")
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True

    def test_rejects_existing_db_rename_race_restored_before_verification(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "victim.db"
        backup = tmp_path / "victim-original.db"
        replacement = tmp_path / "replacement.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES('original')")
        with sqlite3.connect(replacement) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES('replacement')")
        original_connect = sqlite_util_module.sqlite3.connect
        swapped = False

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal swapped
            if database == str(db) and not swapped:
                swapped = True
                db.rename(backup)
                replacement.rename(db)
                connection = original_connect(database, *args, **kwargs)  # type: ignore[arg-type]
                db.rename(replacement)
                backup.rename(db)
                return connection
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True
        with sqlite3.connect(db) as connection:
            value = connection.execute("SELECT value FROM marker").fetchone()[0]
        assert value == "original"

    def test_rejects_rename_race_even_when_sidecar_state_changes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "victim.db"
        backup = tmp_path / "victim-original.db"
        replacement = tmp_path / "replacement.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES('original')")
        with sqlite3.connect(replacement) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES('replacement')")
        original_connect = sqlite_util_module.sqlite3.connect
        swapped = False

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal swapped
            if database == str(db) and not swapped:
                swapped = True
                db.rename(backup)
                replacement.rename(db)
                connection = original_connect(database, *args, **kwargs)  # type: ignore[arg-type]
                db.rename(replacement)
                backup.rename(db)
                db.with_name(f"{db.name}-wal").write_text("fake wal", encoding="utf-8")
                return connection
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        conn = safe_sqlite_connect(db)
        try:
            value = conn.execute("SELECT value FROM marker").fetchone()[0]
            assert value == "original"
        finally:
            conn.close()

        assert swapped is True
        with sqlite3.connect(db) as connection:
            restored_value = connection.execute("SELECT value FROM marker").fetchone()[0]
        assert restored_value == "original"

    def test_rejects_missing_db_created_as_symlink_during_connect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "new.db"
        shadow = tmp_path / "shadow.db"
        with sqlite3.connect(shadow) as connection:
            connection.execute("CREATE TABLE t(x)")
        original_connect = sqlite_util_module.sqlite3.connect
        swapped = False

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal swapped
            if database == str(db) and not swapped:
                swapped = True
                try:
                    db.symlink_to(shadow)
                except OSError as exc:
                    pytest.skip(f"symlink creation unavailable: {exc}")
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="symlink|changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True

    def test_unicode_path(self, tmp_path: Path) -> None:
        db = tmp_path / "数据库.db"
        conn = safe_sqlite_connect(db)
        conn.execute("CREATE TABLE t(x)")
        conn.close()
        assert db.exists()

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        d = tmp_path / "path with spaces"
        d.mkdir()
        db = d / "test.db"
        conn = safe_sqlite_connect(db)
        conn.execute("CREATE TABLE t(x)")
        conn.close()
        assert db.exists()

    def test_journal_mode(self, tmp_path: Path) -> None:
        db = tmp_path / "wal.db"
        conn = safe_sqlite_connect(db, journal_mode="WAL")
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert mode[0] == "wal"
        conn.close()

    def test_busy_timeout(self, tmp_path: Path) -> None:
        db = tmp_path / "busy.db"
        conn = safe_sqlite_connect(db, busy_timeout_ms=10000)
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()
        assert timeout is not None
        assert timeout[0] == 10000
        conn.close()

    def test_trusted_schema_disabled(self, tmp_path: Path) -> None:
        db = tmp_path / "trusted.db"
        conn = safe_sqlite_connect(db)
        trusted_schema = conn.execute("PRAGMA trusted_schema").fetchone()
        assert trusted_schema is not None
        assert trusted_schema[0] == 0
        conn.close()

    def test_memory_database_keeps_safe_pragmas(self) -> None:
        conn = safe_sqlite_connect(":memory:", busy_timeout_ms=1234)
        try:
            conn.execute("CREATE TABLE t(x)")
            assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
            assert conn.execute("PRAGMA trusted_schema").fetchone()[0] == 0
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        finally:
            conn.close()

    def test_empty_path_opens_sqlite_temp_database(self) -> None:
        conn = safe_sqlite_connect("")
        try:
            conn.execute("CREATE TABLE t(x)")
            assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
        finally:
            conn.close()

    def test_windows_read_only_uri_preserves_drive_letter(self) -> None:
        uri = sqlite_util_module._read_only_sqlite_uri(  # pyright: ignore[reportPrivateUsage]
            PureWindowsPath(r"C:\Users\alice\repo\.ahadiff\review.sqlite")
        )
        assert uri == "file:/C:/Users/alice/repo/.ahadiff/review.sqlite?mode=ro"

    def test_rejects_ntfs_reparse_point_on_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stat = SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400)

        def fake_lstat(_path: object) -> SimpleNamespace:
            return fake_stat

        monkeypatch.setattr(sqlite_util_module.os, "lstat", fake_lstat)
        monkeypatch.setattr(sqlite_util_module.sys, "platform", "win32")

        with pytest.raises(PermissionError, match="NTFS reparse point"):
            reject_symlink_path("C:/temp/review.sqlite")

    def test_row_factory(self, tmp_path: Path) -> None:
        db = tmp_path / "factory.db"
        conn = safe_sqlite_connect(db, row_factory=sqlite3.Row)
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.execute("INSERT INTO t VALUES(42)")
        conn.commit()
        row = conn.execute("SELECT x FROM t").fetchone()
        assert row["x"] == 42
        conn.close()

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        db = tmp_path / "fk.db"
        conn = safe_sqlite_connect(db, foreign_keys=True)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk is not None
        assert fk[0] == 1
        conn.close()

    def test_foreign_keys_disabled_by_default(self, tmp_path: Path) -> None:
        db = tmp_path / "nofk.db"
        conn = safe_sqlite_connect(db)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk is not None
        assert fk[0] == 0
        conn.close()

    def test_defensive_flag(self, tmp_path: Path) -> None:
        db = tmp_path / "def.db"
        conn = safe_sqlite_connect(db, defensive=True)
        conn.execute("CREATE TABLE t(x)")
        conn.close()

    def test_timeout_parameter(self, tmp_path: Path) -> None:
        db = tmp_path / "timeout.db"
        conn = safe_sqlite_connect(db, timeout=30.0)
        conn.execute("CREATE TABLE t(x)")
        conn.close()

    def test_negative_busy_timeout_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="busy_timeout_ms"):
            safe_sqlite_connect(tmp_path / "busy-negative.db", busy_timeout_ms=-1)

    def test_negative_timeout_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timeout must be >= 0"):
            safe_sqlite_connect(tmp_path / "timeout-negative.db", timeout=-1)

    def test_invalid_journal_mode_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="invalid journal_mode"):
            safe_sqlite_connect(tmp_path / "bad.db", journal_mode="WAL; DROP TABLE foo")

    def test_journal_mode_case_insensitive(self, tmp_path: Path) -> None:
        db = tmp_path / "lower.db"
        conn = safe_sqlite_connect(db, journal_mode="wal")
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert mode[0] == "wal"
        conn.close()

    def test_allows_wal_database_reopen_when_connect_recreates_sidecars(
        self,
        tmp_path: Path,
    ) -> None:
        db = tmp_path / "wal-reopen.db"
        with sqlite3.connect(db) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE t(x)")
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            sidecar = db.with_name(f"{db.name}{suffix}")
            sidecar.unlink(missing_ok=True)

        conn = safe_sqlite_connect(db)
        try:
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        finally:
            conn.close()

    def test_cleanup_on_pragma_failure(self, tmp_path: Path) -> None:
        db = tmp_path / "corrupt.db"
        db.write_bytes(b"not a sqlite database at all")
        with pytest.raises(sqlite3.DatabaseError):
            safe_sqlite_connect(db, journal_mode="WAL")

    def test_all_params_combined(self, tmp_path: Path) -> None:
        db = tmp_path / "combined.db"
        conn = safe_sqlite_connect(
            db,
            journal_mode="WAL",
            busy_timeout_ms=10000,
            timeout=10.0,
            row_factory=sqlite3.Row,
            foreign_keys=True,
            defensive=True,
        )
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.execute("INSERT INTO t VALUES(1)")
        conn.commit()
        row = conn.execute("SELECT x FROM t").fetchone()
        assert row["x"] == 1
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk["foreign_keys"] == 1
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        assert mode["journal_mode"] == "wal"
        conn.close()


class TestRejectSymlinkPath:
    def test_regular_file_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "regular.txt"
        f.touch()
        reject_symlink_path(f)

    def test_nonexistent_passes(self, tmp_path: Path) -> None:
        reject_symlink_path(tmp_path / "nonexistent")

    def test_symlink_rejected(self, tmp_path: Path) -> None:
        real = tmp_path / "real.txt"
        real.touch()
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        with pytest.raises(PermissionError, match="symlink"):
            reject_symlink_path(link)

    def test_directory_passes(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        reject_symlink_path(d)
