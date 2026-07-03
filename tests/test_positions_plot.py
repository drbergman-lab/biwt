"""Regression tests for PositionsWindow's 2D axis/aspect handling.

format_axis() is exercised directly against a bare matplotlib Axes (no
QApplication needed) since it only touches self.ax0 and the plot_* bounds.
"""
from __future__ import annotations

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
