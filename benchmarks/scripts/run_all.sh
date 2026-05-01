#!/usr/bin/env bash
set -u -o pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
results_dir="$repo_root/benchmarks/results"
output_path="$results_dir/baseline_20260428.json"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$results_dir"

resolve_benchmark_python() {
  if [[ -n "${AHADIFF_BENCH_PYTHON:-}" ]]; then
    printf '%s\n' "$AHADIFF_BENCH_PYTHON"
    return
  fi

  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    printf '%s\n' "$repo_root/.venv/bin/python"
    return
  fi

  if [[ -x "$repo_root/.venv/Scripts/python.exe" ]]; then
    printf '%s\n' "$repo_root/.venv/Scripts/python.exe"
    return
  fi
}

benchmark_python=$(resolve_benchmark_python)

if [[ -z "$benchmark_python" || ! -x "$benchmark_python" ]]; then
  cat >"$output_path" <<'JSON'
{
  "benchmark_runner": {
    "error_type": "MissingBenchmarkPython",
    "message": "Set AHADIFF_BENCH_PYTHON to a valid Python executable or create .venv/bin/python.",
    "status": "error"
  }
}
JSON
  cat "$output_path"
  exit 2
fi

python_shim_dir="$tmp_dir/python-shim"
mkdir -p "$python_shim_dir"
cat >"$python_shim_dir/python3" <<'SH'
#!/usr/bin/env bash
exec "${AHADIFF_BENCH_PYTHON:?}" "$@"
SH
chmod +x "$python_shim_dir/python3"

write_fallback_json() {
  local benchmark_name="$1"
  local stdout_path="$2"
  local stderr_path="$3"
  local reason="$4"
  local returncode="$5"
  local raw_stdout_path="${stdout_path}.raw"
  if [[ -f "$stdout_path" ]]; then
    mv "$stdout_path" "$raw_stdout_path"
  else
    : >"$raw_stdout_path"
  fi
  "$benchmark_python" - "$benchmark_name" "$raw_stdout_path" "$stderr_path" "$reason" "$returncode" >"$stdout_path" <<'PY'
import json
import sys
from pathlib import Path

benchmark_name = sys.argv[1]
stdout_path = Path(sys.argv[2])
stderr_path = Path(sys.argv[3])
reason = sys.argv[4]
returncode = int(sys.argv[5])

payload = {
    "benchmark": benchmark_name,
    "reason": reason,
    "returncode": returncode,
    "status": "error",
    "stdout": stdout_path.read_text(encoding="utf-8", errors="replace"),
    "stderr": stderr_path.read_text(encoding="utf-8", errors="replace"),
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

validate_json() {
  local output_file="$1"
  "$benchmark_python" - "$output_file" <<'PY'
import json
import sys
from pathlib import Path

json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
}

run_benchmark() {
  local benchmark_name="$1"
  local output_file="$2"
  shift 2
  local stderr_file="${output_file}.stderr"
  local returncode=0
  if AHADIFF_BENCH_PYTHON="$benchmark_python" PATH="$python_shim_dir:${PATH:-}" "$@" >"$output_file" 2>"$stderr_file"; then
    if ! validate_json "$output_file" >/dev/null 2>&1; then
      write_fallback_json "$benchmark_name" "$output_file" "$stderr_file" "invalid_json" 0
    fi
  else
    returncode=$?
    write_fallback_json "$benchmark_name" "$output_file" "$stderr_file" "nonzero_exit" "$returncode"
  fi
}

run_benchmark "cli_startup" "$tmp_dir/cli_startup.json" \
  "$benchmark_python" "$script_dir/bench_cli_startup.py"
run_benchmark "api_latency" "$tmp_dir/api_latency.json" \
  "$benchmark_python" "$script_dir/bench_api_latency.py"
run_benchmark "sqlite_queries" "$tmp_dir/sqlite_queries.json" \
  "$benchmark_python" "$script_dir/bench_sqlite_queries.py"
run_benchmark "diff_parse" "$tmp_dir/diff_parse.json" \
  "$benchmark_python" "$script_dir/bench_diff_parse.py"
run_benchmark "bundle_size" "$tmp_dir/bundle_size.json" \
  bash "$script_dir/bench_bundle_size.sh"
run_benchmark "graphify" "$tmp_dir/graphify.json" \
  "$benchmark_python" "$script_dir/bench_graphify.py"
# Run graphify perf gate (separate script with assert thresholds)
# Gate failure is recorded but does not block aggregate JSON output
graphify_gate="$repo_root/benchmarks/graphify/bench_graphify.py"
graphify_gate_status="skip"
if [ -f "$graphify_gate" ]; then
  echo "Running graphify perf gate..."
  if "$benchmark_python" "$graphify_gate" > /dev/null 2>&1; then
    graphify_gate_status="pass"
  else
    graphify_gate_status="fail"
    echo "WARNING: graphify perf gate exceeded thresholds"
  fi
fi

"$benchmark_python" - "$tmp_dir" "$output_path" "$graphify_gate_status" <<'PY'
import json
import sys
from pathlib import Path

tmp_dir = Path(sys.argv[1])
output_path = Path(sys.argv[2])
graphify_gate_status = sys.argv[3] if len(sys.argv) > 3 else "skip"


def load_payload(name: str) -> object:
    path = tmp_dir / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "benchmark": name,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "status": "error",
        }


payload = {
    "cli_startup": load_payload("cli_startup"),
    "api_latency": load_payload("api_latency"),
    "sqlite_queries": load_payload("sqlite_queries"),
    "diff_parse": load_payload("diff_parse"),
    "bundle_size": load_payload("bundle_size"),
    "graphify": load_payload("graphify"),
    "graphify_perf_gate": graphify_gate_status,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ "$graphify_gate_status" == "fail" ]]; then
  echo "graphify perf gate failed" >&2
  exit 1
fi
