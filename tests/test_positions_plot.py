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

from biwt.core.positioning import compute_spatial_placement
from biwt.gui.windows.positions import PositionsWindow


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
