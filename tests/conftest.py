"""Shared pytest setup for the GUI-touching test modules.

Qt's ``offscreen`` platform is selected here rather than in each module, so it
is guaranteed to be set before *any* module imports PyQt5 and creates a
QApplication — pytest imports conftest first.

The ``qapp`` fixture is here for the same reason the topic modules are separate
files: several of them need a QApplication, and a shared fixture means adding a
new test module never means editing an existing one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# tests/ on the path, so the modules can share plain helpers.
sys.path.insert(0, str(Path(__file__).parent))

from helpers import DOMAIN, FIXTURES, WIDGET_KWARGS   # noqa: F401 — re-exported


@pytest.fixture(scope="session")
def qapp():
    """The process-wide QApplication. Qt allows only one, so never tear it down."""
    pytest.importorskip("PyQt5")
    import matplotlib
    matplotlib.use("Agg")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _reap_widgets():
    """Destroy any widget a test left behind.

    Qt keeps top-level widgets alive until something destroys them; past a few
    hundred the offscreen platform segfaults, in whichever module runs next rather
    than the one that leaked.

    Autouse, so it must not depend on ``qapp`` — requesting that fixture would put
    its ``importorskip`` in front of every test in the suite, and the Qt-free
    modules would silently skip rather than run.
    """
    yield
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        try:
            widget.hide()
            widget.deleteLater()
        except RuntimeError:
            pass                    # already destroyed by a narrower fixture
    app.processEvents()


@pytest.fixture
def make_widget(qapp):
    """Factory for a real walkthrough widget, plus the result it completes with.

    Returns ``(widget, completed)`` where *completed* is a one-element list that
    receives the ``BiwtResult`` passed to ``on_complete``.

    Keyword arguments build the ``BiwtInput``, except the widget's own
    construction settings (see ``WIDGET_KWARGS``), which are passed on to
    ``create_biwt_widget``.  Pass ``_source=`` instead to hand it something else
    entirely — a host provider callable — in which case no ``BiwtInput`` is
    constructed here.
    """
    pytest.importorskip("PyQt5")
    from biwt.gui.walkthrough import create_biwt_widget
    from biwt.types import BiwtInput

    built = []

    def _make(_source=None, **kwargs):
        widget_kwargs = {
            name: kwargs.pop(name) for name in WIDGET_KWARGS if name in kwargs
        }
        if _source is None:
            kwargs.setdefault("preferred_domain", DOMAIN)
            _source = BiwtInput(**kwargs)
        elif kwargs:
            raise TypeError("pass either _source or BiwtInput kwargs, not both")
        completed: list = []
        widget = create_biwt_widget(
            _source, on_complete=completed.append, **widget_kwargs
        )
        built.append(widget)
        return widget, completed

    yield _make
    for widget in built:
        widget.deleteLater()


@pytest.fixture
def drive_import(monkeypatch):
    """Import a fixture file through the real file-dialog code path."""
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QFileDialog

    def _drive(widget, name: str) -> None:
        path = FIXTURES / name
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(path), "")),
        )
        widget._import_cb()

    return _drive
