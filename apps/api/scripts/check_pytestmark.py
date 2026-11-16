"""
CI check (Test Suite Integrity follow-up): every test_*.py file must declare a
module-level `pytestmark = pytest.mark.unit` or `pytest.mark.integration`
(CONTRIBUTING.md's documented convention).

Why this exists as a standalone check rather than relying on `pytest -m`: a file
with no marker is not an error under `-m unit` or `-m integration` -- pytest just
silently deselects every test in it. That is exactly how three test files (see
docs/todo.md's "Test Suite Integrity" entry) ran zero times while the docs
claimed a passing count nobody had actually re-verified. `-m` filtering can never
catch this, because from `-m`'s point of view a wrongly-unmarked file and an
intentionally-deselected file look identical -- only a check that looks at every
file, independent of any marker filter, can.

Static (AST-based) rather than an import + pytest-collection check on purpose:
importing every test module would require the full dependency set (psycopg2,
confluent-kafka, a reachable Postgres for fixtures with connection-time
side-effects, etc), which is exactly the heavy setup this check should NOT need
in order to run in seconds on every PR.

Usage:
    python -m apps.api.scripts.check_pytestmark
Exits 1 and lists offending files if any test file lacks a valid pytestmark.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).parents[2] / "api" / "tests"
VALID_MARKS = {"unit", "integration"}


def _pytestmark_marks(tree: ast.Module) -> set[str]:
    """Returns the mark names (e.g. {"unit"}) a module-level `pytestmark =`
    assignment references, by walking `pytest.mark.<name>` attribute chains.
    Handles both `pytestmark = pytest.mark.unit` and
    `pytestmark = [pytest.mark.unit, pytest.mark.slow]`.
    """
    marks: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue

        values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
        for value in values:
            # pytest.mark.unit -> Attribute(value=Attribute(value=Name('pytest'),
            # attr='mark'), attr='unit')
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Attribute)
                and value.value.attr == "mark"
            ):
                marks.add(value.attr)

    return marks


def find_unmarked_files() -> list[Path]:
    offenders = []
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        marks = _pytestmark_marks(tree)
        if not marks & VALID_MARKS:
            offenders.append(path)
    return offenders


def main() -> int:
    offenders = find_unmarked_files()
    if not offenders:
        print("check_pytestmark: all test files declare pytestmark. OK.")
        return 0

    print("check_pytestmark: FAILED -- these test files have no pytestmark "
          "(pytest.mark.unit or pytest.mark.integration) and are silently "
          "excluded from both `pytest -m unit` and `pytest -m integration`:")
    for path in offenders:
        print(f"  - {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print("\nFix: add `pytestmark = pytest.mark.unit` (or `.integration`) at "
          "module level, per CONTRIBUTING.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
