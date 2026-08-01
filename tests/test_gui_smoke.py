"""Headless GUI smoke tests.

Construct the real walkthrough widget and drive ``_import_cb`` on each fixture,
so bugs in GUI constructor / import-path code that the pure-Python suite cannot
reach are still caught in CI.  This is the exact path where two undefined-name
``NameError``s slipped through during development (the ``_import_cb`` log line
referencing a refactored-away local).

Runs under Qt's ``offscreen`` platform, so no display is needed.  The module is
skipped cleanly if PyQt5 is unavailable.
"""
from __future__ import annotations

import os
# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PyQt5")
import matplotlib
matplotlib.use("Agg")
from PyQt5.QtWidgets import QApplication, QFileDialog

from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSpec

FIXTURES = Path(__file__).parent / "fixtures"
DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

CSV_FIXTURES = ["spatial.csv", "nonspatial.csv", "spot_deconv.csv", "spatial_pixels.csv"]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def widget(qapp):
    w = create_biwt_widget(BiwtInput(preferred_domain=DOMAIN), on_complete=lambda _r: None)
    yield w
    w.deleteLater()


def _drive_import(widget, monkeypatch, path: Path) -> None:
    """Monkeypatch the file dialog to select *path*, then run the import."""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(path), "")),
    )
    widget._import_cb()  # import → session setup → infer_domain → seed factor → first window


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_import_builds_first_window(widget, monkeypatch, name):
    _drive_import(widget, monkeypatch, FIXTURES / name)
    assert widget.session.data is not None
    assert widget.session.data.n_cells > 0
    assert widget.window is not None            # a step window was constructed


def test_import_anndata_builds_first_window(widget, monkeypatch):
    pytest.importorskip("anndata")
    _drive_import(widget, monkeypatch, FIXTURES / "test_AnnData.h5ad")
    assert widget.session.data is not None
    assert widget.window is not None
