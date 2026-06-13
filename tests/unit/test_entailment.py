from __future__ import annotations

from ahadiff.claims import entailment
from ahadiff.claims.entailment import PredicateEvidence, analyze_claim_predicates
from ahadiff.contracts import SourceHunk


def _reasons(evidence: tuple[PredicateEvidence, ...]) -> list[str]:
    return [item.reason for item in evidence]


def _supported(evidence: tuple[PredicateEvidence, ...], predicate: str) -> list[PredicateEvidence]:
    return [
        item for item in evidence if item.predicate == predicate and item.outcome == "supported"
    ]


def test_kernel_returns_not_applicable_for_docs_only_binary_and_rename_without_hunks() -> None:
    docs = analyze_claim_predicates(
        "adds usage docs",
        [SourceHunk(file="docs/guide.md", start=1, end=1, side="new")],
        {},
        {"docs/guide.md": "# Guide\n"},
    )
    binary = analyze_claim_predicates(
        "updates image asset",
        [SourceHunk(file="assets/logo.png", start=1, end=1, side="new")],
        {},
        {"assets/logo.png": ""},
    )
    rename_only = analyze_claim_predicates(
        "renames process module without changing behavior",
        [],
        {"src/old_name.py": "def process():\n    return 1\n"},
        {"src/new_name.py": "def process():\n    return 1\n"},
    )

    assert _reasons(docs) == ["not_applicable:non_python_path"]
    assert _reasons(binary) == ["not_applicable:non_python_path"]
    assert _reasons(rename_only) == ["not_applicable:no_source_hunks"]
    assert all(item.outcome == "inconclusive" for item in (*docs, *binary, *rename_only))


def test_kernel_normalizes_lf_and_crlf_without_line_number_shift() -> None:
    evidence = analyze_claim_predicates(
        'adds return literal "done"',
        [SourceHunk(file="src/app.py", start=3, end=3, side="new")],
        {"src/app.py": "def status():\n    ready = True\n    return None\n"},
        {"src/app.py": 'def status():\r\n    ready = True\r\n    return "done"\r\n'},
    )

    supported = _supported(evidence, "return_literal_added")
    assert [(item.start, item.end, item.reason) for item in supported] == [
        (3, 3, 'return_literal_added:"done"')
    ]


def test_kernel_rejects_windows_drive_unc_and_backslash_paths() -> None:
    evidence = analyze_claim_predicates(
        "adds call validate_path",
        [
            SourceHunk(file="C:/repo/app.py", start=1, end=1, side="new"),
            SourceHunk(file="//server/share/app.py", start=1, end=1, side="new"),
            SourceHunk(file=r"src\app.py", start=1, end=1, side="new"),
        ],
        {},
        {
            "C:/repo/app.py": "validate_path()\n",
            "//server/share/app.py": "validate_path()\n",
            r"src\app.py": "validate_path()\n",
        },
    )

    assert _reasons(evidence) == [
        "not_applicable:unsafe_path",
        "not_applicable:unsafe_path",
        "not_applicable:unsafe_path",
    ]
    assert all(item.outcome == "inconclusive" for item in evidence)


def test_kernel_rejects_home_relative_and_oversized_paths_before_matching() -> None:
    long_path = f"src/{'a' * 509}.py"
    evidence = analyze_claim_predicates(
        'adds return literal "ok"',
        [
            SourceHunk(file="~/src/app.py", start=2, end=2, side="new"),
            SourceHunk(file=long_path, start=2, end=2, side="new"),
        ],
        {},
        {
            "~/src/app.py": 'def run():\n    return "ok"\n',
            long_path: 'def run():\n    return "ok"\n',
        },
    )

    assert _reasons(evidence) == ["not_applicable:unsafe_path", "not_applicable:unsafe_path"]
    assert all(item.outcome == "inconclusive" for item in evidence)


def test_kernel_casefolds_path_identity_without_collapsing_distinct_files_on_posix() -> None:
    exact_match = analyze_claim_predicates(
        'adds return literal "ok"',
        [SourceHunk(file="SRC/APP.PY", start=2, end=2, side="new")],
        {"SRC/APP.PY": "def run():\n    return None\n"},
        {"SRC/APP.PY": 'def run():\n    return "ok"\n'},
    )
    distinct_case = analyze_claim_predicates(
        'adds return literal "ok"',
        [SourceHunk(file="SRC/APP.PY", start=2, end=2, side="new")],
        {"src/app.py": "def run():\n    return None\n"},
        {"src/app.py": 'def run():\n    return "ok"\n'},
    )
    ambiguous_case = analyze_claim_predicates(
        'adds return literal "ok"',
        [SourceHunk(file="SRC/APP.PY", start=2, end=2, side="new")],
        {},
        {
            "src/App.py": 'def run():\n    return "wrong"\n',
            "src/app.py": 'def run():\n    return "ok"\n',
        },
    )

    assert _supported(exact_match, "return_literal_added")
    assert _reasons(distinct_case) == ["inconclusive:ambiguous_path_identity"]
    assert _reasons(ambiguous_case) == ["inconclusive:ambiguous_path_identity"]
    assert not _supported(distinct_case, "return_literal_added")


def test_kernel_marks_partial_syntax_inconclusive_not_contradicted() -> None:
    evidence = analyze_claim_predicates(
        'adds return literal "ok"',
        [SourceHunk(file="src/app.py", start=2, end=2, side="new")],
        {"src/app.py": "def run():\n    return None\n"},
        {"src/app.py": 'def run(:\n    return "ok"\n'},
    )

    assert _reasons(evidence) == ["partial_syntax"]
    assert evidence[0].predicate == "syntax"
    assert evidence[0].outcome == "inconclusive"


def test_kernel_scopes_decorators_nested_functions_and_comprehensions_to_changed_hunk() -> None:
    after_text = (
        "@register_route('/v1')\n"
        "def outer(items):\n"
        "    values = [normalize(item) for item in items]\n"
        "    def inner():\n"
        '        return "inner"\n'
        "    return values\n"
    )
    before_text = (
        "def outer(items):\n"
        "    values = [item for item in items]\n"
        "    def inner():\n"
        "        return None\n"
        "    return values\n"
    )

    decorator = analyze_claim_predicates(
        "adds call register_route",
        [SourceHunk(file="src/app.py", start=1, end=1, side="new")],
        {"src/app.py": before_text},
        {"src/app.py": after_text},
    )
    comprehension = analyze_claim_predicates(
        "adds call normalize",
        [SourceHunk(file="src/app.py", start=3, end=3, side="new")],
        {"src/app.py": before_text},
        {"src/app.py": after_text},
    )
    nested_return = analyze_claim_predicates(
        'adds return literal "inner"',
        [SourceHunk(file="src/app.py", start=5, end=5, side="new")],
        {"src/app.py": before_text},
        {"src/app.py": after_text},
    )

    assert [(item.start, item.reason) for item in _supported(decorator, "call_name_added")] == [
        (1, "call_name_added:register_route")
    ]
    assert [(item.start, item.reason) for item in _supported(comprehension, "call_name_added")] == [
        (3, "call_name_added:normalize")
    ]
    assert [
        (item.start, item.reason) for item in _supported(nested_return, "return_literal_added")
    ] == [(5, 'return_literal_added:"inner"')]


def test_kernel_handles_multi_hunk_claims_without_cross_hunk_entailment() -> None:
    evidence = analyze_claim_predicates(
        'adds import json and return literal "ok"',
        [
            SourceHunk(file="src/app.py", start=1, end=1, side="new"),
            SourceHunk(file="src/app.py", start=5, end=5, side="new"),
        ],
        {"src/app.py": "def run():\n    return None\n"},
        {"src/app.py": 'import json\n\n\ndef run():\n    return "ok"\n'},
    )

    supported = [
        (item.predicate, item.start, item.reason)
        for item in evidence
        if item.outcome == "supported"
    ]
    assert supported == [
        ("import_added", 1, "import_added:json"),
        ("return_literal_added", 5, 'return_literal_added:"ok"'),
    ]


def test_kernel_detects_added_return_literal_only_when_after_hunk_contains_literal() -> None:
    supported = analyze_claim_predicates(
        "adds return literal 42",
        [SourceHunk(file="src/app.py", start=2, end=2, side="new")],
        {"src/app.py": "def answer():\n    return 0\n"},
        {"src/app.py": "def answer():\n    return 42\n"},
    )
    outside_hunk = analyze_claim_predicates(
        "adds return literal 42",
        [SourceHunk(file="src/app.py", start=1, end=1, side="new")],
        {"src/app.py": "def answer():\n    return 0\n"},
        {"src/app.py": "def answer():\n    return 42\n"},
    )

    assert _supported(supported, "return_literal_added")
    assert _reasons(outside_hunk) == ["return_literal_added:not_found_in_hunk"]
    assert outside_hunk[0].outcome == "not_supported"


def test_kernel_detects_added_call_name_without_claiming_semantic_proof() -> None:
    evidence = analyze_claim_predicates(
        "adds call emit_metric",
        [SourceHunk(file="src/app.py", start=2, end=2, side="new")],
        {"src/app.py": "def run():\n    return None\n"},
        {"src/app.py": "def run():\n    emit_metric('ok')\n"},
    )

    assert [(item.outcome, item.reason, item.confidence) for item in evidence] == [
        ("supported", "call_name_added:emit_metric", 0.72)
    ]
    assert all("semantic" not in item.reason for item in evidence)


def test_kernel_detects_unicode_call_names_from_english_and_chinese_claims() -> None:
    before_text = "def run():\n    return None\n"
    after_text = "def run():\n    处理()\n"
    source_hunks = [SourceHunk(file="src/app.py", start=2, end=2, side="new")]

    english = analyze_claim_predicates(
        "adds call 处理",
        source_hunks,
        {"src/app.py": before_text},
        {"src/app.py": after_text},
    )
    chinese = analyze_claim_predicates(
        "新增调用 处理",
        source_hunks,
        {"src/app.py": before_text},
        {"src/app.py": after_text},
    )

    assert [(item.outcome, item.reason) for item in english] == [
        ("supported", "call_name_added:处理")
    ]
    assert [(item.outcome, item.reason) for item in chinese] == [
        ("supported", "call_name_added:处理")
    ]


def test_kernel_matches_call_names_case_sensitively() -> None:
    evidence = analyze_claim_predicates(
        "adds call foo",
        [SourceHunk(file="src/app.py", start=3, end=3, side="new")],
        {"src/app.py": "def run():\n    Foo()\n"},
        {"src/app.py": "def run():\n    Foo()\n    foo()\n"},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [
        ("supported", "call_name_added:foo")
    ]


def test_kernel_supports_added_call_when_same_name_existed_outside_hunk() -> None:
    evidence = analyze_claim_predicates(
        "adds call foo",
        [SourceHunk(file="src/app.py", start=5, end=5, side="new")],
        {"src/app.py": ("def existing():\n    foo()\n\ndef run():\n    return None\n")},
        {"src/app.py": ("def existing():\n    foo()\n\ndef run():\n    foo()\n")},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [
        ("supported", "call_name_added:foo")
    ]


def test_kernel_does_not_evaluate_added_predicates_against_old_side_hunks() -> None:
    evidence = analyze_claim_predicates(
        "adds call emit_metric",
        [SourceHunk(file="src/app.py", start=1, end=1, side="old")],
        {"src/app.py": "return None\n"},
        {"src/app.py": "emit_metric()\n"},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [
        ("inconclusive", "inconclusive:old_side_hunk_not_evaluable")
    ]
    assert not _supported(evidence, "call_name_added")


def test_kernel_does_not_support_unchanged_assignment_literal_at_same_position() -> None:
    evidence = analyze_claim_predicates(
        "changes assignment to 2",
        [SourceHunk(file="src/app.py", start=1, end=1, side="new")],
        {"src/app.py": "x = 2\nx = 1\n"},
        {"src/app.py": "x = 2\nx = 1\n"},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [
        ("not_supported", "assignment_literal_changed:not_found_in_hunk")
    ]
    assert not _supported(evidence, "assignment_literal_changed")


def test_kernel_treats_missing_before_text_as_inconclusive_not_empty_file() -> None:
    evidence = analyze_claim_predicates(
        'adds return literal "ok"',
        [SourceHunk(file="src/app.py", start=2, end=2, side="new")],
        {},
        {"src/app.py": 'def run():\n    return "ok"\n'},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [
        ("inconclusive", "inconclusive:missing_before_text")
    ]
    assert not _supported(evidence, "return_literal_added")


def test_kernel_treats_explicit_empty_before_text_as_new_file() -> None:
    evidence = analyze_claim_predicates(
        'adds import json and return literal "ok"',
        [SourceHunk(file="src/new_mod.py", start=1, end=5, side="new")],
        {"src/new_mod.py": ""},
        {"src/new_mod.py": 'import json\n\n\ndef run():\n    return "ok"\n'},
    )

    supported = {
        (item.predicate, item.outcome, item.reason)
        for item in evidence
        if item.outcome == "supported"
    }
    assert supported == {
        ("import_added", "supported", "import_added:json"),
        ("return_literal_added", "supported", 'return_literal_added:"ok"'),
    }


def test_kernel_supports_added_branch_when_other_branch_exists_elsewhere() -> None:
    evidence = analyze_claim_predicates(
        "adds if branch",
        [SourceHunk(file="src/app.py", start=3, end=4, side="new")],
        {"src/app.py": "if old:\n    pass\n"},
        {"src/app.py": "if old:\n    pass\nif new:\n    pass\n"},
    )

    assert [(item.outcome, item.reason) for item in evidence] == [("supported", "branch_added:if")]


def test_kernel_maps_internal_confidence_to_shadow_confidence_band() -> None:
    assert entailment.CONFIDENCE_LOW == "low"
    assert entailment.CONFIDENCE_MEDIUM == "medium"
    assert entailment.CONFIDENCE_MEDIUM_THRESHOLD == 0.5
    assert entailment.confidence_band(0.49) == "low"
    assert entailment.confidence_band(0.5) == "medium"
    assert entailment.confidence_band(0.72) == "medium"
