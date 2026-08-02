# Recipes

Three end-to-end walkthroughs for the datasets people actually bring to BIWT. Each one names
the choices that matter and the traps specific to that data type.

<div class="grid cards" markdown>

-   **[Non-spatial scRNA-seq](nonspatial-scrnaseq.md)**

    A dissociated dataset with no positions. You keep the composition and choose the
    population size.

-   **[Visium spatial data](visium-spatial.md)**

    Spot-level spatial transcriptomics with real tissue geometry. The recipe where units
    matter most — pixel coordinates are not microns.

-   **[Spot deconvolution](spot-deconvolution.md)**

    Visium spots with per-type probabilities, expanded into individual cells.

</div>

## Which one is yours?

| Your data has | Recipe |
|---|---|
| No coordinates | [Non-spatial scRNA-seq](nonspatial-scrnaseq.md) |
| Coordinates and one cell-type label per row | [Visium spatial](visium-spatial.md) |
| Coordinates and `*_probability` columns | [Spot deconvolution](spot-deconvolution.md) |

If your coordinates are a UMAP or t-SNE embedding rather than tissue positions, treat the
data as non-spatial — see [which source the spatial query
found](../guide/spatial-query.md#the-question).
