"""Regression tests for PositionsWindow's 2D axis/aspect handling.

format_axis() is exercised directly against a bare matplotlib Axes (no
QApplication needed) since it only touches self.ax0 and the plot_* bounds.
"""
from __future__ import annotations

from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import pytest

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
            continue_to_write_button=SimpleNamespace(setEnabled=lambda v: None),
        )

        PositionsWindow._replot_all_after_undo(d)

        assert calls.index("recompute_scatter_sizes") < calls.index("sync_par_area")
