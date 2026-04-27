from __future__ import annotations

_C_STYLE_ESCAPE_CHARS = frozenset({"\\", '"', "t", "n", "r", "a", "b", "f", "v"})


def normalize_diff_path_token(candidate: str, *, prefix: str = "") -> str | None:
    raw_value = candidate.strip()
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] == '"':
        value = _unquote_git_path(_normalize_quoted_diff_path_separators(raw_value[1:-1]))
    else:
        value = _normalize_diff_path_separators(raw_value)
    if value == "/dev/null":
        return None
    normalized_prefix = _normalize_diff_path_separators(prefix)
    if normalized_prefix and value.startswith(normalized_prefix):
        value = value.removeprefix(normalized_prefix)
    return _normalize_relative_diff_path(value)


def parse_diff_git_header_paths(line: str) -> tuple[str | None, str | None] | None:
    if not line.startswith("diff --git "):
        return None
    payload = line.removeprefix("diff --git ").strip()
    left, right = _split_git_header_tokens(payload)
    if left is None or right is None:
        return None
    return (
        normalize_diff_path_token(left, prefix="a/"),
        normalize_diff_path_token(right, prefix="b/"),
    )


def _unquote_git_path(value: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\" or index + 1 >= len(value):
            decoded.append(char)
            index += 1
            continue

        next_char = value[index + 1]
        if next_char in {"\\", '"'}:
            decoded.append(next_char)
            index += 2
            continue
        if next_char == "t":
            decoded.append("\t")
            index += 2
            continue
        if next_char == "n":
            decoded.append("\n")
            index += 2
            continue
        if next_char == "r":
            decoded.append("\r")
            index += 2
            continue
        if next_char == "a":
            decoded.append("\a")
            index += 2
            continue
        if next_char == "b":
            decoded.append("\b")
            index += 2
            continue
        if next_char == "f":
            decoded.append("\f")
            index += 2
            continue
        if next_char == "v":
            decoded.append("\v")
            index += 2
            continue
        if next_char in "01234567":
            octal = [next_char]
            index += 2
            while index < len(value) and len(octal) < 3 and value[index] in "01234567":
                octal.append(value[index])
                index += 1
            decoded.append(chr(int("".join(octal), 8)))
            continue

        decoded.append(next_char)
        index += 2
    return "".join(decoded)


def _split_git_header_tokens(payload: str) -> tuple[str | None, str | None]:
    left, offset = _consume_git_header_token(payload, 0)
    if left is None:
        return None, None
    while offset < len(payload) and payload[offset] == " ":
        offset += 1
    right, tail = _consume_git_header_token(payload, offset)
    if right is None:
        return None, None
    if tail != len(payload):
        return None, None
    return left, right


def _consume_git_header_token(payload: str, start: int) -> tuple[str | None, int]:
    if start >= len(payload):
        return None, start
    if payload[start] == '"':
        index = start + 1
        escaped = False
        while index < len(payload):
            char = payload[index]
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if char == '"':
                return payload[start : index + 1], index + 1
            index += 1
        return None, start

    end = start
    while end < len(payload) and payload[end] != " ":
        end += 1
    return payload[start:end], end


def _normalize_relative_diff_path(value: str) -> str | None:
    if value.startswith("/"):
        return None
    if _has_windows_drive_prefix(value):
        return None
    parts: list[str] = []
    for segment in value.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(segment)
    if not parts:
        return None
    return "/".join(parts)


def _normalize_diff_path_separators(value: str) -> str:
    return value.replace("\\", "/")


def _normalize_quoted_diff_path_separators(value: str) -> str:
    # Git subprocesses use core.quotePath=false, but patch files/stdin may still
    # contain quoted raw Windows paths. Detect those before C-style unquoting.
    if _looks_like_raw_windows_quoted_path(value):
        return _normalize_diff_path_separators(value)
    normalized: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            normalized.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            normalized.append("/")
            index += 1
            continue

        next_char = value[index + 1]
        if next_char in _C_STYLE_ESCAPE_CHARS:
            normalized.append(char)
            normalized.append(next_char)
            index += 2
            continue
        if next_char in "01234567":
            normalized.append(char)
            normalized.append(next_char)
            index += 2
            continue

        normalized.append("/")
        index += 1
    return "".join(normalized)


def _looks_like_raw_windows_quoted_path(value: str) -> bool:
    if "\\" not in value:
        return False
    if len(value) >= 2 and value[0] in {"a", "b"} and value[1] == "\\":
        return True
    if "/" in value:
        return False

    single_backslash_count = 0
    index = 0
    while index < len(value):
        if value[index] != "\\":
            index += 1
            continue
        if index + 1 >= len(value):
            return True
        next_char = value[index + 1]
        if next_char == "\\":
            index += 2
            continue
        single_backslash_count += 1
        if next_char in "01234567":
            index += 2
            octal_digits = 1
            while index < len(value) and octal_digits < 3 and value[index] in "01234567":
                index += 1
                octal_digits += 1
            continue
        if next_char not in _C_STYLE_ESCAPE_CHARS:
            return True
        if single_backslash_count >= 2:
            return True
        index += 2
        continue
    return False


def _has_windows_drive_prefix(value: str) -> bool:
    return len(value) >= 2 and value[0].isalpha() and value[1] == ":"


__all__ = ["normalize_diff_path_token", "parse_diff_git_header_paths"]
