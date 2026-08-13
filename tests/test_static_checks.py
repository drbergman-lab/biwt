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
import importlib
import pathlib
import re

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


# ---------------------------------------------------------------------------
# Documentation targets
# ---------------------------------------------------------------------------

DOCS = ROOT / "docs"


def _mkdocstrings_targets():
    """``(page, target, member)`` for every name a reference page asks to render."""
    out = []
    for page in sorted(DOCS.rglob("*.md")):
        text = page.read_text()
        for block in re.finditer(r"^::: (\S+)\n(.*?)(?=^::: |\Z)", text, re.S | re.M):
            target, body = block.group(1), block.group(2)
            members = re.findall(r"^\s+- (\S+)\s*$", body, re.M)
            out.append((page.relative_to(ROOT), target, members or [None]))
    return out


@pytest.mark.parametrize(
    "page,target,members",
    _mkdocstrings_targets(),
    ids=lambda v: str(v) if not isinstance(v, list) else "",
)
def test_every_documented_name_exists(page, target, members):
    """A renamed symbol must not survive in a `:::` block.

    CI builds the site with ``mkdocs --strict``, and mkdocs is not installed
    here — so a stale member is a red CI run nobody can reproduce locally. It has
    happened once already, to a function renamed mid-branch.
    """
    module_path, _, attr = target.rpartition(".")
    try:
        obj = importlib.import_module(target)
    except ImportError:
        obj = importlib.import_module(module_path)
        assert hasattr(obj, attr), f"{page}: no {attr!r} in {module_path}"
        obj = getattr(obj, attr)
    for member in members:
        if member is not None:
            assert hasattr(obj, member), f"{page}: {target} has no {member!r}"
