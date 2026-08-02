# Recipe: Non-spatial scRNA-seq

**You have:** a dissociated single-cell dataset — Scanpy `.h5ad` or Seurat `.rds` — with
annotated cell types and no tissue coordinates. **You want:** a simulation seeded with a
realistic cell-type composition.

## What this recipe gets you

Composition, not architecture. Dissociation destroyed the spatial information, so BIWT places
cells at random within the domain. What survives is the *mixture*: if your tumor is 62%
malignant, 20% T cell, 18% myeloid, your simulation starts that way.

That is the right starting point for a great many models. Spatial structure that emerges
during the simulation is a result; spatial structure you impose at t=0 is an assumption.

## Before you start

Find your annotation column and see the composition you are about to reproduce:

```python
import anndata
adata = anndata.read_h5ad("pbmc.h5ad")
adata.obs["cell_type"].value_counts()
```

That distribution is what BIWT will preserve. If it contains clusters you do not want in the
model — doublets, low-quality cells, ambient-RNA clusters — note them now; you will delete
them two steps in.

## Walking through

### Import and cluster column

Pick the file, then pick your annotation column. Prefer a named column over
`seurat_clusters` / `leiden` if you have one.

### Spatial query

**If this screen does not appear**, BIWT found no coordinates — expected, and you are done
with this question.

**If it does appear**, your object has something BIWT read as coordinates. Before saying yes,
check what it is: many objects carry a UMAP or t-SNE embedding in a place BIWT will find.
Placing cells at their UMAP coordinates draws your embedding in the simulation domain, which
is not tissue and almost certainly not what you want. Say **no**.

### Edit cell types

This is the substantive step for scRNA-seq data, which typically has more clusters than a
model needs.

**Delete** the artifacts: doublets, `low_quality`, high-mito clusters, ambient clusters.

**Merge** aggressively toward what your model distinguishes. If every T-cell subset will get
the same phenotype parameters, they are one cell type. Twelve clusters commonly collapse to
four or five populations.

### Rename

Give them names your config can use. `CD8_T_cell`, not `4`.

### Cell counts — the step that matters

Four modes; for this recipe two are worth considering.

**Scale by proportion** is the usual answer. A 40,000-cell dataset is far more agents than
most PhysiCell runs want. Set a total of a few thousand and BIWT divides it in the observed
ratios. You keep the biology and lose the compute cost.

**Set confluence (%)** is the answer when density is what you are reasoning about. "Seed at
40% confluent" is a claim about the tissue; "seed 3,200 cells" is a claim about a particular
domain size. If you might change the domain later, confluence travels better.

*Use data counts* is right only when the dataset size is already the population you want.
*Set manually* gives you each count directly.

!!! warning "Rare populations disappear at small totals"
    Proportional scaling of a population that is 0.3% of your data down to a 2,000-cell total
    gives you six cells. If a rare type matters to the model, use **Set manually** and
    over-represent it deliberately, rather than letting rounding decide.

### Positions

Random placement inside the domain, with no domain-mismatch dialog — there is no data extent
to compare. Place everything at once and the preview looks like coloured noise.

That is only the default, though. Non-spatial data does not mean the initial condition has to
be unstructured: this screen is where you can build the geometry your model expects. Place
each type in its own pass with a different [plotter](../guide/positions.md) — a disc of tumour,
an annulus of immune cells around it, a rectangle of stroma along one edge — rather than
accepting one uniform scatter.

### Cell parameters

Assign a phenotype template per type. Parameters are what turn a set of positions into a
runnable model.

## What you get

Your chosen number of cells, in the data's type proportions, at random positions with `z = 0`.
