from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

_JS_EXTENSIONS = frozenset({".js", ".jsx", ".mjs", ".cjs"})
_TS_EXTENSIONS = frozenset({".ts"})
_TSX_EXTENSIONS = frozenset({".tsx"})
_GO_EXTENSIONS = frozenset({".go"})
_JAVA_EXTENSIONS = frozenset({".java"})
_PHP_EXTENSIONS = frozenset({".php"})
_RUBY_EXTENSIONS = frozenset({".rb"})
_RUST_EXTENSIONS = frozenset({".rs"})
_C_SHARP_EXTENSIONS = frozenset({".cs"})
_FUNCTION_LIKE_NODE_TYPES = frozenset({"arrow_function", "function_expression"})
_TYPE_DECLARATION_NODE_TYPES = frozenset(
    {"enum_declaration", "interface_declaration", "type_alias_declaration"}
)
_JAVA_TYPE_DECLARATION_NODE_TYPES = frozenset(
    {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
)
_PHP_TYPE_DECLARATION_NODE_TYPES = frozenset(
    {"class_declaration", "trait_declaration", "interface_declaration", "enum_declaration"}
)
_C_SHARP_TYPE_DECLARATION_NODE_TYPES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "record_declaration",
        "enum_declaration",
        "struct_declaration",
        "delegate_declaration",
    }
)
TreeSitterLanguageKey = Literal["js_like", "go", "java", "php", "ruby", "rust", "c_sharp"]


@dataclass(frozen=True)
class TreeSitterSymbolCandidate:
    name: str
    qualified_name: str
    kind: str
    parent: str | None
    start_line: int
    end_line: int


@dataclass(frozen=True)
class TreeSitterExtractionResult:
    records: tuple[TreeSitterSymbolCandidate, ...]
    available: bool
    error: str | None = None


class TreeSitterRuntimeUnavailable(RuntimeError):
    pass


def extract_tree_sitter_symbols(
    path: str,
    source_text: str,
) -> TreeSitterExtractionResult:
    try:
        language_key, language = _load_language_for_path(path)
    except TreeSitterRuntimeUnavailable as exc:
        return TreeSitterExtractionResult(records=(), available=False, error=str(exc))

    try:
        parser = _build_parser(language)
        source_bytes = source_text.encode("utf-8")
        tree = parser.parse(source_bytes)
        records = tuple(_collect_program_symbols(language_key, tree.root_node, source_bytes))
    except Exception as exc:
        return TreeSitterExtractionResult(
            records=(),
            available=True,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    return TreeSitterExtractionResult(records=records, available=True, error=None)


def supports_tree_sitter_path(path: str) -> bool:
    suffix = _path_suffix(path)
    return suffix in (
        _JS_EXTENSIONS
        | _TS_EXTENSIONS
        | _TSX_EXTENSIONS
        | _GO_EXTENSIONS
        | _JAVA_EXTENSIONS
        | _PHP_EXTENSIONS
        | _RUBY_EXTENSIONS
        | _RUST_EXTENSIONS
        | _C_SHARP_EXTENSIONS
    )


def reset_caches() -> None:
    """Clear tree-sitter runtime caches used by symbol extraction."""
    _load_language_for_path.cache_clear()
    _load_tree_sitter_runtime.cache_clear()


@lru_cache(maxsize=9)
def _load_language_for_path(path: str) -> tuple[TreeSitterLanguageKey, object]:
    suffix = _path_suffix(path)
    if suffix in _JS_EXTENSIONS:
        return ("js_like", _load_language_from_module("tree_sitter_javascript", "language"))
    if suffix in _TS_EXTENSIONS:
        return (
            "js_like",
            _load_language_from_module("tree_sitter_typescript", "language_typescript"),
        )
    if suffix in _TSX_EXTENSIONS:
        return ("js_like", _load_language_from_module("tree_sitter_typescript", "language_tsx"))
    if suffix in _GO_EXTENSIONS:
        return ("go", _load_language_from_module("tree_sitter_go", "language"))
    if suffix in _JAVA_EXTENSIONS:
        return ("java", _load_language_from_module("tree_sitter_java", "language"))
    if suffix in _PHP_EXTENSIONS:
        return ("php", _load_language_from_module("tree_sitter_php", "language_php"))
    if suffix in _RUBY_EXTENSIONS:
        return ("ruby", _load_language_from_module("tree_sitter_ruby", "language"))
    if suffix in _RUST_EXTENSIONS:
        return ("rust", _load_language_from_module("tree_sitter_rust", "language"))
    if suffix in _C_SHARP_EXTENSIONS:
        return ("c_sharp", _load_language_from_module("tree_sitter_c_sharp", "language"))
    raise TreeSitterRuntimeUnavailable(f"tree-sitter does not support {path!r}")


def _path_suffix(path: str) -> str:
    head, dot, tail = path.rpartition(".")
    if not dot or not head:
        return ""
    return f".{tail.casefold()}"


@lru_cache(maxsize=2)
def _load_tree_sitter_runtime() -> tuple[Any, Any]:
    try:
        module = importlib.import_module("tree_sitter")
    except ImportError as exc:
        raise TreeSitterRuntimeUnavailable("tree_sitter runtime is not installed") from exc
    parser_cls = getattr(module, "Parser", None)
    language_cls = getattr(module, "Language", None)
    if parser_cls is None or language_cls is None:
        raise TreeSitterRuntimeUnavailable("tree_sitter runtime is missing Parser/Language")
    return parser_cls, language_cls


def _load_language_from_module(module_name: str, export_name: str) -> object:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise TreeSitterRuntimeUnavailable(f"{module_name} grammar wheel is not installed") from exc
    factory = getattr(module, export_name, None)
    if not callable(factory):
        raise TreeSitterRuntimeUnavailable(f"{module_name} does not export {export_name}()")
    _, language_cls = _load_tree_sitter_runtime()
    handle = factory()
    try:
        if isinstance(handle, language_cls):
            return handle
    except TypeError:
        pass
    return language_cls(handle)


def _build_parser(language: object) -> Any:
    parser_cls, _ = _load_tree_sitter_runtime()
    try:
        return parser_cls(language)
    except TypeError:
        parser = parser_cls()
        parser.language = language
        return parser


def _collect_program_symbols(
    language_key: TreeSitterLanguageKey,
    root: Any,
    source_bytes: bytes,
) -> list[TreeSitterSymbolCandidate]:
    if language_key == "js_like":
        return _collect_js_like_program_symbols(root, source_bytes)
    if language_key == "go":
        return _collect_go_program_symbols(root, source_bytes)
    if language_key == "java":
        return _collect_java_program_symbols(root, source_bytes)
    if language_key == "php":
        return _collect_php_program_symbols(root, source_bytes)
    if language_key == "ruby":
        return _collect_ruby_program_symbols(root, source_bytes)
    if language_key == "c_sharp":
        return _collect_c_sharp_program_symbols(root, source_bytes)
    return _collect_rust_program_symbols(root, source_bytes)


def _collect_js_like_program_symbols(
    root: Any, source_bytes: bytes
) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        records.extend(_collect_top_level_symbols(child, source_bytes))
    return records


def _collect_top_level_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    declaration = _unwrap_export_declaration(node)
    if declaration is None:
        return []
    if declaration.type == "class_declaration":
        return _collect_class_symbols(declaration, source_bytes)
    if declaration.type == "function_declaration":
        candidate = _symbol_from_named_node(
            declaration,
            source_bytes,
            kind="function",
            parent=None,
        )
        return [candidate] if candidate is not None else []
    if declaration.type in _TYPE_DECLARATION_NODE_TYPES:
        candidate = _symbol_from_named_node(
            declaration,
            source_bytes,
            kind="type",
            parent=None,
        )
        return [candidate] if candidate is not None else []
    if declaration.type in {"lexical_declaration", "variable_declaration"}:
        return _collect_variable_symbols(declaration, source_bytes)
    return []


def _unwrap_export_declaration(node: Any) -> Any | None:
    if node.type != "export_statement":
        return node
    return node.child_by_field_name("declaration")


def _collect_class_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    class_name = _node_name_text(node, source_bytes)
    if class_name is None:
        return []
    class_record = TreeSitterSymbolCandidate(
        name=class_name,
        qualified_name=class_name,
        kind="class",
        parent=None,
        start_line=_node_start_line(node),
        end_line=_node_end_line(node),
    )
    records = [class_record]
    class_body = node.child_by_field_name("body")
    if class_body is None:
        return records
    for member in class_body.children:
        member_record = _collect_class_member_symbol(member, source_bytes, class_name)
        if member_record is not None:
            records.append(member_record)
    return records


def _collect_class_member_symbol(
    node: Any,
    source_bytes: bytes,
    class_name: str,
) -> TreeSitterSymbolCandidate | None:
    if node.type == "method_definition":
        name = _node_name_text(node, source_bytes)
        if name is None:
            return None
        return TreeSitterSymbolCandidate(
            name=name,
            qualified_name=f"{class_name}.{name}",
            kind="method",
            parent=class_name,
            start_line=_node_start_line(node),
            end_line=_node_end_line(node),
        )
    if node.type == "public_field_definition":
        value = node.child_by_field_name("value")
        if value is None or value.type not in _FUNCTION_LIKE_NODE_TYPES:
            return None
        name = _node_name_text(node, source_bytes)
        if name is None:
            return None
        return TreeSitterSymbolCandidate(
            name=name,
            qualified_name=f"{class_name}.{name}",
            kind="method",
            parent=class_name,
            start_line=_node_start_line(node),
            end_line=_node_end_line(node),
        )
    return None


def _collect_variable_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        value = child.child_by_field_name("value")
        if value is None or value.type not in _FUNCTION_LIKE_NODE_TYPES:
            continue
        name = _node_name_text(child, source_bytes)
        if name is None:
            continue
        records.append(
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=name,
                kind="function",
                parent=None,
                start_line=_node_start_line(child),
                end_line=_node_end_line(child),
            )
        )
    return records


def _collect_go_program_symbols(root: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        if child.type == "function_declaration":
            candidate = _symbol_from_named_node(
                child,
                source_bytes,
                kind="function",
                parent=None,
            )
            if candidate is not None:
                records.append(candidate)
            continue
        if child.type == "method_declaration":
            parent = _go_method_parent_name(child, source_bytes)
            name = _node_name_text(child, source_bytes)
            if parent is None or name is None:
                continue
            records.append(
                TreeSitterSymbolCandidate(
                    name=name,
                    qualified_name=f"{parent}.{name}",
                    kind="method",
                    parent=parent,
                    start_line=_node_start_line(child),
                    end_line=_node_end_line(child),
                )
            )
            continue
        if child.type == "type_declaration":
            records.extend(_collect_go_type_symbols(child, source_bytes))
    return records


def _collect_go_type_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in node.children:
        if child.type != "type_spec":
            continue
        candidate = _symbol_from_named_node(
            child,
            source_bytes,
            kind="type",
            parent=None,
        )
        if candidate is not None:
            records.append(candidate)
    return records


def _collect_java_program_symbols(
    root: Any, source_bytes: bytes
) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        if child.type not in _JAVA_TYPE_DECLARATION_NODE_TYPES:
            continue
        records.extend(_collect_java_type_symbols(child, source_bytes))
    return records


def _collect_java_type_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    parent_name = _node_name_text(node, source_bytes)
    if parent_name is None:
        return []
    kind = _java_symbol_kind(node.type)
    records = [
        TreeSitterSymbolCandidate(
            name=parent_name,
            qualified_name=parent_name,
            kind=kind,
            parent=None,
            start_line=_node_start_line(node),
            end_line=_node_end_line(node),
        )
    ]
    body = _child_by_type(node, {"class_body", "interface_body", "enum_body"})
    if body is None:
        return records
    for member in body.children:
        if member.type == "method_declaration":
            name = _node_name_text(member, source_bytes)
            if name is None:
                continue
            records.append(
                TreeSitterSymbolCandidate(
                    name=name,
                    qualified_name=f"{parent_name}.{name}",
                    kind="method",
                    parent=parent_name,
                    start_line=_node_start_line(member),
                    end_line=_node_end_line(member),
                )
            )
            continue
        if member.type == "constructor_declaration":
            name = _node_name_text(member, source_bytes)
            if name is None:
                continue
            records.append(
                TreeSitterSymbolCandidate(
                    name=name,
                    qualified_name=f"{parent_name}.{name}",
                    kind="constructor",
                    parent=parent_name,
                    start_line=_node_start_line(member),
                    end_line=_node_end_line(member),
                )
            )
    return records


def _collect_rust_program_symbols(
    root: Any, source_bytes: bytes
) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        if child.type == "function_item":
            candidate = _symbol_from_named_node(
                child,
                source_bytes,
                kind="function",
                parent=None,
            )
            if candidate is not None:
                records.append(candidate)
            continue
        if child.type in {"struct_item", "enum_item", "trait_item"}:
            candidate = _symbol_from_named_node(
                child,
                source_bytes,
                kind=_rust_symbol_kind(child.type),
                parent=None,
            )
            if candidate is not None:
                records.append(candidate)
            if child.type == "trait_item":
                records.extend(_collect_rust_trait_methods(child, source_bytes))
            continue
        if child.type == "impl_item":
            records.extend(_collect_rust_impl_methods(child, source_bytes))
    return records


def _collect_php_program_symbols(root: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        records.extend(_collect_php_node_symbols(child, source_bytes))
    return records


def _collect_php_node_symbols(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    if node.type == "namespace_definition":
        body = _child_by_type(node, {"compound_statement", "declaration_list"})
        if body is None:
            return []
        records: list[TreeSitterSymbolCandidate] = []
        for child in body.children:
            records.extend(_collect_php_node_symbols(child, source_bytes))
        return records
    if node.type == "function_definition":
        candidate = _symbol_from_named_node(
            node,
            source_bytes,
            kind="function",
            parent=None,
        )
        return [candidate] if candidate is not None else []
    if node.type not in _PHP_TYPE_DECLARATION_NODE_TYPES:
        return []
    parent_name = _node_name_text(node, source_bytes)
    if parent_name is None:
        return []
    records = [
        TreeSitterSymbolCandidate(
            name=parent_name,
            qualified_name=parent_name,
            kind=_php_symbol_kind(node.type),
            parent=None,
            start_line=_node_start_line(node),
            end_line=_node_end_line(node),
        )
    ]
    body = _child_by_type(node, {"declaration_list", "enum_declaration_list"})
    if body is None:
        return records
    for member in body.children:
        if member.type != "method_declaration":
            continue
        name = _node_name_text(member, source_bytes)
        if name is None:
            continue
        records.append(
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=f"{parent_name}.{name}",
                kind="method",
                parent=parent_name,
                start_line=_node_start_line(member),
                end_line=_node_end_line(member),
            )
        )
    return records


def _collect_ruby_program_symbols(
    root: Any, source_bytes: bytes
) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        records.extend(_collect_ruby_scope_symbols(child, source_bytes, parents=()))
    return records


def _collect_ruby_scope_symbols(
    node: Any,
    source_bytes: bytes,
    *,
    parents: tuple[str, ...],
) -> list[TreeSitterSymbolCandidate]:
    if node.type in {"class", "module"}:
        name = _node_name_text(node, source_bytes)
        if name is None:
            return []
        qualified_name = _qualified_name(parents, name)
        kind = "class" if node.type == "class" else "module"
        records = [
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=qualified_name,
                kind=kind,
                parent=_parent_name(parents),
                start_line=_node_start_line(node),
                end_line=_node_end_line(node),
            )
        ]
        body = _child_by_type(node, {"body_statement"})
        if body is None:
            return records
        next_parents = (*parents, name)
        for member in body.children:
            records.extend(_collect_ruby_scope_symbols(member, source_bytes, parents=next_parents))
        return records
    if node.type == "singleton_class":
        next_parents = _ruby_singleton_class_parents(node, source_bytes, parents)
        if next_parents is None:
            return []
        body = _child_by_type(node, {"body_statement"})
        if body is None:
            return []
        records: list[TreeSitterSymbolCandidate] = []
        for member in body.children:
            records.extend(_collect_ruby_scope_symbols(member, source_bytes, parents=next_parents))
        return records
    if node.type in {"method", "singleton_method"}:
        name = _node_name_text(node, source_bytes)
        if name is None:
            return []
        return [
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=_qualified_name(parents, name),
                kind="method",
                parent=_parent_name(parents),
                start_line=_node_start_line(node),
                end_line=_node_end_line(node),
            )
        ]
    return []


def _collect_c_sharp_program_symbols(
    root: Any, source_bytes: bytes
) -> list[TreeSitterSymbolCandidate]:
    records: list[TreeSitterSymbolCandidate] = []
    for child in root.children:
        records.extend(_collect_c_sharp_node_symbols(child, source_bytes, parents=()))
    return records


def _collect_c_sharp_node_symbols(
    node: Any,
    source_bytes: bytes,
    *,
    parents: tuple[str, ...],
) -> list[TreeSitterSymbolCandidate]:
    if node.type in {"namespace_declaration", "file_scoped_namespace_declaration"}:
        body = _child_by_type(node, {"declaration_list"})
        if body is None:
            return []
        records: list[TreeSitterSymbolCandidate] = []
        for child in body.children:
            records.extend(_collect_c_sharp_node_symbols(child, source_bytes, parents=parents))
        return records
    if node.type not in _C_SHARP_TYPE_DECLARATION_NODE_TYPES:
        return []
    parent_name = _node_name_text(node, source_bytes)
    if parent_name is None:
        return []
    qualified_name = _qualified_name(parents, parent_name)
    records = [
        TreeSitterSymbolCandidate(
            name=parent_name,
            qualified_name=qualified_name,
            kind=_c_sharp_symbol_kind(node.type),
            parent=_parent_name(parents),
            start_line=_node_start_line(node),
            end_line=_node_end_line(node),
        )
    ]
    body = _child_by_type(node, {"declaration_list"})
    if body is None:
        return records
    next_parents = (*parents, parent_name)
    for member in body.children:
        if member.type in _C_SHARP_TYPE_DECLARATION_NODE_TYPES:
            records.extend(
                _collect_c_sharp_node_symbols(member, source_bytes, parents=next_parents)
            )
            continue
        if member.type not in {"method_declaration", "constructor_declaration"}:
            continue
        name = _node_name_text(member, source_bytes)
        if name is None:
            continue
        kind = "constructor" if member.type == "constructor_declaration" else "method"
        records.append(
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=f"{qualified_name}.{name}",
                kind=kind,
                parent=qualified_name,
                start_line=_node_start_line(member),
                end_line=_node_end_line(member),
            )
        )
    return records


def _collect_rust_trait_methods(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    parent = _node_name_text(node, source_bytes)
    if parent is None:
        return []
    body = node.child_by_field_name("body")
    if body is None:
        return []
    records: list[TreeSitterSymbolCandidate] = []
    for member in body.children:
        if member.type != "function_signature_item":
            continue
        name = _node_name_text(member, source_bytes)
        if name is None:
            continue
        records.append(
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=f"{parent}.{name}",
                kind="method",
                parent=parent,
                start_line=_node_start_line(member),
                end_line=_node_end_line(member),
            )
        )
    return records


def _collect_rust_impl_methods(node: Any, source_bytes: bytes) -> list[TreeSitterSymbolCandidate]:
    parent = _field_text(node, "type", source_bytes)
    if parent is None:
        return []
    body = node.child_by_field_name("body")
    if body is None:
        return []
    records: list[TreeSitterSymbolCandidate] = []
    for member in body.children:
        if member.type != "function_item":
            continue
        name = _node_name_text(member, source_bytes)
        if name is None:
            continue
        records.append(
            TreeSitterSymbolCandidate(
                name=name,
                qualified_name=f"{parent}.{name}",
                kind="method",
                parent=parent,
                start_line=_node_start_line(member),
                end_line=_node_end_line(member),
            )
        )
    return records


def _go_method_parent_name(node: Any, source_bytes: bytes) -> str | None:
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return None
    parameter = _child_by_type(receiver, {"parameter_declaration"})
    if parameter is None:
        return None
    receiver_type = parameter.child_by_field_name("type")
    if receiver_type is None:
        return None
    if receiver_type.type == "pointer_type":
        receiver_type = _child_by_type(receiver_type, {"type_identifier"})
        if receiver_type is None:
            return None
    value = source_bytes[receiver_type.start_byte : receiver_type.end_byte].decode("utf-8").strip()
    return value or None


def _java_symbol_kind(node_type: str) -> str:
    if node_type == "class_declaration":
        return "class"
    if node_type == "interface_declaration":
        return "interface"
    if node_type == "enum_declaration":
        return "enum"
    return "record"


def _php_symbol_kind(node_type: str) -> str:
    if node_type == "class_declaration":
        return "class"
    if node_type == "trait_declaration":
        return "trait"
    if node_type == "interface_declaration":
        return "interface"
    return "enum"


def _c_sharp_symbol_kind(node_type: str) -> str:
    if node_type == "class_declaration":
        return "class"
    if node_type == "interface_declaration":
        return "interface"
    if node_type == "record_declaration":
        return "record"
    if node_type == "enum_declaration":
        return "enum"
    if node_type == "struct_declaration":
        return "struct"
    return "delegate"


def _rust_symbol_kind(node_type: str) -> str:
    if node_type == "trait_item":
        return "trait"
    return "type"


def _symbol_from_named_node(
    node: Any,
    source_bytes: bytes,
    *,
    kind: str,
    parent: str | None,
) -> TreeSitterSymbolCandidate | None:
    name = _node_name_text(node, source_bytes)
    if name is None:
        return None
    qualified_name = f"{parent}.{name}" if parent else name
    return TreeSitterSymbolCandidate(
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        parent=parent,
        start_line=_node_start_line(node),
        end_line=_node_end_line(node),
    )


def _node_name_text(node: Any, source_bytes: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    value = source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
    return value or None


def _field_text(node: Any, field_name: str, source_bytes: bytes) -> str | None:
    target = node.child_by_field_name(field_name)
    if target is None:
        return None
    value = source_bytes[target.start_byte : target.end_byte].decode("utf-8").strip()
    return value or None


def _qualified_name(parents: tuple[str, ...], name: str) -> str:
    return ".".join((*parents, name)) if parents else name


def _parent_name(parents: tuple[str, ...]) -> str | None:
    if not parents:
        return None
    return ".".join(parents)


def _ruby_singleton_class_parents(
    node: Any,
    source_bytes: bytes,
    parents: tuple[str, ...],
) -> tuple[str, ...] | None:
    target = node.child_by_field_name("value")
    if target is None:
        return None
    target_text = source_bytes[target.start_byte : target.end_byte].decode("utf-8").strip()
    if target_text == "self":
        return parents
    if target.type in {"constant", "scope_resolution"}:
        return tuple(part for part in target_text.replace("::", ".").split(".") if part)
    return None


def _child_by_type(node: Any, target_types: set[str]) -> Any | None:
    for child in node.children:
        if child.type in target_types:
            return child
    return None


def _node_start_line(node: Any) -> int:
    return int(node.start_point.row) + 1


def _node_end_line(node: Any) -> int:
    return int(node.end_point.row) + 1


__all__ = [
    "TreeSitterExtractionResult",
    "TreeSitterSymbolCandidate",
    "extract_tree_sitter_symbols",
    "reset_caches",
    "supports_tree_sitter_path",
]
