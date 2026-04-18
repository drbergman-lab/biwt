"""
Spatial coordinate transformation and IC DataFrame construction.

The core operation is ``scale_spatial_to_domain``: it takes raw spatial
coordinates (arbitrary units, arbitrary origin) and maps them into the
PhysiCell simulation domain described by a ``DomainSpec``.

``build_ic_dataframe`` then collapses per-cell-type coordinate dicts into
the flat ``BiwtResult.coordinates`` DataFrame.
"""

from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from biwt.types import DomainSpec


# ---------------------------------------------------------------------------
# Coordinate scaling
# ---------------------------------------------------------------------------

def scale_spatial_to_domain(
    coords: np.ndarray,
    domain: DomainSpec,
    preserve_aspect: bool = True,
) -> np.ndarray:
    """Map raw spatial coordinates into the PhysiCell domain.

    Parameters
    ----------
    coords:
        ``(N, 2)`` or ``(N, 3)`` float array of spatial positions in any
        arbitrary unit system (pixels, arbitrary spatial units, etc.).
    domain:
        Target PhysiCell domain in microns.
    preserve_aspect:
        If ``True``, scale both axes by the same factor (the smaller of the
        two domain extents divided by the data extent) so the tissue shape
        is not distorted.  The scaled data is centered in the domain.
        If ``False``, stretch independently to fill the full domain extent
        in each axis.

    Returns
    -------
    ``(N, 3)`` float array with z set to 0 when input was 2-D.
    """
    coords = np.asarray(coords, dtype=float)
    n_dims = coords.shape[1]

    src_min = coords.min(axis=0)
    src_max = coords.max(axis=0)
    src_range = src_max - src_min
    src_range[src_range == 0] = 1.0     # avoid divide-by-zero for degenerate axes

    # Normalize to [0, 1]
    normalized = (coords - src_min) / src_range

    domain_widths = np.array([domain.width, domain.height, domain.depth])
    domain_origins = np.array([domain.xmin, domain.ymin, domain.zmin])

    out = np.zeros((len(coords), 3))

    if preserve_aspect:
        # Scale by the smallest ratio so data fits within domain without distortion,
        # then center the result.
        n_spatial = min(n_dims, 2)  # only x/y for 2-D data
        scale = min(domain_widths[i] for i in range(n_spatial))
        for i in range(n_dims):
            center = domain_origins[i] + 0.5 * domain_widths[i]
            data_width = scale if i < 2 else domain_widths[2]
            out[:, i] = (normalized[:, i] - 0.5) * data_width + center
    else:
        for i in range(n_dims):
            out[:, i] = normalized[:, i] * domain_widths[i] + domain_origins[i]

    # z stays 0 when input was 2-D (already initialised to 0)
    return out


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
    Empty DataFrame (same columns) if *coords_by_type* is empty.
    """
    if not coords_by_type:
        return pd.DataFrame(columns=["x", "y", "z", "type"])

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

    return pd.DataFrame(rows, columns=["x", "y", "z", "type"])


# ---------------------------------------------------------------------------
# Spot deconvolution helpers
# ---------------------------------------------------------------------------

def expand_spot_to_cells(
    spot_center: np.ndarray,
    cell_type_fractions: dict[str, float],
    total_cells: int,
    cell_radius: float = 8.41,
    rng: Optional[np.random.Generator] = None,
) -> dict[str, np.ndarray]:
    """Place cells around a spot center according to fractional composition.

    Parameters
    ----------
    spot_center:
        ``(2,)`` or ``(3,)`` array — center of the spot in domain coordinates.
    cell_type_fractions:
        ``{cell_type: fraction}`` — must sum to ≤ 1.
    total_cells:
        Total number of cells to place across all types.
    cell_radius:
        Approximate cell radius in microns (used to space cells within spot).
    rng:
        Optional NumPy random generator for reproducibility.

    Returns
    -------
    ``{cell_type: (n, 3) ndarray}`` of placed positions.
    """
    if rng is None:
        rng = np.random.default_rng()

    spot_center = np.asarray(spot_center, dtype=float)
    if spot_center.shape[0] < 3:
        spot_center = np.append(spot_center, 0.0)

    counts = {
        ct: max(1, round(frac * total_cells))
        for ct, frac in cell_type_fractions.items()
        if frac > 0
    }

    result: dict[str, np.ndarray] = {}
    for ct, n in counts.items():
        # Randomly jitter within a disk of radius proportional to cell count
        disk_r = cell_radius * np.sqrt(n)
        angles = rng.uniform(0, 2 * np.pi, n)
        radii = disk_r * np.sqrt(rng.uniform(0, 1, n))
        xs = spot_center[0] + radii * np.cos(angles)
        ys = spot_center[1] + radii * np.sin(angles)
        zs = np.full(n, spot_center[2])
        result[ct] = np.column_stack([xs, ys, zs])

    return result
