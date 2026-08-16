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

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt5")
import matplotlib
matplotlib.use("Agg")
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from biwt.core.data_loader import (
    INSTALL_DOCS_URL,
    TROUBLESHOOTING_DOCS_URL,
    LoadError,
)
from biwt.types import DomainSpec

FIXTURES = Path(__file__).parent / "fixtures"
DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

CSV_FIXTURES = ["spatial.csv", "nonspatial.csv", "spot_deconv.csv", "spatial_pixels.csv"]


@pytest.fixture
def widget(make_widget):
    """The walkthrough widget alone; this module never reads the result."""
    return make_widget()[0]


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_import_builds_first_window(widget, drive_import, name):
    drive_import(widget, name)
    assert widget.session.data is not None
    assert widget.session.data.n_cells > 0
    assert widget.window is not None            # a step window was constructed


def test_import_anndata_builds_first_window(widget, drive_import, monkeypatch):
    pytest.importorskip("anndata")
    drive_import(widget, "test_AnnData.h5ad")
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


def test_dependency_error_dialog_links_to_docs(widget, drive_import, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)
    monkeypatch.setitem(sys.modules, "anndata2ri", None)

    drive_import(widget, "no_such_file.rds")

    assert len(boxes) == 1
    text = boxes[0].text()
    assert boxes[0].textFormat() == Qt.RichText
    assert f'<a href="{INSTALL_DOCS_URL}">' in text
    assert "biwt[seurat]" in text
    # Recoverable failure: the user stays in the wizard, nothing was loaded.
    assert widget.session.data is None


def test_file_error_dialog_has_no_docs_link(widget, drive_import, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)

    drive_import(widget, "unsupported.txt")

    assert len(boxes) == 1
    text = boxes[0].text()
    assert boxes[0].textFormat() == Qt.PlainText
    assert "<a href=" not in text
    assert "setup docs" not in text
    assert widget.session.data is None


def test_dialog_renders_whichever_docs_url_the_error_carries(widget, drive_import, monkeypatch):
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
    # ...and so does the grid legend, which names the primary column and its
    # parenthesized mirror rather than heading two separate columns.
    legend = next(t for t in labels if "<b>nanometer</b>" in t)
    assert "(pixel)" in legend


def test_error_message_is_html_escaped(widget, drive_import, monkeypatch):
    boxes = _capture_message_boxes(monkeypatch)

    widget._show_import_error(LoadError("bad <class> & 'quote'", docs_url=INSTALL_DOCS_URL))

    text = boxes[0].text()
    assert "&lt;class&gt;" in text
    assert "<class>" not in text


def test_finish_returns_cell_templates_and_no_xml(widget):
    """_finish hands the template triples straight through and builds no XML.

    Also the only coverage of the function-local imports _finish used to carry:
    a stale one would otherwise surface only at the very end of a real run.
    """
    got = []
    widget.on_complete = got.append
    widget.session.cell_templates = {
        "Tumor": ("/tmp/t.toml", "Tumor", "OPAQUE-TUMOR"),
    }
    widget._finish()

    result = got[0]
    assert result.cell_templates == {
        "Tumor": ("/tmp/t.toml", "Tumor", "OPAQUE-TUMOR"),
    }
    assert not hasattr(result, "cell_definitions_xml")


def test_finish_returns_the_cell_type_map(widget):
    """The host is promised an audit trail: every original label to its final
    name, None where the type was deleted.  It used to be empty on every run."""
    got = []
    widget.on_complete = got.append
    s = widget.session
    s.cell_types_list_original = ["Epithelial-cancer", "Epithelial-unspecified", "B cell"]
    s.cell_type_dict_on_rename = {
        "Epithelial-cancer": "tumor", "Epithelial-unspecified": "tumor",
    }
    widget._finish()

    assert got[0].cell_type_map == {
        "Epithelial-cancer": "tumor",
        "Epithelial-unspecified": "tumor",
        "B cell": None,
    }


def test_the_version_is_visible_on_the_home_screen(widget):
    """A host embeds BIWT as a tab, where no window title is ever shown, so the
    version has to be on the screen itself."""
    from PyQt5.QtWidgets import QLabel

    import biwt

    shown = " ".join(lbl.text() for lbl in widget.findChildren(QLabel))
    assert biwt.__version__ in shown
    assert biwt.__version__ in widget.windowTitle()


# ---------------------------------------------------------------------------
# The landing window
# ---------------------------------------------------------------------------


def test_a_chip_is_shown_for_every_format(widget):
    from biwt.core.data_loader import supported_formats

    shown = " ".join(_labels(widget))
    for fmt in supported_formats():
        assert fmt.label in shown


def test_an_unavailable_format_says_how_to_install_it(widget, drive_import, monkeypatch):
    """The point of the chips: BIWT used to reveal a missing dependency only
    after the user picked a file and read an error dialog."""
    from PyQt5.QtWidgets import QLabel

    from biwt.core.data_loader import INSTALL_DOCS_URL, supported_formats

    unavailable = [f for f in supported_formats() if not f.available]
    if not unavailable:
        pytest.skip("every optional data dependency is installed here")

    fmt = unavailable[0]
    chip = next(lbl for lbl in widget.findChildren(QLabel) if fmt.label in lbl.text())
    assert "✗" in chip.text()
    assert fmt.extra in chip.toolTip()
    assert INSTALL_DOCS_URL in chip.toolTip()


def test_the_landing_screen_pre_answers_nothing(widget):
    """Import is the only question on it; the rest of the wizard asks its own."""
    captions = " ".join(_labels(widget)).lower()
    assert "shortcuts" not in captions
    assert "cell-type column" not in captions
    assert not hasattr(widget, "column_line_edit")


def _drop(widget, *paths):
    from PyQt5.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt5.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(event)
    return event


def test_dropping_a_file_imports_it(widget):
    _drop(widget, FIXTURES / "nonspatial.csv")
    assert widget.session.data is not None
    assert widget.session.data.n_cells == 6
    assert widget.window is not None          # the walkthrough started


def test_dropping_an_unreadable_extension_does_nothing(widget, drive_import, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("nope")
    _drop(widget, junk)
    assert widget.session.data is None


def test_dropping_several_files_does_nothing(widget):
    _drop(widget, FIXTURES / "nonspatial.csv", FIXTURES / "spatial.csv")
    assert widget.session.data is None


def test_the_drop_zone_highlights_only_for_a_droppable_file(widget, drive_import, tmp_path):
    from PyQt5.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt5.QtGui import QDragEnterEvent

    def _drag(path):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDragEnterEvent(QPointF(10, 10).toPoint(), Qt.CopyAction, mime,
                                Qt.LeftButton, Qt.NoModifier)
        widget.dragEnterEvent(event)
        return event.isAccepted()

    junk = tmp_path / "notes.txt"
    junk.write_text("nope")
    assert _drag(FIXTURES / "nonspatial.csv")
    assert not _drag(junk)


def test_the_readme_quick_start_runs(qapp, tmp_path, monkeypatch):
    """Every line of the README's snippet, in order.

    It is the first code a new host runs, and nothing else in the suite touched
    ``apply_light_palette`` — a bad QPalette role there would raise on line one of
    a user's first attempt.
    """
    from biwt.core.positioning import build_ic_dataframe
    from biwt.gui.theme import apply_light_palette
    from biwt.gui.walkthrough import create_biwt_widget
    from biwt.types import BiwtInput, BiwtResult, DomainSpec

    domain = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500, units="micron")
    biwt_input = BiwtInput(preferred_domain=domain)

    written = []

    def on_complete(result):
        out = tmp_path / "cells.csv"
        result.to_csv(str(out))
        written.append(out)

    apply_light_palette(qapp)
    widget = create_biwt_widget(biwt_input, on_complete=on_complete)
    widget.show()

    # Then the callback's own body, on the empty result a Skip produces.
    on_complete(BiwtResult(
        coordinates=build_ic_dataframe({}), cell_type_map={}, domain_used=domain,
    ))
    assert written and written[0].exists()
    assert written[0].read_text().splitlines()[0] == "x,y,z,type"
