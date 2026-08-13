"""
Unified single-cell data loader.

Supported formats
-----------------
.h5ad          AnnData (requires biwt[anndata])
.rds           Seurat / SingleCellExperiment / SpatialExperiment via rpy2 + anndata2ri (requires biwt[seurat])
.rda / .rdata  R workspace files (same rpy2 requirement, loaded with base::load();
               the object of a supported class is used, and an ambiguous
               workspace is refused rather than guessed at)
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

from biwt.core.domain import (
    _detect_spatial_location_from_obsm,
    _detect_spatial_location_from_obs,
    resolve_obs_coord_cols,
    build_obs_coords,
)


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
    host_units_per_data_unit:
        Conversion factor (host units per one raw data-coordinate unit) that the
        *file itself* provided, or ``None`` if none.  Currently only 10x Visium
        `.h5ad` (via ``scalefactors``) supplies this, and what it supplies is
        µm/pixel — so the value only means "host units" for a host measuring in
        microns.  It seeds the editable scale factor in the domain editor; it is
        never applied silently.
    """
    obs: pd.DataFrame
    obsm: dict = field(default_factory=dict)
    spatial_location: Optional[str] = None
    file_path: str = ""
    probability_columns: list = field(default_factory=list)
    host_units_per_data_unit: Optional[float] = None

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

# Setup instructions for the optional data-format dependencies.  Attached to the
# subset of LoadErrors a user fixes by changing their environment rather than
# their file, so any host — GUI, notebook, CLI — can point at the same guide.
#
# Two targets, because the two failure modes have different fixes: a dependency
# that was never installed sends you to the install matrix, while an R stack
# that is present but misbehaving sends you to the numbered troubleshooting
# entries that diagnose it.
DOCS_BASE_URL = "https://drbergman-lab.github.io/biwt/"
INSTALL_DOCS_URL = DOCS_BASE_URL + "getting-started/installation/"
TROUBLESHOOTING_DOCS_URL = DOCS_BASE_URL + "getting-started/troubleshooting/"


class LoadError(Exception):
    """Raised when a file cannot be loaded.

    ``docs_url`` is set when the fix is an installation or environment change
    (a missing optional dependency, a broken R stack) and is ``None`` when the
    failure is about the file itself (unsupported extension, malformed CSV).

    So a host displaying this error should render the link only when
    ``docs_url`` is not ``None``, rather than always linking to the setup docs.
    """

    def __init__(self, message: str, *, docs_url: Optional[str] = None):
        super().__init__(message)
        self.docs_url = docs_url


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# R file extensions that share the same load path
_R_EXTENSIONS = {".rds", ".rda", ".rdata"}


@dataclass(frozen=True)
class FormatSupport:
    """One importable file format, and whether this environment can read it.

    Lets a host say so *before* the user picks a file: BIWT's optional data
    dependencies are otherwise discovered by failing an import and reading the
    error dialog.
    """
    extensions: tuple
    description: str
    requires: tuple = ()      # module names that must be importable
    extra: str = ""           # the pip extra that installs them

    @property
    def label(self) -> str:
        return " ".join(self.extensions)

    @property
    def missing(self) -> tuple:
        """Required modules that are not importable, in declaration order."""
        import importlib.util

        absent = []
        for module in self.requires:
            try:
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False       # a package whose own parent is missing
            if not found:
                absent.append(module)
        return tuple(absent)

    @property
    def available(self) -> bool:
        return not self.missing

    @property
    def hint(self) -> str:
        """Why it is unavailable and how to fix it, or '' when it is available."""
        if self.available:
            return ""
        needs = " and ".join(self.missing)
        fix = f"\npip install {self.extra}" if self.extra else ""
        return f"Needs {needs}, which is not installed.{fix}"


def supported_formats() -> list:
    """Every format ``load`` accepts, with its availability in this environment.

    Probed with ``importlib.util.find_spec``, so asking is cheap and does not
    import the dependency.
    """
    return [
        FormatSupport(
            extensions=(".h5ad",), description="AnnData",
            requires=("anndata",), extra="biwt[anndata]",
        ),
        FormatSupport(
            extensions=(".rds", ".rda", ".rdata"), description="Seurat / SCE",
            requires=("rpy2", "anndata2ri"), extra="biwt[seurat]",
        ),
        FormatSupport(extensions=(".csv",), description="flat table"),
    ]


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
            "Install with:  pip install biwt[anndata]",
            docs_url=INSTALL_DOCS_URL,
        )
    try:
        adata = anndata.read_h5ad(file_path)
    except Exception as e:
        raise LoadError(f"Failed to read '{file_path}' as AnnData: {e}") from e

    mpu = _extract_visium_microns_per_pixel(adata)
    return _from_anndata_object(adata, file_path, host_units_per_data_unit=mpu)


# Classes anndata2ri can convert.  SpatialExperiment is an SCE subclass and goes
# through the SCE path; Seurat needs a re-read so its own method is available.
_SCE_CLASSES = ("SingleCellExperiment", "SpatialExperiment", "SummarizedExperiment")
_R_DATASET_CLASSES = _SCE_CLASSES + ("Seurat",)


def _pick_workspace_object(env, obj_names: list, file_path: str) -> str:
    """Return the name of the single loadable dataset in an R workspace.

    ``base::ls()`` returns names *sorted*, so taking the first took whatever
    sorted first rather than whatever was saved first — a workspace holding
    ``annotations`` and ``seurat_obj`` imported ``annotations``.  Choosing by
    class instead makes the common multi-object workspace work.

    More than one dataset is refused rather than guessed at.  Which one the user
    meant is genuinely unknown, and it would have to be asked somewhere; a file
    holding exactly one object also keeps the run reproducible from the file
    alone.
    """
    matches = []
    for name in obj_names:
        try:
            classes = tuple(env[name].rclass)
        except Exception:
            continue                       # not an R object we can inspect
        if any(c in _R_DATASET_CLASSES for c in classes):
            matches.append(name)

    if len(matches) == 1:
        return matches[0]
    listing = ", ".join(obj_names)
    if not matches:
        raise LoadError(
            f"'{file_path}' contains no Seurat or SingleCellExperiment object.\n"
            f"Objects found: {listing}.\n"
            "Re-save the workspace with the dataset in it, or export it with "
            "saveRDS() to a .rds file.",
            docs_url=TROUBLESHOOTING_DOCS_URL,
        )
    raise LoadError(
        f"'{file_path}' contains more than one dataset: {', '.join(matches)}.\n"
        "BIWT cannot tell which one you meant. Re-save just that one into its "
        "own file — save(obj, file=\"one.rda\") or saveRDS(obj, \"one.rds\").",
        docs_url=TROUBLESHOOTING_DOCS_URL,
    )


def _load_r_file(file_path: str, suffix: str) -> BiwtData:
    """Load an R object file (.rds, .rda, or .rdata) via rpy2 + anndata2ri.

    .rds files contain a single serialised R object (``saveRDS`` / ``readRDS``).
    .rda / .rdata files are R workspace files that can hold several named objects
    (``save`` / ``load``); the one of a supported class is used, and anything
    ambiguous is refused with the reason.  The extension is matched lowercased,
    so the conventional ``.RData`` spelling works.
    """
    try:
        import anndata2ri
        from rpy2.robjects.packages import importr
        from rpy2.robjects import r as reval
    except ImportError:
        raise LoadError(
            "rpy2 and anndata2ri are required for R files.\n"
            "Install with:  pip install biwt[seurat]",
            docs_url=INSTALL_DOCS_URL,
        )
    try:
        anndata2ri.activate()
    except Exception as e:
        # Almost always anndata2ri 2.0+, which dropped activate(); BIWT pins <2.
        raise LoadError(
            f"anndata2ri activation failed: {e}", docs_url=TROUBLESHOOTING_DOCS_URL
        ) from e

    try:
        base = importr("base")

        if suffix == ".rds":
            # readRDS returns the object directly
            robj = base.readRDS(file_path)
        else:
            # load() reads into an environment; pick the dataset out of it
            env = reval("new.env(parent = emptyenv())")
            base.load(file_path, envir=env)
            obj_names = list(base.ls(env))
            if not obj_names:
                raise LoadError(f"No objects found in R workspace '{file_path}'.")
            ws_name = _pick_workspace_object(env, obj_names, file_path)
            robj = env[ws_name]

        classname = tuple(robj.rclass)[0]

        if classname in _SCE_CLASSES:
            adata = anndata2ri.rpy2py(robj)
        elif classname == "Seurat":
            reval("library(Seurat)")
            # Re-read via R string evaluation so Seurat's conversion method is
            # available; funnel through the same anndata2ri path afterwards.
            if suffix == ".rds":
                reval(f'x <- readRDS("{file_path}")')
            else:
                reval(f'load("{file_path}"); x <- get("{ws_name}")')
            adata = reval("as.SingleCellExperiment(x)")
            adata = anndata2ri.rpy2py(adata)
        else:
            raise LoadError(
                f"R object class '{classname}' is not supported. "
                f"Expected one of: {', '.join(_R_DATASET_CLASSES)}."
            )
    except LoadError:
        raise
    except Exception as e:
        # Usually an R-side problem rather than a bad file: SeuratObject not
        # installed in the R that rpy2 bound to, or an ABI-mismatched R.
        raise LoadError(
            f"Failed to read '{file_path}' as R object: {e}", docs_url=TROUBLESHOOTING_DOCS_URL
        ) from e

    mpu = _extract_visium_microns_per_pixel(adata)
    return _from_anndata_object(adata, file_path, host_units_per_data_unit=mpu)


def _load_csv(file_path: str) -> BiwtData:
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        raise LoadError(f"Failed to read '{file_path}' as CSV: {e}") from e

    spatial_location = _detect_spatial_location_from_obs(df)
    prob_cols = _find_probability_columns(df)

    # Synthesize obsm["spatial"] from coordinate columns so the dim-red
    # plotter in EditCellTypesWindow can display the spatial scatter plot.
    # For image columns: imagecol -> x, imagerow -> y (flipped y-up) — see
    # build_obs_coords.
    obsm: dict = {}
    x_col, y_col, z_col, is_image_coords = resolve_obs_coord_cols(list(df.columns))
    if x_col and y_col:
        obsm["spatial"] = build_obs_coords(df, x_col, y_col, z_col, is_image_coords)

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
    host_units_per_data_unit: Optional[float] = None,
) -> BiwtData:
    """Build a BiwtData from an in-memory AnnData object."""
    try:
        obs = adata.obs
        obsm = dict(adata.obsm)
    except Exception as e:
        raise LoadError(f"Could not read obs/obsm from AnnData object: {e}") from e

    if obs.shape[1] == 0:
        # Nothing to pick a cell-type column from; the step would offer an empty
        # dropdown and the next one would read None.
        raise LoadError(f"'{file_path}' has no obs columns to label cell types with.")

    obsm_loc = _detect_spatial_location_from_obsm(obsm)
    spatial_loc = obsm_loc or _detect_spatial_location_from_obs(obs)

    # When spatial coordinates live in obs columns (not an obsm array),
    # synthesize obsm["spatial"] from them (imagerow/imagecol get the y-up flip)
    # so the EditCellTypes dim-reduction plotter can offer a Spatial view.
    if obsm_loc is None and spatial_loc is not None:
        x_col, y_col, z_col, is_image_coords = resolve_obs_coord_cols(list(obs.columns))
        if x_col and y_col and "spatial" not in obsm:
            obsm["spatial"] = build_obs_coords(obs, x_col, y_col, z_col, is_image_coords)

    prob_cols = _find_probability_columns(obs)
    return BiwtData(
        obs=obs,
        obsm=obsm,
        spatial_location=spatial_loc,
        file_path=file_path,
        probability_columns=prob_cols,
        host_units_per_data_unit=host_units_per_data_unit,
    )


def _extract_visium_microns_per_pixel(adata) -> Optional[float]:
    """Extract the µm/pixel scale factor from 10x Visium AnnData metadata.

    10x Visium spots are 55 µm in diameter in the tissue section.  The fullres
    pixel diameter is stored in
    ``adata.uns['spatial'][library_id]['scalefactors']['spot_diameter_fullres']``,
    so µm/pixel = ``55.0 / spot_diameter_fullres``.

    Returns ``None`` for any non-Visium or missing metadata (callers treat that
    as "no file-provided factor").  This is the only format-derived factor BIWT
    currently reads; the value is never applied silently — it seeds the editable
    scale factor in the domain editor.
    """
    try:
        spatial_meta = adata.uns.get("spatial", {})
        if not spatial_meta:
            return None
        library_id = next(iter(spatial_meta))
        scalefactors = spatial_meta[library_id].get("scalefactors", {})
        spot_diameter_px = scalefactors.get("spot_diameter_fullres")
        if spot_diameter_px and spot_diameter_px > 0:
            visium_spot_diameter_um = 55.0
            return visium_spot_diameter_um / spot_diameter_px
    except Exception:
        pass
    return None


def clamp_probabilities(values) -> np.ndarray:
    """Return *values* as floats confined to ``[0, inf)``, everything else zeroed.

    NaN, ±inf and negatives are not weights, but they are also not a reason to
    discard the cell type they belong to: a single NaN used to fail an
    ``(obs[col] >= 0).all()`` test for the whole column, so that type vanished
    from the run with no error and no mention.  Zeroing the offending spot leaves
    the rest of the column — and the cell type — intact.
    """
    arr = np.asarray(values, dtype=float)
    return np.where(np.isfinite(arr) & (arr >= 0.0), arr, 0.0)


def _find_probability_columns(obs: pd.DataFrame) -> list[str]:
    """Return obs columns that look like per-cell-type deconvolution probabilities.

    A column qualifies on its name plus any surviving mass once out-of-range
    values are zeroed; an all-zero column weights nothing and is dropped.
    """
    return [
        col for col in obs.columns
        if col.endswith("_probability") and clamp_probabilities(obs[col]).sum() > 0
    ]
