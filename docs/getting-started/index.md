# Getting started

Three pages, in order:

1. **[Installation](installation.md)** — the pip extras, and the conda recipe for the R
   stack if you need Seurat `.rds` support.
2. **[Your first walkthrough](first-walkthrough.md)** — run the wizard end to end on a small
   CSV, so you have seen every step before you point it at real data.
3. **[Troubleshooting](troubleshooting.md)** — when `.rds` import fails, which it usually
   does for one of six reasons.

## The short version

```bash
pip install "biwt[anndata,gui]"
```

That covers `.csv` and `.h5ad` with the Qt UI, which is what most people need. Seurat `.rds`
support needs a working R alongside the pip extra — see
[installation](installation.md#seurat-rds-import-optional).

If you are using BIWT through a host application such as PhysiCell Studio, the host may
already install it for you. Check the host's documentation first.

## Which format should I bring?

BIWT reads whatever your analysis already produced; there is no advantage to converting.

| You have | Extension | Extra needed |
|---|---|---|
| Scanpy / AnnData object | `.h5ad` | `biwt[anndata]` |
| Seurat object | `.rds` | `biwt[seurat]` + R |
| SingleCellExperiment / SpatialExperiment | `.rds` | `biwt[seurat]` + R |
| R workspace containing one of the above | `.rda`, `.rdata` | `biwt[seurat]` + R |
| A flat table of cells | `.csv` | none |

If you are only trying BIWT out, a CSV is by far the least friction — see
[your first walkthrough](first-walkthrough.md) for a file you can paste.
