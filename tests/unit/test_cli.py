from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import (
    DEFAULT_CONFIG,
    ResolvedSetting,
    write_config_data,
    write_default_config,
)

_RUNNER = CliRunner()


def _init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _write_repo_config(repo_root: Path) -> None:
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    write_default_config(state_dir / "config.toml")


def _write_challenge_enabled_config(repo_root: Path) -> None:
    config = {**DEFAULT_CONFIG, "challenge": {**DEFAULT_CONFIG["challenge"], "enabled": True}}
    write_config_data(repo_root / ".ahadiff" / "config.toml", config)


def _write_cli_qualifying_run(repo_root: Path, run_id: str) -> None:
    run_path = repo_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text(
        json.dumps({"overall": 88.5, "verdict": "pass"}),
        encoding="utf-8",
    )
    (run_path / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_ref": "HEAD~1..HEAD",
                "hunks": [
                    {
                        "file": "foo.py",
                        "new_start": 1,
                        "new_count": 1,
                        "claim_ids": ["claim-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(
        "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps({"claim_id": "claim-1", "status": "verified"}) + "\n",
        encoding="utf-8",
    )


def _repo_root(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_repo_config(repo_root)
    return repo_root


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider_class="ollama",
        model_name="local-model",
        base_url="http://127.0.0.1:11434",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
    )


def test_lazy_class_helpers_resolve_real_classes() -> None:
    assert inspect.isclass(cli_module._install_context_cls())  # pyright: ignore[reportPrivateUsage]
    assert inspect.isclass(cli_module._serve_state_cls())  # pyright: ignore[reportPrivateUsage]


def test_runtime_provider_uses_configured_generate_model_override(
    monkeypatch: Any,
) -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {"generate_model": "gpt-5.5"},
            "providers": {
                "gpt": {
                    "provider_class": "openai_responses",
                    "model_name": "provider-default",
                    "base_url": "http://127.0.0.1:8318",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                }
            },
        },
        resolved={
            "llm.generate_model": ResolvedSetting(
                key="llm.generate_model",
                value="gpt-5.5",
                source="repo:/tmp/repo/.ahadiff/config.toml",
            )
        },
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, _api_key, _target, _explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "gpt-5.5"


def test_runtime_provider_treats_single_configured_remote_as_explicit(
    monkeypatch: Any,
) -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {"generate_model": "gpt-5.5"},
            "providers": {
                "gpt55": {
                    "provider_class": "openai_responses",
                    "model_name": "gpt-5.5",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                }
            },
        },
        resolved={},
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, target, explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "gpt-5.5"
    assert api_key == "test-key"
    assert target == "remote"
    assert explicit is True


def test_runtime_provider_uses_role_models_with_single_configured_provider(
    monkeypatch: Any,
) -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {
                "generate_model": "learn-model",
                "judge_model": "judge-model",
            },
            "providers": {
                "gpt": {
                    "provider_class": "openai_responses",
                    "model_name": "provider-default",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                    "available_models": ("learn-model", "judge-model"),
                }
            },
        },
        resolved={
            "llm.generate_model": ResolvedSetting(
                key="llm.generate_model",
                value="learn-model",
                source="repo:/tmp/repo/.ahadiff/config.toml",
            ),
            "llm.judge_model": ResolvedSetting(
                key="llm.judge_model",
                value="judge-model",
                source="repo:/tmp/repo/.ahadiff/config.toml",
            ),
        },
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    generate_config, _, _, generate_explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )
    judge_config, _, _, judge_explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="LLM judge evaluation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
        role="judge",
    )

    assert generate_config.model_name == "learn-model"
    assert judge_config.model_name == "judge-model"
    assert generate_explicit is True
    assert judge_explicit is True


def test_runtime_provider_keeps_single_provider_model_for_default_llm_model() -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {"generate_model": "gpt-default-from-config-schema"},
            "providers": {
                "local": {
                    "provider_class": "openai",
                    "model_name": "provider-model",
                    "base_url": "http://127.0.0.1:8318",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                }
            },
        },
        resolved={
            "llm.generate_model": ResolvedSetting(
                key="llm.generate_model",
                value="gpt-default-from-config-schema",
                source="default",
            )
        },
    )

    provider_config, _, target, explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "provider-model"
    assert target == "local"
    assert explicit is False


def test_runtime_provider_uses_configured_generate_provider_with_multiple_remotes(
    monkeypatch: Any,
) -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {"generate_provider": "gpt", "generate_model": "gpt-5.5"},
            "providers": {
                "azure": {
                    "provider_class": "azure",
                    "model_name": "gpt-5.5-2026-04-24",
                    "base_url": "https://example.openai.azure.com/openai/deployments/gpt",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                },
                "gpt": {
                    "provider_class": "openai_responses",
                    "model_name": "gpt-5.5",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                },
            },
        },
        resolved={},
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, target, explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.provider_class == "openai_responses"
    assert provider_config.model_name == "gpt-5.5"
    assert api_key == "test-key"
    assert target == "remote"
    assert explicit is True


def test_improve_lang_is_passed_to_run_improve_loop(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root), "--lang", "zh-CN"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "zh-CN"


def test_improve_without_lang_still_runs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("AHADIFF_LANG", raising=False)
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "en"


def test_improve_uses_ahadiff_lang_when_lang_flag_is_omitted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("AHADIFF_LANG", "zh-CN")
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "zh-CN"


def test_improve_rejects_redacted_remote_before_provider_resolution(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    (repo_root / ".ahadiff" / "config.toml").write_text(
        'privacy_mode = "redacted_remote"\n',
        encoding="utf-8",
    )

    def fail_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        raise AssertionError("provider resolution should not run for redacted_remote improve")

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fail_resolve_runtime_provider)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "improve does not support redacted_remote privacy mode" in result.stderr


def test_verify_ci_rejects_finalized_event_from_different_run(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import json

    from ahadiff.contracts import ResultEvent
    from ahadiff.eval.results import finalized_artifact_digest
    from ahadiff.review.database import initialize_review_db, sync_result_event

    repo_root = _repo_root(tmp_path, monkeypatch)
    state_dir = repo_root / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    run_a = state_dir / "runs" / "run_a"
    run_b = state_dir / "runs" / "run_b"
    for run_path in (run_a, run_b):
        run_path.mkdir(parents=True)
        (run_path / "metadata.json").write_text(
            json.dumps({"run_id": run_path.name, "source_ref": "abc123"}) + "\n",
            encoding="utf-8",
        )
        (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    event_id = "018f0f52-91c0-7abc-8123-000000000777"
    artifact_count, checksum = finalized_artifact_digest(run_b)
    (run_b / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": "run_b",
                "event_id": event_id,
                "finalized_at": "2026-04-24T00:00:00Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        ResultEvent(
            event_id=event_id,
            run_id="run_a",
            event_type="learn",
            timestamp="2026-04-24T00:00:00Z",
            source_ref="abc123",
            base_ref=None,
            prompt_version="prompt123",
            eval_bundle_version="eval123",
            rubric_version="rubric-v1",
            overall=88.0,
            verdict="PASS",
            status="keep",
            weakest_dim="evidence",
            note_json=None,
        ),
    )

    result = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(repo_root)])

    assert result.exit_code == 1
    assert "finalized result event does not exist for run: run_b" in result.stderr


def test_non_git_state_dir_rejects_symlink(tmp_path: Path) -> None:
    import pytest

    from ahadiff.core.errors import InputError

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside-state"
    workspace.mkdir()
    outside.mkdir()
    try:
        (workspace / ".ahadiff").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(InputError, match="state dir must not be a symlink"):
        cli_module._state_dir_for_root(workspace, has_git_repo=False)  # pyright: ignore[reportPrivateUsage]


def test_challenge_build_cli_rejects_rebuild_of_active_challenge(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from ahadiff.challenge import ChallengeStage, read_state

    repo_root = _repo_root(tmp_path, monkeypatch)
    _write_challenge_enabled_config(repo_root)
    _write_cli_qualifying_run(repo_root, "good-run")

    first = _RUNNER.invoke(
        app(),
        [
            "challenge",
            "build",
            "good-run",
            "--challenge-id",
            "cli-rebuild",
            "--repo-root",
            str(repo_root),
        ],
    )
    assert first.exit_code == 0, first.stderr

    second = _RUNNER.invoke(
        app(),
        [
            "challenge",
            "build",
            "good-run",
            "--challenge-id",
            "cli-rebuild",
            "--repo-root",
            str(repo_root),
        ],
    )

    assert second.exit_code == 1
    assert "challenge rebuild is only allowed" in second.stderr
    assert read_state(repo_root / ".ahadiff", "cli-rebuild").stage is ChallengeStage.BUILD


def test_review_lang_is_resolved_inside_handler(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, str | None] = {}

    def fake_resolve_locale(**kwargs: str | None) -> str:
        captured.update(kwargs)
        return "en"

    monkeypatch.setattr(cli_module, "resolve_locale", fake_resolve_locale)

    result = _RUNNER.invoke(
        app(),
        ["review", "--repo-root", str(repo_root), "--lang", "en"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["cli_lang"] == "en"


def test_quiz_lang_is_resolved_inside_handler(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, str | None] = {}

    def fake_resolve_locale(**kwargs: str | None) -> str:
        captured.update(kwargs)
        return "zh-CN"

    def fake_load_quiz_questions(path: Path) -> list[Any]:
        del path
        return []

    monkeypatch.setattr(cli_module, "resolve_locale", fake_resolve_locale)
    monkeypatch.setattr(cli_module, "load_quiz_questions", fake_load_quiz_questions)

    result = _RUNNER.invoke(
        app(),
        ["quiz", "run-1", "--repo-root", str(repo_root), "--lang", "zh-CN"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["cli_lang"] == "zh-CN"


def test_cli_learn_passes_quiz_output_caps_to_generator(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    patch_path = repo_root / "sample.patch"
    patch_path.write_text(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    run_id = "run-cli-quiz-caps"
    run_path = repo_root / ".ahadiff" / "runs" / run_id
    captured: dict[str, object] = {}

    class _FakeLearnability:
        score = 0.8
        threshold = 0.3
        skip_lesson_quiz = False
        forced = False

        def as_metadata(self) -> dict[str, object]:
            return {"score": self.score, "threshold": self.threshold}

    capture = SimpleNamespace(
        run_id=run_id,
        state_dir=repo_root / ".ahadiff",
        persisted_patch_text=patch_path.read_text(encoding="utf-8"),
        metadata={"diff_stats": {"total_changed_lines": 10, "file_count": 1}},
        run_source=SimpleNamespace(
            source_kind="patch",
            source_ref=str(patch_path),
            capability_level=3,
            degraded_flags={},
        ),
        graphify_status=SimpleNamespace(has_graph=False, source_path=None),
    )

    def fake_capture_patch(**kwargs: object) -> object:
        del kwargs
        return capture

    def fake_write_input_artifacts(_capture: object) -> tuple[Path, Path]:
        run_path.mkdir(parents=True)
        written_patch = run_path / "patch.diff"
        metadata_path = run_path / "metadata.json"
        written_patch.write_text(patch_path.read_text(encoding="utf-8"), encoding="utf-8")
        metadata_path.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")
        return written_patch, metadata_path

    def fake_resolve_runtime_provider(
        **kwargs: object,
    ) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_extract_claims(**kwargs: object) -> tuple[Path, tuple[object, ...]]:
        output_path = Path(str(kwargs["output_path"]))
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path, ()

    def fake_write_verified_claims(output_path: Path, *_args: object, **_kwargs: object) -> None:
        output_path.write_text('{"claim_id":"claim-1","status":"verified"}\n', encoding="utf-8")

    def fake_generate_lessons(**kwargs: object) -> object:
        del kwargs
        lesson_dir = run_path / "lesson"
        lesson_dir.mkdir()
        full_path = lesson_dir / "lesson.full.md"
        hint_path = lesson_dir / "lesson.hint.md"
        compact_path = lesson_dir / "lesson.compact.md"
        full_path.write_text("full\n", encoding="utf-8")
        hint_path.write_text("hint\n", encoding="utf-8")
        compact_path.write_text("compact\n", encoding="utf-8")
        return SimpleNamespace(
            full_path=full_path,
            hint_path=hint_path,
            compact_path=compact_path,
        )

    def fake_generate_quiz(**kwargs: object) -> tuple[object, tuple[object, ...]]:
        captured.update(kwargs)
        quiz_dir = run_path / "quiz"
        quiz_dir.mkdir()
        quiz_path = quiz_dir / "quiz.jsonl"
        quiz_path.write_text("", encoding="utf-8")
        return SimpleNamespace(quiz_path=quiz_path, misconception_path=None), ()

    def fake_evaluate_run(_run_path: Path) -> object:
        return SimpleNamespace(verdict="PASS", overall=90.0)

    def fake_persist_evaluated_run(**kwargs: object) -> tuple[object, list[str]]:
        del kwargs
        return SimpleNamespace(event=SimpleNamespace(status="keep")), []

    def fake_assess_learnability(*_args: object, **_kwargs: object) -> _FakeLearnability:
        return _FakeLearnability()

    def fake_load_empty_records(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        return ()

    def fake_load_text_map(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def fake_verify_claim_candidates(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        return (SimpleNamespace(record=SimpleNamespace(status="verified")),)

    def fake_generate_cards_for_run(**_kwargs: object) -> None:
        return None

    def fake_append_concepts(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cli_module, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(cli_module, "write_input_artifacts", fake_write_input_artifacts)
    monkeypatch.setattr(cli_module, "assess_learnability", fake_assess_learnability)
    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "extract_claim_candidates_from_run", fake_extract_claims)
    monkeypatch.setattr(cli_module, "load_claim_candidates", fake_load_empty_records)
    monkeypatch.setattr(cli_module, "load_line_map_records", fake_load_empty_records)
    monkeypatch.setattr(cli_module, "load_symbol_records", fake_load_empty_records)
    monkeypatch.setattr(cli_module, "load_text_map", fake_load_text_map)
    monkeypatch.setattr(
        cli_module,
        "verify_claim_candidates",
        fake_verify_claim_candidates,
    )
    monkeypatch.setattr(cli_module, "write_verified_claims_jsonl", fake_write_verified_claims)
    monkeypatch.setattr(cli_module, "generate_lessons_from_run", fake_generate_lessons)
    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz)
    monkeypatch.setattr(cli_module, "evaluate_run", fake_evaluate_run)
    monkeypatch.setattr(cli_module, "generate_cards_for_run", fake_generate_cards_for_run)
    monkeypatch.setattr(cli_module, "_persist_evaluated_run", fake_persist_evaluated_run)
    monkeypatch.setattr(cli_module, "append_concepts", fake_append_concepts)

    result = _RUNNER.invoke(
        app(),
        ["learn", "--patch", str(patch_path), "--repo-root", str(repo_root), "--force-learn"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (result.exception, result.stdout, result.stderr)
    assert captured["quiz_output_token_cap"] == 18_000
    assert captured["misconception_output_token_cap"] == 6_000


# --- F2 regression: --api-key-env prefix validation ---


def test_api_key_env_rejects_unsafe_names() -> None:
    """validate_repo_api_key_env_name blocks non-AHADIFF_ prefixed env var names."""
    import pytest

    from ahadiff.core.config import validate_repo_api_key_env_name
    from ahadiff.core.errors import ConfigError

    with pytest.raises(ConfigError, match="AHADIFF_"):
        validate_repo_api_key_env_name("AWS_SECRET_ACCESS_KEY")
    with pytest.raises(ConfigError, match="AHADIFF_"):
        validate_repo_api_key_env_name("GITHUB_TOKEN")
    validate_repo_api_key_env_name("AHADIFF_PROVIDER_API_KEY")
    validate_repo_api_key_env_name("OPENAI_API_KEY")
