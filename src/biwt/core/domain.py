"""
Domain inference logic.

Priority order for resolving the final DomainSpec:
  1. preferred        — host-supplied DomainSpec (always wins if provided)
  2. platform_microns — coordinates already in µm from platform metadata
                        (currently: 10x Visium via adata.uns['spatial'] scale factors)
  3. data_range       — min/max of raw coordinate arrays (obsm or obs columns),
                        scaled by microns_per_pixel when available
  4. default          — ±500 µm × ±10 µm fallback

Public entry point: ``infer_domain(preferred, obs, obsm, microns_per_pixel)``
"""

from __future__ import annotations

from typing import Optional
import numpy as np

from biwt.types import DomainSpec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_domain(
    preferred: Optional[DomainSpec] = None,
    obs=None,                               # pd.DataFrame | None
    obsm: Optional[dict] = None,
    spatial_key: Optional[str] = None,
    microns_per_pixel: Optional[float] = None,
) -> DomainSpec:
    """Return the best available DomainSpec given what the data provides.

    Parameters
    ----------
    preferred:
        DomainSpec from the host.  Returned immediately if not ``None``.
    obs:
        AnnData / DataFrame of per-cell metadata.  Checked for x/y(/z) columns
        when obsm yields nothing useful.
    obsm:
        Dict of named coordinate arrays (e.g. ``{"spatial": ndarray, ...}``).
    spatial_key:
        Explicit key to use in ``obsm``.  If ``None``, heuristic search is used.
    microns_per_pixel:
        Scale factor from platform metadata (e.g. 10x Visium).  When provided,
        raw pixel coordinates are multiplied by this value before computing the
        domain bounding box so the result is in µm.  ``None`` means coordinates
        are assumed to already be in µm (or the scale is unknown).
    """
    if preferred is not None:
        return preferred

    # --- try obsm ---------------------------------------------------------
    if obsm is not None:
        key = spatial_key or _find_spatial_key(obsm)
        if key and key in obsm:
            coords = np.asarray(obsm[key], dtype=float)
            if coords.ndim == 2 and coords.shape[1] >= 2:
                if microns_per_pixel is not None:
                    coords = coords * microns_per_pixel
                    source = "platform_microns"
                else:
                    source = "data_range"
                return _domain_from_coords(coords, source=source)

    # --- try obs columns --------------------------------------------------
    if obs is not None:
        try:
            cols = list(obs.columns)
        except AttributeError:
            cols = []
        x_col, y_col, z_col, _is_pixels = resolve_obs_coord_cols(cols)
        if x_col and y_col:
            xy = build_obs_coords(obs, x_col, y_col, z_col, _is_pixels)
            if microns_per_pixel is not None:
                xy = xy * microns_per_pixel
                source = "platform_microns"
            else:
                source = "data_range"
            return _domain_from_coords(xy, source=source)

    return DomainSpec.default()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain_from_coords(coords: np.ndarray, source: str = "data_range") -> DomainSpec:
    """Build a DomainSpec from the bounding box of a coordinate array."""
    xmin, xmax = float(coords[:, 0].min()), float(coords[:, 0].max())
    ymin, ymax = float(coords[:, 1].min()), float(coords[:, 1].max())
    zmin, zmax = -10.0, 10.0
    if coords.shape[1] >= 3:
        zmin = float(coords[:, 2].min())
        zmax = float(coords[:, 2].max())
    return DomainSpec(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
                      zmin=zmin, zmax=zmax, source=source)


def _find_spatial_key(obsm: dict) -> Optional[str]:
    """Return the first obsm key that looks like spatial coordinates."""
    priority = ["spatial", "X_spatial", "spatial_coords"]
    for p in priority:
        if p in obsm:
            return p
    for key in obsm:
        kl = key.lower()
        if "spatial" in kl or "coord" in kl:
            return key
    return None


_COORD_CANDIDATES: dict[str, list[str]] = {
    "x": ["x", "x_coord", "coord_x", "spatial_x", "x_centroid", "cell_x"],
    "y": ["y", "y_coord", "coord_y", "spatial_y", "y_centroid", "cell_y"],
    "z": ["z", "z_coord", "coord_z", "spatial_z", "z_centroid", "cell_z"],
}

# Pixel-space coordinate columns, consulted only as a last resort after the
# x/y/z candidates above.  These come from 10x Visium tissue-position tables
# (``imagerow`` / ``imagecol``, as exported by Space Ranger / VisiumSD).  By
# that convention ``imagecol`` is the horizontal (x) axis and ``imagerow`` is
# the vertical (y) axis, and image rows increase *downward* — so ``imagerow``
# must be flipped when converting to a y-up coordinate system (see
# ``build_obs_coords``).  There is no pixel z axis.
_PIXEL_COORD_CANDIDATES: dict[str, list[str]] = {
    "x": ["imagecol", "image_col"],
    "y": ["imagerow", "image_row"],
}


def _find_coord_col(columns: list[str], axis: str) -> Optional[str]:
    """Case-insensitive search for a spatial axis column."""
    cols_lower = {c.lower(): c for c in columns}
    for candidate in _COORD_CANDIDATES.get(axis, []):
        if candidate in cols_lower:
            return cols_lower[candidate]
    return None


def _find_pixel_coord_col(columns: list[str], axis: str) -> Optional[str]:
    """Case-insensitive search for a pixel-space (imagerow/imagecol) axis column."""
    cols_lower = {c.lower(): c for c in columns}
    for candidate in _PIXEL_COORD_CANDIDATES.get(axis, []):
        if candidate in cols_lower:
            return cols_lower[candidate]
    return None


def resolve_obs_coord_cols(
    columns: list[str],
) -> tuple[Optional[str], Optional[str], Optional[str], bool]:
    """Resolve which obs columns hold spatial coordinates.

    Returns ``(x_col, y_col, z_col, is_pixels)``.

    Standard ``x``/``y``/``z`` columns take priority.  Only when they are
    absent do we fall back to pixel-space ``imagecol``/``imagerow`` columns
    (``is_pixels=True``); the pixel fallback has no z axis, so ``z_col`` is
    ``None`` in that case.  Returns ``(None, None, None, False)`` when no
    usable coordinate columns are found.
    """
    x_col = _find_coord_col(columns, "x")
    y_col = _find_coord_col(columns, "y")
    if x_col and y_col:
        return x_col, y_col, _find_coord_col(columns, "z"), False
    px = _find_pixel_coord_col(columns, "x")   # imagecol → x
    py = _find_pixel_coord_col(columns, "y")   # imagerow → y
    if px and py:
        return px, py, None, True
    return None, None, None, False


def build_obs_coords(obs, x_col: str, y_col: str,
                     z_col: Optional[str], is_pixels: bool) -> np.ndarray:
    """Build an ``(N, 2)`` or ``(N, 3)`` float coordinate array from obs columns.

    When *is_pixels* is True the y column is an image row index (increasing
    downward), so it is reflected about its maximum to produce a y-up
    coordinate (top of the image → largest y).  The reflection keeps the
    coordinate range identical while fixing the orientation.
    """
    x = np.asarray(obs[x_col].values, dtype=float)
    y = np.asarray(obs[y_col].values, dtype=float)
    if is_pixels:
        # Image rows increase downward; flip to a y-up coordinate system.
        y = y.max() - y
    stacked = [x, y]
    if z_col:
        stacked.append(np.asarray(obs[z_col].values, dtype=float))
    return np.column_stack(stacked)


# ---------------------------------------------------------------------------
# Spatial-location description helpers (used by data_loader)
# ---------------------------------------------------------------------------

def classify_domain_mismatch(
    data: DomainSpec,
    preferred: DomainSpec,
) -> Optional[str]:
    """Classify the relationship between data coordinates and the preferred domain.

    Returns
    -------
    "outside"
        One or more data boundaries exceed the preferred domain — those cells
        would be excluded from the simulation.
    "small"
        Data fits inside the preferred domain but covers < 50% of at least one
        axis, or < 50% of the 2-D area — cells would be very sparse.
    None
        No significant mismatch.
    """
    # Use a small tolerance (1e-6 µm ≈ sub-nanometer) to absorb floating-point
    # noise from min/max computations on coordinate arrays.
    tol = 1e-6
    fits_inside = (
        data.xmin >= preferred.xmin - tol and data.xmax <= preferred.xmax + tol
        and data.ymin >= preferred.ymin - tol and data.ymax <= preferred.ymax + tol
    )
    if not fits_inside:
        return "outside"
    if preferred.width == 0 or preferred.height == 0:
        return None
    if (
        data.width  < 0.5 * preferred.width
        or data.height < 0.5 * preferred.height
        or data.width * data.height < 0.5 * preferred.width * preferred.height
    ):
        return "small"
    return None


# ---------------------------------------------------------------------------
# Spatial-location description helpers (used by data_loader)
# ---------------------------------------------------------------------------

def _detect_spatial_location_from_obsm(obsm: dict) -> Optional[str]:
    """Return a human-readable description of where spatial data lives in obsm."""
    key = _find_spatial_key(obsm)
    if key:
        return f"obsm['{key}']"
    return None


def _detect_spatial_location_from_obs(obs) -> Optional[str]:
    """Return a human-readable description of spatial columns in an obs DataFrame."""
    try:
        cols = list(obs.columns)
    except AttributeError:
        return None
    x_col, y_col, z_col, is_pixels = resolve_obs_coord_cols(cols)
    if not (x_col and y_col):
        return None
    if is_pixels:
        return f"obs columns '{x_col}', '{y_col}' (pixel coordinates)"
    if z_col:
        return f"obs columns '{x_col}', '{y_col}', '{z_col}'"
    return f"obs columns '{x_col}', '{y_col}'"
