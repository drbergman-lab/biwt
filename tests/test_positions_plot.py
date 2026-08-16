"""Regression tests for PositionsWindow's 2D axis/aspect handling.

format_axis() is exercised directly against a bare matplotlib Axes (no
QApplication needed) since it only touches self.ax0 and the plot_* bounds.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import pytest

from pathlib import Path

from biwt.core.positioning import compute_spatial_placement
from biwt.gui.windows.positions import PositionsWindow
from biwt.types import DomainSpec

FIXTURES = Path(__file__).parent / "fixtures"

# Deep enough that DomainSpec.is_2d is False, so the axes are a real 3-D
# projection — the condition the reported crash needed.
DOMAIN_3D = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500,
                       zmin=-750, zmax=750)


class _Dummy:
    plot_is_2d = True


def _scale(ax):
    dx, dy = ax.transData.transform((1, 1)) - ax.transData.transform((0, 0))
    return dx, dy


class TestFormatAxisAspect:
    def test_equal_aspect_applied_immediately(self):
        """A square domain must yield an equal x/y pixel-per-micron scale
        without requiring a canvas.draw() first."""
        fig = Figure()
        ax = fig.add_subplot(111, adjustable="box")
        d = _Dummy()
        d.ax0 = ax
        d.plot_xmin, d.plot_xmax = -500, 500
        d.plot_ymin, d.plot_ymax = -500, 500

        PositionsWindow.format_axis(d)

        dx, dy = _scale(ax)
        assert dx == pytest.approx(dy)

    def test_scale_updates_after_domain_aspect_ratio_changes(self):
        """Switching to a domain with a different aspect ratio must change
        the effective pixel-per-micron scale immediately (used by
        _recompute_scatter_sizes to size the spot/cell markers)."""
        fig = Figure()
        ax = fig.add_subplot(111, adjustable="box")
        d = _Dummy()
        d.ax0 = ax
        d.plot_xmin, d.plot_xmax = -500, 500
        d.plot_ymin, d.plot_ymax = -500, 500
        PositionsWindow.format_axis(d)
        square_scale = _scale(ax)

        d.plot_xmin, d.plot_xmax = -2000, 2000
        d.plot_ymin, d.plot_ymax = -250, 250
        PositionsWindow.format_axis(d)
        wide_scale = _scale(ax)

        assert wide_scale[0] == pytest.approx(wide_scale[1])
        assert wide_scale[0] != pytest.approx(square_scale[0])


class TestReplotOrdering:
    def test_scatter_sizes_recomputed_before_sync_par_area(self):
        """sync_par_area() re-invokes the current plotter (e.g. spatial_plotter),
        which reads self.scatter_sizes / self.cell_type_micron2_area_dict to size
        its preview markers. _recompute_scatter_sizes() must run first, or the
        preview gets created with stale, pre-domain-change sizes."""
        calls: list[str] = []
        d = SimpleNamespace(
            walkthrough=SimpleNamespace(session=SimpleNamespace(coords_by_type={})),
            ax0=SimpleNamespace(cla=lambda: calls.append("cla")),
            preview_patch=None,
            format_axis=lambda: calls.append("format_axis"),
            _recompute_scatter_sizes=lambda: calls.append("recompute_scatter_sizes"),
            update_legend_window=lambda: calls.append("update_legend_window"),
            sync_par_area=lambda: calls.append("sync_par_area"),
            _refresh_continue_gate=lambda: calls.append("refresh_continue_gate"),
        )

        PositionsWindow._replot_all_after_undo(d)

        assert calls.index("recompute_scatter_sizes") < calls.index("sync_par_area")


class TestDefaultSpatialPars:
    # Fixture data: x in [10, 50] (extent 40), y in [0, 40] (extent 40).
    COORDS = np.array([[10.0, 40.0, 0.0], [50.0, 0.0, 0.0]])

    def _dummy(self, scale):
        d = SimpleNamespace(
            walkthrough=SimpleNamespace(session=SimpleNamespace(
                use_spatial_data=True,
                spatial_data_final=self.COORDS,
                effective_scale=lambda: scale)),
            plot_is_2d=True,
            plot_xmin=-500.0, plot_xmax=500.0, plot_dx=1000.0,
            plot_ymin=-500.0, plot_ymax=500.0, plot_dy=1000.0,
        )
        return d

    def test_no_factor_places_raw_extent_centered(self):
        # effective_scale()==1.0: original extent (40×40), centered in the domain.
        pars = PositionsWindow._default_spatial_pars(self._dummy(scale=1.0))
        assert pars == [-20.0, -20.0, 40.0, 40.0]

    def test_factor_scales_data_directly_centered(self):
        # effective_scale()==0.5: 40×40 data → 20×20, centered (NOT fill-to-domain).
        pars = PositionsWindow._default_spatial_pars(self._dummy(scale=0.5))
        assert pars == [-10.0, -10.0, 20.0, 20.0]


class TestComputeSpatialPlacement:
    def test_scale_and_center_2d(self):
        pars = compute_spatial_placement((40.0, 40.0), (0.0, 0.0), 0.5, True)
        assert pars == [-10.0, -10.0, 20.0, 20.0]

    def test_scale_and_center_3d(self):
        pars = compute_spatial_placement((40.0, 40.0, 10.0), (0.0, 0.0, 0.0), 0.5, False)
        assert pars == [-10.0, -10.0, -2.5, 20.0, 20.0, 5.0]

    def test_invariant_output_equals_raw_times_factor(self):
        # Key invariant: with domain = data_bbox × F (the "Use Data Domain"
        # case, so the domain center = data_center × F), a mapped point == raw × F.
        F = 0.5
        data = np.array([[10.0, 40.0], [50.0, 0.0], [30.0, 20.0]])
        dmin, dmax = data.min(0), data.max(0)
        extent = dmax - dmin
        domain_center = ((dmin + dmax) / 2.0) * F
        x0, y0, w, h = compute_spatial_placement(
            tuple(extent), tuple(domain_center), F, True)
        base = (data - dmin) / extent           # normalized [0,1] (matches the plotter)
        mapped = base * [w, h] + [x0, y0]
        np.testing.assert_allclose(mapped, data * F)


class TestZeroCountPlacement:
    """A cell type with a count of zero is treated as already placed.

    It has nothing to contribute, so it must not be selectable and must not hold
    up the Continue gate. Before this, a zero-count type in a 3D domain made the
    positions step unexitable: _plot_single_3d returned on the empty result
    before disabling the checkbox, and Continue waits for every checkbox to be
    disabled.
    """

    @staticmethod
    def _win(counts):
        return SimpleNamespace(
            walkthrough=SimpleNamespace(session=SimpleNamespace(cell_counts=counts))
        )

    def test_positive_count_is_placeable(self):
        w = self._win({"Tumor": 7})
        assert PositionsWindow._is_placeable(w, "Tumor") is True

    def test_zero_count_is_not_placeable(self):
        w = self._win({"Tumor": 7, "Ghost": 0})
        assert PositionsWindow._is_placeable(w, "Ghost") is False

    def test_unknown_type_is_not_placeable(self):
        assert PositionsWindow._is_placeable(self._win({}), "Missing") is False

    def test_missing_cell_counts_does_not_raise(self):
        """cell_counts is Optional; the window must not explode before it is set."""
        assert PositionsWindow._is_placeable(self._win(None), "Tumor") is False

    # -- the Continue gate ------------------------------------------------

    @staticmethod
    def _gate(enabled_flags):
        state = {}
        w = SimpleNamespace(
            checkbox_dict={
                name: SimpleNamespace(isEnabled=lambda e=en: e)
                for name, en in enabled_flags.items()
            },
            continue_to_write_button=SimpleNamespace(
                setEnabled=lambda v: state.__setitem__("enabled", v)
            ),
        )
        PositionsWindow._refresh_continue_gate(w)
        return state["enabled"]

    def test_gate_closed_while_a_type_is_pending(self):
        assert self._gate({"Tumor": True, "Ghost": False}) is False

    def test_gate_opens_once_every_type_is_settled(self):
        assert self._gate({"Tumor": False, "Ghost": False}) is True

    def test_gate_opens_when_every_type_has_zero_count(self):
        """All-zero is allowed, and nothing can ever be plotted — so Continue
        must be live immediately rather than waiting for a plot that cannot
        happen."""
        assert self._gate({"Ghost": False, "Phantom": False}) is True


class TestRectDragParameterSlots:
    """A drag must write into the slots the active plotter actually uses.

    2-D lays the parameters out as (x0, y0, width, height); 3-D inserts z0 and
    appends depth, giving (x0, y0, z0, width, height, depth). Hard-coding 2 and
    3 for the extents put the drag's x-span into z0 and its y-span into width
    whenever the 3-D spatial plotter — the only one with mouse handling in 3-D —
    was dragged.
    """

    @staticmethod
    def _drag(is_2d):
        writes: dict[int, float] = {}
        d = SimpleNamespace(
            plot_is_2d=is_2d,
            _assign_par=lambda v, i: writes.__setitem__(i, v),
        )
        # Drag from (10, 20) to (110, 220): x0=10, y0=20, width=100, height=200.
        PositionsWindow._rect_helper(d, SimpleNamespace(xdata=110, ydata=220), 10, 20)
        return writes

    def test_2d_slots(self):
        assert self._drag(True) == {0: 10, 1: 20, 2: 100, 3: 200}

    def test_3d_slots_skip_z0(self):
        w = self._drag(False)
        assert w == {0: 10, 1: 20, 3: 100, 4: 200}

    def test_3d_drag_leaves_z0_and_depth_untouched(self):
        """A drag is an xy-plane gesture; the z parameters stay as typed."""
        w = self._drag(False)
        assert 2 not in w and 5 not in w

    def test_origin_is_the_lower_left_corner_either_way(self):
        """Dragging up-left must still yield the min corner, not the press point."""
        for is_2d in (True, False):
            writes = {}
            d = SimpleNamespace(
                plot_is_2d=is_2d,
                _assign_par=lambda v, i: writes.__setitem__(i, v),
            )
            PositionsWindow._rect_helper(d, SimpleNamespace(xdata=10, ydata=20), 110, 220)
            assert (writes[0], writes[1]) == (10, 20)


# ---------------------------------------------------------------------------
# Spot deconvolution: placement after the cell types have been edited
# ---------------------------------------------------------------------------

class TestSpotDeconvolutionPlacement:
    """The post-rename probability dicts have to be the ones indexed.

    ``apply_rename`` used to rewrite ``cell_prob_feature_dicts`` in place, which was
    not idempotent and paired profiles with the wrong coordinates on a second pass.
    The fix writes ``cell_prob_feature_dicts_final`` alongside ``spatial_data_final``
    — and ``_plot_spot_deconvolution`` is its only reader, so nothing exercised it:
    the old expression could be restored with the whole suite still green.

    Without the fix the dicts are keyed by the *original* labels while the selection
    holds the *final* ones, so every renamed type's probability mass silently
    disappears and none of its cells are placed.
    """

    @staticmethod
    def _walk_to_positions(qapp, monkeypatch):
        from PyQt5.QtWidgets import QDialog, QFileDialog

        from biwt.gui.walkthrough import DomainEditorDialog, create_biwt_widget
        from biwt.types import BiwtInput, DomainSpec

        monkeypatch.setattr(DomainEditorDialog, "exec_",
                            lambda self: QDialog.Rejected)
        widget = create_biwt_widget(
            BiwtInput(preferred_domain=DomainSpec(xmin=0, xmax=300,
                                                 ymin=0, ymax=300)),
            on_complete=lambda result: None,
        )
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(FIXTURES / "spot_deconv.csv"), "")),
        )
        widget._import_cb()

        def name():
            return type(widget.window).__name__

        assert name() == "SpotDeconvolutionQueryWindow"
        widget.window.yes_rb.setChecked(True)
        widget.window.process_window()                      # -> EditCellTypes

        assert name() == "EditCellTypesWindow"
        widget.window._checkbox["Macrophage"].setChecked(True)
        widget.window._delete_cb()
        widget.window.process_window()                      # -> RenameCellTypes

        assert name() == "RenameCellTypesWindow"
        widget.window._line_edits["Tumor"].setText("Neoplastic")
        widget.window.process_window()

        for _ in range(4):
            qapp.processEvents()
            if name() == "PositionsWindow":
                return widget
            widget.window.process_window()
        raise AssertionError(f"never reached Positions (stuck on {name()})")

    def test_a_renamed_type_is_still_placed(self, qapp, monkeypatch):
        widget = self._walk_to_positions(qapp, monkeypatch)
        win, s = widget.window, widget.session
        assert sorted(s.cell_types_list_final) == ["Neoplastic", "T_cell"]

        for cb in win.checkbox_dict.values():
            cb.setChecked(True)
        win.cell_pos_button_group.button(win.spatial_plotter_id).setChecked(True)
        win.plot_cell_pos()

        assert len(s.coords_by_type.get("Neoplastic", [])) > 0
        # Every spot that was plotted placed something: nothing was dropped for
        # want of a key.  Not every spot is plotted — this fixture's placement
        # rectangle is x -50..350 against a 0..300 domain, so 3 of the 6 fall
        # outside it and are skipped, the same way the non-deconvolution branch
        # skips them.
        assert len(s.plotted_cell_types_per_spot) == 3
        assert sum(len(v) for v in s.coords_by_type.values()) == \
            len(s.plotted_cell_types_per_spot)

    def test_the_dicts_are_keyed_by_the_final_names(self, qapp, monkeypatch):
        widget = self._walk_to_positions(qapp, monkeypatch)
        s = widget.session
        keys = {k for d in s.cell_prob_feature_dicts_final for k in d}
        assert keys == {"Neoplastic", "T_cell"}
        # The source dicts were not mutated to get there.
        assert {k for d in s.cell_prob_feature_dicts for k in d} == {
            "Macrophage", "T_cell", "Tumor",
        }


class TestPlottingIntoA3DDomain:
    """Spatial plotting in a 3-D domain — reported as a hard crash.

    ``self.circles()`` builds a 2-D ``PatchCollection``; adding one to a 3-D axes
    makes ``canvas.draw()`` raise ``AttributeError: 'PatchCollection' object has
    no attribute 'do_3d_projection'``. That escapes the Plot slot, and PyQt5 turns
    an exception escaping a slot into a fatal abort, so it killed the host.

    Three call sites chose a renderer independently and two assumed 2-D.
    """

    @staticmethod
    def _at_positions(qapp, monkeypatch, fixture, domain, n_per_spot=1):
        from PyQt5.QtWidgets import QDialog, QFileDialog

        from biwt.gui.walkthrough import DomainEditorDialog, create_biwt_widget
        from biwt.types import BiwtInput

        monkeypatch.setattr(DomainEditorDialog, "exec_",
                            lambda self: QDialog.Rejected)
        widget = create_biwt_widget(
            BiwtInput(preferred_domain=domain), on_complete=lambda result: None,
        )
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(FIXTURES / fixture), "")),
        )
        widget._import_cb()
        for _ in range(8):
            qapp.processEvents()
            if type(widget.window).__name__ == "PositionsWindow":
                break
            widget.window.process_window()
        assert type(widget.window).__name__ == "PositionsWindow"
        win = widget.window
        for cb in win.checkbox_dict.values():
            cb.setChecked(True)
        win.cell_pos_button_group.button(win.spatial_plotter_id).setChecked(True)
        win.num_box.setValue(n_per_spot)
        return widget, win

    # The reported repro used a Visium .h5ad; spot_deconv.csv is the fixture with
    # the same shape — coordinates plus *_probability columns.
    @pytest.mark.parametrize("fixture,n_per_spot", [
        ("spot_deconv.csv", 1),     # exactly what was reported
        ("spot_deconv.csv", 4),     # the sub-spot renderer, same call site
        ("spatial.csv", 1),         # already worked; guards against regressing it
        ("spatial.csv", 3),         # the third call site
    ])
    def test_plotting_does_not_raise(self, qapp, monkeypatch, fixture, n_per_spot):
        widget, win = self._at_positions(qapp, monkeypatch, fixture, DOMAIN_3D,
                                         n_per_spot)
        win.plot_cell_pos()          # would abort the host before the fix
        s = widget.session
        assert sum(len(v) for v in s.coords_by_type.values()) > 0

    @pytest.mark.parametrize("fixture", ["spot_deconv.csv", "spatial.csv"])
    def test_cells_land_inside_an_offset_z_range(self, qapp, monkeypatch, fixture):
        """z=0 was hardcoded, so a domain not straddling zero placed every cell
        outside itself."""
        offset = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500,
                            zmin=100, zmax=400)
        widget, win = self._at_positions(qapp, monkeypatch, fixture, offset, 3)
        win.plot_cell_pos()
        placed = np.vstack([v for v in widget.session.coords_by_type.values()
                            if len(v)])
        assert len(placed) > 0
        assert placed[:, 2].min() >= 100
        assert placed[:, 2].max() <= 400

    def test_every_drawn_cell_reaches_the_host(self, qapp, monkeypatch):
        """The sub-spot arm drew cells and stored none, so the canvas filled while
        ``coordinates`` came back empty — in 2-D as well as 3-D."""
        flat = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)
        widget, win = self._at_positions(qapp, monkeypatch, "spot_deconv.csv",
                                         flat, 4)
        win.plot_cell_pos()
        s = widget.session
        drawn = sum(len(r["cell_types"]) for r in s.plotted_cell_types_per_spot)
        assert drawn == 4 * len(s.plotted_cell_types_per_spot)
        assert sum(len(v) for v in s.coords_by_type.values()) == drawn

    def test_a_region_the_domain_cannot_reach_gives_up(self, qapp, monkeypatch):
        """``_wedge_sample_2d`` had no fail counter where its 3-D twin does, so an
        unreachable region spun forever inside the Plot slot.

        Under a SIGALRM watchdog: without it a regression hangs the run instead of
        failing it, which is how this went unnoticed in the first place.
        """
        import signal

        widget, win = self._at_positions(qapp, monkeypatch, "spatial.csv",
                                         DOMAIN_3D)

        def _boom(signum, frame):
            raise TimeoutError("_wedge_sample_2d did not give up")

        old = signal.signal(signal.SIGALRM, _boom)
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        try:
            # A disc wholly outside the domain: nothing sampled can be accepted.
            out = win._wedge_sample_2d(5, win.plot_xmax + 10_000, 0.0, 1.0)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        assert out.shape == (0, 3)


class TestBuildingOnAnAsymmetricDomain:
    """The window must construct whatever the domain's bounds happen to be.

    Reported from a real run: merge, rename, plot, go back, change the merges —
    and the rebuilt window raised ``AttributeError: no attribute 'par_text'``
    from its own constructor, which PyQt5 turns into a fatal abort.

    ``_default_wh`` branched on which side of the centre was farther and, on the
    longer one, wrote the shifted centre into a parameter field. The centre is the
    midpoint, so the two sides are equal and that branch is only reachable when
    halving the bounds rounds one side up. It also ran from
    ``_create_patch_history``, before any parameter field existed.
    """

    # y is the axis that actually trips it for the documentation fixture: the
    # midpoint of (-32.41, 2160.68) is 2.3e-13 nearer the top.
    TIPPING = DomainSpec(xmin=-102.36, xmax=2441.1, ymin=-32.41, ymax=2160.68)

    @staticmethod
    def _positions_window(domain):
        from helpers import window_at_rename

        w = window_at_rename()
        w.session.user_domain = domain
        return PositionsWindow(w)

    def test_the_tie_break_is_real_and_not_hypothetical(self):
        """Guard the premise: if this stops being true the test proves nothing."""
        mn, mx = self.TIPPING.ymin, self.TIPPING.ymax
        c = 0.5 * (mn + mx)
        assert abs(mn - c) > abs(mx - c)
        assert abs(mn - c) - abs(mx - c) < 1e-9      # a rounding artefact, not real

    def test_the_window_builds(self, qapp):
        win = self._positions_window(self.TIPPING)
        assert win.par_text != []                    # the fields it used to precede

    @pytest.mark.parametrize("domain", [
        DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500),   # symmetric
        DomainSpec(xmin=0, xmax=300, ymin=0, ymax=300),         # offset, exact
        DomainSpec(xmin=100, xmax=400, ymin=-750, ymax=750),    # mixed
    ])
    def test_other_domains_still_build(self, qapp, domain):
        assert self._positions_window(domain).par_text != []

    def test_the_default_rectangle_is_unchanged(self, qapp):
        """The rewrite must be numerically identical, not merely non-crashing.

        With the centre at the midpoint, ``max(dL, dR)`` is the same number the
        old ``else`` branch produced, so a symmetric domain keeps its exact
        parameters: centre 0,0 and a quarter-domain half-extent.
        """
        win = self._positions_window(
            DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500))
        assert win._default_rectangle_pars() == [0.0, 0.0, 250.0, 250.0]

    def test_the_centre_agrees_with_the_extents(self, qapp):
        """The old branch wrote a centre the returned parameters contradicted."""
        win = self._positions_window(self.TIPPING)
        x0, y0, w, h = win._default_rectangle_pars()
        assert (x0, y0) == win._default_center()
        assert (w, h) == win._default_wh(win._default_center())[:2]
