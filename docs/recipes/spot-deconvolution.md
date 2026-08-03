# Recipe: Spot deconvolution

**You have:** spot-level spatial data — Visium, usually — where a deconvolution analysis
estimated the cell-type mixture in each spot. **You want:** individual cells, at tissue
positions, in the estimated proportions.

## What the data looks like

One row per spot, coordinates, and one probability column per cell type:

| x | y | Tumor_probability | T_cell_probability | Macrophage_probability |
|---|---|---|---|---|
| 1204 | 3388 | 0.7 | 0.2 | 0.1 |
| 1451 | 3380 | 0.1 | 0.1 | 0.8 |

BIWT recognizes columns ending in `_probability`. The naming matters — if your deconvolution
tool wrote `Tumor_prop` or `frac_Tumor`, rename the columns before importing:

```python
adata.obs = adata.obs.rename(columns={"Tumor_prop": "Tumor_probability"})
```

Common sources of this shape: cell2location, RCTD, SPOTlight, Seurat's anchor-based transfer.
Each writes proportions differently; normalize the column names first.

## Why bother

A Visium spot is 55 µm across and contains roughly 1–10 cells. Treating each spot as one agent
gives you a sparse, low-resolution population — and throws away the mixture information the
deconvolution produced.

Expanding spots into cells gives you a population whose density and local composition both
reflect the tissue. Where the data says a spot is 70% tumor and 30% immune, you get cells in
roughly that ratio at roughly that location.

## Walking through

### Import

BIWT detects both the coordinates and the probability columns.

### Spot deconvolution → **yes**

Accepting means the probability columns define your cell types, so the
[cluster column](../guide/cluster-column.md) screen is skipped — there is nothing to pick.

Your cell types are now derived from the column names: `Tumor_probability` becomes `Tumor`.

### Spatial query → **yes**

Placing deconvolved cells at random would discard the reason you deconvolved them.

### Edit and rename

The same considerations as elsewhere: merge types your model does not distinguish, delete
ones it does not include.

One case specific to deconvolution: tools often emit a small probability for every reference
type in every spot, including types that are not really present. Such a type will not place
stray cells — allocation is deterministic from the per-spot proportions, and a trivially
probable type simply never wins a cell. But it still occupies a row on every subsequent screen
and a `<cell_definition>` in the output, so you could consider deleting it here to keep the
type list honest.

??? info "How cells are apportioned within a spot"
    Each spot's cells are handed out by equal-proportions (Huntington–Hill) apportionment with
    a **shifted divisor**. A type currently holding *c* cells competes for the next one with
    priority `p / √((c+1)(c+2))`, starting at `p / √2`; the highest priority wins each cell in
    turn.

    The shift is the important part. In textbook Huntington–Hill the first seat is free — its
    divisor is `√(0·1) = 0`, giving infinite priority — which would put one cell of *every*
    reference type in *every* spot, exactly the thin-film problem. Here the first cell must be
    won like any other, so a type appears only once its probability is a large enough fraction
    of the leading type's.

    The rule is scale-invariant: multiplying every probability in a spot by a constant leaves
    the allocation unchanged. That is why BIWT can filter the mixture down to the types you
    kept without renormalizing it.

### Domain editor

Same as the [Visium recipe](visium-spatial.md#the-domain-editor-the-step-that-matters) —
check the µm-per-pixel factor before anything else, then pick whether the domain fits the
tissue or the tissue sits inside your domain.

### Positions

The preview should show tissue structure with visibly mixed populations, denser than a
one-cell-per-spot placement would be.

## Traps

!!! warning "Cell counts multiply, and you cannot rein them in later"
    Expansion turns each spot into several cells. A few thousand spots readily becomes tens
    of thousands of agents.

    Because you are using spatial data, the [cell counts](../guide/cell-counts.md) screen is
    skipped — the counts follow from the expansion, and there is no in-wizard control to
    reduce them. If the result is more agents than your simulation can carry, subset the
    spots *before* importing:

    ```python
    import numpy as np
    rng = np.random.default_rng(0)
    keep = rng.choice(adata.n_obs, size=1000, replace=False)
    adata[keep].write_h5ad("visium_subset.h5ad")
    ```

    Sampling spots preserves both the spatial distribution and the mixtures; sampling cells
    afterwards would not.

!!! note "Probabilities are estimates"
    Deconvolution output is a model fit, not a measurement. The expanded population inherits
    every bias of the reference used to deconvolve it. If the reference lacked a cell type
    present in the tissue, no amount of expansion will conjure it.

## What you get

Multiple cells per spot, at tissue positions, in the deconvolved proportions, with `z = 0`.
