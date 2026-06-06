from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

if TYPE_CHECKING:
    from types import ModuleType


def _load_check_wheel_webui_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_wheel_webui.py"
    spec = importlib.util.spec_from_file_location("check_wheel_webui", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_webui_wheel(
    tmp_path: Path,
    files: dict[str, str],
    *,
    include_typed_marker: bool = True,
    include_dist_info: bool = True,
) -> Path:
    wheel_path = tmp_path / "ahadiff-1.1.0-py3-none-any.whl"
    with ZipFile(wheel_path, "w") as wheel:
        if include_typed_marker:
            wheel.writestr("ahadiff/py.typed", "")
        for relative_name, text in files.items():
            wheel.writestr(f"ahadiff/_webui/{relative_name}", text)
        if include_dist_info:
            wheel.writestr(
                "ahadiff-1.1.0.dist-info/WHEEL",
                "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            wheel.writestr(
                "ahadiff-1.1.0.dist-info/METADATA",
                "Metadata-Version: 2.4\nName: ahadiff\nVersion: 1.1.0\n",
            )
            wheel.writestr("ahadiff-1.1.0.dist-info/RECORD", "")
    return wheel_path


def _index_html() -> str:
    return "\n".join(
        [
            '<link rel="stylesheet" href="/assets/index-abc123.css">',
            '<script type="module" src="/assets/main-abc123.js"></script>',
            '<script src="/registerSW.js"></script>',
        ]
    )


def _register_sw_js() -> str:
    return 'navigator.serviceWorker.register("/sw.js");'


def _sw_precache_js(*urls: str) -> str:
    entries = ",".join(f'{{url:"{url}",revision:"1"}}' for url in urls)
    return f"const precacheManifest=[{entries}];precacheAndRoute(precacheManifest);"


def _workbox_fixture_files(*precache_urls: str) -> dict[str, str]:
    return {
        "index.html": _index_html(),
        "registerSW.js": _register_sw_js(),
        "sw.js": _sw_precache_js(*precache_urls),
        "manifest.webmanifest": '{"icons":[{"src":"/icons/ahadiff-192.png"}]}',
        "favicon.svg": "<svg></svg>",
        "icons/ahadiff-192.png": "",
        "icons/ahadiff.svg": "<svg></svg>",
        "assets/index-abc123.css": "@font-face{src:url(./font-123.woff2)}",
        "assets/font-123.woff2": "",
        "assets/main-abc123.js": "export const ok = true;",
    }


def _complete_workbox_precache_urls() -> tuple[str, ...]:
    return (
        "/",
        "/registerSW.js",
        "/manifest.webmanifest",
        "/favicon.svg",
        "/icons/ahadiff-192.png",
        "/icons/ahadiff.svg",
        "/assets/index-abc123.css",
        "/assets/font-123.woff2",
        "/assets/main-abc123.js",
    )


def test_check_wheel_webui_fails_when_js_dynamic_import_chunk_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": '<script type="module" src="/assets/main-abc123.js"></script>',
            "assets/main-abc123.js": 'const route = () => import("./lazy-def456.js");',
        },
    )

    with pytest.raises(RuntimeError, match="assets/lazy-def456\\.js"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_precache_omits_existing_split_chunk(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": _index_html(),
            "registerSW.js": _register_sw_js(),
            "sw.js": _sw_precache_js(
                "/",
                "/assets/main-abc123.js",
                "/assets/index-abc123.css",
            ),
            "assets/index-abc123.css": ".app{color:#111}",
            "assets/main-abc123.js": (
                'const lazy = "./" + "lazy-def456.js";export const route = () => import(lazy);'
            ),
            "assets/lazy-def456.js": "export const ok = true;",
        },
    )

    with pytest.raises(RuntimeError, match="assets/lazy-def456\\.js"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_js_bundles_lack_complete_precache_manifest(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": _index_html(),
            "registerSW.js": _register_sw_js(),
            "sw.js": _sw_precache_js("/"),
            "assets/index-abc123.css": ".app{color:#111}",
            "assets/main-abc123.js": "export const ok = true;",
        },
    )

    with pytest.raises(RuntimeError, match="precache manifest"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_service_worker_registration_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": "\n".join(
                [
                    '<link rel="stylesheet" href="/assets/index-abc123.css">',
                    '<script type="module" src="/assets/main-abc123.js"></script>',
                ]
            ),
            "sw.js": _sw_precache_js(
                "/",
                "/assets/main-abc123.js",
                "/assets/index-abc123.css",
            ),
            "assets/index-abc123.css": ".app{color:#111}",
            "assets/main-abc123.js": "export const ok = true;",
        },
    )

    with pytest.raises(RuntimeError, match="registerSW\\.js"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_precache_urls_are_not_in_precache_call(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": _index_html(),
            "registerSW.js": _register_sw_js(),
            "sw.js": 'const fakePrecacheManifest=[{url:"/"},{url:"/assets/main-abc123.js"},'
            '{url:"/assets/index-abc123.css"}];precacheAndRoute([]);',
            "assets/index-abc123.css": ".app{color:#111}",
            "assets/main-abc123.js": "export const ok = true;",
        },
    )

    with pytest.raises(RuntimeError, match="precache manifest"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_accepts_complete_precache_manifest_for_split_chunks(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        {
            "index.html": _index_html(),
            "registerSW.js": _register_sw_js(),
            "sw.js": _sw_precache_js(
                "/",
                "/registerSW.js",
                "/assets/main-abc123.js",
                "/assets/index-abc123.css",
                "/assets/lazy-def456.js",
                "/assets/logo-123.png",
            ),
            "assets/index-abc123.css": ".app{background:url(./logo-123.png)}",
            "assets/logo-123.png": "",
            "assets/main-abc123.js": 'const route = () => import("./lazy-def456.js");',
            "assets/lazy-def456.js": "export const ok = true;",
        },
    )

    assert "referenced assets verified" in module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_html_srcset_asset_is_missing(tmp_path: Path) -> None:
    module = _load_check_wheel_webui_module()
    files = _workbox_fixture_files(*_complete_workbox_precache_urls())
    files["index.html"] = _index_html() + '<img srcset="/assets/missing-1x.png 1x">'
    wheel_path = _write_webui_wheel(
        tmp_path,
        files,
    )

    with pytest.raises(RuntimeError, match="assets/missing-1x\\.png"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_manifest_shortcut_icon_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    files = _workbox_fixture_files(*_complete_workbox_precache_urls())
    files["manifest.webmanifest"] = (
        '{"icons":[{"src":"/icons/ahadiff-192.png"}],'
        '"shortcuts":[{"icons":[{"src":"/icons/missing-shortcut.png"}]}],'
        '"screenshots":[{"src":"/icons/missing-screenshot.png"}]}'
    )
    wheel_path = _write_webui_wheel(tmp_path, files)

    with pytest.raises(RuntimeError, match="icons/missing-(shortcut|screenshot)\\.png"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_css_import_asset_is_missing(tmp_path: Path) -> None:
    module = _load_check_wheel_webui_module()
    files = _workbox_fixture_files(*_complete_workbox_precache_urls())
    files["assets/index-abc123.css"] = '@import "./missing.css";.app{color:#111}'
    wheel_path = _write_webui_wheel(tmp_path, files)

    with pytest.raises(RuntimeError, match="assets/missing\\.css"):
        module.check_wheel_webui(wheel_path)


@pytest.mark.parametrize(
    ("bad_reference", "expected"),
    [
        ("/assets/%2e%2e/missing.js", r"traversal"),
        ("/assets%5cmissing.js", r"backslash"),
    ],
)
def test_check_wheel_webui_fails_on_malformed_local_asset_references(
    tmp_path: Path,
    bad_reference: str,
    expected: str,
) -> None:
    module = _load_check_wheel_webui_module()
    files = _workbox_fixture_files(*_complete_workbox_precache_urls())
    files["index.html"] = _index_html() + f'<script type="module" src="{bad_reference}"></script>'
    wheel_path = _write_webui_wheel(tmp_path, files)

    with pytest.raises(RuntimeError, match=expected):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_wheel_metadata_is_missing(tmp_path: Path) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        _workbox_fixture_files(*_complete_workbox_precache_urls()),
        include_dist_info=False,
    )

    with pytest.raises(RuntimeError, match="dist-info"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_precache_omits_workbox_font(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    urls = tuple(
        url for url in _complete_workbox_precache_urls() if url != "/assets/font-123.woff2"
    )
    wheel_path = _write_webui_wheel(tmp_path, _workbox_fixture_files(*urls))

    with pytest.raises(RuntimeError, match="assets/font-123\\.woff2"):
        module.check_wheel_webui(wheel_path)


@pytest.mark.parametrize(
    ("missing_url", "expected_reference"),
    [
        ("/icons/ahadiff-192.png", r"icons/ahadiff-192\.png"),
        ("/icons/ahadiff.svg", r"icons/ahadiff\.svg"),
    ],
)
def test_check_wheel_webui_fails_when_precache_omits_workbox_icon(
    tmp_path: Path,
    missing_url: str,
    expected_reference: str,
) -> None:
    module = _load_check_wheel_webui_module()
    urls = tuple(url for url in _complete_workbox_precache_urls() if url != missing_url)
    wheel_path = _write_webui_wheel(tmp_path, _workbox_fixture_files(*urls))

    with pytest.raises(RuntimeError, match=expected_reference):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_precache_omits_workbox_webmanifest(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    urls = tuple(url for url in _complete_workbox_precache_urls() if url != "/manifest.webmanifest")
    wheel_path = _write_webui_wheel(tmp_path, _workbox_fixture_files(*urls))

    with pytest.raises(RuntimeError, match="manifest\\.webmanifest"):
        module.check_wheel_webui(wheel_path)


def test_check_wheel_webui_fails_when_wheel_omits_typed_marker(
    tmp_path: Path,
) -> None:
    module = _load_check_wheel_webui_module()
    wheel_path = _write_webui_wheel(
        tmp_path,
        _workbox_fixture_files(*_complete_workbox_precache_urls()),
        include_typed_marker=False,
    )

    with pytest.raises(RuntimeError, match="ahadiff/py\\.typed"):
        module.check_wheel_webui(wheel_path)
