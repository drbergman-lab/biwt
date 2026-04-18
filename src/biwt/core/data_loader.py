"""
Unified single-cell data loader.

Supported formats
-----------------
.h5ad          AnnData (requires biwt[anndata])
.rds           Seurat / SingleCellExperiment via rpy2 + anndata2ri (requires biwt[seurat])
.rda / .rdata  R workspace files (same rpy2 requirement; loaded with base::load())
.csv           Flat tabular; spatial coordinates inferred from column names

All paths return a ``BiwtData`` object with a common interface so downstream
core logic never needs to know the source format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

from biwt.core.domain import _detect_spatial_location_from_obsm, _detect_spatial_location_from_obs


# ---------------------------------------------------------------------------
# BiwtData — unified in-memory representation
# ---------------------------------------------------------------------------

@dataclass
class BiwtData:
    """Unified in-memory representation of imported single-cell data.

    Attributes
    ----------
    obs:
        Per-cell metadata DataFrame (cluster labels, cell-type columns, etc.).
        Analogous to AnnData.obs.
    obsm:
        Named coordinate arrays (e.g. ``{"spatial": ndarray, "X_umap": ndarray}``).
        Analogous to AnnData.obsm.
    spatial_location:
        Human-readable description of where spatial coordinates were found,
        e.g. ``"obsm['spatial']"`` or ``"obs columns 'x', 'y'"`` or ``None``.
    file_path:
        Path the data was loaded from.
    probability_columns:
        Obs columns that look like per-cell-type deconvolution probabilities.
    microns_per_pixel:
        Scale factor derived from platform metadata (e.g. 10x Visium
        ``scalefactors``).  ``None`` when not available; ``domain.py`` uses
        this to convert pixel-space coordinates to µm before domain inference.
    """
    obs: pd.DataFrame
    obsm: dict = field(default_factory=dict)
    spatial_location: Optional[str] = None
    file_path: str = ""
    probability_columns: list = field(default_factory=list)
    microns_per_pixel: Optional[float] = None

    @property
    def column_names(self) -> list[str]:
        return list(self.obs.columns)

    @property
    def has_spatial(self) -> bool:
        return self.spatial_location is not None

    @property
    def n_cells(self) -> int:
        return len(self.obs)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LoadError(Exception):
    """Raised when a file cannot be loaded."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# R file extensions that share the same load path
_R_EXTENSIONS = {".rds", ".rda", ".rdata"}


def load(file_path: str) -> BiwtData:
    """Load single-cell data from *file_path* and return a ``BiwtData``.

    Dispatches on file extension:
        ``.h5ad``              → AnnData
        ``.rds``               → R object saved with ``saveRDS()``
        ``.rda`` / ``.rdata``  → R workspace saved with ``save()``
        ``.csv``               → flat CSV

    Raises
    ------
    LoadError
        On unsupported format or read failure, with an actionable message.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".h5ad":
        return _load_h5ad(file_path)
    if suffix in _R_EXTENSIONS:
        return _load_r_file(file_path, suffix)
    if suffix == ".csv":
        return _load_csv(file_path)
    raise LoadError(
        f"Unsupported file extension '{suffix}'. "
        "BIWT supports: .h5ad, .rds, .rda, .rdata, .csv"
    )


# ---------------------------------------------------------------------------
# Format-specific loaders
# ---------------------------------------------------------------------------

def _load_h5ad(file_path: str) -> BiwtData:
    try:
        import anndata
    except ImportError:
        raise LoadError(
            "anndata is required for .h5ad files.\n"
            "Install with:  pip install biwt[anndata]"
        )
    try:
        adata = anndata.read_h5ad(file_path)
    except Exception as e:
        raise LoadError(f"Failed to read '{file_path}' as AnnData: {e}") from e

    mpp = _extract_visium_microns_per_pixel(adata)
    return _from_anndata_object(adata, file_path, microns_per_pixel=mpp)


def _load_r_file(file_path: str, suffix: str) -> BiwtData:
    """Load an R object file (.rds, .rda, or .rdata) via rpy2 + anndata2ri.

    .rds files contain a single serialised R object (``saveRDS`` / ``readRDS``).
    .rda / .rdata files are R workspace files that can contain multiple named
    objects (``save`` / ``load``).  We grab the first object in the workspace;
    if the file was produced by a standard Seurat/SCE export workflow it will
    contain exactly one object.
    """
    try:
        import anndata2ri
        from rpy2.robjects.packages import importr
        from rpy2.robjects import r as reval
    except ImportError:
        raise LoadError(
            "rpy2 and anndata2ri are required for R files.\n"
            "Install with:  pip install biwt[seurat]"
        )
    try:
        anndata2ri.activate()
    except Exception as e:
        raise LoadError(f"anndata2ri activation failed: {e}") from e

    try:
        base = importr("base")

        if suffix == ".rds":
            # readRDS returns the object directly
            robj = base.readRDS(file_path)
        else:
            # load() reads into an environment; grab the first named object
            env = reval("new.env(parent = emptyenv())")
            base.load(file_path, envir=env)
            obj_names = list(base.ls(env))
            if not obj_names:
                raise LoadError(f"No objects found in R workspace '{file_path}'.")
            robj = env[obj_names[0]]

        classname = tuple(robj.rclass)[0]

        if classname in ("SingleCellExperiment", "SummarizedExperiment"):
            adata = anndata2ri.rpy2py(robj)
        elif classname == "Seurat":
            reval("library(Seurat)")
            # Re-read via R string evaluation so Seurat's conversion method is
            # available; funnel through the same anndata2ri path afterwards.
            if suffix == ".rds":
                reval(f'x <- readRDS("{file_path}")')
            else:
                reval(f'load("{file_path}"); x <- get(ls()[1])')
            adata = reval("as.SingleCellExperiment(x)")
            adata = anndata2ri.rpy2py(adata)
        else:
            raise LoadError(
                f"R object class '{classname}' is not supported. "
                "Expected: Seurat, SingleCellExperiment, or SummarizedExperiment."
            )
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f"Failed to read '{file_path}' as R object: {e}") from e

    return _from_anndata_object(adata, file_path)


def _load_csv(file_path: str) -> BiwtData:
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        raise LoadError(f"Failed to read '{file_path}' as CSV: {e}") from e

    spatial_location = _detect_spatial_location_from_obs(df)
    prob_cols = _find_probability_columns(df)

    # Synthesize obsm["spatial"] from coordinate columns so the dim-red
    # plotter in EditCellTypesWindow can display the spatial scatter plot.
    obsm: dict = {}
    if spatial_location is not None:
        from biwt.core.domain import _find_coord_col
        cols = list(df.columns)
        x_col = _find_coord_col(cols, "x") or _find_coord_col(cols, "imagerow")
        y_col = _find_coord_col(cols, "y") or _find_coord_col(cols, "imagecol")
        if x_col and y_col:
            z_col = _find_coord_col(cols, "z")
            xy = np.column_stack([df[x_col].to_numpy(float), df[y_col].to_numpy(float)])
            if z_col:
                obsm["spatial"] = np.column_stack([xy, df[z_col].to_numpy(float)])
            else:
                obsm["spatial"] = xy

    return BiwtData(
        obs=df,
        obsm=obsm,
        spatial_location=spatial_location,
        file_path=file_path,
        probability_columns=prob_cols,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _from_anndata_object(
    adata,
    file_path: str,
    microns_per_pixel: Optional[float] = None,
) -> BiwtData:
    """Build a BiwtData from an in-memory AnnData object."""
    try:
        obs = adata.obs
        obsm = dict(adata.obsm)
    except Exception as e:
        raise LoadError(f"Could not read obs/obsm from AnnData object: {e}") from e

    spatial_loc = (
        _detect_spatial_location_from_obsm(obsm)
        or _detect_spatial_location_from_obs(obs)
    )
    prob_cols = _find_probability_columns(obs)
    return BiwtData(
        obs=obs,
        obsm=obsm,
        spatial_location=spatial_loc,
        file_path=file_path,
        probability_columns=prob_cols,
        microns_per_pixel=microns_per_pixel,
    )


def _extract_visium_microns_per_pixel(adata) -> Optional[float]:
    """Extract the µm/pixel scale factor from 10x Visium AnnData metadata.

    10x Visium spots are 55 µm in diameter in the tissue section.
    The fullres pixel diameter is stored in
    ``adata.uns['spatial'][library_id]['scalefactors']['spot_diameter_fullres']``.

    Returns ``None`` for any non-Visium or missing metadata — callers treat
    ``None`` as "scale unknown; use raw coordinates".

    Platform-specific notes
    -----------------------
    This currently handles 10x Visium only.  Other platforms with known
    physical scales (Xenium, MERFISH, etc.) typically store coordinates
    already in µm and do not need this conversion.  Add cases here as
    support for other platforms is added.
    """
    try:
        spatial_meta = adata.uns.get("spatial", {})
        if not spatial_meta:
            return None
        # Take the first library (multi-library arrays are uncommon)
        library_id = next(iter(spatial_meta))
        scalefactors = spatial_meta[library_id].get("scalefactors", {})
        spot_diameter_px = scalefactors.get("spot_diameter_fullres")
        if spot_diameter_px and spot_diameter_px > 0:
            visium_spot_diameter_um = 55.0
            return visium_spot_diameter_um / spot_diameter_px
    except Exception:
        pass
    return None


def _find_probability_columns(obs: pd.DataFrame) -> list[str]:
    """Return obs columns that look like per-cell-type deconvolution probabilities."""
    return [
        col for col in obs.columns
        if col.endswith("_probability") and (obs[col] >= 0).all() and obs[col].sum() > 0
    ]
