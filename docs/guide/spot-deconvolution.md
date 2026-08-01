# 2. Spot deconvolution

**Shown when:** your data has per-cell-type probability columns **and** spatial coordinates.
Otherwise this screen never appears.

## The question

Spot-based spatial transcriptomics — Visium most commonly — does not measure single cells.
Each spot covers a small patch of tissue containing several cells, and a deconvolution
analysis estimates what mixture of cell types that patch contains. The result is one row per
*spot*, with a probability per cell type:

| x | y | Tumor_probability | T_cell_probability | Macrophage_probability |
|---|---|---|---|---|
| 120 | 340 | 0.7 | 0.2 | 0.1 |
| 145 | 338 | 0.1 | 0.1 | 0.8 |

BIWT asks whether to expand those spots into individual cells.

## Choosing yes

Each spot becomes several cells, allocated in proportion to its probabilities. The spot at
`(120, 340)` above contributes mostly tumor cells, with a few T cells and macrophages mixed
in. Your agent-based model gets a plausible cell population rather than a grid of
mixture-valued spots.

Choosing yes also means BIWT already knows what the cell types are — they come from the
probability column names — so the [cluster column](cluster-column.md) screen is skipped.

## Choosing no

BIWT treats the file as ordinary per-row data and moves on to the
[cluster column](cluster-column.md) screen, where you pick a single metadata column holding
one label per row. The probability columns are ignored.

This is the right answer when the probability columns are not really a deconvolution — for
example, classifier confidence scores where you want the argmax, not a mixture.

## Which to pick

Choose **yes** if the rows are spots and you want cells. Choose **no** if the rows are
already cells, or if you want exactly one cell per row at its recorded position.

The counts matter here. Deconvolution multiplies your row count — a few thousand spots can
become tens of thousands of cells. If that is more than your simulation wants, you can rein
it in later at the [cell counts](cell-counts.md) screen only if you are *not* using spatial
data; with spatial data the counts follow from the expansion.

## Next

[Spatial query →](spatial-query.md) if you said yes, or
[cluster column →](cluster-column.md) if you said no.
