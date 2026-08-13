"""
Spatial coordinate transformation and IC DataFrame construction.

``compute_spatial_placement`` sizes and centers the data's extent inside the
host's domain; the positions window applies the result to the coordinates it
plots.  ``build_ic_dataframe`` then collapses the per-cell-type coordinate
dicts into the flat ``BiwtResult.coordinates`` DataFrame the host receives.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Coordinate scaling
# ---------------------------------------------------------------------------

def compute_spatial_placement(data_extent, domain_center, scale, is_2d):
    """Placement rectangle for the spatial plotter.

    The data is scaled uniformly by *scale* (host-units per data unit) and
    centered at *domain_center* — a pure scale + translate, so aspect ratio is
    always preserved.  *scale* of ``1.0`` places the data at its own extent,
    centered (no conversion).

    Parameters
    ----------
    data_extent:
        Sequence ``(dx, dy)`` (2-D) or ``(dx, dy, dz)`` (3-D) — the data's
        bounding-box widths.
    domain_center:
        Sequence ``(cx, cy)`` or ``(cx, cy, cz)`` — the domain center to place
        the scaled data around.
    scale:
        Uniform multiplier applied to every axis extent.
    is_2d:
        When True use only x/y.

    Returns
    -------
    ``[x0, y0, w, h]`` (2-D) or ``[x0, y0, z0, w, h, d]`` (3-D): the placement
    rectangle's origin (min corner) followed by its widths.
    """
    n = 2 if is_2d else 3
    wh = [float(data_extent[i]) * scale for i in range(n)]
    origin = [float(domain_center[i]) - wh[i] / 2.0 for i in range(n)]
    return origin + wh


# ---------------------------------------------------------------------------
# IC DataFrame construction
# ---------------------------------------------------------------------------

def build_ic_dataframe(
    coords_by_type: dict[str, np.ndarray],
) -> pd.DataFrame:
    """Convert per-cell-type coordinate arrays into the standard IC DataFrame.

    Parameters
    ----------
    coords_by_type:
        ``{cell_type_name: (N, 3) ndarray}`` — one entry per kept cell type.

    Returns
    -------
    DataFrame with columns ``["x", "y", "z", "type"]``.
    A cell type whose array is empty contributes no rows — that is how a
    zero-count type reaches the output: defined, but placing nothing.
    Empty DataFrame (same columns, same dtypes) if no rows result at all.
    """
    rows = []
    for cell_type, coords in coords_by_type.items():
        coords = np.asarray(coords)
        for row in coords:
            rows.append({
                "x": float(row[0]),
                "y": float(row[1]),
                "z": float(row[2]) if len(row) > 2 else 0.0,
                "type": cell_type,
            })

    if not rows:
        # pd.DataFrame([]) types every column as object, which would then
        # propagate into a host's concat/append of real coordinates.
        return _empty_ic_dataframe()

    return pd.DataFrame(rows, columns=["x", "y", "z", "type"])


def _empty_ic_dataframe() -> pd.DataFrame:
    """Zero-row IC DataFrame with the dtypes a populated one would have."""
    return pd.DataFrame({
        "x": pd.Series(dtype="float64"),
        "y": pd.Series(dtype="float64"),
        "z": pd.Series(dtype="float64"),
        "type": pd.Series(dtype="object"),
    })


# ---------------------------------------------------------------------------
# Spot deconvolution helpers
# ---------------------------------------------------------------------------

def apportion_spot_cells(
    probabilities: dict[str, float],
    n_cells: int,
) -> dict[str, int]:
    """Divide *n_cells* among the cell types in *probabilities*.

    Equal-proportions (Huntington–Hill) apportionment with a **shifted
    divisor**: a type already holding ``c`` cells competes for the next one at
    priority ``p / sqrt((c+1)(c+2))``, starting from ``p / sqrt(2)``.

    The shift is the important part.  Textbook Huntington–Hill gives every party
    a free first seat — its divisor is ``sqrt(0*1) = 0``, i.e. infinite priority
    — which here would drop one cell of *every* reference type into *every*
    spot, including the ~1e-4 probabilities a deconvolution emits for types that
    are not really present.  Making the first cell compete like any other means
    a type appears only once its probability is a meaningful fraction of the
    leading type's.

    The rule is scale-invariant: multiplying every probability by a constant
    leaves the result unchanged.  So *probabilities* need not sum to 1, and
    filtering to a subset of types without renormalizing is safe.

    Ties are broken **at random**.  Exact ties are common — two types at 0.5
    across many spots — and breaking them deterministically (by ``max()``, i.e.
    by dict order, i.e. by ``obs`` column order) would award the surplus to the
    same type in every spot.  That is a tissue-wide population skew, not
    per-spot noise that averages out.

    Returns ``{cell_type: count}`` over exactly the keys of *probabilities*,
    summing to ``max(n_cells, 0)``.
    """
    counts = {k: 0 for k in probabilities}
    if n_cells <= 0 or not probabilities:
        return counts

    priorities = {k: v / np.sqrt(2) for k, v in probabilities.items()}
    for _ in range(n_cells):
        best = max(priorities.values())
        tied = [k for k, v in priorities.items() if v == best]
        winner = tied[0] if len(tied) == 1 else tied[np.random.randint(len(tied))]
        counts[winner] += 1
        priorities[winner] = probabilities[winner] / np.sqrt(
            (counts[winner] + 1) * (counts[winner] + 2)
        )
    return counts
