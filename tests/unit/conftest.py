from collections.abc import Iterator

import pytest

from ahadiff.git import tree_sitter_runtime


@pytest.fixture(autouse=True)
def reset_tree_sitter_runtime_caches() -> Iterator[None]:
    tree_sitter_runtime.reset_caches()
    try:
        yield
    finally:
        tree_sitter_runtime.reset_caches()
