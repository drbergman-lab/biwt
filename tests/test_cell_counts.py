"""CellCountsWindow behavior — the four count modes and their cross-syncing.

Driven headless against the real window; the ``qapp`` fixture lives in
conftest.py.
"""
from __future__ import annotations


import pytest

pytest.importorskip("PyQt5")

from biwt.gui.windows.cell_counts import CellCountsWindow
from helpers import window_at_rename



def _counts_window(zero_type=None):
    """CellCountsWindow driven to the non-spatial counts step on the CSV fixture.

    The fixture has 6 rows: Tumor 2, T_cell 3, Macrophage 1.
    """
    w = window_at_rename()
    s = w.session
    if zero_type:
        s.cell_counts[zero_type] = 0
    win = CellCountsWindow(w)
    win._rb_props.setChecked(True)
    win._mode_changed(1)
    return win


def _type_proportion(win, cell_type, value):
    """Type *value* into *cell_type*'s Proportion field the way a user would."""
    le = win._w_prop[cell_type]
    le.setText(str(value))
    le.textEdited.emit(str(value))


class TestProportionMode:
    """Editing one Proportion field rescales the others — except when it can't."""

    def test_editing_a_proportion_rescales_the_other_types(self, qapp):
        win = _counts_window()
        _type_proportion(win, "Tumor", 40)          # Tumor is 2 of 6 rows
        assert win._w_prop["T_cell"].text() == "60"
        assert win._w_prop["Macrophage"].text() == "20"

    def test_edited_row_stays_internally_consistent(self, qapp):
        """The sibling loop skips the edited row, so its own Manual field has to
        be mirrored explicitly or Manual/Confluence disagree with Proportion."""
        win = _counts_window()
        _type_proportion(win, "Tumor", 40)
        assert win._w_manual["Tumor"].text() == win._w_prop["Tumor"].text() == "40"

    def test_zero_share_row_is_also_consistent(self, qapp):
        win = _counts_window(zero_type="Macrophage")
        _type_proportion(win, "Macrophage", 7)
        assert win._w_manual["Macrophage"].text() == win._w_prop["Macrophage"].text() == "7"

    def test_zero_share_edit_does_not_zero_the_other_types(self, qapp):
        """A type with no share of the data implies nothing about the total, so
        scaling everyone by a multiplier derived from it would wipe the table."""
        win = _counts_window(zero_type="Macrophage")
        _type_proportion(win, "Macrophage", 7)
        assert win._w_prop["T_cell"].text() == "3"
        assert win._w_prop["Tumor"].text() == "2"
        assert win._w_manual["T_cell"].text() == "3"
        assert win._w_manual["Tumor"].text() == "2"


def test_a_long_cell_type_name_does_not_widen_the_counts_table(qapp):
    """The name column wraps instead of pushing the numeric columns off-screen."""
    from PyQt5.QtWidgets import QLabel

    from biwt.gui.widgets import ROW_LABEL_MAX_WIDTH

    long_name = "Epithelial-cancer" * 6
    win = _counts_window()
    s = win.walkthrough.session
    s.cell_types_list_final = [long_name]
    s.cell_counts = {long_name: 6}
    s.cell_volume = {long_name: 2494.0}
    rebuilt = CellCountsWindow(win.walkthrough)

    label = next(lbl for lbl in rebuilt.findChildren(QLabel) if lbl.text() == long_name)
    assert label.wordWrap()
    assert label.maximumWidth() == ROW_LABEL_MAX_WIDTH
