#!/usr/bin/env bash
set -u -o pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
viewer_dir="$repo_root/viewer"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

emit_json() {
  python3 - "$@" <<'PY'
import json
import sys
from pathlib import Path

mode = sys.argv[1]
viewer_dir = Path(sys.argv[2])

if mode == "missing_viewer":
    payload = {
        "benchmark": "bundle_size",
        "reason": "viewer_missing",
        "status": "skipped",
    }
elif mode == "missing_pnpm":
    payload = {
        "benchmark": "bundle_size",
        "reason": "pnpm_missing",
        "status": "skipped",
    }
else:
    build_exit = int(sys.argv[3])
    build_log = Path(sys.argv[4])
    log_text = build_log.read_text(encoding="utf-8", errors="replace")
    dist_dir = viewer_dir / "dist"
    if build_exit != 0:
        payload = {
            "benchmark": "bundle_size",
            "build_log_tail": log_text.splitlines()[-20:],
            "status": "error",
        }
    elif not dist_dir.is_dir():
        payload = {
            "benchmark": "bundle_size",
            "reason": "dist_missing_after_build",
            "status": "error",
        }
    else:
        files = sorted(path for path in dist_dir.rglob("*") if path.is_file())
        js_files = [
            {
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(viewer_dir)),
            }
            for path in files
            if path.suffix == ".js"
        ]
        payload = {
            "benchmark": "bundle_size",
            "build_log_tail": log_text.splitlines()[-20:],
            "dist_directory": str(dist_dir.relative_to(viewer_dir)),
            "dist_total_bytes": sum(path.stat().st_size for path in files),
            "js_files": js_files,
            "status": "ok",
            "viewer_directory": str(viewer_dir),
        }

print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

if [[ ! -d "$viewer_dir" ]]; then
  emit_json "missing_viewer" "$viewer_dir"
  exit 0
fi

if ! command -v pnpm >/dev/null 2>&1; then
  emit_json "missing_pnpm" "$viewer_dir"
  exit 0
fi

build_log="$tmp_dir/build.log"
(
  cd "$viewer_dir" && pnpm run build
) >"$build_log" 2>&1
build_exit=$?
emit_json "build" "$viewer_dir" "$build_exit" "$build_log"
exit 0
