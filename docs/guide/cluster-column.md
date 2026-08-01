# 3. Cluster column

**Shown when:** you have not already chosen a column, and you are not doing
[spot deconvolution](spot-deconvolution.md).

## The question

A dropdown lists every column in your data's metadata table. You pick the one holding
cell-type labels.

This is the single most consequential choice in the wizard. Everything downstream — which
types exist, what you can merge, how many cells of each go into the domain — derives from
this column.

## Picking the right column

Real objects carry a lot of columns, and several of them look plausible. Typical candidates
in a Seurat or Scanpy object:

| Column | Usually holds | Good choice? |
|---|---|---|
| `seurat_clusters`, `leiden`, `louvain` | Numeric cluster IDs (`0`, `1`, `2`, …) | Only if you have not annotated them yet |
| `cell_type`, `celltype`, `annotation` | Human-readable labels (`Tumor`, `CD8 T cell`) | Usually what you want |
| `orig.ident`, `sample`, `batch` | Which sample the cell came from | No — this is experimental design, not cell identity |
| `predicted.id` | Labels transferred from a reference | Yes, if that is your annotation |

If you pick a numeric cluster column, you get cell types named `0`, `1`, `2`. That works, and
you can give them real names at the [rename step](rename-cell-types.md) — but if you already
have an annotated column, use it and save yourself the mapping.

!!! tip "Not sure which column is which?"
    Inspect the object before you start. In Python, `adata.obs.head()` and
    `adata.obs.nunique()` will tell you quickly which columns hold a small number of
    repeated string values — the signature of a cell-type annotation. In R,
    `head(seurat_obj@meta.data)`.

## What happens next

BIWT extracts the unique values from your chosen column as the initial cell-type list, and
records which cell has which label. Both feed the [edit cell types](edit-cell-types.md)
screen.

If the spot deconvolution question was asked, a **Go Back** button is available here so you
can change that answer.

## Next

[Spatial query →](spatial-query.md) if your data has coordinates; otherwise
[edit cell types →](edit-cell-types.md).
