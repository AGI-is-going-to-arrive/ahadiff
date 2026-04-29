from __future__ import annotations

import pytest

from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import (
    SYMBOLS_SCHEMA,
    SYMBOLS_SCHEMA_VERSION,
    extract_symbols,
    serialize_symbols_payload,
)
from ahadiff.git.tree_sitter_runtime import TreeSitterExtractionResult, TreeSitterSymbolCandidate


def test_extract_symbols_prefers_python_ast_over_section_header() -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1,2 @@ def retry_with_backoff(max_retries=3):\n"
        "-    return 1\n"
        "+    result = 1\n"
        "+    return result\n"
    )
    after_text = "def retry_with_backoff(max_retries=3):\n    result = 1\n    return result\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/app.py": after_text},
    )

    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.qualified_name == "retry_with_backoff"
    assert symbol.kind == "function"
    assert symbol.extractor == "python_ast"
    assert symbol.confidence == "high"


def test_extract_symbols_falls_back_to_regex_when_python_ast_fails() -> None:
    patch = (
        "diff --git a/src/broken.py b/src/broken.py\n"
        "--- a/src/broken.py\n"
        "+++ b/src/broken.py\n"
        "@@ -1 +1,2 @@ def broken(\n"
        "-def broken(old):\n"
        "+def broken(\n"
        "+    return 1\n"
    )
    after_text = "def broken(\n    return 1\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/broken.py": after_text},
    )

    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.qualified_name == "broken"
    assert symbol.extractor == "regex"
    assert symbol.confidence == "medium"
    assert symbol.error is not None
    assert "SyntaxError" in symbol.error
    assert symbol.range.end == 2


def test_extract_symbols_regex_fallback_finds_export_const_arrow_fn_for_body_only_change() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -2 +2 @@\n"
        "-  return oldValue;\n"
        "+  return nextValue;\n"
    )
    after_text = "export const renderCard = () => {\n  return nextValue;\n};\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.qualified_name == "renderCard"
    assert symbol.kind == "function"
    assert symbol.extractor == "regex"
    assert symbol.confidence == "medium"


def test_extract_symbols_handles_deleted_and_renamed_files() -> None:
    deleted_patch = (
        "diff --git a/src/old.py b/src/old.py\n"
        "deleted file mode 100644\n"
        "--- a/src/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@ def legacy_api():\n"
        "-def legacy_api():\n"
        "-    return 1\n"
    )
    renamed_patch = (
        "diff --git a/src/old_name.py b/src/new_name.py\n"
        "similarity index 100%\n"
        "rename from src/old_name.py\n"
        "rename to src/new_name.py\n"
        "@@ -1,2 +1,2 @@ def old_name():\n"
        "-def old_name():\n"
        "+def new_name():\n"
        "     return 1\n"
    )

    deleted_symbols = extract_symbols(
        parse_unified_diff(deleted_patch),
        before_text_by_path={"src/old.py": "def legacy_api():\n    return 1\n"},
    )
    renamed_symbols = extract_symbols(
        parse_unified_diff(renamed_patch),
        before_text_by_path={"src/old_name.py": "def old_name():\n    return 1\n"},
        after_text_by_path={"src/new_name.py": "def new_name():\n    return 1\n"},
    )

    assert deleted_symbols[0].change_kind == "deleted"
    assert deleted_symbols[0].qualified_name == "legacy_api"
    renamed_names = {(symbol.path, symbol.qualified_name) for symbol in renamed_symbols}
    assert ("src/old_name.py", "old_name") in renamed_names
    assert ("src/new_name.py", "new_name") in renamed_names
    assert ("src/new_name.py", "old_name") not in renamed_names
    assert all(symbol.change_kind == "renamed" for symbol in renamed_symbols)


def test_extract_symbols_returns_empty_for_binary_files() -> None:
    binary_patch = (
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "new file mode 100644\n"
        "Binary files /dev/null and b/assets/logo.png differ\n"
    )

    assert extract_symbols(parse_unified_diff(binary_patch)) == ()


def test_extract_symbols_keeps_text_hunks_when_binary_marker_is_mixed() -> None:
    mixed_patch = (
        "diff --git a/src/demo.ts b/src/demo.ts\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/demo.ts\n"
        "+++ b/src/demo.ts\n"
        "@@ -1 +1 @@ function renderDemo() {\n"
        '-  return "old";\n'
        '+  return "new";\n'
        "Binary files a/src/demo.ts and b/src/demo.ts differ\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(mixed_patch),
        after_text_by_path={"src/demo.ts": 'function renderDemo() {\n  return "new";\n}\n'},
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "renderDemo"


def test_extract_symbols_regex_fallback_finds_function_expression_for_body_only_change() -> None:
    patch = (
        "diff --git a/src/helpers.ts b/src/helpers.ts\n"
        "--- a/src/helpers.ts\n"
        "+++ b/src/helpers.ts\n"
        "@@ -2 +2 @@\n"
        '-  return "old";\n'
        '+  return "new";\n'
    )
    after_text = 'const buildCard = function () {\n  return "new";\n};\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/helpers.ts": after_text},
        symbol_extractor="builtin",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "buildCard"
    assert symbols[0].kind == "function"
    assert symbols[0].extractor == "regex"


def test_extract_symbols_regex_fallback_tracks_js_class_and_static_async_method_scope() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -3 +3 @@\n"
        '-    return "old";\n'
        '+    return "new";\n'
    )
    after_text = (
        'export default class Widget {\n  static async renderCard() {\n    return "new";\n  }\n}\n'
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Widget" in names
    assert "Widget.renderCard" in names
    render_symbol = next(
        symbol for symbol in symbols if symbol.qualified_name == "Widget.renderCard"
    )
    assert render_symbol.parent == "Widget"
    assert render_symbol.kind == "method"
    assert render_symbol.extractor == "regex"


def test_extract_symbols_regex_fallback_finds_generic_arrow_function() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -2 +2 @@\n"
        "-  return oldValue;\n"
        "+  return nextValue;\n"
    )
    after_text = "export const renderCard = <T,>(value: T) => {\n  return nextValue;\n};\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "renderCard"
    assert symbols[0].kind == "function"
    assert symbols[0].extractor == "regex"


def test_extract_symbols_regex_fallback_ignores_object_literal_methods() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -3 +3 @@\n"
        "-    return oldValue;\n"
        "+    return nextValue;\n"
    )
    after_text = "const registry = {\n  renderCard() {\n    return nextValue;\n  },\n};\n"

    assert (
        extract_symbols(
            parse_unified_diff(patch),
            after_text_by_path={"src/widget.ts": after_text},
            symbol_extractor="builtin",
        )
        == ()
    )


def test_tree_sitter_tracks_js_class_method_and_ignores_object_literal_methods() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_javascript")
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -4 +4 @@\n"
        "-    return oldValue;\n"
        "+    return `value: ${nextValue}`;\n"
    )
    after_text = (
        "export default class Widget {\n"
        "  renderCard() {\n"
        '    const template = "}";\n'
        "    // comment with } brace\n"
        "    return `value: ${nextValue}`;\n"
        "  }\n"
        "}\n"
        "const registry = {\n"
        "  renderCard() {\n"
        "    return 3;\n"
        "  },\n"
        "};\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Widget" in names
    assert "Widget.renderCard" in names
    assert "registry.renderCard" not in names
    render_symbol = next(
        symbol for symbol in symbols if symbol.qualified_name == "Widget.renderCard"
    )
    assert render_symbol.parent == "Widget"
    assert render_symbol.extractor == "tree_sitter"
    assert render_symbol.confidence == "high"


def test_extract_symbols_tree_sitter_uses_runtime_records_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -3 +3 @@\n"
        '-    return "old";\n'
        '+    return "new";\n'
    )
    after_text = 'export default class Widget {\n  renderCard() {\n    return "new";\n  }\n}\n'

    def fake_tree_sitter_extract(path: str, source_text: str) -> TreeSitterExtractionResult:
        del path, source_text
        return TreeSitterExtractionResult(
            records=(
                TreeSitterSymbolCandidate(
                    name="Widget",
                    qualified_name="Widget",
                    kind="class",
                    parent=None,
                    start_line=1,
                    end_line=5,
                ),
                TreeSitterSymbolCandidate(
                    name="renderCard",
                    qualified_name="Widget.renderCard",
                    kind="method",
                    parent="Widget",
                    start_line=2,
                    end_line=4,
                ),
            ),
            available=True,
            error=None,
        )

    monkeypatch.setattr(
        "ahadiff.git.symbols.extract_tree_sitter_symbols",
        fake_tree_sitter_extract,
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert names == {"Widget", "Widget.renderCard"}
    assert all(symbol.extractor == "tree_sitter" for symbol in symbols)


def test_extract_symbols_regex_fallback_handles_braces_in_string_and_comment() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -4 +4 @@\n"
        "-    return oldValue;\n"
        "+    return `value: ${nextValue}`;\n"
    )
    after_text = (
        "export default class Widget {\n"
        "  renderCard() {\n"
        '    const template = "}";\n'
        "    // comment with } brace\n"
        "    return `value: ${nextValue}`;\n"
        "  }\n"
        "}\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Widget" in names
    assert "Widget.renderCard" in names


def test_extract_symbols_regex_fallback_handles_multiline_block_comment_braces() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -5 +5 @@\n"
        '-    return "old";\n'
        '+    return "new";\n'
    )
    after_text = (
        "export default class Widget {\n"
        "  renderCard() {\n"
        "    /*\n"
        "      } confusing brace in comment\n"
        "    */\n"
        '    return "new";\n'
        "  }\n"
        "}\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Widget" in names
    assert "Widget.renderCard" in names


def test_extract_symbols_regex_fallback_ignores_multiline_block_comment_signatures() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -8 +8 @@\n"
        "-    return oldValue;\n"
        "+    return nextValue;\n"
    )
    after_text = (
        "export default class Widget {\n"
        "  /*\n"
        "  fakeRender(value) {\n"
        "    return ignored(value);\n"
        "  }\n"
        "  */\n"
        "  renderCard() {\n"
        "    return nextValue;\n"
        "  }\n"
        "}\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="builtin",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Widget" in names
    assert "Widget.renderCard" in names
    assert "Widget.fakeRender" not in names


def test_extract_symbols_merges_same_symbol_across_multiple_hunks() -> None:
    patch = (
        "diff --git a/src/demo.py b/src/demo.py\n"
        "--- a/src/demo.py\n"
        "+++ b/src/demo.py\n"
        "@@ -1,2 +1,2 @@ def render_demo():\n"
        "-def render_demo():\n"
        "+def render_demo():\n"
        "     return 1\n"
        "@@ -4 +4 @@ def render_demo():\n"
        "-    return 2\n"
        "+    return 3\n"
    )
    after_text = "def render_demo():\n    return 1\n\n    return 3\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/demo.py": after_text},
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "render_demo"
    assert len(symbols[0].hunk_ids) == 2


def test_extract_symbols_tree_sitter_merges_same_symbol_across_multiple_hunks() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_typescript")
    patch = (
        "diff --git a/src/demo.ts b/src/demo.ts\n"
        "--- a/src/demo.ts\n"
        "+++ b/src/demo.ts\n"
        "@@ -1,2 +1,2 @@\n"
        "-const renderDemo = () => {\n"
        "+const renderDemo = () => {\n"
        "   return 1;\n"
        "@@ -3 +3 @@\n"
        "-  return 2;\n"
        "+  return 3;\n"
    )
    after_text = "const renderDemo = () => {\n  return 1;\n  return 3;\n};\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/demo.ts": after_text},
        symbol_extractor="tree_sitter",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "renderDemo"
    assert symbols[0].extractor == "tree_sitter"
    assert len(symbols[0].hunk_ids) == 2


def test_extract_symbols_tree_sitter_tracks_go_method_parent_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_go")
    patch = (
        "diff --git a/src/service.go b/src/service.go\n"
        "--- a/src/service.go\n"
        "+++ b/src/service.go\n"
        "@@ -6 +6 @@\n"
        '-    return "old"\n'
        '+    return "new"\n'
    )
    after_text = (
        "package demo\n\n"
        "type Service struct{}\n\n"
        'func (s *Service) Render() string {\n    return "new"\n}\n'
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/service.go": after_text},
        symbol_extractor="tree_sitter",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "Service.Render"
    assert symbols[0].parent == "Service"
    assert symbols[0].extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_go_type_declaration() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_go")
    patch = (
        "diff --git a/src/service.go b/src/service.go\n"
        "--- a/src/service.go\n"
        "+++ b/src/service.go\n"
        "@@ -3 +3 @@\n"
        "-type Service struct{}\n"
        "+type Service struct{ value int }\n"
    )
    after_text = "package demo\n\ntype Service struct{ value int }\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/service.go": after_text},
        symbol_extractor="tree_sitter",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "Service"
    assert symbols[0].kind == "type"
    assert symbols[0].extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_java_class_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_java")
    patch = (
        "diff --git a/src/Service.java b/src/Service.java\n"
        "--- a/src/Service.java\n"
        "+++ b/src/Service.java\n"
        "@@ -3 +3 @@\n"
        '-    return "old";\n'
        '+    return "new";\n'
    )
    after_text = 'class Service {\n  String render() {\n    return "new";\n  }\n}\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/Service.java": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Service" in names
    assert "Service.render" in names
    render_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Service.render")
    assert render_symbol.parent == "Service"
    assert render_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_java_interface_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_java")
    patch = (
        "diff --git a/src/Named.java b/src/Named.java\n"
        "--- a/src/Named.java\n"
        "+++ b/src/Named.java\n"
        "@@ -2 +2 @@\n"
        "-  String name();\n"
        "+  CharSequence name();\n"
    )
    after_text = "interface Named {\n  CharSequence name();\n}\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/Named.java": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Named" in names
    assert "Named.name" in names
    method_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Named.name")
    assert method_symbol.parent == "Named"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_rust_impl_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_rust")
    patch = (
        "diff --git a/src/lib.rs b/src/lib.rs\n"
        "--- a/src/lib.rs\n"
        "+++ b/src/lib.rs\n"
        "@@ -4 +4 @@\n"
        '-        String::from("old")\n'
        '+        String::from("new")\n'
    )
    after_text = (
        "struct Service;\n\n"
        "impl Service {\n"
        "    fn render(&self) -> String {\n"
        '        String::from("new")\n'
        "    }\n"
        "}\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/lib.rs": after_text},
        symbol_extractor="tree_sitter",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "Service.render"
    assert symbols[0].parent == "Service"
    assert symbols[0].extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_rust_trait_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_rust")
    patch = (
        "diff --git a/src/lib.rs b/src/lib.rs\n"
        "--- a/src/lib.rs\n"
        "+++ b/src/lib.rs\n"
        "@@ -2 +2 @@\n"
        "-    fn render(&self) -> String;\n"
        "+    fn render(&self) -> &'static str;\n"
    )
    after_text = "trait Render {\n    fn render(&self) -> &'static str;\n}\n"

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/lib.rs": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Render" in names
    assert "Render.render" in names
    method_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Render.render")
    assert method_symbol.parent == "Render"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_php_namespace_class_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_php")
    patch = (
        "diff --git a/src/Service.php b/src/Service.php\n"
        "--- a/src/Service.php\n"
        "+++ b/src/Service.php\n"
        "@@ -4 +4 @@\n"
        '-  public function run(): string { return "old"; }\n'
        '+  public function run(): string { return "new"; }\n'
    )
    after_text = (
        "<?php\n"
        "namespace App\\Core {\n"
        "class Service {\n"
        '  public function run(): string { return "new"; }\n'
        "}\n"
        "}\n"
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/Service.php": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Service" in names
    assert "Service.run" in names
    method_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Service.run")
    assert method_symbol.parent == "Service"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_ruby_nested_singleton_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_ruby")
    patch = (
        "diff --git a/src/service.rb b/src/service.rb\n"
        "--- a/src/service.rb\n"
        "+++ b/src/service.rb\n"
        "@@ -4 +4 @@\n"
        '-      "old"\n'
        '+      "new"\n'
    )
    after_text = (
        'module Outer\n  class Service\n    def self.boot\n      "new"\n    end\n  end\nend\n'
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/service.rb": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Outer" in names
    assert "Outer.Service" in names
    assert "Outer.Service.boot" in names
    method_symbol = next(
        symbol for symbol in symbols if symbol.qualified_name == "Outer.Service.boot"
    )
    assert method_symbol.parent == "Outer.Service"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_ruby_singleton_class_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_ruby")
    patch = (
        "diff --git a/src/service.rb b/src/service.rb\n"
        "--- a/src/service.rb\n"
        "+++ b/src/service.rb\n"
        "@@ -4 +4 @@\n"
        '-      "old"\n'
        '+      "new"\n'
    )
    after_text = 'class Service\n  class << self\n    def boot\n      "new"\n    end\n  end\nend\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/service.rb": after_text},
        symbol_extractor="tree_sitter",
    )

    assert "Service.boot" in {symbol.qualified_name for symbol in symbols}
    method_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Service.boot")
    assert method_symbol.parent == "Service"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_tree_sitter_tracks_csharp_namespace_class_method_scope() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_c_sharp")
    patch = (
        "diff --git a/src/Service.cs b/src/Service.cs\n"
        "--- a/src/Service.cs\n"
        "+++ b/src/Service.cs\n"
        "@@ -3 +3 @@\n"
        '-  string Run() { return "old"; }\n'
        '+  string Run() { return "new"; }\n'
    )
    after_text = 'namespace Demo.Core {\nclass Service {\n  string Run() { return "new"; }\n}\n}\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/Service.cs": after_text},
        symbol_extractor="tree_sitter",
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Service" in names
    assert "Service.Run" in names
    method_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Service.Run")
    assert method_symbol.parent == "Service"
    assert method_symbol.extractor == "tree_sitter"


def test_extract_symbols_regex_fallback_finds_enclosing_python_symbol_for_body_only_change() -> (
    None
):
    patch = (
        "diff --git a/src/retry.py b/src/retry.py\n"
        "--- a/src/retry.py\n"
        "+++ b/src/retry.py\n"
        "@@ -2 +2 @@\n"
        '-    return "old"\n'
        '+    return "new"\n'
    )
    after_text = 'def retry_once():\n    return "new"\n\ndef trailing(\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/retry.py": after_text},
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "retry_once"
    assert symbols[0].extractor == "regex"


def test_extract_symbols_regex_fallback_tracks_nested_parent_scope() -> None:
    patch = (
        "diff --git a/src/service.py b/src/service.py\n"
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -3 +3 @@\n"
        '-        return "old"\n'
        '+        return "new"\n'
    )
    after_text = 'class Service:\n    def run(self):\n        return "new"\n\ndef trailing(\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/service.py": after_text},
    )

    names = {symbol.qualified_name for symbol in symbols}
    assert "Service" in names
    assert "Service.run" in names
    run_symbol = next(symbol for symbol in symbols if symbol.qualified_name == "Service.run")
    assert run_symbol.parent == "Service"
    assert run_symbol.extractor == "regex"


def test_extract_symbols_tree_sitter_unavailable_falls_back_to_regex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -2 +2 @@\n"
        "-  return oldValue;\n"
        "+  return nextValue;\n"
    )
    after_text = "export const renderCard = () => {\n  return nextValue;\n};\n"

    def fake_tree_sitter_extract(path: str, source_text: str) -> TreeSitterExtractionResult:
        del path, source_text
        return TreeSitterExtractionResult(
            records=(),
            available=False,
            error="tree_sitter runtime is not installed",
        )

    monkeypatch.setattr(
        "ahadiff.git.symbols.extract_tree_sitter_symbols",
        fake_tree_sitter_extract,
    )

    symbols = extract_symbols(
        parse_unified_diff(patch),
        after_text_by_path={"src/widget.ts": after_text},
        symbol_extractor="tree_sitter",
    )

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "renderCard"
    assert symbols[0].extractor == "regex"
    assert symbols[0].error == "tree_sitter runtime is not installed"


def test_extract_symbols_section_header_tracks_parent_from_explicit_scope_hint() -> None:
    patch = (
        "diff --git a/src/widget.ts b/src/widget.ts\n"
        "--- a/src/widget.ts\n"
        "+++ b/src/widget.ts\n"
        "@@ -2 +2 @@ Widget.render\n"
        "-  return oldValue;\n"
        "+  return nextValue;\n"
    )

    symbols = extract_symbols(parse_unified_diff(patch))

    assert len(symbols) == 1
    assert symbols[0].qualified_name == "Widget.render"
    assert symbols[0].parent == "Widget"
    assert symbols[0].extractor == "section_header"


def test_extract_symbols_keeps_python_scope_on_old_side_for_cross_extension_rename() -> None:
    patch = (
        "diff --git a/src/old.py b/src/new.txt\n"
        "similarity index 100%\n"
        "rename from src/old.py\n"
        "rename to src/new.txt\n"
        "@@ -3 +3 @@\n"
        '-        return "old"\n'
        '+        return "new"\n'
    )
    before_text = 'class Service:\n    def run(self):\n        return "old"\n\ndef trailing(\n'
    after_text = 'class Service:\n    def run(self):\n        return "new"\n\ndef trailing(\n'

    symbols = extract_symbols(
        parse_unified_diff(patch),
        before_text_by_path={"src/old.py": before_text},
        after_text_by_path={"src/new.txt": after_text},
    )

    names = {(symbol.path, symbol.qualified_name) for symbol in symbols}
    assert ("src/old.py", "Service.run") in names
    old_symbol = next(
        symbol
        for symbol in symbols
        if symbol.path == "src/old.py" and symbol.qualified_name == "Service.run"
    )
    assert old_symbol.parent == "Service"


def test_serialize_symbols_payload_wraps_schema_and_symbols() -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@ def demo():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    after_text = "def demo():\n    return 2\n"

    payload = serialize_symbols_payload(
        extract_symbols(
            parse_unified_diff(patch),
            after_text_by_path={"src/app.py": after_text},
        )
    )

    assert payload["artifact"] == "symbols"
    assert payload["schema"] == SYMBOLS_SCHEMA
    assert payload["schema_version"] == SYMBOLS_SCHEMA_VERSION
    assert payload["symbols"][0]["qualified_name"] == "demo"
