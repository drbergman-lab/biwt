#!/usr/bin/env python3
"""Generate a synthetic Visium-like dataset for documentation screenshots.

Why synthetic rather than a public 10x dataset: raw Visium carries no cell-type
annotation, so a real file would need a full clustering pass before BIWT's
cluster-column dropdown showed anything interesting.  Synthetic also lets us
tune the composition to read clearly at screenshot resolution, and regenerates
in a second when the UI changes.

The output is built to exercise the screens that actually need a picture:

  * ``obsm["spatial"]`` in *pixel* space, so the data/host unit distinction is
    visible rather than hypothetical.
  * ``uns["spatial"][lib]["scalefactors"]["spot_diameter_fullres"]``, which is
    the one factor BIWT reads from a file — it seeds the "microns per data
    unit" field in the domain editor.  BIWT computes 55.0 / spot_diameter_fullres
    (a Visium spot is 55 µm across), so 110.0 px gives exactly 0.5 µm/pixel.
  * A tissue ~2000 µm across.  Against a default ±500 µm domain that classifies
    as "outside", so the domain editor opens on its own at the positions step —
    which is the context that screenshot wants to show.
  * Cell types with two obvious merges (Tumor_Core + Tumor_Edge, M1 + M2
    Macrophage), so the edit-cell-types screen demonstrates merging rather than
    just listing.
  * Decoy obs columns, so the cluster-column dropdown looks like a real object
    and the "which column?" advice has something to bite on.

Usage
-----
    pip install "biwt[anndata]"
    python scripts/make_screenshot_data.py                  # -> screenshot_data.h5ad
    python scripts/make_screenshot_data.py --deconv         # + probability columns
    python scripts/make_screenshot_data.py --out /tmp/x.h5ad

Then take two passes through the wizard with the same file:

    Pass 1 — answer YES at the spatial query.  Covers import, cluster column,
             edit cell types, rename, positions, domain editor, cell parameters.
    Pass 2 — answer NO at the spatial query.  Covers cell counts, which is
             skipped whenever spatial data is used.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

# A Visium spot is 55 µm in diameter; BIWT divides that by the fullres pixel
# diameter to get µm/pixel.  110 px -> 0.5 µm/pixel.
SPOT_DIAMETER_FULLRES = 110.0
VISIUM_SPOT_DIAMETER_UM = 55.0

LIBRARY_ID = "demo_section"

# (name, n_cells, radial mean in px, radial sd in px)
#
# Everything is laid out radially around a common center: a dense tumor core,
# a rim of tumor edge, macrophages infiltrating that rim, a T-cell margin
# outside it, and fibroblast stroma spread through the periphery.
POPULATIONS = [
    ("Tumor_Core",     600,    0.0,  380.0),
    ("Tumor_Edge",     300,  900.0,  160.0),
    ("M2_Macrophage",  200,  700.0,  280.0),
    ("M1_Macrophage",  200, 1150.0,  220.0),
    ("CD8_T_cell",     300, 1450.0,  240.0),
    ("Fibroblast",     400, 1700.0,  420.0),
]

# Cluster IDs are deliberately finer-grained than the annotation, the way a
# real Leiden/Louvain result is — so picking the cluster column instead of the
# annotation column visibly gives you numbers to rename.
CLUSTERS_PER_TYPE = {
    "Tumor_Core":    [0, 3],
    "Tumor_Edge":    [1],
    "M2_Macrophage": [4],
    "M1_Macrophage": [2],
    "CD8_T_cell":    [5, 7],
    "Fibroblast":    [6],
}

# Offset so coordinates sit inside a plausible fullres image rather than at the
# origin — real Visium coordinates never start at 0.
CENTER_PX = (2400.0, 2100.0)

N_GENES = 30


def build(rng: np.random.Generator) -> tuple[pd.DataFrame, np.ndarray]:
    """Return per-cell obs and an (n, 2) array of pixel coordinates."""
    labels: list[str] = []
    coords: list[np.ndarray] = []

    for name, n, r_mean, r_sd in POPULATIONS:
        # Radial placement with an angular bias per population, so the picture
        # has structure instead of looking like concentric perfect rings.
        radius = np.abs(rng.normal(r_mean, r_sd, size=n))
        theta = rng.uniform(0.0, 2.0 * np.pi, size=n)
        # Squash slightly on y so the tissue reads as a section, not a disc.
        x = CENTER_PX[0] + radius * np.cos(theta)
        y = CENTER_PX[1] + radius * np.sin(theta) * 0.82

        labels.extend([name] * n)
        coords.append(np.column_stack([x, y]))

    xy = np.vstack(coords)
    n_cells = len(labels)

    cluster = np.array([
        rng.choice(CLUSTERS_PER_TYPE[label]) for label in labels
    ])

    obs = pd.DataFrame({
        # Decoys first, in the order a real object tends to carry them — the
        # cluster-column dropdown shows this order.
        "orig.ident":     pd.Categorical(rng.choice(["sample_A", "sample_B"], n_cells)),
        "nCount_RNA":     rng.integers(1_200, 42_000, n_cells),
        "nFeature_RNA":   rng.integers(600, 7_500, n_cells),
        "percent.mt":     np.round(rng.gamma(2.0, 1.6, n_cells), 2),
        "phase":          pd.Categorical(rng.choice(["G1", "S", "G2M"], n_cells,
                                                    p=[0.6, 0.22, 0.18])),
        "seurat_clusters": pd.Categorical(cluster),
        # The one you actually want.
        "cell_type":      pd.Categorical(labels),
    })
    obs.index = [f"CELL_{i:05d}" for i in range(n_cells)]
    return obs, xy


def add_probability_columns(obs: pd.DataFrame, rng: np.random.Generator) -> None:
    """Add per-spot deconvolution probabilities that agree with ``cell_type``.

    Only needed for the spot-deconvolution screen.  Adding these changes the
    wizard's path — BIWT asks the deconvolution question and then skips the
    cluster-column step — so it is opt-in.
    """
    types = list(dict.fromkeys(obs["cell_type"].astype(str)))
    # Dominant type gets most of the mass; the rest is spread as plausible noise.
    weights = rng.dirichlet(np.ones(len(types)) * 0.4, size=len(obs))
    dominant = np.array([types.index(t) for t in obs["cell_type"].astype(str)])
    weights[np.arange(len(obs)), dominant] += 2.0
    weights /= weights.sum(axis=1, keepdims=True)

    for i, t in enumerate(types):
        obs[f"{t}_probability"] = np.round(weights[:, i], 4)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Visium-like data for BIWT doc screenshots.",
    )
    parser.add_argument("--out", default="screenshot_data.h5ad",
                        help="output .h5ad path (default: %(default)s)")
    parser.add_argument("--deconv", action="store_true",
                        help="add *_probability columns (enables the spot-deconvolution step)")
    parser.add_argument("--seed", type=int, default=0,
                        help="RNG seed (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        import anndata
    except ImportError:
        print('anndata is required to write .h5ad.  Install with: '
              'pip install "biwt[anndata]"', file=sys.stderr)
        return 1

    rng = np.random.default_rng(args.seed)
    obs, xy = build(rng)
    if args.deconv:
        add_probability_columns(obs, rng)

    # BIWT never reads X, but AnnData needs one and downstream tools expect it
    # to be non-degenerate.  Kept small so the file stays a few hundred KB.
    X = rng.poisson(1.4, size=(len(obs), N_GENES)).astype(np.float32)

    adata = anndata.AnnData(X=X, obs=obs)
    adata.var_names = [f"GENE{i:03d}" for i in range(N_GENES)]
    adata.obsm["spatial"] = xy

    adata.uns["spatial"] = {
        LIBRARY_ID: {
            "scalefactors": {
                # The only value BIWT reads.
                "spot_diameter_fullres": SPOT_DIAMETER_FULLRES,
                # Present for realism; BIWT ignores these.
                "tissue_hires_scalef": 0.15,
                "tissue_lowres_scalef": 0.045,
                "fiducial_diameter_fullres": SPOT_DIAMETER_FULLRES * 1.6,
            },
            # Real Visium also carries hires/lowres PNGs here.  Omitted so the
            # fixture stays small; BIWT does not look at them.
            "images": {},
        }
    }

    adata.write_h5ad(args.out)

    um_per_px = VISIUM_SPOT_DIAMETER_UM / SPOT_DIAMETER_FULLRES
    span_px = xy.max(axis=0) - xy.min(axis=0)
    span_um = span_px * um_per_px

    print(f"wrote {args.out}")
    print(f"  {len(obs)} cells, {obs['cell_type'].nunique()} types, "
          f"{len(obs.columns)} obs columns")
    print(f"  extent      {span_px[0]:.0f} x {span_px[1]:.0f} px "
          f"-> {span_um[0]:.0f} x {span_um[1]:.0f} um at {um_per_px} um/px")
    print(f"  scale factor seeded from file: {um_per_px} um per data unit")
    if args.deconv:
        print("  probability columns added -> spot-deconvolution step will appear")
    print()
    print("Screenshot passes (same file, twice):")
    print("  1. answer YES at the spatial query -> import, cluster column,")
    print("     edit cell types, rename, positions, domain editor, cell parameters")
    print("  2. answer NO  at the spatial query -> cell counts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
