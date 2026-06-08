from __future__ import annotations

import ast
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from ahadiff import __version__
from ahadiff import cli as cli_module
from ahadiff.cli import app


def _is_typer_command_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(target, ast.Attribute)
        and target.attr in {"callback", "command"}
        and isinstance(target.value, ast.Name)
        and target.value.id.endswith("_APP")
    )


def _iter_argument_annotations(function: ast.FunctionDef) -> list[tuple[str, ast.expr]]:
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    if function.args.vararg is not None:
        arguments.append(function.args.vararg)
    if function.args.kwarg is not None:
        arguments.append(function.args.kwarg)
    return [(argument.arg, argument.annotation) for argument in arguments if argument.annotation]


def _annotation_uses_literal(annotation: ast.expr) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id == "Literal")
        or (isinstance(node, ast.Attribute) and node.attr == "Literal")
        for node in ast.walk(annotation)
    )


def test_cli_click_command_builds_without_literal_parameter_crash() -> None:
    command = get_command(app())
    assert command is not None

    result = CliRunner().invoke(app(), ["--version"], catch_exceptions=False)

    assert result.exit_code == 0
    assert f"ahadiff {__version__}" in result.stdout


def test_typer_command_parameter_annotations_do_not_use_literal() -> None:
    assert cli_module.__file__ is not None
    source_path = Path(cli_module.__file__)
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in module.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not any(_is_typer_command_decorator(decorator) for decorator in node.decorator_list):
            continue
        for argument_name, annotation in _iter_argument_annotations(node):
            if _annotation_uses_literal(annotation):
                offenders.append(f"{node.name}.{argument_name}: {ast.unparse(annotation)}")

    assert not offenders, "Typer command parameters must not use Literal: " + ", ".join(offenders)
