# 4. Spatial query

**Shown when:** BIWT found spatial coordinates in your data. If it found none, there is
nothing to ask and this screen is skipped — placement will be random.

## The question

"Use the spatial coordinates from the data?" Yes or no.

## Yes — place cells where the data says

Cells are placed at their recorded positions, uniformly scaled and centered to fit the
domain. Relative geometry is preserved exactly: a tumor core stays a core, an immune margin
stays a margin, and the ratio of any two distances is unchanged.

Consequences:

- **Cell counts follow from the data.** One cell per row, so the
  [cell counts](cell-counts.md) screen is skipped. You cannot ask for "500 tumor cells" here
  — you get however many the data has, minus anything you delete.
- **The [domain editor](domain.md) becomes relevant.** How your data's extent maps onto the
  simulation box is now a real decision, and BIWT will raise it at the
  [positions](positions.md) screen if the fit looks wrong.

## No — place cells randomly

Cells are distributed at random within the domain. Their type composition is preserved, but
their positions are not.

Consequences:

- **You choose the counts.** The [cell counts](cell-counts.md) screen appears, with four ways
  to specify how many cells of each type to place.
- **Coordinates in the file are ignored entirely.**

## Which to pick

Say **yes** when spatial arrangement is part of what you are modeling — tumor–immune
architecture, spatial gradients, anything where "where the cells are" is the point.

Say **no** when the arrangement is not meaningful, or you do not want it. Two common cases:

- Your coordinates are a **dimensionality-reduction embedding** (UMAP, t-SNE), not physical
  positions. These are not tissue geometry and should not be treated as such.
- You want a **synthetic population** with realistic composition but a controlled size —
  seeding a simulation with 2,000 cells in the observed proportions rather than the 40,000 in
  your dataset.

!!! warning "UMAP coordinates can look like spatial data"
    If your object stores an embedding in a place BIWT reads as coordinates, this screen will
    offer to use it. Placing cells at their UMAP positions produces a picture of your
    embedding, not of tissue. If the preview at the [positions](positions.md) step looks like
    a UMAP, come back and answer no.

## Next

[Edit cell types →](edit-cell-types.md).
