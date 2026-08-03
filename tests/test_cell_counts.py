"""CellCountsWindow behavior — the four count modes and their cross-syncing.

Driven headless against the real window; the ``qapp`` fixture lives in
conftest.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt5")

from biwt.core import data_loader
from biwt.gui.walkthrough import BioinformaticsWalkthrough
from biwt.gui.windows.cell_counts import CellCountsWindow
from biwt.types import BiwtInput, DomainSpec

FIXTURES = Path(__file__).parent / "fixtures"
DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)


def _counts_window(zero_type=None):
    """CellCountsWindow driven to the non-spatial counts step on the CSV fixture.

    The fixture has 6 rows: Tumor 2, T_cell 3, Macrophage 1.
    """
    w = BioinformaticsWalkthrough(BiwtInput(preferred_domain=DOMAIN))
    s = w.session
    s.data = data_loader.load(str(FIXTURES / "nonspatial.csv"))
    s.current_column = "type"
    s.collect_cell_type_data()
    s.use_spatial_data = False
    s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
    s.compute_intermediate_types()
    s.cell_types_list_final = list(s.intermediate_types)
    s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
    s.apply_rename()
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
