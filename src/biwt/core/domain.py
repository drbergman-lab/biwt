"""
Domain inference logic.

Priority order for resolving the final DomainSpec:
  1. preferred    — host-supplied DomainSpec (always wins if provided)
  2. data_range   — min/max of the raw coordinate arrays (obsm or obs columns),
                    used exactly as found (no unit conversion).  When the
                    coordinates come from image columns (imagerow/imagecol) the
                    domain units are set to ``"pixel"``.
  3. default      — ±500 µm × ±10 µm fallback

Public entry point: ``infer_domain(preferred, obs, obsm)``
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
) -> DomainSpec:
    """Return the best available DomainSpec given what the data provides.

    Coordinates are used exactly as found — BIWT applies no unit conversion.
    When they come from image columns (imagerow/imagecol) the domain units are
    reported as ``"pixel"``.

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
    """
    if preferred is not None:
        return preferred

    # Reported units come from the obs columns: image (imagerow/imagecol)
    # coordinates are pixels, everything else is assumed microns.  Resolve once
    # so the units are consistent whether the bounds come from obsm or obs —
    # a synthesized obsm["spatial"] (built from image columns) would otherwise
    # take the obsm path and lose the pixel-units signal.
    try:
        obs_cols = list(obs.columns) if obs is not None else []
    except AttributeError:
        obs_cols = []
    x_col, y_col, z_col, is_image_coords = resolve_obs_coord_cols(obs_cols)
    units = "pixel" if is_image_coords else "micron"

    # --- try obsm ---------------------------------------------------------
    if obsm is not None:
        key = spatial_key or _find_spatial_key(obsm)
        if key and key in obsm:
            coords = np.asarray(obsm[key], dtype=float)
            if coords.ndim == 2 and coords.shape[1] >= 2:
                return _domain_from_coords(coords, source="data_range", units=units)

    # --- try obs columns --------------------------------------------------
    if x_col and y_col:
        xy = build_obs_coords(obs, x_col, y_col, z_col, is_image_coords)
        return _domain_from_coords(xy, source="data_range", units=units)

    return DomainSpec.default()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain_from_coords(coords: np.ndarray, source: str = "data_range",
                        units: str = "micron") -> DomainSpec:
    """Build a DomainSpec from the bounding box of a coordinate array."""
    xmin, xmax = float(coords[:, 0].min()), float(coords[:, 0].max())
    ymin, ymax = float(coords[:, 1].min()), float(coords[:, 1].max())
    zmin, zmax = -10.0, 10.0
    if coords.shape[1] >= 3:
        zmin = float(coords[:, 2].min())
        zmax = float(coords[:, 2].max())
    return DomainSpec(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
                      zmin=zmin, zmax=zmax, source=source, units=units)


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


def _find_coord_col(columns: list[str], axis: str) -> Optional[str]:
    """Case-insensitive search for a spatial axis column."""
    cols_lower = {c.lower(): c for c in columns}
    for candidate in _COORD_CANDIDATES.get(axis, []):
        if candidate in cols_lower:
            return cols_lower[candidate]
    return None


# Pixel-space coordinate columns from 10x Visium tissue-position tables
# (``imagerow`` / ``imagecol``, as exported by Space Ranger / VisiumSD).
# Consulted only as a last resort, after the x/y/z candidates above.  By that
# convention ``imagecol`` is the horizontal (x) axis and ``imagerow`` is the
# vertical (y) axis; image rows increase *downward*, so ``imagerow`` is flipped
# when building a y-up coordinate array (see ``build_obs_coords``).  There is no
# pixel z axis.  NOTE: coordinates are used as-is (no unit conversion); a future
# session could add a pixels→microns scale factor (see progress.md).
_PIXEL_COORD_CANDIDATES: dict[str, list[str]] = {
    "x": ["imagecol", "image_col"],
    "y": ["imagerow", "image_row"],
}


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

    Returns ``(x_col, y_col, z_col, is_image_coords)``.  Standard ``x``/``y``/``z``
    columns take priority; only when they are absent do we fall back to
    pixel-space ``imagecol``/``imagerow`` columns (``is_image_coords=True``, no z axis).
    Returns ``(None, None, None, False)`` when nothing usable is found.
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
                     z_col: Optional[str], is_image_coords: bool) -> np.ndarray:
    """Build an ``(N, 2)`` or ``(N, 3)`` float coordinate array from obs columns.

    When *is_image_coords* is True the y column is an image row index (increasing
    downward), so it is reflected about its maximum to give a y-up coordinate
    (top of image → largest y).  The reflection preserves the coordinate range.
    """
    x = np.asarray(obs[x_col].values, dtype=float)
    y = np.asarray(obs[y_col].values, dtype=float)
    if is_image_coords:
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
    x_col, y_col, z_col, is_image_coords = resolve_obs_coord_cols(cols)
    if not (x_col and y_col):
        return None
    if is_image_coords:
        return f"obs columns '{x_col}', '{y_col}' (pixel coordinates)"
    if z_col:
        return f"obs columns '{x_col}', '{y_col}', '{z_col}'"
    return f"obs columns '{x_col}', '{y_col}'"
