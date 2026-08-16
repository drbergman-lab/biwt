"""LoadCellTemplatesWindow — what the host gets back, and how to get nothing.

Driven headless against the real window; the ``qapp`` fixture lives in
conftest.py.  The .toml fixtures hold deliberately non-XML content, so a value
that arrives intact proves BIWT never interpreted it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QAbstractButton, QFileDialog, QInputDialog, QLabel, QMessageBox,
)

from biwt.core.templates import load_templates_from_file
from biwt.gui.windows.load_cell_templates import (
    _ICON_AUTO,
    _ICON_DEFAULT,
    _ICON_NONE,
    _NO_TEMPLATE,
    _NO_TEMPLATE_LABEL,
    LoadCellTemplatesWindow,
)
from helpers import (
    DOMAIN,
    FIXTURES,
    TEMPLATES_A,
    TEMPLATES_B,
    session_through_rename,
    window_at_rename,
)



def _templates_window(paths=(), rename=None, **biwt_input_kwargs):
    """The window driven to the cell-templates step on the non-spatial CSV fixture.

    That fixture's final cell types are Macrophage, T_cell and Tumor; *rename*
    maps any of them to a different final name.
    """
    w = window_at_rename(rename=rename, cell_template_paths=list(paths),
                         **biwt_input_kwargs)
    return LoadCellTemplatesWindow(w)


def _dropdown(win, cell_type):
    return next(dd for ct, dd in win._dropdowns if ct == cell_type)


def _select(win, cell_type, label_startswith):
    """Pick the first row whose label starts with *label_startswith*."""
    dd = _dropdown(win, cell_type)
    for row in range(win._model.rowCount()):
        if win._model.item(row).text().startswith(label_startswith):
            dd.setCurrentIndex(row)
            return row
    raise AssertionError(f"no row labeled {label_startswith!r}")


def _user_select(win, cell_type, label_startswith):
    """Pick a row the way a user does — including the activated signal.

    Programmatic setCurrentIndex emits currentIndexChanged but *not* activated,
    which is exactly how the window tells a user's choice from its own.
    """
    row = _select(win, cell_type, label_startswith)
    _dropdown(win, cell_type).activated.emit(row)
    return row


def _row_labels(win):
    return [win._model.item(r).text() for r in range(win._model.rowCount())]


def _add_file(win, monkeypatch, path):
    """Load *path* through the real Add-templates dialog path."""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(path)], "")),
    )
    win._add_templates_cb()


class TestNaming:
    def test_both_screens_call_them_cell_templates(self, qapp):
        """The library on the landing screen and the list at this step are the
        same objects, so they get the same name.  They had two — the landing
        screen said "Cell parameter templates" and the step "parameter
        templates" — which reads as two different things being loaded."""
        win = _templates_window([TEMPLATES_A])
        for widget in (win.walkthrough, win):
            # SectionHeader is a disabled QPushButton, so labels alone miss the
            # landing screen's heading — the one this test exists for.
            shown = " ".join(
                w.text()
                for kind in (QLabel, QAbstractButton)
                for w in widget.findChildren(kind)
            ).lower()
            assert "cell templates" in shown
            assert "parameter template" not in shown


class TestDefaultSelections:
    def test_name_matched_template_is_preselected(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Tumor"
        assert win.walkthrough.session.cell_templates["Macrophage"][1] == "Macrophage"

    def test_case_insensitive_match_is_preselected(self, qapp):
        # templates_b.toml offers "t_cell"; the data type is "T_cell".
        win = _templates_window([TEMPLATES_B])
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"

    def test_unmatched_type_falls_back_to_the_default_template(self, qapp):
        # templates_a.toml has no T_cell template, but does have "default".
        win = _templates_window([TEMPLATES_A])
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "default"

    def test_unmatched_type_without_a_default_is_unassigned(self, qapp):
        # templates_b.toml has no "default" and nothing matching Macrophage.
        win = _templates_window([TEMPLATES_B])
        assert "Macrophage" not in win.walkthrough.session.cell_templates

    def test_defaults_reach_the_session_before_continue_is_clicked(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert set(win.walkthrough.session.cell_templates) == {
            "Tumor", "Macrophage", "T_cell"
        }
        assert not win.walkthrough.session.templates_assigned

    def test_a_host_predicate_overrides_the_matching(self, qapp):
        # Match everything: types with no exact-named template take the
        # sorted-first one instead of falling back to "default".  An exact match
        # still wins outright — the predicate is never asked about it.
        win = _templates_window([TEMPLATES_A], name_matches=lambda a, b: True)
        chosen = {ct: e[1] for ct, e in win.walkthrough.session.cell_templates.items()}
        assert chosen == {
            "Macrophage": "Macrophage",
            "T_cell": "default",       # first in AaBbCc order
            "Tumor": "Tumor",
        }


class TestResultShape:
    def test_entry_is_path_name_content(self, qapp):
        win = _templates_window([TEMPLATES_A])
        path, name, content = win.walkthrough.session.cell_templates["Tumor"]
        assert name == "Tumor"
        assert content == "OPAQUE-A-TUMOR"
        assert path.endswith("templates_a.toml")

    def test_content_is_the_toml_value_verbatim(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _select(win, "Tumor", "default")
        assert win.walkthrough.session.cell_templates["Tumor"][2] == (
            "    OPAQUE-A-DEFAULT\n"
        )

    def test_path_is_absolute(self, qapp, monkeypatch):
        import os
        # chdir rather than a repo-root-relative literal: a path that misses opens a
        # blocking QMessageBox inside the constructor, so a wrong cwd hangs the run
        # instead of failing it.
        monkeypatch.chdir(FIXTURES)
        win = _templates_window(["templates_a.toml"])
        path = win.walkthrough.session.cell_templates["Tumor"][0]
        assert os.path.isabs(path)

    def test_order_follows_the_final_cell_types(self, qapp):
        win = _templates_window([TEMPLATES_A])
        s = win.walkthrough.session
        assert list(s.cell_templates) == [
            ct for ct in s.cell_types_list_final if ct in s.cell_templates
        ]


class TestNoneOption:
    def test_none_is_row_zero_in_by_name_mode(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert win._model.item(0).text() == _NO_TEMPLATE_LABEL
        assert win._model.item(0).data(Qt.UserRole) is _NO_TEMPLATE

    def test_none_is_row_zero_in_by_source_mode(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win._sort_toggled(1, True)
        assert win._model.item(0).text() == _NO_TEMPLATE_LABEL
        # The source header follows it, and is not selectable.
        assert win._model.item(1).data(Qt.UserRole) is None
        assert not (win._model.item(1).flags() & Qt.ItemIsSelectable)

    def test_selecting_none_removes_the_type_from_the_session(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert "Tumor" in win.walkthrough.session.cell_templates
        _dropdown(win, "Tumor").setCurrentIndex(0)
        templates = win.walkthrough.session.cell_templates
        assert "Tumor" not in templates          # absent, not None
        assert "Macrophage" in templates         # its neighbours are untouched

    def test_none_survives_a_sort_mode_switch(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _dropdown(win, "Tumor").setCurrentIndex(0)
        win._sort_toggled(1, True)               # By Source
        assert "Tumor" not in win.walkthrough.session.cell_templates
        win._sort_toggled(0, True)               # back to By Name
        assert "Tumor" not in win.walkthrough.session.cell_templates
        assert "Macrophage" in win.walkthrough.session.cell_templates


class TestSkip:
    def test_skip_assigns_no_templates_and_advances(self, qapp):
        win = _templates_window([TEMPLATES_A])
        advanced = []
        win.walkthrough.advance = lambda: advanced.append(True)
        win._skip_cb()
        assert win.walkthrough.session.cell_templates == {}
        assert win.walkthrough.session.templates_assigned
        assert advanced == [True]

    def test_skip_resets_every_dropdown_to_none(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win.walkthrough.advance = lambda: None
        win._skip_cb()
        # The screen must not show selections that contradict the empty result.
        assert all(dd.currentIndex() == 0 for _, dd in win._dropdowns)

    def test_continue_with_a_type_unassigned_does_not_warn(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        win.walkthrough.advance = lambda: None
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **k: warned.append(a)),
        )
        _dropdown(win, "Tumor").setCurrentIndex(0)
        win.process_window()
        assert warned == []
        assert win.walkthrough.session.templates_assigned
        assert "Tumor" not in win.walkthrough.session.cell_templates


class TestNoTemplatesAvailable:
    def test_window_builds_with_no_template_files(self, qapp):
        win = _templates_window([])
        assert _row_labels(win) == [_NO_TEMPLATE_LABEL]

    def test_every_dropdown_shows_none(self, qapp):
        win = _templates_window([])
        assert all(dd.currentText() == _NO_TEMPLATE_LABEL for _, dd in win._dropdowns)

    def test_continue_yields_an_empty_mapping(self, qapp):
        win = _templates_window([])
        win.walkthrough.advance = lambda: None
        win.process_window()
        assert win.walkthrough.session.cell_templates == {}
        assert win.walkthrough.session.templates_assigned


class TestSourceLabels:
    def test_one_file_shows_bare_names(self, qapp):
        win = _templates_window([TEMPLATES_A])
        # AaBbCc order, so "default" sorts among the capitalized names.
        assert _row_labels(win) == [_NO_TEMPLATE_LABEL, "default", "Macrophage", "Tumor"]

    def test_two_files_tag_every_entry_with_its_source(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        labels = _row_labels(win)[1:]
        assert all("templates_" in label for label in labels)
        assert "Tumor (templates_a.toml)" in labels
        assert "Tumor (templates_b.toml)" in labels


class TestSameNameInTwoFiles:
    def test_both_entries_are_offered(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        keys = [
            win._model.item(r).data(Qt.UserRole)
            for r in range(win._model.rowCount())
        ]
        tumor_paths = {k[1] for k in keys if isinstance(k, tuple) and k[0] == "Tumor"}
        assert len(tumor_paths) == 2

    def test_two_types_can_carry_the_same_name_from_different_files(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _select(win, "Tumor", "Tumor (templates_a.toml)")
        _select(win, "Macrophage", "Tumor (templates_b.toml)")
        entries = win.walkthrough.session.cell_templates
        assert entries["Tumor"][1] == entries["Macrophage"][1] == "Tumor"
        assert entries["Tumor"][0] != entries["Macrophage"][0]
        assert entries["Tumor"][2] == "OPAQUE-A-TUMOR"
        assert entries["Macrophage"][2] == "OPAQUE-B-TUMOR"

    def test_preselection_is_the_same_in_both_sort_modes(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        by_name = dict(win.walkthrough.session.cell_templates)
        win._sort_toggled(1, True)
        assert win.walkthrough.session.cell_templates == by_name


class TestRuntimeFileAdd:
    def test_added_templates_appear_in_the_model(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert "Tumor (templates_b.toml)" in _row_labels(win)

    def test_types_the_new_file_cannot_improve_are_left_where_they_were(
        self, qapp, monkeypatch
    ):
        win = _templates_window([TEMPLATES_A])
        before = dict(win.walkthrough.session.cell_templates)
        _add_file(win, monkeypatch, TEMPLATES_B)
        after = win.walkthrough.session.cell_templates
        # templates_b only improves T_cell (it adds "t_cell"); see
        # TestReMatchOnFileAdd for the merge rules themselves.
        assert {ct: after[ct] for ct in ("Tumor", "Macrophage")} == {
            ct: before[ct] for ct in ("Tumor", "Macrophage")
        }

    def test_the_same_file_twice_does_not_duplicate_entries(self, qapp, monkeypatch):
        # Re-added under a different spelling, which is what abspath normalizes.
        win = _templates_window([TEMPLATES_A])
        rows = _row_labels(win)
        monkeypatch.chdir(FIXTURES)
        _add_file(win, monkeypatch, "templates_a.toml")
        assert _row_labels(win) == rows

    def test_an_unreadable_file_warns_and_changes_nothing(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        rows = _row_labels(win)
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **k: warned.append(a)),
        )
        _add_file(win, monkeypatch, str(FIXTURES / "no_such_templates.toml"))
        assert warned
        assert _row_labels(win) == rows


class TestNoFrameworkSpecificChrome:
    def test_no_label_mentions_physicell_or_experimental(self, qapp):
        win = _templates_window([TEMPLATES_A])
        texts = " ".join(lbl.text() for lbl in win.findChildren(QLabel)).lower()
        assert "physicell" not in texts
        assert "experimental" not in texts


class TestBulkActions:
    def test_all_to_none_empties_the_mapping(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert win.walkthrough.session.cell_templates
        win._assign(_NO_TEMPLATE)
        assert win.walkthrough.session.cell_templates == {}
        assert all(dd.currentIndex() == 0 for _, dd in win._dropdowns)

    def test_all_to_default_assigns_the_default_template(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win._assign_baseline()
        chosen = {ct: e[1] for ct, e in win.walkthrough.session.cell_templates.items()}
        assert chosen == {"Macrophage": "default", "T_cell": "default", "Tumor": "default"}

    def test_all_to_default_is_disabled_without_a_default_template(self, qapp):
        # templates_b.toml has no "default".
        win = _templates_window([TEMPLATES_B])
        assert not win._default_btn.isEnabled()
        assert win._auto_btn.isEnabled()

    def test_bulk_buttons_are_disabled_with_no_templates(self, qapp):
        win = _templates_window([])
        assert not win._auto_btn.isEnabled()
        assert not win._default_btn.isEnabled()

    def test_auto_match_restores_the_computed_selection(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "Tumor", _NO_TEMPLATE_LABEL)
        assert "Tumor" not in win.walkthrough.session.cell_templates
        win._auto_match()
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Tumor"

    def test_auto_match_overrides_a_user_pick(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "Tumor", "Macrophage")
        win._auto_match()
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Tumor"

    def test_loading_a_default_template_enables_the_button(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_B])
        assert not win._default_btn.isEnabled()
        _add_file(win, monkeypatch, TEMPLATES_A)
        assert win._default_btn.isEnabled()


class TestReMatchOnFileAdd:
    """A newly loaded file can name a better match than anything on offer."""

    def test_untouched_type_picks_up_a_match_from_the_new_file(self, qapp, monkeypatch):
        # With templates_a alone, T_cell has no name match and falls back to
        # "default"; templates_b brings "t_cell", which does match.
        win = _templates_window([TEMPLATES_A])
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "default"
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"

    def test_a_user_picked_type_is_left_alone(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "T_cell", "Macrophage")
        _add_file(win, monkeypatch, TEMPLATES_B)
        # "t_cell" would have matched, but this row is the user's decision.
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "Macrophage"

    def test_an_explicit_none_is_left_alone(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "T_cell", _NO_TEMPLATE_LABEL)
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert "T_cell" not in win.walkthrough.session.cell_templates

    def test_untouched_neighbours_of_a_touched_type_still_refresh(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "Tumor", _NO_TEMPLATE_LABEL)
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert "Tumor" not in win.walkthrough.session.cell_templates
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"

    def test_bulk_actions_count_as_user_choices(self, qapp, monkeypatch):
        # "All to (none)" is a decision, so a later file load must not undo it.
        win = _templates_window([TEMPLATES_A])
        win._assign(_NO_TEMPLATE)
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert win.walkthrough.session.cell_templates == {}

    def test_auto_match_reopens_every_row_to_refreshing(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "T_cell", "Macrophage")
        win._auto_match()               # clears the divergence
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"

    def test_sorting_does_not_count_as_touching(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        win._sort_toggled(1, True)         # By Source
        win._sort_toggled(0, True)         # back to By Name
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"


class TestTouchedTracking:
    """The merge-on-file-add rule rests on telling a user's pick from our own.

    Driven with real input events rather than a hand-emitted signal, since the
    whole mechanism is the difference between QComboBox.activated (user only)
    and currentIndexChanged (both).
    """

    def test_a_real_keyboard_pick_marks_the_type_as_touched(self, qapp):
        win = _templates_window([TEMPLATES_A])
        dd = _dropdown(win, "Tumor")
        dd.setCurrentIndex(0)          # so Key_Down always has somewhere to go
        before = dd.currentIndex()
        QTest.keyClick(dd, Qt.Key_Down)
        assert dd.currentIndex() != before
        assert "Tumor" in win._touched

    def test_a_programmatic_change_does_not(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _dropdown(win, "Tumor").setCurrentIndex(0)
        assert "Tumor" not in win._touched

    def test_a_model_rebuild_does_not(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win._sort_toggled(1, True)
        assert win._touched == set()


class TestPerTypeActions:
    """The same three actions as the Set all row, scoped to one cell type."""

    def test_icons_pair_each_row_button_with_its_bulk_button(self, qapp):
        """The pairing is the icon, so it has to render identically at both
        scopes — comparing the drawn pixels, since two QIcons loaded from one
        file are different objects."""
        from PyQt5.QtCore import QSize

        def drawn(widget):
            return widget.icon().pixmap(QSize(18, 18)).toImage()

        win = _templates_window([TEMPLATES_A])
        assert drawn(win._row_auto["Tumor"]) == drawn(win._auto_btn)
        assert drawn(win._row_default["Tumor"]) == drawn(win._default_btn)

    def test_row_tooltips_name_the_action_and_nothing_else(self, qapp):
        # The "Set all" row above already pairs these glyphs with words, so a row
        # tooltip only has to say what the button does.
        win = _templates_window([TEMPLATES_A])
        for ct in ("Tumor", "T_cell", "Macrophage"):
            assert win._row_auto[ct].toolTip() == "Auto-match"
            assert win._row_default[ct].toolTip() == "Assign default"

    def test_none_one_clears_only_that_type(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win._assign(_NO_TEMPLATE, ["Tumor"])
        templates = win.walkthrough.session.cell_templates
        assert "Tumor" not in templates
        assert templates["Macrophage"][1] == "Macrophage"

    def test_default_one_assigns_only_that_type(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win._assign_baseline(["Tumor"])
        templates = win.walkthrough.session.cell_templates
        assert templates["Tumor"][1] == "default"
        assert templates["Macrophage"][1] == "Macrophage"

    def test_auto_match_one_restores_only_that_type(self, qapp):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "Tumor", "Macrophage")
        _user_select(win, "Macrophage", _NO_TEMPLATE_LABEL)
        win._auto_match(["Tumor"])
        templates = win.walkthrough.session.cell_templates
        assert templates["Tumor"][1] == "Tumor"          # recomputed
        assert "Macrophage" not in templates             # left as the user set it

    def test_default_one_and_none_one_count_as_user_choices(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        win._assign(_NO_TEMPLATE, ["T_cell"])
        _add_file(win, monkeypatch, TEMPLATES_B)
        # templates_b names a match for T_cell, but this row was a decision.
        assert "T_cell" not in win.walkthrough.session.cell_templates

    def test_auto_match_one_reopens_that_row_to_refreshing(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _user_select(win, "T_cell", "Macrophage")
        win._auto_match(["T_cell"])
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"

    def test_row_default_buttons_disabled_without_a_default_template(self, qapp):
        win = _templates_window([TEMPLATES_B])
        assert not win._row_default["Tumor"].isEnabled()
        assert win._row_auto["Tumor"].isEnabled()

    def test_row_buttons_disabled_with_no_templates(self, qapp):
        win = _templates_window([])
        assert not win._row_auto["Tumor"].isEnabled()
        assert not win._row_default["Tumor"].isEnabled()

    def test_loading_a_default_template_enables_the_row_buttons(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_B])
        assert not win._row_default["Tumor"].isEnabled()
        _add_file(win, monkeypatch, TEMPLATES_A)
        assert win._row_default["Tumor"].isEnabled()

    def test_clicking_a_row_button_works_end_to_end(self, qapp):
        # The wiring, not just the handler: real click on the real widget.
        win = _templates_window([TEMPLATES_A])
        QTest.mouseClick(win._row_default["Tumor"], Qt.LeftButton)
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "default"


def _write_toml(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return str(path)


def _remove_file(win, monkeypatch, label, ok=True):
    monkeypatch.setattr(
        QInputDialog, "getItem",
        staticmethod(lambda *a, **k: (label, ok)),
    )
    win._remove_templates_cb()


class TestAmbiguousDefault:
    """Two files defining 'default' means there is no single default."""

    def _second_default(self, tmp_path):
        return _write_toml(tmp_path, "other.toml", '"default" = "OPAQUE-OTHER-DEFAULT"\n')

    def test_default_buttons_are_withdrawn(self, qapp, monkeypatch, tmp_path):
        win = _templates_window([TEMPLATES_A])
        assert win._default_btn.isEnabled()
        _add_file(win, monkeypatch, self._second_default(tmp_path))
        assert not win._default_btn.isEnabled()
        assert not win._row_default["Tumor"].isEnabled()

    def test_the_disabled_button_explains_why(self, qapp, monkeypatch, tmp_path):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, self._second_default(tmp_path))
        for tip in (win._default_btn.toolTip(), win._row_default["Tumor"].toolTip()):
            assert tip == ("Multiple 'default' templates found. "
                           "Manually select which template to apply.")

    def test_the_fallback_tier_disappears(self, qapp, monkeypatch, tmp_path):
        # T_cell matches nothing in either file, so it had fallen back to
        # "default"; with two defaults it must go unassigned instead of guessing.
        win = _templates_window([TEMPLATES_A])
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "default"
        _add_file(win, monkeypatch, self._second_default(tmp_path))
        assert "T_cell" not in win.walkthrough.session.cell_templates

    def test_both_defaults_remain_individually_selectable(self, qapp, monkeypatch, tmp_path):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, self._second_default(tmp_path))
        labels = [lbl for lbl in _row_labels(win) if lbl.startswith("default")]
        assert len(labels) == 2
        _select(win, "T_cell", "default (other.toml)")
        assert win.walkthrough.session.cell_templates["T_cell"][2] == "OPAQUE-OTHER-DEFAULT"

    def test_removing_one_restores_the_default_action(self, qapp, monkeypatch, tmp_path):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, self._second_default(tmp_path))
        assert not win._default_btn.isEnabled()
        _remove_file(win, monkeypatch, "other.toml")
        assert win._default_btn.isEnabled()
        assert win._row_default["Tumor"].isEnabled()


class TestRemoveLibraryFile:
    def test_removing_a_file_drops_its_templates(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _remove_file(win, monkeypatch, "templates_b.toml")
        labels = _row_labels(win)
        assert not any("templates_b" in lbl for lbl in labels)
        assert any(lbl.startswith("Tumor") for lbl in labels)

    def test_a_row_using_the_removed_file_re_auto_matches(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        # T_cell matches "t_cell", which only templates_b provides.
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "t_cell"
        _remove_file(win, monkeypatch, "templates_b.toml")
        # Falls back to templates_a's "default" rather than keeping a dead key.
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "default"

    def test_a_user_pick_from_the_removed_file_is_not_silently_substituted(
        self, qapp, monkeypatch
    ):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _user_select(win, "Tumor", "Tumor (templates_b.toml)")
        _remove_file(win, monkeypatch, "templates_b.toml")
        entry = win.walkthrough.session.cell_templates.get("Tumor")
        # Re-auto-matched to the surviving Tumor template; never left pointing at
        # the removed file, and never holding templates_b content.
        assert entry is not None
        assert entry[0].endswith("templates_a.toml")
        assert entry[2] == "OPAQUE-A-TUMOR"

    def test_picks_from_surviving_files_are_kept(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _user_select(win, "Macrophage", "Macrophage")
        _remove_file(win, monkeypatch, "templates_b.toml")
        assert win.walkthrough.session.cell_templates["Macrophage"][1] == "Macrophage"

    def test_removing_the_last_file_empties_the_library(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _remove_file(win, monkeypatch, "templates_a.toml")
        assert _row_labels(win) == [_NO_TEMPLATE_LABEL]
        win.walkthrough.advance = lambda: None
        win.process_window()
        assert win.walkthrough.session.cell_templates == {}

    def test_a_host_supplied_file_can_be_removed(self, qapp, monkeypatch):
        # The host's library is a starting point, not a fixture the user is stuck with.
        win = _templates_window([TEMPLATES_A])
        _remove_file(win, monkeypatch, "templates_a.toml")
        assert win._template_db == {}

    def test_cancelling_the_dialog_changes_nothing(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        before = dict(win.walkthrough.session.cell_templates)
        rows = _row_labels(win)
        _remove_file(win, monkeypatch, "templates_a.toml", ok=False)
        assert _row_labels(win) == rows
        assert win.walkthrough.session.cell_templates == before

    def test_the_remove_button_is_disabled_with_no_files(self, qapp):
        assert not _templates_window([])._remove_btn.isEnabled()

    def test_the_remove_button_re_disables_after_the_last_removal(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        assert win._remove_btn.isEnabled()
        _remove_file(win, monkeypatch, "templates_a.toml")
        assert not win._remove_btn.isEnabled()


class TestLibrarySurvivesRebuilding:
    """Going back and changing an earlier step rebuilds this window.

    The user's library must not be collateral damage: only *Remove templates from
    file…* takes a file out.
    """

    def _rebuilt(self, win):
        """A fresh window on the same session, as advance() would build."""
        return LoadCellTemplatesWindow(win.walkthrough)

    def test_a_runtime_added_file_survives(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, TEMPLATES_B)
        assert any("templates_b" in lbl for lbl in _row_labels(win))

        again = self._rebuilt(win)
        assert any("templates_b" in lbl for lbl in _row_labels(again))

    def test_a_removal_survives(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _remove_file(win, monkeypatch, "templates_b.toml")

        again = self._rebuilt(win)
        assert not any("templates_b" in lbl for lbl in _row_labels(again))

    def test_removing_a_host_file_survives(self, qapp, monkeypatch):
        # The host re-passes cell_template_paths on every construction, so this
        # only works because the session records what is actually in play.
        win = _templates_window([TEMPLATES_A])
        _remove_file(win, monkeypatch, "templates_a.toml")
        assert self._rebuilt(win)._template_db == {}

    def test_a_removed_file_can_be_added_back(self, qapp, monkeypatch):
        """Removal is not a ban: nothing about the file is remembered, so the
        Add button takes it as it would any other."""
        win = _templates_window([TEMPLATES_A])
        _remove_file(win, monkeypatch, "templates_a.toml")
        assert win._template_db == {}

        _add_file(win, monkeypatch, TEMPLATES_A)
        assert any(lbl.startswith("Tumor") for lbl in _row_labels(win))
        assert self._rebuilt(win)._template_db != {}      # and it stays back

    def test_the_session_records_the_library(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A])
        _add_file(win, monkeypatch, TEMPLATES_B)
        paths = win.walkthrough.session.template_library_paths
        assert [p.split("/")[-1] for p in paths] == ["templates_a.toml", "templates_b.toml"]

    def test_an_unreadable_host_path_is_dropped_rather_than_re_warned(
        self, qapp, monkeypatch, tmp_path
    ):
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)),
        )
        win = _templates_window([TEMPLATES_A, str(tmp_path / "missing.toml")])
        assert len(warned) == 1
        assert win.walkthrough.session.template_library_paths == [
            p for p in win.walkthrough.session.template_library_paths if p.endswith("a.toml")
        ]
        self._rebuilt(win)
        assert len(warned) == 1          # not warned about again


class TestRowLayout:
    """One long cell-type name must not set the width of every row."""

    def test_every_dropdown_starts_at_the_same_x(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win.show()
        qapp.processEvents()
        assert len({dd.x() for _, dd in win._dropdowns}) == 1

    def test_a_long_cell_type_name_wraps_instead_of_widening_the_row(self, qapp):
        from biwt.gui.widgets import ROW_LABEL_MAX_WIDTH

        win = _templates_window([TEMPLATES_A])
        long_name = "Epithelial-cancer Basal Classical unspecified subtype 4"
        win.walkthrough.session.cell_types_list_final = [long_name]
        rebuilt = LoadCellTemplatesWindow(win.walkthrough)
        label = next(
            lbl for lbl in rebuilt.findChildren(QLabel) if lbl.text() == long_name
        )
        # Every character is still on screen; the row grows taller, not wider.
        assert long_name in label.text()
        assert label.wordWrap()
        assert label.maximumWidth() == ROW_LABEL_MAX_WIDTH


class TestTiedTemplateNames:
    """Two files can both define 'Tumor'; matching then has no reason to prefer
    either, so the row says so instead of looking decided."""

    def test_a_tie_is_flagged_on_the_marker(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        # Only what the screen does not already say: the dropdown label reads
        # "Tumor (templates_a.toml)", so the notice names the other file.
        assert win._row_flag["Tumor"].toolTip() == (
            "'Tumor' also defined by templates_b.toml."
        )

    def test_the_dropdown_carries_no_second_copy_of_the_notice(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        assert _dropdown(win, "Tumor").toolTip() == ""

    def test_the_flag_names_the_alternative_not_the_chosen_one(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        _select(win, "Tumor", "Tumor (templates_b.toml)")
        assert win._row_flag["Tumor"].toolTip() == (
            "'Tumor' also defined by templates_a.toml."
        )

    def test_an_unambiguous_name_is_not_flagged(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        # "Macrophage" and "t_cell" each come from one file only.
        assert win._row_flag["Macrophage"].toolTip() == ""
        assert win._row_flag["T_cell"].toolTip() == ""

    def test_a_marker_appears_beside_the_ambiguous_row(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win.show()
        qapp.processEvents()
        assert win._row_flag["Tumor"].isVisible()
        assert not win._row_flag["Macrophage"].isVisible()

    def test_clicking_the_marker_dismisses_it(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win.show()
        qapp.processEvents()
        QTest.mouseClick(win._row_flag["Tumor"], Qt.LeftButton)
        assert not win._row_flag["Tumor"].isVisible()

    def test_a_dismissed_marker_returns_while_the_row_is_still_ambiguous(self, qapp):
        """No 'already silenced' memory: the flag is recomputed from scratch."""
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win.show()
        qapp.processEvents()
        QTest.mouseClick(win._row_flag["Tumor"], Qt.LeftButton)
        assert not win._row_flag["Tumor"].isVisible()

        # Any change refreshes the flags — here, a different row entirely.
        _select(win, "Macrophage", _NO_TEMPLATE_LABEL)
        qapp.processEvents()
        assert win._row_flag["Tumor"].isVisible()

    def test_the_marker_stays_gone_once_the_tie_is_resolved(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win.show()
        qapp.processEvents()
        assert win._row_flag["Tumor"].isVisible()
        _remove_file(win, monkeypatch, "templates_b.toml")
        qapp.processEvents()
        assert not win._row_flag["Tumor"].isVisible()

    def test_no_markers_with_a_single_library(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win.show()
        qapp.processEvents()
        assert not any(f.isVisible() for f in win._row_flag.values())

    def test_the_flag_clears_when_the_other_file_is_removed(self, qapp, monkeypatch):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        assert win._row_flag["Tumor"].toolTip()
        _remove_file(win, monkeypatch, "templates_b.toml")
        assert win._row_flag["Tumor"].toolTip() == ""


def _drop_templates(win, *paths):
    from PyQt5.QtCore import QMimeData, QPointF, QUrl
    from PyQt5.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    win.dropEvent(event)
    return event


class TestDroppingLibraries:
    """Several libraries at once is the point: they accumulate, unlike the data
    file on the landing screen, where a second file would replace the session."""

    def test_dropping_two_files_loads_both(self, qapp, tmp_path):
        extra = _write_toml(tmp_path, "extra.toml", '"Neutrophil" = "OPAQUE-N"\n')
        win = _templates_window([])
        _drop_templates(win, TEMPLATES_A, extra)

        labels = " ".join(_row_labels(win))
        assert "Tumor" in labels and "Neutrophil" in labels
        assert len(win.walkthrough.session.template_library_paths) == 2

    def test_matching_happens_once_against_the_finished_library(self, qapp, tmp_path):
        """Not once per file: a type must not be decided by an early file and
        then left behind when a better match arrives in the same drop."""
        better = _write_toml(tmp_path, "better.toml", '"T_cell" = "OPAQUE-EXACT"\n')
        win = _templates_window([])
        _drop_templates(win, TEMPLATES_A, better)

        # templates_a would have given T_cell the "default" fallback on its own.
        assert win.walkthrough.session.cell_templates["T_cell"][1] == "T_cell"

    def test_an_unreadable_file_does_not_stop_the_others(self, qapp, tmp_path, monkeypatch):
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)),
        )
        broken = _write_toml(tmp_path, "broken.toml", '"Tumor" = ')
        win = _templates_window([])
        _drop_templates(win, broken, TEMPLATES_A)

        assert warned
        assert any(lbl.startswith("Tumor") for lbl in _row_labels(win))

    def test_non_toml_files_are_ignored(self, qapp, tmp_path):
        junk = tmp_path / "notes.txt"
        junk.write_text("nope")
        win = _templates_window([])
        _drop_templates(win, junk)
        assert win._template_db == {}

    def test_a_drop_survives_the_window_being_rebuilt(self, qapp):
        win = _templates_window([])
        _drop_templates(win, TEMPLATES_A)
        rebuilt = LoadCellTemplatesWindow(win.walkthrough)
        assert rebuilt._template_db != {}

    def test_dragging_a_toml_highlights_the_hint(self, qapp, tmp_path):
        from PyQt5.QtCore import QMimeData, QPointF, QUrl
        from PyQt5.QtGui import QDragEnterEvent

        def _drag(path):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            event = QDragEnterEvent(QPointF(10, 10).toPoint(), Qt.CopyAction, mime,
                                    Qt.LeftButton, Qt.NoModifier)
            win.dragEnterEvent(event)
            return event.isAccepted()

        junk = tmp_path / "notes.txt"
        junk.write_text("nope")
        win = _templates_window([])
        assert _drag(TEMPLATES_A)
        assert not _drag(junk)

    def test_the_button_remains_the_route_that_always_works(self, qapp, monkeypatch):
        """A streamed remote session never delivers a drop, so the dialog must
        stay — and must accept several files, like the drop does."""
        called = {}
        monkeypatch.setattr(
            QFileDialog, "getOpenFileNames",
            staticmethod(lambda *a, **k: called.setdefault("hit", True) and None
                         or ([TEMPLATES_A, TEMPLATES_B], "")),
        )
        win = _templates_window([])
        win._add_templates_cb()
        assert called
        assert len(win.walkthrough.session.template_library_paths) == 2


class TestRowButtonSizing:
    """The glyphs must be readable without the rows growing to fit them."""

    def test_a_button_is_never_taller_than_its_dropdown(self, qapp):
        win = _templates_window([TEMPLATES_A])
        win.show()
        qapp.processEvents()
        for ct, dd in win._dropdowns:
            assert win._row_auto[ct].height() <= dd.height()
            assert win._row_default[ct].height() <= dd.height()

    def test_every_action_icon_loads(self, qapp):
        """A missing or unparseable SVG yields a null QIcon and a blank button —
        silent, and invisible to every other test here."""
        from biwt.gui.widgets import action_icon

        for name in (_ICON_AUTO, _ICON_DEFAULT, _ICON_NONE):
            assert not action_icon(name).isNull()

    def test_the_three_actions_look_different(self, qapp):
        """Guards the copy-paste failure: three buttons wired to one icon."""
        from PyQt5.QtCore import QSize

        from biwt.gui.widgets import action_icon

        drawn = [action_icon(n).pixmap(QSize(18, 18)).toImage()
                 for n in (_ICON_AUTO, _ICON_DEFAULT, _ICON_NONE)]
        assert drawn[0] != drawn[1] and drawn[1] != drawn[2] and drawn[0] != drawn[2]

    def test_the_row_buttons_carry_an_icon_and_no_text(self, qapp):
        win = _templates_window([TEMPLATES_A])
        btn = win._row_default["Tumor"]
        assert btn.text() == ""
        assert not btn.icon().isNull()


class TestSourceStaysVisibleWhenTheListCloses:
    """A closed combo box shows only its current item's text.

    Under a By Source header an item needs no file name; closed, it has no header
    to lean on. The box therefore paints a fuller label than the model carries —
    the popup stays uncluttered and the selection still names its source.
    """

    def test_by_source_paints_the_source_although_the_item_omits_it(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win._sort_toggled(1, True)                       # By Source
        dd = _dropdown(win, "Tumor")
        assert "templates_a.toml" not in dd.currentText()      # the popup item
        assert "templates_a.toml" in dd.displayed_text()       # what is drawn

    def test_both_sort_modes_read_the_same_when_closed(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        by_name = _dropdown(win, "Tumor").displayed_text()
        win._sort_toggled(1, True)
        assert _dropdown(win, "Tumor").displayed_text() == by_name

    def test_a_single_library_stays_uncluttered_in_both_modes(self, qapp):
        win = _templates_window([TEMPLATES_A])
        assert _dropdown(win, "Tumor").displayed_text() == "Tumor"
        win._sort_toggled(1, True)
        assert _dropdown(win, "Tumor").displayed_text() == "Tumor"

    def test_the_popup_keeps_bare_names_under_its_headers(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win._sort_toggled(1, True)
        labels = _row_labels(win)
        assert "templates_a.toml" in labels                    # the header
        assert "\u2003Tumor" in labels                          # the item, unadorned

    def test_the_none_row_is_left_alone(self, qapp):
        win = _templates_window([TEMPLATES_A])
        dd = _dropdown(win, "Tumor")
        dd.setCurrentIndex(0)
        assert dd.displayed_text() == _NO_TEMPLATE_LABEL

    def test_the_source_is_a_separate_right_aligned_half(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        assert _dropdown(win, "Tumor").displayed_parts() == ("Tumor", "templates_a.toml")

    def test_a_roomy_box_shows_both_halves(self, qapp):
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        assert _dropdown(win, "Tumor").text_layout(400) == ("Tumor", "templates_a.toml")

    def test_a_narrow_box_keeps_the_name_and_drops_the_source(self, qapp):
        """The name is what identifies the choice; a half-elided path qualifies
        nothing, so the qualifier is what goes."""
        primary, secondary = _dropdown(
            _templates_window([TEMPLATES_A, TEMPLATES_B]), "Tumor"
        ).text_layout(120)
        assert secondary == ""
        assert primary == "Tumor"

    def test_a_very_narrow_box_elides_the_name_itself(self, qapp):
        primary, secondary = _dropdown(
            _templates_window([TEMPLATES_A, TEMPLATES_B]), "Macrophage"
        ).text_layout(40)
        assert secondary == ""
        assert primary != "Macrophage" and primary.endswith("…")

    def test_both_halves_of_the_label_reach_the_screen(self, qapp):
        """Guards the override itself: `displayed_text()` can be right while
        `paintEvent` draws something else.

        Differential, and against the same widget: comparing one combo's pixels to
        another's only proves *something* differs, so it survived deleting either
        `drawText` call — including the secondary, which is the whole reason this
        class exists. Changing one half at a time and requiring the pixels to move
        is what pins each of them.
        """
        win = _templates_window([TEMPLATES_A, TEMPLATES_B])
        win._sort_toggled(1, True)
        win.show()
        qapp.processEvents()
        dd = _dropdown(win, "Tumor")
        primary, secondary = dd.displayed_parts()
        assert primary and secondary            # the case worth testing
        original = dd.display_for_index

        def grab_with(parts):
            dd.display_for_index = lambda _idx: parts
            dd.update()
            qapp.processEvents()
            return dd.grab().toImage()

        try:
            baseline = grab_with((primary, secondary))
            assert grab_with(("Zzzzzz", secondary)) != baseline    # primary drawn
            assert grab_with((primary, "zzzzzz.toml")) != baseline  # secondary drawn
        finally:
            dd.display_for_index = original


class TestHostDefinedCellTypes:
    """``BiwtInput.host_cell_type_names`` as template candidates.

    A type the host already defines is an answer to "what parameters should this
    cell type have?" — arguably the best one — so the names join the dropdown. They
    carry no content, and come back under a reserved source so the host can tell
    them apart from a template it has to build something from.
    """

    def test_a_host_cell_type_is_offered_and_qualified(self, qapp):
        win = _templates_window(host_cell_type_names=["Tumor", "CD8 T cell"])
        labels = _row_labels(win)
        assert "Tumor (Host)" in labels
        assert "CD8 T cell (Host)" in labels

    def test_the_qualifier_is_the_host_name_not_the_sentinel(self, qapp):
        win = _templates_window(host_cell_type_names=["Tumor"], host_name="Studio")
        assert "Tumor (Studio)" in _row_labels(win)
        assert not any("<host>" in lbl for lbl in _row_labels(win))

    def test_the_host_qualifier_survives_being_the_only_source(self, qapp):
        """A file qualifier is dropped when there is nothing to disambiguate.

        A host qualifier is not: it distinguishes "a type you already have" from
        "a template", which is information even when it is the only source.
        """
        win = _templates_window(host_cell_type_names=["Tumor"])
        assert win._source_paths() == ["<host>"]
        assert "Tumor (Host)" in _row_labels(win)

    def test_it_matches_and_comes_back_under_the_reserved_source(self, qapp):
        from biwt.types import HOST_SOURCE

        win = _templates_window(host_cell_type_names=["Tumor"], host_name="Studio")
        win.process_window()
        assert win.walkthrough.session.cell_templates["Tumor"] == (
            HOST_SOURCE, "Tumor", "",
        )

    def test_the_sentinel_could_never_be_a_real_path(self, qapp):
        from biwt.types import HOST_SOURCE

        # A host that forgets to check should fail loudly, not read some file.
        assert not Path(HOST_SOURCE).exists()
        assert set("<>") & set(HOST_SOURCE)

    def test_it_matches_on_equal_footing_with_a_file_template(self, qapp):
        """Both sources feed one candidate pool.

        The host name matches a type no library covers, and the library still
        matches the types the host does not name.
        """
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["T_cell"])
        win.process_window()
        templates = win.walkthrough.session.cell_templates
        assert templates["T_cell"][0] == "<host>"
        assert templates["Tumor"][0] == TEMPLATES_A

    def test_the_host_wins_a_same_name_tie(self, qapp):
        """"Your model already has this type" beats "here is a template for one".

        No scoring needed: a name is either the host's or it is not, so among the
        sources offering one name there is exactly one to put first.
        """
        from biwt.types import HOST_SOURCE

        win = _templates_window([TEMPLATES_A], host_cell_type_names=["Tumor"],
                             host_name="Studio")
        win.process_window()
        assert win.walkthrough.session.cell_templates["Tumor"][0] == HOST_SOURCE
        # The file template is still there, still selectable, and the row says so.
        assert "Tumor (templates_a.toml)" in _row_labels(win)
        assert win._row_flag["Tumor"].toolTip() == (
            "'Tumor' also defined by templates_a.toml."
        )

    def test_the_host_is_listed_first_in_by_source_mode(self, qapp):
        """Display order follows the preference, so the winning group leads."""
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["Tumor"],
                             host_name="Studio")
        assert win._source_paths()[0] == "<host>"
        win._sort_toggled(1, True)
        headers = [lbl for lbl in _row_labels(win)
                   if lbl in {"Studio", "templates_a.toml"}]
        assert headers == ["Studio", "templates_a.toml"]

    def test_a_file_template_still_wins_where_the_host_has_no_such_type(self, qapp):
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["Tumor"])
        win.process_window()
        assert win.walkthrough.session.cell_templates["Macrophage"][0] == TEMPLATES_A

    def test_host_types_are_not_removable(self, qapp, monkeypatch):
        win = _templates_window(host_cell_type_names=["Tumor"], host_name="Studio")
        # Nothing was loaded from a file, so there is nothing to unload.
        assert win._library_paths() == []
        assert win._remove_btn.isEnabled() is False

        offered = []
        monkeypatch.setattr(
            QInputDialog, "getItem",
            staticmethod(lambda *a, **k: (offered.extend(a[3]), ("", False))[1]),
        )
        win._remove_templates_cb()
        assert offered == []

    def test_the_hosts_default_is_the_baseline(self, qapp):
        """`default` means "the host's baseline" when the host has one.

        A library `default` is a generic starting point; the host's is that host's
        actual default cell type, which is what the action is asking for.
        """
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["default"])
        assert win._baseline_key() == ("default", "<host>")

        win._assign_baseline()
        win.process_window()
        assert {v[0] for v in win.walkthrough.session.cell_templates.values()} == {
            "<host>"
        }

    def test_the_hosts_default_settles_two_library_defaults(self, qapp, tmp_path):
        """Ambiguity that used to withdraw the action now has an answer.

        Two libraries each defining `default` leaves neither as *the* baseline, so
        the action is normally withdrawn. A host `default` outranks both, so the
        buttons stay enabled and point at it.
        """
        second = _write_toml(tmp_path, "other.toml", '"default" = "OPAQUE-OTHER"')
        win = _templates_window([TEMPLATES_A, second], host_cell_type_names=["default"])
        assert win._default_btn.isEnabled() is True
        assert all(b.isEnabled() for b in win._row_default.values())
        assert win._baseline_key() == ("default", "<host>")

    def test_two_library_defaults_without_a_host_one_are_still_ambiguous(
        self, qapp, tmp_path
    ):
        second = _write_toml(tmp_path, "other.toml", '"default" = "OPAQUE-OTHER"')
        win = _templates_window([TEMPLATES_A, second])
        assert win._baseline_key() is None
        assert win._default_btn.isEnabled() is False

    def test_the_hosts_default_supplies_the_auto_match_fallback(self, qapp):
        """Auto-match and the `default` action must not disagree about `default`."""
        win = _templates_window([TEMPLATES_B], host_cell_type_names=["default"])
        win.process_window()
        # Macrophage matches nothing in templates_b, so it takes the baseline —
        # which templates_b does not supply, but the host does.
        assert win.walkthrough.session.cell_templates["Macrophage"] == (
            "<host>", "default", "",
        )
        assert win._default_btn.isEnabled() is True

    def test_without_a_host_default_an_unmatched_type_stays_unset(self, qapp):
        win = _templates_window([TEMPLATES_B], host_cell_type_names=["Tumor"])
        win.process_window()
        assert "Macrophage" not in win.walkthrough.session.cell_templates
        assert win._default_btn.isEnabled() is False

    def test_unusable_host_names_are_dropped(self, qapp):
        """A host list is arbitrary input: blanks, repeats and non-strings.

        Asserting the whole row list, not just the rows mentioning Tumor — filtering
        made the blank entries invisible to the assertion, and they were reaching the
        model as selectable rows that handed the host `(HOST_SOURCE, '', '')`.
        `None` is the load-bearing case: it reaches `casefold()` while sorting.
        """
        from biwt.types import HOST_SOURCE

        win = _templates_window(
            host_cell_type_names=["Tumor", "Tumor", "", "   ", None]
        )
        assert _row_labels(win) == [_NO_TEMPLATE_LABEL, "Tumor (Host)"]
        assert sorted(win._template_db) == [("Tumor", HOST_SOURCE)]

    def test_by_source_mode_groups_them_under_the_host_name(self, qapp):
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["CD8 T cell"],
                             host_name="Studio")
        win._sort_toggled(1, True)
        assert "Studio" in _row_labels(win)          # a group header

    def test_a_blank_host_name_still_reads_as_something(self, qapp):
        """`host_name` reaches the screen, so a host passing "" must not show `Tumor ()`."""
        win = _templates_window(host_cell_type_names=["Tumor"], host_name="   ")
        assert "Tumor (Host)" in _row_labels(win)

    def test_a_matching_name_from_another_source_is_flagged(self, qapp):
        """The marker is about matching, not about identical spelling.

        `tumor` from the host and `Tumor` from a library are one contest; the
        marker names the rival's spelling too, since the dropdown does not show it.
        """
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["tumor"])
        assert win._row_flag["Tumor"].toolTip() == (
            "'tumor' also defined by templates_a.toml (as 'Tumor')."
        )

    def test_the_fallback_takes_the_host_default_and_names_the_library(self, qapp):
        """T_cell matches nothing in templates_a, so it takes the baseline."""
        win = _templates_window([TEMPLATES_A], host_cell_type_names=["default"])
        assert win.walkthrough.session.cell_templates["T_cell"][0] == "<host>"
        assert win._row_flag["T_cell"].toolTip() == (
            "'default' also defined by templates_a.toml."
        )

    def test_a_type_actually_named_default_still_prefers_the_host(self, qapp):
        """The exclusion is about the fallback tier, not about the name.

        Where `default` is a real match for the cell type, the host wins it like
        any other name — and the library entry is then the flagged rival.
        """
        win = _templates_window([TEMPLATES_A], rename={"Tumor": "default"},
                             host_cell_type_names=["default"])
        win.process_window()
        assert win.walkthrough.session.cell_templates["default"][0] == "<host>"
        assert win._row_flag["default"].toolTip() == (
            "'default' also defined by templates_a.toml."
        )


class TestBadPathsAreReportedOnce:
    def test_a_batch_of_unreadable_paths_gives_one_dialog(self, qapp, monkeypatch):
        """A modal per bad path has to be dismissed before the step will open.

        `list("some/path.toml")` — a host meaning to pass one path — produces one
        bad path per character, which is how this was found.  A bare string is
        repaired to one path now, but a list of junk still has to arrive as one
        complaint.
        """
        shown = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: shown.append(a[2])))
        bad = list("tests/fixtures/templates_z.toml")
        win = _templates_window(bad)

        assert len(shown) == 1
        assert f"Could not load {len(set(bad))} template files" in shown[0]
        assert win._template_db == {}          # nothing loaded, step still opens

    def test_one_bad_path_still_names_it(self, qapp, monkeypatch):
        shown = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: shown.append(a[2])))
        _templates_window(["/no/such/file.toml"])

        assert len(shown) == 1
        assert "Could not load template file" in shown[0]
        assert "/no/such/file.toml" in shown[0]


class TestReAddingAnEditedFile:
    def test_the_file_replaces_what_it_contributed_before(self, qapp, monkeypatch, tmp_path):
        """Adding a file must show that file as it is now, not merged with what
        it held last time — a template deleted from it would otherwise linger."""
        path = tmp_path / "lib.toml"
        path.write_text('"Alpha" = "A"\n"Beta" = "B"\n')
        win = _templates_window([str(path)])
        assert {n for n, _ in win._template_db} == {"Alpha", "Beta"}

        path.write_text('"Beta" = "B2"\n"Gamma" = "G"\n')     # Alpha deleted
        _add_file(win, monkeypatch, str(path))

        assert {n for n, _ in win._template_db} == {"Beta", "Gamma"}
        assert win._template_db[("Beta", str(path))] == "B2"


class TestAPickStrandedByAnEditedFile:
    """The file no longer offers the template a cell type was pointing at.

    Not matching it any more is the intended behaviour — nothing should invent a
    template that is gone. What was untested is that the row actually lets go of
    it: a stale pick left in ``_touched`` would be treated as the user's own
    choice and preserved against a key no longer in the model.
    """

    def test_the_row_lets_go_and_re_matches(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "lib.toml"
        # "Extra" is what the user picks by hand; "Tumor" is what name matching
        # would choose on its own.
        path.write_text('"Tumor" = "T"\n"Extra" = "X"\n')
        win = _templates_window([str(path)])
        _user_select(win, "Tumor", "Extra")
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Extra"
        assert "Tumor" in win._touched

        path.write_text('"Tumor" = "T"\n')                 # Extra deleted
        _add_file(win, monkeypatch, str(path))

        assert ("Extra", str(path)) not in win._template_db
        # Back to the name match rather than stuck on a template that is gone.
        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Tumor"
        assert "Tumor" not in win._touched

    def test_a_pick_the_file_still_offers_is_kept(self, qapp, monkeypatch, tmp_path):
        """The discard must be conditional, or every re-add would throw away the
        user's choices."""
        path = tmp_path / "lib.toml"
        path.write_text('"Tumor" = "T"\n"Extra" = "X"\n')
        win = _templates_window([str(path)])
        _user_select(win, "Tumor", "Extra")

        path.write_text('"Tumor" = "T"\n"Extra" = "X2"\n')   # Extra survives
        _add_file(win, monkeypatch, str(path))

        assert win.walkthrough.session.cell_templates["Tumor"][1] == "Extra"
        assert win.walkthrough.session.cell_templates["Tumor"][2] == "X2"
        assert "Tumor" in win._touched


class TestLibraryPathsAreDeduplicated:
    def test_the_same_file_under_two_spellings_is_one_entry(self, qapp, monkeypatch):
        """Two entries for one file left Remove taking out only one of them, so the
        templates came back on the next rebuild."""
        from PyQt5.QtWidgets import QInputDialog

        twice = [TEMPLATES_A, str(FIXTURES) + "/./templates_a.toml"]
        win = _templates_window(twice)
        s = win.walkthrough.session
        assert len(s.template_library_paths) == 1

        label = win._source_display_names()[s.template_library_paths[0]]
        monkeypatch.setattr(QInputDialog, "getItem",
                            staticmethod(lambda *a, **k: (label, True)))
        win._remove_templates_cb()

        assert s.template_library_paths == []
        assert win._template_db == {}


class TestSourcesLineUpInAColumn:
    """By Name draws the name left and the file right, so files share an edge.

    The failure this guards is subtle: right-aligning inside
    ``SE_ItemViewItemText`` looks correct but changes nothing, because that rect
    is sized to each row's own text. It only shows up with files of *different*
    name lengths — with equal-length names a ragged left edge and an aligned
    right edge are indistinguishable.
    """

    @staticmethod
    def _two_libraries(tmp_path):
        short = tmp_path / "a.toml"
        short.write_text('"Tumor" = "T"\n"default" = "D"\n')
        long = tmp_path / "much_longer_library_name.toml"
        long.write_text('"Macrophage" = "M"\n"T_cell" = "C"\n')
        return _templates_window([str(short), str(long)]), short, long

    def _layouts(self, win):
        """``{name: (primary, secondary)}`` as the popup actually draws them."""
        from PyQt5.QtWidgets import QStyleOptionViewItem

        dd = win._dropdowns[0][1]
        view = dd.view()
        view.resize(win._fitted_dropdown_width(), view.height())
        delegate = dd.itemDelegate()
        out = {}
        for row in range(win._model.rowCount()):
            index = win._model.index(row, 0)
            parts = win._popup_parts(index)
            if not parts:
                continue
            opt = QStyleOptionViewItem()
            opt.initFrom(view)
            opt.rect = view.visualRect(index)
            out[parts[0]] = delegate.row_layout(opt, index)
        return out

    def test_the_band_does_not_depend_on_the_row_content(self, qapp, tmp_path):
        """Alignment *is* a shared drawing band.

        Given one row rect, every row must be drawn in the same band — otherwise
        right-aligning inside it reproduces the ragged edge it was meant to fix.
        Qt hands every row of a list the same rect, so this is the whole of it.
        Deliberately not measured through ``visualRect``: that reflects each row's
        own size hint and the view's layout state, neither of which is the
        delegate's behaviour.
        """
        from PyQt5.QtCore import QRect
        from PyQt5.QtWidgets import QStyleOptionViewItem

        win, _, _ = self._two_libraries(tmp_path)
        dd = win._dropdowns[0][1]
        view = dd.view()
        delegate = dd.itemDelegate()
        row_rect = QRect(0, 0, 400, 20)          # one rect, as Qt would pass it

        bands = {}
        for row in range(win._model.rowCount()):
            index = win._model.index(row, 0)
            parts = win._popup_parts(index)
            if not parts:
                continue
            opt = QStyleOptionViewItem()
            opt.initFrom(view)
            opt.rect = QRect(row_rect)
            delegate.initStyleOption(opt, index)
            band = delegate.text_rect(opt, view.style(), view)
            bands[parts[0]] = (band.left(), band.right())

        assert len(bands) > 1, "needs at least two split rows to mean anything"
        assert len(set(bands.values())) == 1, f"bands differ by row: {bands}"
        # And the band is the row, inset — not something narrower per row.
        left, right = next(iter(bands.values()))
        assert left > 0 and right < row_rect.right()
        assert right - left > 0.9 * row_rect.width()

    def test_every_row_keeps_its_file_name(self, qapp, tmp_path):
        """A short name next to a long one must not tip one row over the elision
        threshold while its neighbour stays intact."""
        win, short, long = self._two_libraries(tmp_path)
        drawn = self._layouts(win)
        assert drawn, "no rows were split"
        assert all(sec for _, sec in drawn.values()), drawn
        assert drawn["Tumor"][1] == "a.toml"
        assert drawn["Macrophage"][1] == "much_longer_library_name.toml"

    def test_the_window_reserves_the_aligned_width(self, qapp, tmp_path):
        """The reserved width must cover the aligned layout, not the ragged one.

        Crossed on purpose: the longest *name* and the longest *file* are in
        different rows, which is exactly when widest-name + widest-file exceeds
        every combined single line — and when sizing from the latter clips.
        """
        from biwt.gui.widgets import split_width

        win, _, _ = self._two_libraries(tmp_path)
        fm = win.fontMetrics()
        crossed = [("a_very_long_cell_type_name", "z.toml"),
                   ("x", "a_very_long_library_name.toml")]
        longest_single_line = max(
            fm.horizontalAdvance(f"{n} ({s})") for n, s in crossed)
        assert split_width(fm, crossed) > longest_single_line
        # And the window asks for at least what its own entries need.
        assert win._fitted_dropdown_width() >= split_width(
            fm, list(win._parts.values()))

    def test_by_source_rows_are_not_split(self, qapp, tmp_path):
        """The group header already names the file; repeating it on every row
        under it would be noise."""
        win, _, _ = self._two_libraries(tmp_path)
        win._sort_toggled(1, True)
        for row in range(win._model.rowCount()):
            assert win._popup_parts(win._model.index(row, 0)) is None

    def test_the_none_row_is_never_split(self, qapp, tmp_path):
        win, _, _ = self._two_libraries(tmp_path)
        assert win._popup_parts(win._model.index(0, 0)) is None

    def test_a_single_library_has_nothing_to_qualify(self, qapp, tmp_path):
        """One file loaded means the source is never in question, so no split."""
        only = tmp_path / "a.toml"
        only.write_text('"Tumor" = "T"\n')
        win = _templates_window([str(only)])
        assert all(win._popup_parts(win._model.index(r, 0)) is None
                   for r in range(win._model.rowCount()))

    def test_the_item_text_still_reads_as_one_string(self, qapp, tmp_path):
        """The split is presentation only: the item's own text is what a closed
        box, a screen reader and the rest of these tests read."""
        win, _, _ = self._two_libraries(tmp_path)
        assert "Tumor (a.toml)" in _row_labels(win)


class TestLandingScreenLibrary:
    """The landing screen holds the library each run starts from.

    Its entries outlive the session, which every import rebuilds — and the host's
    own files are entries like any other: listed, and removable.
    """

    @staticmethod
    def _add_home(widget, monkeypatch, *paths):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileNames",
            staticmethod(lambda *a, **k: ([str(p) for p in paths], "")),
        )
        widget._add_home_templates_cb()

    @staticmethod
    def _remove_home(widget, monkeypatch, label, *, ok=True):
        monkeypatch.setattr(
            QInputDialog, "getItem",
            staticmethod(lambda *a, **k: (label, ok)),
        )
        widget._remove_home_template_cb()

    @staticmethod
    def _params_step(widget):
        session_through_rename(widget.session)
        return LoadCellTemplatesWindow(widget)

    @staticmethod
    def _abandon_run(widget):
        """What closing a step window does — importing again is refused otherwise."""
        widget._allow_import(True)

    def test_a_listed_file_reaches_the_step(self, make_widget, drive_import, monkeypatch):
        w, _ = make_widget()
        self._add_home(w, monkeypatch, TEMPLATES_A)
        drive_import(w, "nonspatial.csv")

        win = self._params_step(w)
        assert ("Tumor", str(Path(TEMPLATES_A).resolve())) in win._template_db

    def test_it_survives_a_second_import(self, make_widget, drive_import, monkeypatch):
        w, _ = make_widget()
        self._add_home(w, monkeypatch, TEMPLATES_A)
        drive_import(w, "nonspatial.csv")
        self._abandon_run(w)
        drive_import(w, "nonspatial.csv")       # the session is rebuilt here

        win = self._params_step(w)
        assert ("Tumor", str(Path(TEMPLATES_A).resolve())) in win._template_db

    def test_the_hosts_files_are_listed_from_the_start(self, make_widget):
        """Before any import, so the user can see what they already have."""
        w, _ = make_widget(cell_template_paths=[TEMPLATES_B])
        assert w._library_paths == [str(Path(TEMPLATES_B).resolve())]
        assert "templates_b.toml" in w._template_summary.text()

    def test_host_files_come_first_and_the_users_follow(
        self, make_widget, drive_import, monkeypatch
    ):
        w, _ = make_widget(cell_template_paths=[TEMPLATES_B])
        self._add_home(w, monkeypatch, TEMPLATES_A)
        drive_import(w, "nonspatial.csv")

        assert w.session.template_library_paths == [
            str(Path(TEMPLATES_B).resolve()), str(Path(TEMPLATES_A).resolve()),
        ]

    def test_a_removed_host_file_is_gone_for_good(
        self, make_widget, drive_import, monkeypatch
    ):
        """Seeded, not imposed — and nothing re-seeds it, at this import or any."""
        w, _ = make_widget(cell_template_paths=[TEMPLATES_B])
        self._remove_home(w, monkeypatch, "templates_b.toml")
        assert w._library_paths == []

        drive_import(w, "nonspatial.csv")
        assert w.session.template_library_paths == []
        assert self._params_step(w)._template_db == {}

        self._abandon_run(w)
        drive_import(w, "nonspatial.csv")
        assert w.session.template_library_paths == []

    def test_a_cancelled_removal_changes_nothing(self, make_widget, monkeypatch):
        w, _ = make_widget(cell_template_paths=[TEMPLATES_B])
        self._remove_home(w, monkeypatch, "templates_b.toml", ok=False)
        assert w._library_paths == [str(Path(TEMPLATES_B).resolve())]

    def test_a_later_host_resolution_cannot_touch_the_library(
        self, make_widget, drive_import
    ):
        """The library is the widget's, so a per-run value cannot rewrite it."""
        from biwt.types import BiwtInput

        w, _ = make_widget(
            _source=lambda: BiwtInput(preferred_domain=DOMAIN),
            cell_template_paths=[TEMPLATES_B],
        )
        drive_import(w, "nonspatial.csv")
        assert w.session.template_library_paths == [str(Path(TEMPLATES_B).resolve())]

    def test_a_file_added_twice_is_listed_once(self, make_widget, monkeypatch):
        w, _ = make_widget()
        self._add_home(w, monkeypatch, TEMPLATES_A)
        self._add_home(w, monkeypatch, TEMPLATES_A)
        assert w._library_paths == [str(Path(TEMPLATES_A).resolve())]

    def test_an_unreadable_file_is_reported_at_the_step_and_survives_it(
        self, make_widget, drive_import, monkeypatch
    ):
        """The landing screen names files; reading them is the step's job.

        So a file that has gone bad since it was picked has to land there as a
        warning, not as a traceback.
        """
        w, _ = make_widget()
        self._add_home(w, monkeypatch, FIXTURES / "no_such_templates.toml")
        drive_import(w, "nonspatial.csv")

        shown = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: shown.append(a[2])))
        win = self._params_step(w)

        assert len(shown) == 1
        assert "no_such_templates.toml" in shown[0]
        assert win._template_db == {}                    # step built anyway
        assert win.walkthrough.session.template_library_paths == []

    def test_the_summary_names_each_file(self, make_widget, monkeypatch):
        w, _ = make_widget()
        assert "every import" in w._template_summary.text()
        self._add_home(w, monkeypatch, TEMPLATES_A, TEMPLATES_B)

        text = w._template_summary.text()
        assert "templates_a.toml" in text
        assert "templates_b.toml" in text
        assert "2 files, carried into every import." in text
        assert TEMPLATES_A in w._template_summary.toolTip()

    def test_files_beyond_the_fourth_collapse_to_a_count(
        self, make_widget, monkeypatch, tmp_path
    ):
        w, _ = make_widget()
        files = []
        for i in range(6):
            f = tmp_path / f"lib_{i}.toml"
            f.write_text(f'"Tumor_{i}" = "T"\n')
            files.append(f)
        self._add_home(w, monkeypatch, *files)

        text = w._template_summary.text()
        assert "lib_3.toml" in text
        assert "lib_4.toml" not in text
        assert "…and 2 more" in text
        assert "6 files, carried" in text

    def test_two_files_of_one_name_are_told_apart(
        self, make_widget, monkeypatch, tmp_path
    ):
        """The step's labelling rule, so a file reads the same in both places."""
        w, _ = make_widget()
        paths = []
        for parent in ("mine", "theirs"):
            d = tmp_path / parent
            d.mkdir()
            (d / "lib.toml").write_text('"Tumor" = "T"\n')
            paths.append(d / "lib.toml")
        self._add_home(w, monkeypatch, *paths)

        text = w._template_summary.text()
        assert "mine/lib.toml" in text
        assert "theirs/lib.toml" in text

    def test_remove_is_disabled_with_nothing_to_remove(self, make_widget, monkeypatch):
        w, _ = make_widget()
        assert not w._remove_templates_btn.isEnabled()
        self._add_home(w, monkeypatch, TEMPLATES_A)
        assert w._remove_templates_btn.isEnabled()
        self._remove_home(w, monkeypatch, "templates_a.toml")
        assert not w._remove_templates_btn.isEnabled()

    def test_removing_at_the_step_leaves_the_landing_list_alone(
        self, make_widget, drive_import, monkeypatch
    ):
        """The step edits the run; the landing screen edits what runs start from."""
        w, _ = make_widget()
        self._add_home(w, monkeypatch, TEMPLATES_A)
        drive_import(w, "nonspatial.csv")
        win = self._params_step(w)
        _remove_file(win, monkeypatch, "templates_a.toml")

        assert win._template_db == {}
        assert w._library_paths == [str(Path(TEMPLATES_A).resolve())]

        self._abandon_run(w)
        drive_import(w, "nonspatial.csv")
        assert ("Tumor", str(Path(TEMPLATES_A).resolve())) in self._params_step(w)._template_db
