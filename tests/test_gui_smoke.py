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

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt5")
import matplotlib
matplotlib.use("Agg")
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from biwt.core.data_loader import (
    INSTALL_DOCS_URL,
    TROUBLESHOOTING_DOCS_URL,
    LoadError,
)
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


# ---------------------------------------------------------------------------
# "Import failed" dialog
# ---------------------------------------------------------------------------

def _capture_message_boxes(monkeypatch) -> list:
    """Intercept the modal exec_() so dialogs never block, recording each box."""
    boxes = []

    def fake_exec(self):
        boxes.append(self)
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    return boxes


def test_dependency_error_dialog_links_to_docs(widget, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)
    monkeypatch.setitem(sys.modules, "anndata2ri", None)

    _drive_import(widget, monkeypatch, FIXTURES / "no_such_file.rds")

    assert len(boxes) == 1
    text = boxes[0].text()
    assert boxes[0].textFormat() == Qt.RichText
    assert f'<a href="{INSTALL_DOCS_URL}">' in text
    assert "biwt[seurat]" in text
    # Recoverable failure: the user stays in the wizard, nothing was loaded.
    assert widget.session.data is None


def test_file_error_dialog_has_no_docs_link(widget, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)

    _drive_import(widget, monkeypatch, FIXTURES / "unsupported.txt")

    assert len(boxes) == 1
    text = boxes[0].text()
    assert "<a href=" not in text
    assert "setup docs" not in text
    assert widget.session.data is None


def test_dialog_renders_whichever_docs_url_the_error_carries(widget, monkeypatch):
    # The dialog must not hardcode the install page — R-stack failures point at
    # troubleshooting instead.
    boxes = _capture_message_boxes(monkeypatch)

    widget._show_import_error(
        LoadError("anndata2ri activation failed: boom",
                  docs_url=TROUBLESHOOTING_DOCS_URL)
    )

    assert f'<a href="{TROUBLESHOOTING_DOCS_URL}">' in boxes[0].text()


def _domain_editor(qapp, data_units="data unit", host_units="micron"):
    from biwt.gui.walkthrough import DomainEditorDialog
    return DomainEditorDialog(
        None,
        data_domain=DomainSpec(-100, 4900, -100, 4300, units=data_units),
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500,
                                    units=host_units),
        file_factor=0.5,
    )


def _labels(dlg) -> list:
    from PyQt5.QtWidgets import QLabel
    return [l.text() for l in dlg.findChildren(QLabel)]


def test_scale_factor_label_uses_ratio_notation(qapp):
    """The docs describe this field as `{host unit}/{data unit}`.

    Ratio notation keeps both unit names singular, which is how
    ``DomainSpec.units`` stores them ("micron", not "microns").
    """
    labels = _labels(_domain_editor(qapp))
    assert "micron/data unit:" in labels
    assert not any(" per data unit" in t for t in labels)


def test_scale_factor_label_is_derived_from_both_domains(qapp):
    """Neither side of the ratio is hardcoded.

    A data domain that carries a real unit name renders as "micron/pixel"
    with no further change to the dialog.
    """
    labels = _labels(_domain_editor(qapp, data_units="pixel", host_units="nanometer"))
    assert "nanometer/pixel:" in labels
    # ...and the bounds column headers use the same names.
    assert "<b>pixel</b>" in labels
    assert "<b>nanometer</b>" in labels


def test_error_message_is_html_escaped(widget, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)

    widget._show_import_error(LoadError("bad <class> & 'quote'", docs_url=INSTALL_DOCS_URL))

    text = boxes[0].text()
    assert "&lt;class&gt;" in text
    assert "<class>" not in text
