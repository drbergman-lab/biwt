"""RenameCellTypesWindow layout — a merged type's label must not run the window.

A merged cell type is labeled with *every* original name that fed it, so that
label's natural width is unbounded.  One such row used to dictate the width of
the whole window: the fields ended up misaligned and the merged row's own field
was squeezed to a stub behind a horizontal scrollbar.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QLabel

from biwt.gui.walkthrough import BioinformaticsWalkthrough
from biwt.gui.widgets import ROW_LABEL_MAX_WIDTH
from biwt.gui.windows.rename_cell_types import RenameCellTypesWindow
from biwt.types import BiwtInput, DomainSpec

DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

TYPES = ["B cell", "Endocrine", "Epithelial-cancer", "Fibroblast", "myCAF"]
MERGED = [
    "Epithelial-cancer",
    "Epithelial-cancer Basal",
    "Epithelial-cancer Classical",
    "Epithelial-unspecified",
    "Epithelial-unspecified Classical",
]


@pytest.fixture
def rename_window(qapp):
    """Factory for a shown RenameCellTypesWindow.

    Shown, because geometry is only laid out for a visible window — which is what
    the alignment assertions read. Teardown is the autouse `_reap_widgets`
    fixture in conftest.
    """

    def _make(merge=True):
        w = BioinformaticsWalkthrough(BiwtInput(preferred_domain=DOMAIN))
        s = w.session
        s.intermediate_types = list(TYPES)
        s.intermediate_type_pre_image = {ct: [ct] for ct in TYPES}
        if merge:
            s.intermediate_type_pre_image["Epithelial-cancer"] = list(MERGED)
        win = RenameCellTypesWindow(w)
        win.resize(700, 480)
        win.show()
        return win

    return _make


class TestRowLayout:
    def test_every_field_starts_at_the_same_x(self, qapp, rename_window):
        win = rename_window()
        qapp.processEvents()
        assert len({le.x() for le in win._line_edits.values()}) == 1

    def test_fields_align_even_without_a_long_label(self, qapp, rename_window):
        win = rename_window(merge=False)
        qapp.processEvents()
        assert len({le.x() for le in win._line_edits.values()}) == 1

    def test_the_window_is_narrower_than_its_longest_label_would_demand(self, qapp, rename_window):
        win = rename_window(merge=True)
        full = ", ".join(MERGED) + " ⇒ "
        natural = win.fontMetrics().horizontalAdvance(full)
        # The label column is capped, so the window is sized for the cap rather
        # than for the text — which is the whole point.
        assert win.sizeHint().width() < natural
        assert win.sizeHint().width() < 600

    def test_the_long_label_shows_every_name_by_wrapping(self, qapp, rename_window):
        win = rename_window()
        qapp.processEvents()
        label = win._labels["Epithelial-cancer"]
        # Nothing hidden: the label wraps inside its capped column, so the row
        # gets taller while the window stays the same width.
        for original in MERGED:
            assert original in label.text()
        assert label.wordWrap()
        assert label.maximumWidth() == ROW_LABEL_MAX_WIDTH
        assert label.height() > 2 * label.fontMetrics().height()

    def test_the_full_list_is_available_on_hover(self, qapp, rename_window):
        win = rename_window()
        tip = win._labels["Epithelial-cancer"].toolTip()
        for original in MERGED:
            assert original in tip

    def test_short_labels_are_left_alone(self, qapp, rename_window):
        win = rename_window()
        label = win._labels["Fibroblast"]
        assert label.text() == "Fibroblast"
        assert not label.wordWrap()
        assert label.toolTip() == ""       # nothing hidden, nothing to reveal

    def test_the_arrow_sits_beside_the_field_not_inside_the_label(self, qapp, rename_window):
        """Appended to the label, the ⇒ drifted to the end of the last wrapped
        line — visibly adrift from the field it points at."""
        from biwt.gui.widgets import ROW_ARROW

        win = rename_window()
        qapp.processEvents()
        assert ROW_ARROW not in win._labels["Epithelial-cancer"].text()

        arrows = [
            lbl for lbl in win.findChildren(QLabel) if lbl.text() == ROW_ARROW
        ]
        assert len(arrows) == len(TYPES)
        field = win._line_edits["Epithelial-cancer"]
        arrow = min(arrows, key=lambda a: abs(a.y() + a.height() // 2
                                              - (field.y() + field.height() // 2)))
        # Vertically centered on its field, and immediately to its left.
        assert abs((arrow.y() + arrow.height() // 2)
                   - (field.y() + field.height() // 2)) <= 2
        assert arrow.x() < field.x()


class TestRenamingStillWorks:
    def test_a_merged_group_maps_every_original_to_the_new_name(self, qapp, rename_window):
        win = rename_window()
        win._line_edits["Epithelial-cancer"].setText("tumor")
        win.walkthrough.advance = lambda: None
        win.walkthrough.session.cell_types_original = list(TYPES)
        win.process_window()

        mapping = win.walkthrough.session.cell_type_dict_on_rename
        assert {mapping[o] for o in MERGED} == {"tumor"}
        assert mapping["Fibroblast"] == "Fibroblast"


class TestLongLabelPrimitives:
    """Cell-type names come from the data and survive merging and renaming, so
    any of them can be arbitrarily long. Two shared helpers keep one long name
    from setting the width of whatever panel it lands in."""

    LONG = "Epithelial-cancer" * 6

    def test_a_wrapping_label_keeps_every_character(self, qapp):
        from biwt.gui.widgets import ROW_LABEL_MAX_WIDTH, row_label

        label = row_label(self.LONG)
        assert label.text() == self.LONG          # nothing dropped
        assert label.wordWrap()
        assert label.width() <= ROW_LABEL_MAX_WIDTH or label.maximumWidth() == ROW_LABEL_MAX_WIDTH

    def test_a_checkbox_is_elided_because_it_cannot_wrap(self, qapp):
        from PyQt5.QtWidgets import QCheckBox

        from biwt.gui.widgets import ROW_LABEL_MAX_WIDTH, set_elided_text

        cb = QCheckBox()
        set_elided_text(cb, self.LONG)
        assert cb.text() != self.LONG
        assert "…" in cb.text()
        assert cb.toolTip() == self.LONG          # the full name is a hover away
        assert cb.fontMetrics().horizontalAdvance(cb.text()) <= ROW_LABEL_MAX_WIDTH + 10

    def test_a_short_name_is_left_exactly_as_it_is(self, qapp):
        from PyQt5.QtWidgets import QCheckBox

        from biwt.gui.widgets import set_elided_text

        cb = QCheckBox()
        set_elided_text(cb, "Fibroblast")
        assert cb.text() == "Fibroblast"
        assert cb.toolTip() == ""

    def test_an_annotation_survives_the_ellipsis(self, qapp):
        """The edit step appends '⇒ Merge Gp. #2' and later reads it back off the
        label, so clipping must never eat it."""
        from PyQt5.QtWidgets import QCheckBox

        from biwt.gui.widgets import set_elided_text

        cb = QCheckBox()
        set_elided_text(cb, self.LONG, suffix=" ⇒ Merge Gp. #2")
        assert cb.text().endswith(" ⇒ Merge Gp. #2")
        assert "⇒ Merge Gp." in cb.text()
        assert cb.toolTip().endswith(" ⇒ Merge Gp. #2")
