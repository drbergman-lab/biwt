"""DomainEditorDialog behavior — bounds validation, extents, and how a host
seeds the "Skip domain validation" checkbox.

Driven headless against the real dialog; the ``qapp`` fixture lives in
conftest.py.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QDialogButtonBox, QWidget

from biwt.gui.walkthrough import DomainEditorDialog, create_biwt_widget
from biwt.types import BiwtInput, DomainSpec

DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)


HOST_DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500,
                         zmin=-10, zmax=10)
DATA_DOMAIN = DomainSpec(xmin=0, xmax=2000, ymin=0, ymax=1500,
                         zmin=0, zmax=0, units="data unit")


@pytest.fixture
def editor(qapp):
    """Domain editor opened on a valid, symmetric host domain."""
    parent = QWidget()
    dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN,
                             host_name="Studio", initial_domain=HOST_DOMAIN)
    yield dlg
    dlg.deleteLater()
    parent.deleteLater()


class TestDomainBoundsValidation:
    """OK is gated on the bounds making sense.

    Before this, an inverted or unparseable domain was accepted verbatim: it
    flowed into the placement scaling and the emitted <x_min>/<x_max>, and an
    unparseable field silently became 0.0.
    """

    def test_valid_domain_enables_ok(self, editor):
        assert editor._ok_btn.isEnabled()

    @pytest.mark.parametrize("lo,hi", [("xmin", "xmax"),
                                       ("ymin", "ymax"),
                                       ("zmin", "zmax")])
    def test_inverted_axis_disables_ok(self, editor, lo, hi):
        editor._host_fields[hi].setText(str(editor._parse(editor._host_fields[lo]) - 1))
        assert not editor._ok_btn.isEnabled()
        assert {lo, hi} <= editor._invalid_bounds()

    @pytest.mark.parametrize("lo,hi", [("xmin", "xmax"),
                                       ("ymin", "ymax"),
                                       ("zmin", "zmax")])
    def test_zero_width_axis_disables_ok(self, editor, lo, hi):
        """A collapsed axis divides by zero in the placement scaling."""
        editor._host_fields[hi].setText(editor._host_fields[lo].text())
        assert not editor._ok_btn.isEnabled()

    def test_unparseable_bound_disables_ok(self, editor):
        editor._host_fields["ymin"].setText("")
        assert not editor._ok_btn.isEnabled()
        assert "ymin" in editor._invalid_bounds()

    def test_only_the_offending_axis_is_flagged(self, editor):
        editor._host_fields["xmax"].setText("-900")
        bad = editor._invalid_bounds()
        assert {"xmin", "xmax"} <= bad
        assert not ({"ymin", "ymax", "zmin", "zmax"} & bad)

    def test_repairing_re_enables_ok(self, editor):
        editor._host_fields["xmax"].setText("-900")
        assert not editor._ok_btn.isEnabled()
        editor._host_fields["xmax"].setText("500")
        assert editor._ok_btn.isEnabled()

    def test_cancel_is_never_gated(self, editor):
        """An unusable domain must always be escapable."""
        editor._host_fields["xmax"].setText("-900")
        box = editor.findChild(QDialogButtonBox)
        assert box.button(QDialogButtonBox.Cancel).isEnabled()

    def test_result_round_trips_a_valid_domain(self, editor):
        dom, _factor, _apply = editor.result()
        assert (dom.xmin, dom.xmax) == (-500.0, 500.0)
        assert (dom.zmin, dom.zmax) == (-10.0, 10.0)
        assert dom.source == "user_edited"


class TestDomainExtents:
    """Width/height/depth are shown and editable, in host units only."""

    def test_extents_derived_on_open(self, editor):
        assert editor._extent_fields["width"].text() == "1000"
        assert editor._extent_fields["height"].text() == "1000"
        assert editor._extent_fields["depth"].text() == "20"

    def test_editing_a_bound_updates_its_extent(self, editor):
        editor._host_fields["xmax"].setText("-100")
        assert editor._extent_fields["width"].text() == "400"

    def test_editing_an_extent_moves_only_the_maximum(self, editor):
        """The minimum is anchored, so exactly one bound changes."""
        editor._extent_fields["width"].setText("800")
        editor._on_extent_edited("width")
        assert editor._host_fields["xmin"].text() == "-500"   # untouched
        assert editor._host_fields["xmax"].text() == "300"

    def test_editing_an_extent_leaves_other_axes_alone(self, editor):
        editor._extent_fields["width"].setText("800")
        editor._on_extent_edited("width")
        assert editor._host_fields["ymin"].text() == "-500"
        assert editor._host_fields["ymax"].text() == "500"
        assert editor._extent_fields["depth"].text() == "20"

    def test_minimum_and_extent_are_independently_settable(self, qapp):
        """Set the left edge, then the width; the width must not drag the edge
        back. This is why the minimum is anchored rather than the center."""
        parent = QWidget()
        asym = DomainSpec(xmin=-300, xmax=500, ymin=-500, ymax=500,
                          zmin=-10, zmax=10)
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN,
                                 initial_domain=asym)
        assert dlg._extent_fields["width"].text() == "800"
        dlg._extent_fields["width"].setText("1000")
        dlg._on_extent_edited("width")
        assert (dlg._host_fields["xmin"].text(),
                dlg._host_fields["xmax"].text()) == ("-300", "700")

    def test_extent_repairs_an_unparseable_maximum(self, editor):
        """The maximum is written, not read, so it need not already be valid."""
        editor._host_fields["xmax"].setText("")
        assert not editor._ok_btn.isEnabled()
        editor._extent_fields["width"].setText("250")
        editor._on_extent_edited("width")
        assert editor._host_fields["xmax"].text() == "-250"
        assert editor._ok_btn.isEnabled()

    def test_negative_extent_is_refused_by_the_gate(self, editor):
        """Rather than silently inverting the axis."""
        editor._extent_fields["width"].setText("-100")
        editor._on_extent_edited("width")
        assert not editor._ok_btn.isEnabled()


@pytest.fixture
def scaled_editor(qapp):
    """Domain editor with a factor, so the data-units cells are live."""
    parent = QWidget()
    dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN,
                             host_name="Studio", initial_domain=HOST_DOMAIN,
                             file_factor=2.0)
    yield dlg
    dlg.deleteLater()
    parent.deleteLater()


class TestAxisGridLayout:
    """The grid is axis-major: an extent shares a row with its own bounds.

    Before this, the six bounds were laid out as flat rows and the three extents
    were appended after all of them, so ``Width`` sat six rows below the
    ``X min`` / ``X max`` that produced it.  Nothing but a tuple buried in the
    extent table knew the two were related.
    """

    def _row_of(self, dlg, widget):
        """Grid row holding *widget*, which lives inside a paired cell."""
        idx = dlg._grid.indexOf(widget.parent())
        assert idx != -1, f"{widget!r} is not inside a grid cell"
        return dlg._grid.getItemPosition(idx)[0]

    @pytest.mark.parametrize("extent,lo,hi", [("width", "xmin", "xmax"),
                                              ("height", "ymin", "ymax"),
                                              ("depth", "zmin", "zmax")])
    def test_extent_shares_its_axis_row(self, editor, extent, lo, hi):
        """This is the guard: width is on the X row, structurally."""
        row = self._row_of(editor, editor._extent_fields[extent])
        assert row == self._row_of(editor, editor._host_fields[lo])
        assert row == self._row_of(editor, editor._host_fields[hi])

    def test_each_axis_gets_its_own_row(self, editor):
        rows = {ax.extent: self._row_of(editor, editor._extent_fields[ax.extent])
                for ax in editor._AXES}
        assert len(set(rows.values())) == 3

    def test_xy_is_derived_from_the_axis_table(self, editor):
        """_XY must not drift from _AXES the way the old flat lists could."""
        assert editor._XY == ("xmin", "xmax", "ymin", "ymax")


class TestDataUnitExtents:
    """Each extent carries a data-units mirror alongside the host-units value."""

    def test_du_extents_derived_on_open(self, scaled_editor):
        # host width 1000, factor 2.0 → 500 data units
        assert scaled_editor._du_extent_fields["width"].text() == "500"
        assert scaled_editor._du_extent_fields["height"].text() == "500"

    def test_du_extent_follows_a_bound_edit(self, scaled_editor):
        scaled_editor._host_fields["xmax"].setText("-100")
        assert scaled_editor._extent_fields["width"].text() == "400"
        assert scaled_editor._du_extent_fields["width"].text() == "200"

    def test_editing_a_du_extent_moves_the_maximum(self, scaled_editor):
        """Same anchor-the-minimum rule, expressed in data units."""
        scaled_editor._du_extent_fields["width"].setText("100")   # → 200 host
        scaled_editor._on_du_extent_edited("width")
        assert scaled_editor._host_fields["xmin"].text() == "-500"   # untouched
        assert scaled_editor._host_fields["xmax"].text() == "-300"
        assert scaled_editor._extent_fields["width"].text() == "200"

    def test_du_extent_edit_leaves_the_typed_field_alone(self, scaled_editor):
        """The mirror must not rewrite the field being typed in."""
        scaled_editor._du_extent_fields["width"].setText("100")
        scaled_editor._on_du_extent_edited("width")
        assert scaled_editor._du_extent_fields["width"].text() == "100"

    def test_du_extent_edit_leaves_other_axes_alone(self, scaled_editor):
        scaled_editor._du_extent_fields["width"].setText("100")
        scaled_editor._on_du_extent_edited("width")
        assert scaled_editor._host_fields["ymax"].text() == "500"
        assert scaled_editor._du_extent_fields["height"].text() == "500"

    def test_no_factor_leaves_du_extents_empty_and_inert(self, editor):
        """The default fixture has no factor, so there is nothing to convert."""
        assert editor._du_extent_fields["width"].text() == ""
        assert not editor._du_extent_fields["width"].isEnabled()


class TestZRowIsPresentButInert:
    """Z carries the same widgets as x and y, so the row reads uniformly.

    It is not wired to the factor: z is a slab depth, not a measurement in data
    units.  Building the cells anyway means enabling them later is a matter of
    flipping ``factor_scaled`` on the axis record.
    """

    @pytest.mark.parametrize("key", ["zmin", "zmax"])
    def test_z_has_data_unit_bound_widgets(self, scaled_editor, key):
        assert key in scaled_editor._du_fields

    def test_z_data_unit_cells_stay_disabled_even_with_a_factor(self, scaled_editor):
        assert not scaled_editor._du_fields["zmin"].isEnabled()
        assert not scaled_editor._du_fields["zmax"].isEnabled()
        assert not scaled_editor._du_extent_fields["depth"].isEnabled()

    def test_z_data_unit_cells_stay_empty(self, scaled_editor):
        assert scaled_editor._du_extent_fields["depth"].text() == ""

    def test_z_explains_itself(self, scaled_editor):
        assert "not scaled" in scaled_editor._du_fields["zmin"].toolTip()

    def test_host_z_is_unaffected_by_the_factor(self, scaled_editor):
        """The depth still derives from the host bounds as before."""
        assert scaled_editor._extent_fields["depth"].text() == "20"


class TestDomainAcceptedSeedsCheckbox:
    """BiwtInput.domain_accepted sets the checkbox's default, not the outcome.

    It used to be OR-ed with the checkbox, so a host passing True left the user
    looking at an unticked box that did nothing and could not be untangled.
    """

    @pytest.mark.parametrize("host_value", [True, False])
    def test_host_value_seeds_the_checkbox(self, qapp, host_value):
        w = create_biwt_widget(
            BiwtInput(preferred_domain=DOMAIN, domain_accepted=host_value),
            on_complete=lambda _r: None,
        )
        assert w._domain_accepted_cb.isChecked() is host_value
        w.deleteLater()

    @pytest.mark.parametrize("host_value", [True, False])
    def test_user_can_override_in_either_direction(self, qapp, host_value):
        w = create_biwt_widget(
            BiwtInput(preferred_domain=DOMAIN, domain_accepted=host_value),
            on_complete=lambda _r: None,
        )
        w._domain_accepted_cb.setChecked(not host_value)
        assert w._domain_accepted_cb.isChecked() is (not host_value)
        w.deleteLater()


class TestBiwtInputDefaults:
    def test_preferred_domain_defaults(self):
        """A host that does not care about the domain can omit it."""
        assert BiwtInput().preferred_domain == DomainSpec.default()

    def test_default_is_not_shared_between_instances(self):
        a, b = BiwtInput(), BiwtInput()
        assert a.preferred_domain is not b.preferred_domain
