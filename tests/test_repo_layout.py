"""Repo-level invariants about how the test tree is packaged and type-checked.

`tests/dispatch/conftest.py` and `tests/conftest.py` are both named `conftest.py`.
While no directory under `tests/` held an `__init__.py`, mypy derived both module
names from the containing directory alone, got `conftest` twice, reported
`Duplicate module named "conftest"` and aborted — which silently removed every
file under `tests/` from type-checking. The plan requires `disallow_untyped_defs`
with every `def`, tests included, so a tree that cannot be checked defeats that
silently: nothing fails, the annotation coverage simply stops existing.

`__init__.py` in every source directory is what makes a module name derivable from
the path, so the names are unique by construction rather than by luck. That is
what this file pins.

The check is deliberately structural rather than "run mypy and assert it passes".
A faithful `mypy packages apps tests tools` takes ~2 minutes from a cold cache,
which is too slow to put in the suite; and the cheap approximations do not work —
`--follow-imports=skip` drops the `tests.dispatch.conftest` import that is half of
the collision, so it cannot see the clash at all. The structural rule is instant
and names its cause. See the task-2 report for the recommendation to widen CI's
mypy line to cover `tests/`.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The trees mypy is asked to check.
TYPED_TREES = ("packages", "apps", "tests", "tools")


def _source_dirs(tree: str) -> list[Path]:
    """`tree` and every directory below it that holds a `.py` file."""
    root = REPO_ROOT / tree
    candidates = [root, *(child for child in root.rglob("*") if child.is_dir())]
    return [d for d in candidates if any(child.suffix == ".py" for child in d.iterdir() if child.is_file())]


def test_every_source_directory_is_an_importable_package() -> None:
    """Without `__init__.py` a module name is just the file's basename, so two
    files of the same name anywhere in the tree collide — which is exactly what
    the two `conftest.py` files did."""
    bare = sorted(
        str(directory.relative_to(REPO_ROOT))
        for tree in TYPED_TREES
        for directory in _source_dirs(tree)
        if not (directory / "__init__.py").exists()
    )
    assert bare == [], f"source directories without __init__.py (module names collide): {bare}"
