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
        x_col = _find_coord_col(cols, "x")
        y_col = _find_coord_col(cols, "y")
        if x_col and y_col:
            xy = np.column_stack([obs[x_col].values, obs[y_col].values]).astype(float)
            z_col = _find_coord_col(cols, "z")
            if z_col:
                xy = np.column_stack([xy, obs[z_col].values])
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


def _find_coord_col(columns: list[str], axis: str) -> Optional[str]:
    """Case-insensitive search for a spatial axis column."""
    cols_lower = {c.lower(): c for c in columns}
    for candidate in _COORD_CANDIDATES.get(axis, []):
        if candidate in cols_lower:
            return cols_lower[candidate]
    return None


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
    x_col = _find_coord_col(cols, "x")
    y_col = _find_coord_col(cols, "y")
    if x_col and y_col:
        z_col = _find_coord_col(cols, "z")
        if z_col:
            return f"obs columns '{x_col}', '{y_col}', '{z_col}'"
        return f"obs columns '{x_col}', '{y_col}'"
    return None
