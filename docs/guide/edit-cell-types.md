# 5. Edit cell types

**Shown when:** always.

## The question

Every cell type found in your [cluster column](cluster-column.md) is listed alphabetically
with three options: **Keep**, **Merge**, or **Delete**.

When your data has spatial coordinates, a scatter plot sits alongside the list, colored by
cell type, so you can see what you are about to change. **Show Legend** opens the color key
in a popup.

## Keep

The default. The type survives into the output as its own population.

## Merge

Combine two or more types into one. You pick a merge target, and every merged type collapses
into it.

This is the screen where a clustering result becomes a model. Single-cell analyses routinely
produce more clusters than a simulation needs — eight T-cell subsets, four macrophage
states, three fibroblast populations. If your model does not distinguish them, merge them.

Typical merges:

- `CD8_effector`, `CD8_memory`, `CD8_exhausted` → one `CD8_T_cell` population
- `M1_macrophage`, `M2_macrophage` → `macrophage`, if polarization is a simulation output
  rather than an input
- Several numeric clusters that annotation showed to be the same cell type

!!! note "A merge with only one partner dissolves"
    If you set up a merge and then remove all but the target, BIWT quietly turns it back into
    a Keep. A merge of one thing is not a merge.

## Delete

Drop the type from the output entirely. Its cells do not appear in the result at all.

Use this for populations that are artifacts or are irrelevant to the model: doublets,
low-quality clusters, ambient-RNA clusters, or tissue types outside the scope of what you are
simulating.

!!! warning "You cannot delete everything"
    At least one cell type must survive. BIWT blocks the attempt rather than producing an
    empty result.

## Thinking about it the right way

Ask what your model actually distinguishes. A cell type in a PhysiCell simulation is a set of
phenotype parameters — motility, secretion, mechanics, death rates. Two clusters that will
receive identical parameters are the same cell type as far as the model is concerned, however
distinct their transcriptomes. Merge them.

Conversely, do not merge two populations you intend to give different behavior, even if they
are transcriptionally similar.

## Next

[Rename cell types →](rename-cell-types.md).
