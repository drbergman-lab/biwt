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

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


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
