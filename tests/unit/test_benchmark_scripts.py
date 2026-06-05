from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ALL_SCRIPT = REPO_ROOT / "benchmarks" / "scripts" / "run_all.sh"
BASELINE_PATH = REPO_ROOT / "benchmarks" / "results" / "baseline_20260428.json"
GRAPHIFY_BENCH_SCRIPT = REPO_ROOT / "benchmarks" / "scripts" / "bench_graphify.py"
SERVE_READ_BENCH_SCRIPT = REPO_ROOT / "benchmarks" / "scripts" / "bench_serve_read_routes.py"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
BENCHMARK_MANIFEST = REPO_ROOT / "benchmarks" / "manifest.json"
GRAPH_PRESENT_FIXTURE = (
    REPO_ROOT
    / "benchmarks"
    / "fixtures"
    / "integration"
    / "pinned_011_graph_present"
    / "graph.json"
)


def _load_graphify_bench_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ahadiff_bench_graphify", GRAPHIFY_BENCH_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_serve_read_bench_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ahadiff_bench_serve_read_routes",
        SERVE_READ_BENCH_SCRIPT,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_all_uses_configured_project_python(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/usr/bin/env bash\nexit 17\n", encoding="utf-8")
    fake_python.chmod(0o755)
    fake_mktemp = fake_bin / "mktemp"
    fake_mktemp.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'tmpdir="${TMPDIR:-/tmp}"',
                "if command -v cygpath >/dev/null 2>&1; then",
                '  tmpdir="$(cygpath -u "$tmpdir" 2>/dev/null || printf "%s" "$tmpdir")"',
                "fi",
                'exec /usr/bin/mktemp "$@" "$tmpdir/bench-tmp.XXXXXX"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_mktemp.chmod(0o755)

    original_output = BASELINE_PATH.read_text(encoding="utf-8") if BASELINE_PATH.exists() else None

    env = os.environ.copy()
    env["AHADIFF_BENCH_PYTHON"] = sys.executable
    env["TMPDIR"] = str(tmp_path)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    try:
        completed = subprocess.run(
            ["bash", str(RUN_ALL_SCRIPT)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=360,
            env=env,
        )

        assert completed.returncode == 0
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        assert payload["cli_startup"]["status"] == "ok"
        assert payload["diff_parse"]["status"] == "ok"
        assert payload["sqlite_queries"]["status"] == "ok"
        assert payload["graphify"]["status"] == "ok"
        assert payload["graphify"]["fixture"] == "large_graph.json"
    finally:
        if original_output is None:
            BASELINE_PATH.unlink(missing_ok=True)
        else:
            BASELINE_PATH.write_text(original_output, encoding="utf-8")


def test_graphify_benchmark_reports_token_reduction_metric() -> None:
    module = _load_graphify_bench_module()

    result = module.bench_token_reduction(module.LARGE_FIXTURE_GRAPH)

    assert result["operation"] == "graph_context_token_reduction"
    assert result["raw_estimated_tokens"] > result["sliced_estimated_tokens"]
    assert 0.0 < result["token_reduction_ratio"] <= 1.0


def test_run_all_treats_graphify_perf_gate_as_release_blocking() -> None:
    script = RUN_ALL_SCRIPT.read_text(encoding="utf-8")

    assert "graphify perf gate failed" in script
    assert '[[ "$graphify_gate_status" == "fail" ]]' in script


def test_run_all_treats_serve_read_route_gate_as_release_blocking() -> None:
    script = RUN_ALL_SCRIPT.read_text(encoding="utf-8")

    assert "serve read-route perf gate failed" in script
    assert (
        '[[ "$serve_read_gate_status" == "fail" || "$serve_read_gate_status" == "error" ]]'
        in script
    )


def test_serve_read_route_benchmark_fails_http_errors() -> None:
    module = _load_serve_read_bench_module()

    class FakeResponse:
        status_code = 500
        content = b'{"error":"boom"}'

    class FakeClient:
        def get(self, path: str, headers: dict[str, str]) -> FakeResponse:
            _ = (path, headers)
            return FakeResponse()

    result = module._measure_route(  # pyright: ignore[reportPrivateUsage]
        cast("Any", FakeClient()),
        "GET /api/runs",
        "/api/runs",
        False,
    )

    assert result["status"] == "fail"
    assert "http_status_500" in result["validation_errors"]


def test_release_workflow_runs_graphify_perf_gate() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "benchmarks/graphify/bench_graphify.py" in workflow


def test_graph_present_fixture_is_manifested_and_parseable() -> None:
    from ahadiff.graphify import parse_graph_json

    raw_manifest: object = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw_manifest, dict)
    manifest = cast("dict[str, object]", raw_manifest)
    raw_entries = manifest["entries"]
    assert isinstance(raw_entries, list)
    raw_entry_items = cast("list[object]", raw_entries)
    graph_entry: dict[str, object] | None = None
    for raw_entry in raw_entry_items:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast("dict[str, object]", raw_entry)
        if entry.get("id") == "pinned_011_graph_present":
            graph_entry = entry
            break
    assert graph_entry is not None
    assert graph_entry["path"] == "fixtures/integration/pinned_011_graph_present"
    assert graph_entry["kind"] == "integration"
    tags = graph_entry["tags"]
    assert isinstance(tags, list)
    assert "graph-present" in tags

    graph = parse_graph_json(GRAPH_PRESENT_FIXTURE)

    assert len(graph.nodes) == 15
    assert len(graph.links) == 17
    assert len(graph.hyperedges) == 2
    assert any(node.metadata.get("community") == 1 for node in graph.nodes)
    assert any(edge.metadata.get("confidence") == "EXTRACTED" for edge in graph.links)
