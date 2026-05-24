from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.testclient import TestClient

import ahadiff.llm.provider as provider_module
from ahadiff.contracts.serve_demo import DemoQuizPreview
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def test_demo_learn_preview_is_public_without_token(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.get("/api/demo/learn-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["locale"] == "en"
    assert payload["sample_diff"]
    assert 1 <= len(payload["claims"]) <= 3
    assert payload["quiz"]["choices"][payload["quiz"]["answer_index"]]


def test_demo_learn_preview_is_deterministic_across_calls(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    first = client.get("/api/demo/learn-preview").json()
    second = client.get("/api/demo/learn-preview").json()

    assert first == second


def test_demo_learn_preview_uses_accept_language_locale(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.get(
        "/api/demo/learn-preview",
        headers={"accept-language": "zh-CN,zh;q=0.9,en;q=0.1"},
    )

    payload = response.json()
    assert payload["locale"] == "zh-CN"
    assert "什么情况下" in payload["quiz"]["question"]
    assert (
        payload["claims"][0]["text"]
        != client.get("/api/demo/learn-preview").json()["claims"][0]["text"]
    )


def test_demo_learn_preview_does_not_call_provider_path(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fail_make_provider(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("demo endpoint must not create a provider")

    def fail_generate(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("demo endpoint must not call provider.generate")

    monkeypatch.setattr(provider_module, "make_provider", fail_make_provider)
    monkeypatch.setattr(provider_module.ManagedProvider, "generate", fail_generate)
    client = _client(tmp_path / ".ahadiff")

    response = client.get("/api/demo/learn-preview")

    assert response.status_code == 200


def test_demo_learn_preview_does_not_create_state_dir(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.get("/api/demo/learn-preview")

    assert response.status_code == 200
    assert not state_dir.exists()


def test_demo_quiz_answer_index_must_reference_choice() -> None:
    DemoQuizPreview(question="Q?", choices=["A", "B"], answer_index=1)

    try:
        DemoQuizPreview(question="Q?", choices=["A", "B"], answer_index=2)
    except ValueError as exc:
        assert "answer_index" in str(exc)
    else:
        raise AssertionError("answer_index outside choices should be rejected")


def test_demo_route_is_registered_before_api_catchall(tmp_path: Path) -> None:
    app = create_app(ServeState(state_dir=tmp_path / ".ahadiff", token="test-token", locale="en"))
    paths = [getattr(route, "path", "") for route in app.routes]

    assert paths.index("/api/demo/learn-preview") < paths.index("/api/{rest_of_path:path}")


def test_demo_route_is_not_write_rate_limited(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")
    headers = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}

    for _ in range(12):
        response = client.post("/api/demo/learn-preview", json={}, headers=headers)
        assert response.status_code == 404
