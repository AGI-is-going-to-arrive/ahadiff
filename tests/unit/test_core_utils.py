"""Tests for core.json_util and core.sqlite_util."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

import ahadiff.core.sqlite_util as sqlite_util_module
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.sqlite_util import reject_symlink_path, safe_sqlite_connect


def _read_write_target(path: Path) -> str:
    return sqlite_util_module._read_write_sqlite_uri(path)  # pyright: ignore[reportPrivateUsage]


def _is_existing_db_connect_target(database: Any, path: Path) -> bool:
    if database == _read_write_target(path):
        return True
    return (
        isinstance(database, str)
        and database.startswith("file:/proc/self/fd/")
        and database.endswith("?mode=rw")
    )


class TestSafeJsonLoads:
    def test_valid_json(self) -> None:
        assert safe_json_loads('{"x": 1}') == {"x": 1}

    def test_valid_json_list(self) -> None:
        assert safe_json_loads("[1, 2, 3]") == [1, 2, 3]

    def test_valid_json_string(self) -> None:
        assert safe_json_loads('"hello"') == "hello"

    def test_valid_json_bytes(self) -> None:
        assert safe_json_loads(b'{"x": 1}') == {"x": 1}

    def test_rejects_oversized_string_input(self) -> None:
        with pytest.raises(ValueError, match="JSON input too large"):
            safe_json_loads('"abcdef"', max_input_bytes=4)

    def test_rejects_oversized_bytes_input(self) -> None:
        with pytest.raises(ValueError, match="JSON input too large"):
            safe_json_loads(b'"abcdef"', max_input_bytes=4)

    def test_normal_sized_string_input_parses_with_size_check(self) -> None:
        assert safe_json_loads('{"x": "ok"}', max_input_bytes=32) == {"x": "ok"}

    def test_normal_sized_bytes_input_parses_with_size_check(self) -> None:
        assert safe_json_loads(b'{"x": "ok"}', max_input_bytes=32) == {"x": "ok"}

    def test_custom_max_input_bytes_accepts_exact_limit(self) -> None:
        payload = '{"x": 1}'
        assert safe_json_loads(payload, max_input_bytes=len(payload.encode("utf-8"))) == {"x": 1}
        with pytest.raises(ValueError, match="JSON input too large"):
            safe_json_loads(payload, max_input_bytes=len(payload.encode("utf-8")) - 1)

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
    @pytest.mark.parametrize("persistent_churn", [False, True])
    def test_windows_parent_metadata_churn_closes_before_full_revalidation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        persistent_churn: bool,
    ) -> None:
        db = tmp_path / "windows-parent-churn.db"
        original_connect = sqlite_util_module.sqlite3.connect
        initial = original_connect(db)
        try:
            initial.execute("CREATE TABLE marker(value TEXT)")
            initial.execute("INSERT INTO marker VALUES('original')")
            initial.commit()
        finally:
            initial.close()
        original_prepare = sqlite_util_module._prepare_open_verification  # pyright: ignore[reportPrivateUsage]
        original_parent_state = sqlite_util_module._parent_directory_state  # pyright: ignore[reportPrivateUsage]
        attempts: list[sqlite3.Connection] = []
        preparations = 0
        directory_revision = 0

        def prepare_after_close(path: Path, *, create_missing: bool = False) -> Any:
            nonlocal preparations
            for previous in attempts:
                with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                    previous.execute("SELECT 1")
            preparations += 1
            return original_prepare(path, create_missing=create_missing)

        def parent_state(path: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
            identity, token = original_parent_state(path)
            assert token is not None
            return identity, (token[0] + directory_revision, token[1] + directory_revision)

        def interleaved_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal directory_revision
            connection = original_connect(database, *args, **kwargs)
            attempts.append(connection)
            if persistent_churn or len(attempts) == 1:
                # A journal can be created and removed between the two snapshots:
                # the parent token changes, while file/sidecar identities match.
                directory_revision += 1
            return connection

        def no_fd_path(_fd: int | None) -> Path | None:
            return None

        monkeypatch.setattr(sqlite_util_module.sys, "platform", "win32")
        monkeypatch.setattr(sqlite_util_module, "_sqlite_proc_fd_path", no_fd_path)
        monkeypatch.setattr(sqlite_util_module, "_prepare_open_verification", prepare_after_close)
        monkeypatch.setattr(sqlite_util_module, "_parent_directory_state", parent_state)
        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", interleaved_connect)

        if persistent_churn:
            with pytest.raises(PermissionError, match="database path changed during open"):
                safe_sqlite_connect(db)
            expected_attempts = sqlite_util_module._OPEN_VERIFICATION_RETRIES  # pyright: ignore[reportPrivateUsage]
        else:
            connection = safe_sqlite_connect(db)
            try:
                assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
            finally:
                connection.close()
            expected_attempts = 2

        assert len(attempts) == preparations == expected_attempts
        for previous in attempts:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                previous.execute("SELECT 1")

    def test_windows_retry_rechecks_ancestors_before_reopening(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ancestor = tmp_path / "ancestor"
        parent = ancestor / "child"
        parent.mkdir(parents=True)
        db = parent / "review.sqlite"
        db.write_bytes(b"")
        original_connect = sqlite_util_module.sqlite3.connect
        original_lstat = sqlite_util_module.os.lstat
        original_parent_state = sqlite_util_module._parent_directory_state  # pyright: ignore[reportPrivateUsage]
        attempts: list[sqlite3.Connection] = []
        ancestor_checks = 0
        unsafe_ancestor = False

        def reparse_after_connect(path: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal ancestor_checks
            result = original_lstat(path, *args, **kwargs)
            if Path(path) == ancestor:
                ancestor_checks += 1
                if unsafe_ancestor:
                    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                        attempts[0].execute("SELECT 1")
                    return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result

        def parent_state(path: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
            identity, token = original_parent_state(path)
            assert token is not None
            offset = int(unsafe_ancestor)
            return identity, (token[0] + offset, token[1] + offset)

        def interleaved_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal unsafe_ancestor
            connection = original_connect(database, *args, **kwargs)
            attempts.append(connection)
            unsafe_ancestor = True
            return connection

        def no_fd_path(_fd: int | None) -> Path | None:
            return None

        monkeypatch.setattr(sqlite_util_module.sys, "platform", "win32")
        monkeypatch.setattr(sqlite_util_module, "_sqlite_proc_fd_path", no_fd_path)
        monkeypatch.setattr(sqlite_util_module.os, "lstat", reparse_after_connect)
        monkeypatch.setattr(sqlite_util_module, "_parent_directory_state", parent_state)
        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", interleaved_connect)

        with pytest.raises(PermissionError, match="NTFS reparse point"):
            safe_sqlite_connect(db)

        assert ancestor_checks == 2
        assert len(attempts) == 1

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows path opens remain fail-closed")
    def test_concurrent_commit_during_open_discards_ambiguous_connection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "concurrent.db"
        original_connect = sqlite_util_module.sqlite3.connect
        initial = original_connect(db)
        try:
            initial.execute("CREATE TABLE marker(value INTEGER)")
            initial.execute("INSERT INTO marker VALUES(1)")
            initial.commit()
        finally:
            initial.close()
        opened = threading.Barrier(2)
        committed = threading.Barrier(2)
        attempts: list[sqlite3.Connection] = []

        def write_while_opening() -> None:
            opened.wait(timeout=5)
            writer = original_connect(db)
            try:
                writer.execute("INSERT INTO marker VALUES(2)")
                writer.commit()
            finally:
                writer.close()
                committed.wait(timeout=5)

        def interleaved_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = original_connect(database, *args, **kwargs)
            if _is_existing_db_connect_target(database, db):
                attempts.append(connection)
                if len(attempts) == 1:
                    opened.wait(timeout=5)
                    committed.wait(timeout=5)
            return connection

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", interleaved_connect)
        with ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(write_while_opening)
            connection = safe_sqlite_connect(db)
            writer.result(timeout=5)
        try:
            assert connection.execute("SELECT value FROM marker ORDER BY value").fetchall() == [
                (1,),
                (2,),
            ]
            assert len(attempts) == 2
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                attempts[0].execute("SELECT 1")
        finally:
            connection.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows path opens remain fail-closed")
    def test_persistent_same_inode_commit_churn_exhausts_verification(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "busy.db"
        original_connect = sqlite_util_module.sqlite3.connect
        initial = original_connect(db)
        try:
            initial.execute("CREATE TABLE marker(value INTEGER)")
            initial.execute("INSERT INTO marker VALUES(0)")
            initial.commit()
        finally:
            initial.close()
        attempts: list[sqlite3.Connection] = []

        def churning_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = original_connect(database, *args, **kwargs)
            attempts.append(connection)
            writer = original_connect(db)
            try:
                writer.execute("UPDATE marker SET value = value + 1")
                writer.commit()
            finally:
                writer.close()
            return connection

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", churning_connect)
        with pytest.raises(PermissionError, match="database path changed during open"):
            safe_sqlite_connect(db)

        assert len(attempts) == sqlite_util_module._OPEN_VERIFICATION_RETRIES  # pyright: ignore[reportPrivateUsage]
        for connection in attempts:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX rename semantics")
    def test_one_time_rename_restore_discards_connection_to_substituted_database(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db, replacement, backup = (tmp_path / name for name in ("db", "replacement", "backup"))
        original_connect = sqlite_util_module.sqlite3.connect
        for path, marker in ((db, "original"), (replacement, "substituted")):
            initial = original_connect(path)
            try:
                initial.execute("CREATE TABLE marker(value TEXT)")
                initial.execute("INSERT INTO marker VALUES(?)", (marker,))
                initial.commit()
            finally:
                initial.close()
        attempts: list[sqlite3.Connection] = []

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            if not attempts:
                db.rename(backup)
                replacement.rename(db)
                connection = original_connect(database, *args, **kwargs)
                db.rename(replacement)
                backup.rename(db)
            else:
                connection = original_connect(database, *args, **kwargs)
            attempts.append(connection)
            return connection

        def no_fd_path(_fd: int | None) -> Path | None:
            return None

        # Exercise the POSIX pathname fallback even on hosts with /proc/self/fd.
        monkeypatch.setattr(sqlite_util_module, "_sqlite_proc_fd_path", no_fd_path)
        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)
        connection = safe_sqlite_connect(db)
        try:
            assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
            assert len(attempts) == 2
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                attempts[0].execute("SELECT value FROM marker")
        finally:
            connection.close()
        untouched = original_connect(replacement)
        try:
            assert untouched.execute("SELECT value FROM marker").fetchone() == ("substituted",)
        finally:
            untouched.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX rename semantics")
    def test_identity_replacement_is_rejected_before_sidecar_retry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "db"
        replacement = tmp_path / "replacement"
        backup = tmp_path / "backup"
        original_connect = sqlite_util_module.sqlite3.connect
        for path in (db, replacement):
            initial = original_connect(path)
            initial.execute("CREATE TABLE marker(value INTEGER)")
            initial.close()
        replacement_bytes = replacement.read_bytes()
        attempts: list[sqlite3.Connection] = []

        def replacing_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = original_connect(database, *args, **kwargs)
            attempts.append(connection)
            if len(attempts) == 1:
                db.rename(backup)
                replacement.rename(db)
                db.with_name(f"{db.name}-wal").write_bytes(b"sidecar churn")
            return connection

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", replacing_connect)
        with pytest.raises(PermissionError, match="database path changed during open"):
            safe_sqlite_connect(db)

        assert len(attempts) == 1
        assert db.read_bytes() == replacement_bytes
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            attempts[0].execute("SELECT 1")

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

    def test_rejects_new_db_under_symlinked_parent(self, tmp_path: Path) -> None:
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir()
        link_parent = tmp_path / "link-parent"
        try:
            link_parent.symlink_to(real_parent, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(PermissionError, match="symlink"):
            safe_sqlite_connect(link_parent / "new.db")

    def test_rejects_existing_db_under_symlinked_parent(self, tmp_path: Path) -> None:
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir()
        db = real_parent / "existing.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE t(x)")
        link_parent = tmp_path / "link-parent"
        try:
            link_parent.symlink_to(real_parent, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(PermissionError, match="symlink"):
            safe_sqlite_connect(link_parent / "existing.db")

    def test_allows_macos_var_alias_system_path(self) -> None:
        if sys.platform != "darwin":
            pytest.skip("macOS alias behavior only applies on Darwin")

        with tempfile.TemporaryDirectory(prefix="ahadiff-sqlite-alias-") as temp_dir:
            temp_root = Path(temp_dir)
            if str(temp_root).startswith("/private/var/"):
                alias_root = Path("/var") / temp_root.relative_to("/private/var")
            elif str(temp_root).startswith("/var/"):
                alias_root = temp_root
            else:
                pytest.skip(f"temporary directory is outside macOS /var alias space: {temp_root}")

            db = alias_root / "alias.db"
            conn = safe_sqlite_connect(db)
            conn.execute("CREATE TABLE t(x INTEGER)")
            conn.execute("INSERT INTO t VALUES(1)")
            conn.commit()
            conn.close()

            with safe_sqlite_connect(db, read_only=True) as ro_conn:
                row = ro_conn.execute("SELECT x FROM t").fetchone()
            assert row is not None
            assert row[0] == 1

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX unlink of an open file")
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
            if _is_existing_db_connect_target(database, db) and not swapped:
                swapped = True
                db.unlink()
                try:
                    db.symlink_to(shadow)
                except OSError as exc:
                    pytest.skip(f"symlink creation unavailable: {exc}")
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="symlink|changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX rename of an open file")
    def test_rejects_persistent_existing_db_rename_race_restored_before_verification(
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
            if _is_existing_db_connect_target(database, db):
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

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX rename of an open file")
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
            if _is_existing_db_connect_target(database, db) and not swapped:
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

        if sys.platform.startswith("linux"):
            with pytest.raises(PermissionError, match="changed during open"):
                safe_sqlite_connect(db)
        else:
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

    def test_allows_unrelated_parent_directory_churn_when_target_file_is_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "stable.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES('original')")
        original_connect = sqlite_util_module.sqlite3.connect
        connect_target = _read_write_target(db)
        churned = False

        def churning_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal churned
            connection = original_connect(database, *args, **kwargs)  # type: ignore[arg-type]
            if database == connect_target and not churned:
                churned = True
                sibling = db.with_name("sibling.tmp")
                sibling.write_text("noise", encoding="utf-8")
                sibling.unlink()
            return connection

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", churning_connect)

        conn = safe_sqlite_connect(db)
        try:
            value = conn.execute("SELECT value FROM marker").fetchone()[0]
            assert value == "original"
        finally:
            conn.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX unlink of an open file")
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
            if _is_existing_db_connect_target(database, db) and not swapped:
                swapped = True
                db.unlink()
                try:
                    db.symlink_to(shadow)
                except OSError as exc:
                    pytest.skip(f"symlink creation unavailable: {exc}")
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="symlink|changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows directory handles prevent rename")
    def test_new_db_parent_swap_to_symlink_does_not_create_outside_target(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        parent_backup = tmp_path / "parent-backup"
        outside = tmp_path / "outside"
        outside.mkdir()
        db = parent / "race.db"
        outside_target = outside / "race.db"
        original_connect = sqlite_util_module.sqlite3.connect
        swapped = False

        def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal swapped
            if _is_existing_db_connect_target(database, db) and not swapped:
                swapped = True
                parent.rename(parent_backup)
                try:
                    parent.symlink_to(outside, target_is_directory=True)
                except OSError as exc:
                    parent_backup.rename(parent)
                    pytest.skip(f"symlink creation unavailable: {exc}")
            return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite_util_module.sqlite3, "connect", swapping_connect)

        with pytest.raises(PermissionError, match="changed during open"):
            safe_sqlite_connect(db)

        assert swapped is True
        assert not outside_target.exists()

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


def test_unit_default_config_io_stays_in_isolated_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate_user_global_config: Path
) -> None:
    from ahadiff.core import config as config_module
    from ahadiff.core import paths as paths_module
    from ahadiff.core import registry as registry_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    global_path = isolate_user_global_config / "config.toml"
    expected_reads = {workspace / ".ahadiff" / "config.toml", global_path}
    checked_reads: list[Path] = []
    original_read = config_module._read_toml  # pyright: ignore[reportPrivateUsage]

    def checked_read(path: Path) -> dict[str, Any]:
        assert path in expected_reads, "unit config reads must never reach the user directory"
        checked_reads.append(path)
        return original_read(path)

    monkeypatch.setattr(config_module, "_read_toml", checked_read)
    assert paths_module.global_config_dir() == isolate_user_global_config
    assert config_module.global_config_dir() == isolate_user_global_config
    assert registry_module.global_config_dir() == isolate_user_global_config
    config_module.write_config_data(global_path, {"quiz": {"quiz_question_count": 7}})
    snapshot = config_module.load_workspace_config(workspace)
    assert snapshot.global_config_path == global_path
    assert snapshot.values["quiz"]["quiz_question_count"] == 7
    assert global_path in checked_reads
    assert (isolate_user_global_config / ".global.lock").is_file()
    registry_module.save_registry([])
    assert registry_module.load_registry() == []
    assert (isolate_user_global_config / "registry.json").is_file()


def test_unit_isolation_preserves_path_overrides_and_worker_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate_user_global_config: Path
) -> None:
    from ahadiff.core import paths as paths_module

    explicit_home = tmp_path / "explicit-home"
    assert paths_module.global_config_dir(platform="darwin", env={"HOME": str(explicit_home)}) == (
        explicit_home / "Library" / "Application Support" / "ahadiff"
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(paths_module.usage_db_path).result() == (
            isolate_user_global_config / "usage.sqlite"
        )

    override = tmp_path / "custom-global"

    def custom_global_config_dir(**kwargs: object) -> Path:
        return override

    monkeypatch.setattr(paths_module, "global_config_dir", custom_global_config_dir)
    assert paths_module.usage_db_path() == override / "usage.sqlite"
