"""Static checks over the package and the suite.

A missing import inside a method is invisible to the tests unless one of them
reaches that exact line. ``positions.py`` used ``DomainSource`` in the
domain-editor auto-show path — a path every test deliberately avoided, because it
opens a modal dialog — and shipped a ``NameError`` that only appeared in a live
Studio run.

The suite is checked too, for a different failure: two test classes sharing a name
means the first one silently never runs. That had happened, and cost two tests.

pyflakes reads the source rather than running it, so it does not care which paths
are reachable.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pyflakes_checker = pytest.importorskip(
    "pyflakes.checker", reason="pyflakes is in the dev extra"
)
pyflakes_messages = pytest.importorskip("pyflakes.messages")

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROOTS = (ROOT / "src" / "biwt", ROOT / "tests")

# Latent runtime errors and silently discarded code. Unused imports are left out
# on purpose: they are untidy rather than wrong, and one of them
# (``biwt.gui.__init__``'s PyQt5 availability probe) is deliberate.
FATAL = (
    pyflakes_messages.UndefinedName,
    pyflakes_messages.UndefinedLocal,
    pyflakes_messages.UndefinedExport,
    pyflakes_messages.RedefinedWhileUnused,
)


def _sources():
    return sorted(f for root in ROOTS for f in root.rglob("*.py"))


def test_there_are_modules_to_check():
    """Guard against a path typo quietly making the check below vacuous."""
    found = _sources()
    assert len(found) > 20
    assert any(f.name == "walkthrough.py" for f in found)
    assert any(f.name == "test_session.py" for f in found)


@pytest.mark.parametrize("path", _sources(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_undefined_or_shadowed_names(path):
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    checker = pyflakes_checker.Checker(tree, filename=str(path))
    problems = [
        str(msg).replace(f"{ROOT}/", "")
        for msg in checker.messages
        if isinstance(msg, FATAL)
    ]
    assert not problems, "\n".join(problems)
