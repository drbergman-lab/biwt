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
from biwt.types import BiwtInput, DomainSource, DomainSpec

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
        # These bounds *are* the host's, so that is what the source says — see
        # TestReportedSource.
        assert dom.source == DomainSource.HOST


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
                             file_factor=2.0, current_factor=2.0)
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


class TestFactorChangesPropagate:
    """Every data-units cell tracks the factor, and an empty field means none.

    Three defects sat here. The size mirrors were derived once and never
    re-derived when the factor changed, so they showed a span computed with the
    previous factor. The bound mirrors kept their last values when the factor
    became unusable, advertising a conversion that no longer applied. And an
    empty field silently fell back to the file's value, which left a blank
    field, live mirrors and a greyed-out restore button all disagreeing about
    what was in effect.
    """

    def test_size_mirrors_follow_a_factor_change(self, scaled_editor):
        """The bug: bounds re-derived, sizes did not."""
        assert scaled_editor._du_extent_fields["width"].text() == "500"   # 1000 / 2
        scaled_editor._factor_edit.setText("4")
        assert scaled_editor._du_fields["xmax"].text() == "125"           # 500 / 4
        assert scaled_editor._du_extent_fields["width"].text() == "250"   # 1000 / 4

    def test_clearing_the_factor_means_no_factor(self, scaled_editor):
        scaled_editor._factor_edit.setText("")
        assert scaled_editor._effective_factor() is None

    def test_clearing_the_factor_clears_every_mirror(self, scaled_editor):
        """Rather than leaving values that correspond to no live factor."""
        scaled_editor._factor_edit.setText("")
        for attr in ("xmin", "xmax", "ymin", "ymax"):
            assert scaled_editor._du_fields[attr].text() == ""
            assert not scaled_editor._du_fields[attr].isEnabled()
        for key in ("width", "height"):
            assert scaled_editor._du_extent_fields[key].text() == ""

    def test_an_unparseable_factor_also_clears_the_mirrors(self, scaled_editor):
        scaled_editor._factor_edit.setText("abc")
        assert scaled_editor._du_fields["xmax"].text() == ""

    def test_a_non_positive_factor_is_not_usable(self, scaled_editor):
        scaled_editor._factor_edit.setText("0")
        assert scaled_editor._effective_factor() is None
        assert scaled_editor._du_fields["xmax"].text() == ""

    def test_reset_is_the_way_back_and_is_offered(self, scaled_editor):
        """Emptying the field must not make the file's value unreachable."""
        scaled_editor._factor_edit.setText("")
        assert scaled_editor._reset_btn.isEnabled()
        scaled_editor._on_reset()
        assert scaled_editor._effective_factor() == 2.0
        assert scaled_editor._du_extent_fields["width"].text() == "500"
        assert not scaled_editor._reset_btn.isEnabled()   # back at the file value

    def test_placeholder_names_the_restore_path(self, scaled_editor):
        assert scaled_editor._factor_edit.placeholderText() == "none — ↺ restores 2"

    def test_placeholder_is_honest_when_the_file_has_no_factor(self, editor):
        """Nothing to restore, so nothing is promised."""
        assert editor._factor_edit.placeholderText() == "none found in file"
        assert not editor._reset_btn.isEnabled()

    def test_host_bounds_survive_losing_the_factor(self, scaled_editor):
        """Only the mirrors go; the stored domain is host units and stands."""
        scaled_editor._factor_edit.setText("")
        assert scaled_editor._host_fields["xmax"].text() == "500"
        assert scaled_editor._extent_fields["width"].text() == "1000"
        assert scaled_editor._ok_btn.isEnabled()

    def test_result_reports_no_factor_once_cleared(self, scaled_editor):
        scaled_editor._factor_edit.setText("")
        _dom, factor, _apply = scaled_editor.result()
        assert factor is None


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


class TestInitialPreset:
    """Which domain the dialog opens on.

    The caller chooses: the data extent when the data's coordinates are in use, the
    host's otherwise — a computed extent from scaled non-spatial layout is not a
    meaningful default to hand someone. Untested, both this branch and its caller
    could be deleted with the suite still green, and a non-spatial run would have
    silently offered ±500 in place of the host's domain.
    """

    @staticmethod
    def _dialog(preset):
        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN,
                                 host_name="Studio", initial_preset=preset)
        dlg._parent_ref = parent
        return dlg

    @pytest.mark.parametrize("preset,expected_x,expected_source", [
        (DomainSource.DATA, (0.0, 2000.0), DomainSource.DATA),
        (DomainSource.HOST, (-500.0, 500.0), DomainSource.HOST),
    ])
    def test_the_preset_decides_what_enter_accepts(
        self, qapp, preset, expected_x, expected_source
    ):
        dlg = self._dialog(preset)
        domain, _factor, _apply = dlg.result()
        assert (domain.xmin, domain.xmax) == expected_x
        assert domain.source == expected_source

    def test_the_default_preset_is_the_data_extent(self, qapp):
        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN, host_name="Studio")
        dlg._parent_ref = parent
        assert dlg.result()[0].source == DomainSource.DATA


class TestReportedSource:
    """`DomainSpec.source` has to say where the accepted bounds came from.

    A host is told to check `source != DomainSource.HOST` to see whether its own
    domain survived the walkthrough. The dialog used to stamp USER on every accepted
    domain, which made that check always true — including for a user who pressed
    Enter on the pre-filled values without touching a field, and then saw their host
    domain quietly replaced by the data extent.
    """

    @staticmethod
    def _dialog(**kwargs):
        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN,
                                 host_name="Studio", **kwargs)
        dlg._parent_ref = parent          # keep it alive for the test
        return dlg

    def test_accepting_the_prefilled_values_reports_data(self, qapp):
        # First open pre-fills from the data, so Enter adopts the data extent.
        dlg = self._dialog()
        dom, _f, _a = dlg.result()
        assert (dom.xmin, dom.xmax) == (0.0, 2000.0)
        assert dom.source == DomainSource.DATA

    def test_use_host_domain_then_accept_reports_host(self, qapp):
        dlg = self._dialog()
        dlg._fill_preferred()
        dom, _f, _a = dlg.result()
        assert dom.source == DomainSource.HOST

    def test_editing_a_bound_reports_user(self, qapp):
        dlg = self._dialog()
        dlg._fill_preferred()
        dlg._host_fields["xmax"].setText("750")
        dom, _f, _a = dlg.result()
        assert dom.source == DomainSource.USER

    def test_a_revisit_that_changes_nothing_still_reports_honestly(self, qapp):
        # Reopened on a domain the user had edited earlier: still USER.
        edited = DomainSpec(xmin=-100, xmax=900, ymin=-100, ymax=900,
                            zmin=-10, zmax=10, source=DomainSource.USER)
        dlg = self._dialog(initial_domain=edited)
        assert dlg.result()[0].source == DomainSource.USER

    def test_host_wins_when_the_two_domains_coincide(self, qapp):
        """If the data extent happens to equal the host domain, the host's domain
        did survive — saying DATA would send a host chasing a change that
        never happened."""
        parent = QWidget()
        dlg = DomainEditorDialog(parent, HOST_DOMAIN, HOST_DOMAIN, host_name="Studio")
        dlg._parent_ref = parent
        assert dlg.result()[0].source == DomainSource.HOST

    def test_the_scale_factor_does_not_confuse_the_comparison(self, qapp):
        """With a factor applied, the data extent in host units is raw x factor —
        which is what the fields hold and what the check has to compare against."""
        dlg = self._dialog(current_factor=0.5)
        dom, factor, _a = dlg.result()
        assert factor == 0.5
        assert (dom.xmin, dom.xmax) == (0.0, 1000.0)
        assert dom.source == DomainSource.DATA


class TestDataPresetNeedsRealData:
    def test_the_data_preset_is_off_without_coordinates(self, qapp):
        """A non-spatial file has no data domain — `data_domain` is BIWT's own
        fallback box, so offering it as "the data's" would be a lie."""
        from PyQt5.QtWidgets import QPushButton

        parent = QWidget()
        dlg = DomainEditorDialog(parent, DomainSpec.default(), HOST_DOMAIN,
                                 host_name="Studio")
        btn = next(b for b in dlg.findChildren(QPushButton)
                   if b.text() == "Use Data Domain")
        assert not btn.isEnabled()
        assert "no spatial coordinates" in btn.toolTip()

    def test_it_is_on_when_the_data_has_an_extent(self, qapp):
        from PyQt5.QtWidgets import QPushButton

        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN, host_name="Studio")
        btn = next(b for b in dlg.findChildren(QPushButton)
                   if b.text() == "Use Data Domain")
        assert btn.isEnabled()


class TestSubstitutedHostDomain:
    """An unusable host domain is replaced by BIWT's box before the dialog opens.

    Accepting it must not then be reported as the host's: the numbers on screen
    are BIWT's, and a host checking `source != HOST` to see whether its own
    domain survived would be told it did.
    """

    def test_accepting_a_substituted_domain_reports_default(self, qapp):
        substituted = BiwtInput(
            preferred_domain=DomainSpec(xmin=0, xmax=0, ymin=-500, ymax=500)
        ).preferred_domain
        assert substituted.source == DomainSource.DEFAULT      # __post_init__ did it

        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, substituted, host_name="Scratch")
        dlg._fill_preferred()
        assert dlg.result()[0].source == DomainSource.DEFAULT

    def test_a_real_host_domain_still_reports_host(self, qapp):
        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN, host_name="Scratch")
        dlg._fill_preferred()
        assert dlg.result()[0].source == DomainSource.HOST


class TestClearedFactorStaysCleared:
    def test_reopening_does_not_restore_the_file_factor(self, qapp):
        """The file's value is what ↺ is for; re-opening must not undo a clear."""
        parent = QWidget()
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, HOST_DOMAIN, host_name="Studio",
                                 file_factor=2.0, current_factor=None)
        assert dlg._factor_edit.text() == ""
        assert dlg.result()[1] is None


class TestHostDomainPrecision:
    def test_a_host_domain_of_many_decimals_survives_the_round_trip(self, qapp):
        """The fields rounded to two decimals, so `_source_of` — which compares what
        they hold against the host's domain — called an untouched domain `user`, and
        the perturbed bounds were what got placed into."""
        parent = QWidget()
        host = DomainSpec(xmin=-499.567, xmax=500.123, ymin=-250.891, ymax=250.045)
        dlg = DomainEditorDialog(parent, DATA_DOMAIN, host, host_name="Studio")
        dlg._fill_preferred()

        domain, _factor, _apply = dlg.result()
        assert (domain.xmin, domain.xmax) == (host.xmin, host.xmax)
        assert (domain.ymin, domain.ymax) == (host.ymin, host.ymax)
        assert domain.source == DomainSource.HOST


class TestTypingInTheDataUnitsColumn:
    """``_on_du_edited`` — the multiply behind an accepted domain.

    The other tests drive fields with ``setText``, which emits ``textChanged``;
    these handlers listen for ``textEdited``, which only a real edit emits. So
    this direction of the conversion had never run, though ``result()`` reads the
    host fields it writes.
    """

    def test_a_typed_data_units_bound_becomes_host_units(self, qapp, scaled_editor):
        from PyQt5.QtTest import QTest

        dlg = scaled_editor
        F = dlg._effective_factor()
        field = dlg._du_fields["xmax"]
        field.setEnabled(True)
        field.clear()
        QTest.keyClicks(field, "25")

        assert dlg._parse(dlg._host_fields["xmax"]) == pytest.approx(25.0 * F)

    def test_the_host_bound_it_wrote_is_what_result_returns(self, qapp, scaled_editor):
        from PyQt5.QtTest import QTest

        dlg = scaled_editor
        F = dlg._effective_factor()
        for attr, typed in (("xmin", "-10"), ("xmax", "25")):
            field = dlg._du_fields[attr]
            field.setEnabled(True)
            field.clear()
            QTest.keyClicks(field, typed)

        domain = dlg.result()[0]
        assert domain.xmin == pytest.approx(-10.0 * F)
        assert domain.xmax == pytest.approx(25.0 * F)
