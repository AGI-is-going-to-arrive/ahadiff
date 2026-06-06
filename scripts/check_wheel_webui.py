#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

WEBUI_PREFIX = "ahadiff/_webui/"
INDEX_NAME = f"{WEBUI_PREFIX}index.html"
TYPED_MARKER_NAME = "ahadiff/py.typed"
ASSET_CHUNK_SUFFIXES = (".css", ".js")
TRACKED_ROOT_FILES = {"manifest.json", "manifest.webmanifest", "site.webmanifest"}
TRACKED_ROOT_FILES.update({"registerSW.js", "sw.js"})
REQUIRED_PWA_ROOT_FILES = {"registerSW.js", "sw.js"}
WORKBOX_PRECACHE_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".png",
    ".svg",
    ".webmanifest",
    ".woff2",
}
LOCAL_ASSET_EXTENSIONS = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".otf",
    ".png",
    ".svg",
    ".ttf",
    ".txt",
    ".wasm",
    ".webmanifest",
    ".webp",
    ".woff",
    ".woff2",
}
LOCAL_REF_RE = re.compile(r"""(?P<quote>["'`])(?P<url>\.?/?[A-Za-z0-9._~/-]+)(?P=quote)""")
QUOTED_REF_RE = re.compile(
    r"""(?P<quote>["'`])"""
    r"""(?P<url>(?:\.?/|/)?"""
    r"""(?:assets/[^"'`\s)]+|icons/[^"'`\s)]+|workbox-[^"'`\s)]+\.js|favicon\.svg|"""
    r"""registerSW\.js|sw\.js|manifest(?:\.json|\.webmanifest)?|site\.webmanifest)"""
    r"""(?:[?#][^"'`]*)?)"""
    r"""(?P=quote)"""
)
CSS_URL_RE = re.compile(r"""url\(\s*(?P<quote>["']?)(?P<url>[^)"']+)(?P=quote)\s*\)""")
CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*)?(?P<quote>["']?)(?P<url>[^"')\s;]+)(?P=quote)\s*\)?"""
)
WORKBOX_DEFINE_RE = re.compile(r"""define\(\s*\[\s*(?P<quote>["'])(?P<name>\./workbox-[^"']+)""")
JS_QUOTED_LOCAL_REF_RE = re.compile(
    r"""(?P<quote>["'`])(?P<url>(?:\.{1,2}/|/|assets/|icons/)[^"'`\s)]+)(?P=quote)"""
)
NEW_URL_RE = re.compile(
    r"""new\s+URL\(\s*(?P<quote>["'`])(?P<url>[^"'`]+)(?P=quote)\s*,\s*import\.meta\.url\s*\)"""
)
PRECACHE_URL_RE = re.compile(r"""(?P<key>\burl)\s*:\s*(?P<quote>["'])(?P<url>[^"']+)(?P=quote)""")
PRECACHE_CALL_RE = re.compile(
    r"""\b(?:[A-Za-z_$][\w$]*\.)?precacheAndRoute\(\s*(?P<arg>[A-Za-z_$][\w$]*|\[)"""
)


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_attrs(attrs)

    def handle_startendtag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_attrs(attrs)

    def _scan_attrs(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in {"href", "src"}:
                reference = _normalize_webui_reference(value)
                if reference is not None:
                    self.references.add(reference)
            elif name == "srcset":
                for candidate in _srcset_urls(value):
                    reference = _normalize_webui_reference(candidate)
                    if reference is not None:
                        self.references.add(reference)


def _srcset_urls(value: str) -> set[str]:
    urls: set[str] = set()
    for candidate in value.split(","):
        parts = candidate.strip().split()
        if parts:
            urls.add(parts[0])
    return urls


def _normalize_webui_reference(value: str) -> str | None:
    raw_value = value.strip()
    if not raw_value or raw_value.startswith(("http:", "https:", "//", "data:", "blob:", "#")):
        return None

    path = unquote(urlsplit(raw_value).path)
    if not path:
        return None
    if "\\" in path:
        raise RuntimeError(f"malformed local WebUI reference contains backslash: {raw_value}")
    if any(part == ".." for part in path.split("/")):
        raise RuntimeError(f"malformed local WebUI reference contains traversal: {raw_value}")

    normalized = posixpath.normpath(path.removeprefix("./").removeprefix("/"))
    if normalized == "." or normalized.startswith("../") or normalized.startswith("/"):
        return None
    if "\\" in normalized:
        return None
    if (
        normalized.startswith(("assets/", "icons/"))
        or (normalized.startswith("workbox-") and normalized.endswith(".js"))
        or normalized in TRACKED_ROOT_FILES
        or normalized == "favicon.svg"
    ):
        return normalized
    return None


def _normalize_relative_reference(base_name: str, value: str) -> str | None:
    raw_value = value.strip()
    if raw_value.startswith(("http:", "https:", "//", "data:", "blob:", "#")):
        return None
    path = unquote(urlsplit(raw_value).path)
    if not path:
        return None
    if "\\" in path:
        raise RuntimeError(f"malformed local WebUI reference contains backslash: {raw_value}")
    if any(part == ".." for part in path.split("/")):
        raise RuntimeError(f"malformed local WebUI reference contains traversal: {raw_value}")
    base_dir = posixpath.dirname(base_name)
    return _normalize_webui_reference(posixpath.normpath(posixpath.join(base_dir, path)))


def _normalize_javascript_reference(js_name: str, value: str) -> str | None:
    raw_value = value.strip()
    if not _is_probable_local_asset_reference(raw_value):
        return None
    if raw_value.startswith(("/", "assets/", "icons/")):
        return _normalize_webui_reference(raw_value)
    return _normalize_relative_reference(js_name, raw_value)


def _normalize_precache_reference(value: str) -> str | None:
    raw_value = value.strip()
    if not raw_value or raw_value.startswith(("http:", "https:", "//", "data:", "blob:", "#")):
        return None

    path = unquote(urlsplit(raw_value).path)
    if path in {"", "/", "./"}:
        return "index.html"
    if "\\" in path:
        raise RuntimeError(f"malformed WebUI precache reference contains backslash: {raw_value}")
    if any(part == ".." for part in path.split("/")):
        raise RuntimeError(f"malformed WebUI precache reference contains traversal: {raw_value}")

    normalized = posixpath.normpath(path.removeprefix("./").removeprefix("/"))
    if normalized == ".":
        return "index.html"
    if normalized.startswith("../") or normalized.startswith("/") or "\\" in normalized:
        return None
    return normalized


def _is_probable_local_asset_reference(value: str) -> bool:
    path = unquote(urlsplit(value.strip()).path)
    if not path:
        return False
    normalized = posixpath.normpath(path.removeprefix("./").removeprefix("/"))
    if normalized in TRACKED_ROOT_FILES or normalized == "favicon.svg":
        return True
    suffix = Path(normalized).suffix.lower()
    return suffix in LOCAL_ASSET_EXTENSIONS


def _extract_references(text: str) -> set[str]:
    parser = _ReferenceParser()
    parser.feed(text)
    references = set(parser.references)
    for match in QUOTED_REF_RE.finditer(text):
        reference = _normalize_webui_reference(match.group("url"))
        if reference is not None:
            references.add(reference)
    return references


def _extract_css_references(css_name: str, text: str) -> set[str]:
    references: set[str] = set()
    for match in CSS_URL_RE.finditer(text):
        reference = _normalize_relative_reference(css_name, match.group("url"))
        if reference is not None:
            references.add(reference)
    for match in CSS_IMPORT_RE.finditer(text):
        reference = _normalize_relative_reference(css_name, match.group("url"))
        if reference is not None:
            references.add(reference)
    return references


def _extract_javascript_references(js_name: str, text: str) -> set[str]:
    references: set[str] = set()
    for match in JS_QUOTED_LOCAL_REF_RE.finditer(text):
        reference = _normalize_javascript_reference(js_name, match.group("url"))
        if reference is not None:
            references.add(reference)
    for match in NEW_URL_RE.finditer(text):
        reference = _normalize_javascript_reference(js_name, match.group("url"))
        if reference is not None:
            references.add(reference)
    return references


def _extract_manifest_references(text: str) -> set[str]:
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return set()
    if not isinstance(manifest, dict):
        return set()

    references: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            src = value.get("src")
            if isinstance(src, str):
                reference = _normalize_webui_reference(src)
                if reference is not None:
                    references.add(reference)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(manifest)
    return references


def _extract_precache_references(text: str) -> set[str]:
    precache_text = _precache_manifest_text(text)
    if precache_text is None:
        return set()
    references: set[str] = set()
    for match in PRECACHE_URL_RE.finditer(precache_text):
        reference = _normalize_precache_reference(match.group("url"))
        if reference is not None:
            references.add(reference)
    return references


def _precache_manifest_text(text: str) -> str | None:
    call = PRECACHE_CALL_RE.search(text)
    if call is None:
        return None
    arg = call.group("arg")
    if arg == "[":
        return _balanced_array_text(text, call.start("arg"))

    assignment_re = re.compile(rf"""\b(?:const|let|var)\s+{re.escape(arg)}\s*=\s*(?P<array>\[)""")
    assignments = list(assignment_re.finditer(text, 0, call.start()))
    if not assignments:
        return None
    return _balanced_array_text(text, assignments[-1].start("array"))


def _balanced_array_text(text: str, start: int) -> str | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_service_worker_references(text: str) -> tuple[set[str], set[str]]:
    references = _extract_references(text)
    precache_references = _extract_precache_references(text)
    references.update(precache_references)
    for match in LOCAL_REF_RE.finditer(text):
        reference = _normalize_webui_reference(match.group("url"))
        if reference is not None:
            references.add(reference)
    for match in WORKBOX_DEFINE_RE.finditer(text):
        workbox_name = match.group("name")
        if not workbox_name.endswith(".js"):
            workbox_name = f"{workbox_name}.js"
        reference = _normalize_webui_reference(workbox_name)
        if reference is not None:
            references.add(reference)
    return references, precache_references


def _has_complete_precache_manifest(
    precache_references: set[str],
    required_precache_references: set[str],
) -> bool:
    return required_precache_references.issubset(precache_references)


def _is_generated_service_worker_helper(reference: str) -> bool:
    return reference == "sw.js" or (reference.startswith("workbox-") and reference.endswith(".js"))


def _is_dotfile_build_artifact(reference: str) -> bool:
    return any(part.startswith(".") for part in reference.split("/"))


def _workbox_precache_references(names: set[str]) -> set[str]:
    references: set[str] = set()
    for name in names:
        if not name.startswith(WEBUI_PREFIX):
            continue
        reference = name.removeprefix(WEBUI_PREFIX)
        if (
            not reference
            or reference.endswith("/")
            or _is_dotfile_build_artifact(reference)
            or _is_generated_service_worker_helper(reference)
        ):
            continue
        if Path(reference).suffix.lower() in WORKBOX_PRECACHE_EXTENSIONS:
            references.add(reference)
    return references


def _webui_asset_chunks(names: set[str]) -> set[str]:
    return {
        name.removeprefix(WEBUI_PREFIX)
        for name in names
        if name.startswith(f"{WEBUI_PREFIX}assets/") and name.endswith(ASSET_CHUNK_SUFFIXES)
    }


def _format_webui_references(references: list[str]) -> str:
    return ", ".join(f"{WEBUI_PREFIX}{reference}" for reference in references)


def _read_webui_text(wheel: ZipFile, relative_name: str) -> str:
    return wheel.read(f"{WEBUI_PREFIX}{relative_name}").decode("utf-8", errors="replace")


def _has_complete_wheel_metadata(names: set[str]) -> bool:
    dist_info_dirs = {
        name.split("/", 1)[0]
        for name in names
        if name.startswith("ahadiff-") and ".dist-info/" in name
    }
    return any(
        f"{dist_info_dir}/WHEEL" in names
        and f"{dist_info_dir}/METADATA" in names
        and f"{dist_info_dir}/RECORD" in names
        for dist_info_dir in dist_info_dirs
    )


def check_wheel_webui(wheel_path: Path) -> str:
    try:
        with ZipFile(wheel_path) as wheel:
            names = set(wheel.namelist())
            if not _has_complete_wheel_metadata(names):
                raise RuntimeError(f"{wheel_path}: missing ahadiff .dist-info wheel metadata")
            if TYPED_MARKER_NAME not in names:
                raise RuntimeError(f"{wheel_path}: missing {TYPED_MARKER_NAME}")
            if INDEX_NAME not in names:
                raise RuntimeError(f"{wheel_path}: missing {INDEX_NAME}")

            present_asset_chunks = _webui_asset_chunks(names)
            index_text = _read_webui_text(wheel, "index.html")
            references = _extract_references(index_text)
            asset_bundles = {
                reference
                for reference in references
                if reference.startswith("assets/") and reference.endswith(ASSET_CHUNK_SUFFIXES)
            }
            if not asset_bundles:
                raise RuntimeError(
                    f"{wheel_path}: {INDEX_NAME} does not reference any assets/*.js or "
                    "assets/*.css bundle"
                )

            pwa_root_files = {
                reference
                for reference in {"registerSW.js", "sw.js"}
                if f"{WEBUI_PREFIX}{reference}" in names
            }
            pending = set(references)
            pending.update(pwa_root_files)
            scanned: set[str] = {"index.html"}
            precache_references: set[str] = set()
            while pending:
                reference = pending.pop()
                if reference in scanned or f"{WEBUI_PREFIX}{reference}" not in names:
                    continue
                scanned.add(reference)
                if reference == "registerSW.js":
                    pending.update(_extract_references(_read_webui_text(wheel, reference)))
                elif reference == "sw.js":
                    sw_text = _read_webui_text(wheel, reference)
                    if "self.__WB_MANIFEST" in sw_text:
                        raise RuntimeError(
                            f"{wheel_path}: sw.js contains unresolved self.__WB_MANIFEST"
                        )
                    sw_references, sw_precache_references = _extract_service_worker_references(
                        sw_text
                    )
                    precache_references.update(sw_precache_references)
                    pending.update(sw_references)
                elif reference in TRACKED_ROOT_FILES:
                    pending.update(_extract_manifest_references(_read_webui_text(wheel, reference)))
                elif reference.startswith("assets/") and reference.endswith(".js"):
                    js_references = _extract_javascript_references(
                        reference,
                        _read_webui_text(wheel, reference),
                    )
                    pending.update(js_references)
                elif reference.startswith("assets/") and reference.endswith(".css"):
                    css_text = _read_webui_text(wheel, reference)
                    pending.update(_extract_css_references(reference, css_text))
                references.update(pending)

            missing = sorted(
                reference for reference in references if f"{WEBUI_PREFIX}{reference}" not in names
            )
            if missing:
                missing_text = ", ".join(f"{WEBUI_PREFIX}{reference}" for reference in missing)
                raise RuntimeError(f"{wheel_path}: missing referenced WebUI assets: {missing_text}")

            missing_graph_chunks = sorted(
                reference
                for reference in present_asset_chunks
                if reference not in references and reference not in precache_references
            )
            if missing_graph_chunks:
                missing_text = _format_webui_references(missing_graph_chunks)
                raise RuntimeError(
                    f"{wheel_path}: WebUI asset chunks are present but not reachable from "
                    f"the static graph or service-worker precache manifest: {missing_text}"
                )

            missing_pwa_root_files = sorted(
                reference
                for reference in REQUIRED_PWA_ROOT_FILES
                if f"{WEBUI_PREFIX}{reference}" not in names
            )
            if missing_pwa_root_files:
                missing_text = _format_webui_references(missing_pwa_root_files)
                raise RuntimeError(
                    f"{wheel_path}: missing required WebUI service-worker root files: "
                    f"{missing_text}"
                )

            required_precache_references = _workbox_precache_references(names)
            has_js_chunks = any(reference.endswith(".js") for reference in present_asset_chunks)
            if (has_js_chunks or pwa_root_files) and not _has_complete_precache_manifest(
                precache_references,
                required_precache_references,
            ):
                missing_precache_references = sorted(
                    required_precache_references - precache_references
                )
                missing_text = _format_webui_references(missing_precache_references)
                raise RuntimeError(
                    f"{wheel_path}: complete service-worker precache manifest is required; "
                    f"missing WebUI entries: {missing_text}"
                )

            return (
                f"{wheel_path}: WebUI index.html and {len(references)} referenced assets verified"
            )
    except BadZipFile as exc:
        raise RuntimeError(f"{wheel_path}: not a valid wheel/zip file") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate packaged AhaDiff WebUI wheel assets.")
    parser.add_argument("wheels", nargs="+", type=Path)
    args = parser.parse_args(argv)

    failures: list[str] = []
    for wheel_path in args.wheels:
        if not wheel_path.is_file():
            failures.append(f"{wheel_path}: wheel file does not exist")
            continue
        try:
            print(check_wheel_webui(wheel_path))
        except RuntimeError as exc:
            failures.append(str(exc))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
