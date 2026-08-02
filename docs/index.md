# BIWT

**BioInformatics WalkThrough** — a guided wizard that turns single-cell data into initial
conditions for agent-based models.

You bring an `.h5ad`, a Seurat `.rds`, or a plain `.csv`. BIWT walks you through choosing
which metadata column holds your cell-type labels, merging and renaming those types,
deciding how many cells to place and where, and attaching phenotype parameters. It hands
back a table of positioned cells ready to drop into a simulation.

BIWT is a standalone, pip-installable package. It is host-agnostic: it ships a Qt widget and
a small data contract, and any application can embed it.
[PhysiCell Studio](https://github.com/PhysiCell-Tools/PhysiCell-Studio) is the current host.

---

## Start here

<div class="grid cards" markdown>

-   **New to BIWT**

    Install it, then run the wizard end to end on a small file.

    [Getting started →](getting-started/index.md)

-   **Working through the wizard**

    What each step asks, why, and what happens if you skip it.

    [User guide →](guide/index.md)

-   **You have a specific dataset**

    Worked examples for Visium, plain scRNA-seq, and deconvolved spots.

    [Recipes →](recipes/index.md)

-   **Embedding BIWT in your own app**

    The `BiwtInput` / `BiwtResult` contract and how to wire up the widget.

    [Embedding BIWT →](integration/index.md)

</div>

---

## What BIWT produces

The wizard ends by handing the host a [`BiwtResult`][biwt.types.BiwtResult]. Its
`coordinates` field is a DataFrame with one row per placed cell:

| x | y | z | type |
|---|---|---|------|
| -213.4 | 88.1 | 0.0 | tumor |
| -198.7 | 91.6 | 0.0 | tumor |
| 42.0 | -310.5 | 0.0 | macrophage |

Those column names are the PhysiCell convention — note `type`, not `cell_type`. Optionally
the result also carries a serialized PhysiCell cell-definitions XML block, assembled from
whichever phenotype templates you picked.

**BIWT never writes to disk.** It returns the result in memory and the host decides where it
goes. That is deliberate: it keeps the package usable from a notebook or a script, not only
from inside an application that owns a file dialog.

---

## Scope and limits

BIWT is a *setup* tool. It does not run simulations, and it does not do bioinformatics
analysis — it consumes the output of an analysis you have already done. In particular it
expects your cell-type calls to exist already, as a column in `obs` (or a set of per-spot
probability columns, for deconvolved spatial data).

Current limits worth knowing before you start:

- **3D placement is partial.** Give the domain a z extent greater than 20 µm and the
  [plotters](guide/positions.md) place cells in depth — including the Spatial plotter, which
  uses your data's z column. But spot-deconvolution placement, and the extra cells from
  *Num cells per spot*, are always put at `z = 0`.
- **Single Visium library.** Multi-library arrays use the first library's scale factors.
- **Gene expression is not carried through.** Only positions and type labels reach the
  result; `substrate_data` and `gene_expression` are reserved but unpopulated.

---

## Reading these docs

Coloured boxes mean specific things:

!!! note "Note"
    Context or behavior worth knowing. Nothing goes wrong if you skip it.

!!! tip "Tip"
    Optional advice that will make your result better.

!!! warning "Warning"
    You can get a wrong or surprising result here.

!!! danger "Danger"
    This silently corrupts your output. Read it.

Collapsed **Why…** boxes hold background you can safely skip on a first pass.

---

## Project links

- [Source on GitHub](https://github.com/drbergman-lab/biwt)
- [Issue tracker](https://github.com/drbergman-lab/biwt/issues)
- [PyPI](https://pypi.org/project/biwt/)
