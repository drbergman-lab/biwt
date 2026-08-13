"""EditCellTypesWindow — keep / merge / delete, and how merge groups change.

Merge-group membership used to be read back out of the checkbox *label* ("does it
contain '⇒ Merge Gp.'"), because the session dict genuinely cannot express it: a
group's first member maps to itself, exactly as a kept type does. Membership is
now tracked as state, and this module pins the behavior that depended on it.
"""
from __future__ import annotations


import pytest

pytest.importorskip("PyQt5")

from biwt.gui.windows.edit_cell_types import EditCellTypesWindow
from helpers import walkthrough_with_data



def _edit_window(types=None):
    """The edit window over *types* (default: the non-spatial fixture's three)."""
    w = walkthrough_with_data()
    s = w.session
    s.current_column = "type"
    s.collect_cell_type_data()
    if types is not None:
        s.cell_types_list_original = list(types)
    return EditCellTypesWindow(w)


def _check(win, *cell_types):
    for ct in cell_types:
        win._checkbox[ct].setChecked(True)


def _mapping(win):
    return win.walkthrough.session.cell_type_dict_on_edit


class TestDefaults:
    def test_everything_starts_kept(self, qapp):
        win = _edit_window()
        assert _mapping(win) == {ct: ct for ct in _mapping(win)}
        assert win._merge_group == {}


class TestMerge:
    def test_merging_points_both_at_the_first_member(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        assert _mapping(win)["Macrophage"] == "Macrophage"
        assert _mapping(win)["Tumor"] == "Macrophage"

    def test_both_members_share_a_group(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        assert win._merge_group["Macrophage"] == win._merge_group["Tumor"]

    def test_the_label_shows_the_group(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        assert "⇒ Merge Gp. #1" in win._checkbox["Tumor"].text()


class TestGroupMembershipChanges:
    """Leaving a group of two dissolves it; joining another absorbs it."""

    def test_keeping_the_group_leader_restores_its_partner(self, qapp):
        # The case the label-reading code existed for: the leader's mapping is
        # indistinguishable from a kept type's, so state alone could not tell.
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        win._set_keep("Macrophage")

        assert _mapping(win)["Tumor"] == "Tumor"
        assert win._merge_group == {}

    def test_keeping_a_follower_restores_the_leader(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        win._set_keep("Tumor")

        assert _mapping(win)["Macrophage"] == "Macrophage"
        assert win._merge_group == {}

    def test_deleting_a_member_restores_the_other(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        _check(win, "Tumor")
        win._delete_cb()

        assert _mapping(win)["Tumor"] is None
        assert _mapping(win)["Macrophage"] == "Macrophage"
        assert win._merge_group == {}

    def test_a_group_of_three_survives_losing_a_follower(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "T_cell", "Tumor")
        win._merge_cb()
        win._set_keep("Tumor")

        # Two are still merged under the original leader, so nothing dissolves.
        assert _mapping(win)["T_cell"] == "Macrophage"
        assert _mapping(win)["Tumor"] == "Tumor"
        assert set(win._merge_group) == {"Macrophage", "T_cell"}

    def test_a_group_of_three_elects_a_new_leader_when_it_loses_the_old(self, qapp):
        """The departed type must not stay the target the others merge into.

        The leader is the first checked member, so its own mapping points at itself
        — the same shape a kept type has. Keeping it therefore looked like a no-op
        and left T_cell and Tumor pointing at a type the user had just taken out of
        the group, folding them into it anyway.
        """
        win = _edit_window()
        _check(win, "Macrophage", "T_cell", "Tumor")
        win._merge_cb()
        win._set_keep("Macrophage")

        assert _mapping(win)["Macrophage"] == "Macrophage"      # out, kept
        assert _mapping(win)["T_cell"] == "T_cell"              # the new leader
        assert _mapping(win)["Tumor"] == "T_cell"               # still merged with it
        assert set(win._merge_group) == {"T_cell", "Tumor"}

    def test_deleting_the_leader_of_three_does_not_merge_into_a_deleted_type(self, qapp):
        """Worse than Keep: the survivors would name a type absent from the output."""
        win = _edit_window()
        _check(win, "Macrophage", "T_cell", "Tumor")
        win._merge_cb()
        _check(win, "Macrophage")
        win._delete_cb()

        assert _mapping(win)["Macrophage"] is None
        assert _mapping(win)["T_cell"] == "T_cell"
        assert _mapping(win)["Tumor"] == "T_cell"

    def test_the_repaired_group_produces_one_output_type(self, qapp):
        """Downstream proof: the pre-image is what the user actually asked for."""
        win = _edit_window()
        _check(win, "Macrophage", "T_cell", "Tumor")
        win._merge_cb()
        win._set_keep("Macrophage")
        s = win.walkthrough.session
        s.compute_intermediate_types()

        assert s.intermediate_type_pre_image == {
            "Macrophage": ["Macrophage"],
            "T_cell": ["T_cell", "Tumor"],
        }


class TestMergedTypesAreLockedIn:
    """Re-merging is not a case to handle — the UI makes it unreachable.

    Merging disables the checkbox, so the only way out of a group is the type's
    own Keep button, which removes it from the group first.  A type can therefore
    never belong to two groups, and no code has to reconcile that.
    """

    def test_merging_disables_the_checkboxes(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        assert not win._checkbox["Macrophage"].isEnabled()
        assert not win._checkbox["Tumor"].isEnabled()

    def test_keep_is_the_only_way_back_and_it_re_enables(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "Tumor")
        win._merge_cb()
        assert win._keep_btn["Macrophage"].isEnabled()

        win._set_keep("Macrophage")
        assert win._checkbox["Macrophage"].isEnabled()
        assert "Macrophage" not in win._merge_group

    def test_deleting_also_locks_the_checkbox(self, qapp):
        win = _edit_window()
        _check(win, "Tumor")
        win._delete_cb()
        assert not win._checkbox["Tumor"].isEnabled()
        assert win._keep_btn["Tumor"].isEnabled()

    def test_no_type_can_be_in_two_groups(self, qapp):
        """Whatever the user does, each type has at most one group id."""
        win = _edit_window(["A", "B", "C", "D"])
        _check(win, "A", "B")
        win._merge_cb()
        # C and D are the only ones still selectable.
        selectable = [ct for ct, cb in win._checkbox.items() if cb.isEnabled()]
        assert selectable == ["C", "D"]
        _check(win, *selectable)
        win._merge_cb()
        assert len(set(win._merge_group.values())) == 2
        assert set(win._merge_group) == {"A", "B", "C", "D"}


class TestLabelIsDisplayOnly:
    def test_a_name_containing_the_annotation_is_not_read_as_merged(self, qapp):
        """The old code asked the label whether a type was merged.

        A cell type is named by the data, so a name can contain anything —
        including the very text the annotation used.
        """
        sneaky = "Tumor ⇒ Merge Gp. #1"
        win = _edit_window([sneaky, "Macrophage"])
        # Kept, never merged: nothing may dissolve, and no group exists.
        win._set_keep(sneaky)
        assert _mapping(win) == {sneaky: sneaky, "Macrophage": "Macrophage"}
        assert win._merge_group == {}


class TestEveryTypeDeleted:
    def test_continue_is_refused_with_nothing_left(self, qapp, monkeypatch):
        """Counts, placement and the plot all reduce over the cell types, so an
        empty set raises somewhere downstream whatever is patched."""
        from PyQt5.QtWidgets import QMessageBox

        warned = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warned.append(a[2])))
        win = _edit_window()
        _check(win, *win._checkbox)
        win._delete_cb()
        advanced = []
        win.walkthrough.advance = lambda: advanced.append(True)

        win.process_window()
        assert advanced == []
        assert "at least one cell type" in warned[0].lower()

    def test_one_survivor_is_enough(self, qapp):
        win = _edit_window()
        _check(win, "Macrophage", "T_cell")
        win._delete_cb()
        advanced = []
        win.walkthrough.advance = lambda: advanced.append(True)
        win.process_window()
        assert advanced == [True]
