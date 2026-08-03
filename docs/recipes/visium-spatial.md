# Recipe: Visium spatial data

**You have:** a 10x Visium dataset, spatially annotated, with one dominant cell-type call per
spot. **You want:** cells placed in tissue geometry inside your simulation domain.

If your spots carry per-type *probabilities* rather than a single label, use the
[spot deconvolution recipe](spot-deconvolution.md) instead.

## Before you start

Confirm three things about your object:

```python
import anndata
adata = anndata.read_h5ad("visium.h5ad")

adata.obsm.keys()          # expect 'spatial'
adata.obs.columns          # find your cell-type annotation column
adata.uns.get("spatial")   # scale factors live here for Visium
```

The third one matters more than it looks. Visium coordinates are in **full-resolution image
pixels**, and the µm-per-pixel conversion lives in `uns["spatial"]`. If that metadata
survived your pipeline, BIWT reads it and pre-fills the scale factor. If it did not, you will
supply the number yourself.

## Walking through

### Import

Pick the `.h5ad`. BIWT reads `obsm["spatial"]` and — if the Visium metadata is present —
extracts µm per pixel.

If your object stores coordinates as `imagerow` / `imagecol` columns in `obs` rather than an
`obsm` array, BIWT still finds them. It maps `imagecol` to x and flips `imagerow`
(`y = rowmax − imagerow`) because image rows increase downward.

### Cluster column

Choose your annotation column — the one with names like `Tumor`, `Stroma`, `Immune`, not the
numeric `cluster` column, unless numbers are all you have.

### Spatial query → **yes**

This is the whole point of Visium data. Say yes.

### Edit and rename

Merge the subclusters your model does not distinguish. Annotations are sometimes region-level
rather than cell-type-level — `Tumor_edge` and `Tumor_core`, say. Where that is the case,
decide whether your simulation treats them as one cell type in different environments, or as
two cell types. If the former, merge them.

### The domain editor — the step that matters

At the positions screen the [domain editor](../guide/domain.md) will almost certainly open on
its own, because raw Visium coordinates run into the thousands while a PhysiCell domain is
typically ±500 µm. This is the mismatch it exists to catch.

**Check the `micron/data unit` field first.**

- If it is pre-filled, BIWT read it from your file. A typical Visium value is around 0.5–2 µm
  per pixel depending on the image resolution. Sanity-check it: your tissue's real extent is
  the pixel span × this factor.
- If it shows `none found in file`, the metadata did not survive. Compute it yourself: a
  Visium spot is 55 µm in diameter with 100 µm center-to-center spacing, so if you can measure
  the pixel distance between adjacent spot centers, µm-per-pixel is 100 divided by that.

**Then decide the domain.** Two reasonable approaches:

- **Fit the domain to the tissue.** Click **Use Data Domain**, which fills host-units with
  raw × factor. Your domain becomes exactly the tissue extent in microns. Best when the
  tissue *is* the simulation.
- **Keep your domain and let the tissue sit inside it.** Click **`Use <host> Domain`**. The
  cells occupy a centered region proportional to their real size. Best when the domain has
  meaning of its own — a fixed well, a defined volume.

Leave **Apply scale factor to data** on. Turning it off places cells at their raw pixel
extent, which for Visium is thousands of units wide and almost never what you want.

### Positions

Look at the preview. It should look like your tissue section. If it looks like a small blob
in a big empty box, your scale factor is too small; if cells are being reported out of
bounds, it is too large.

## Traps

!!! danger "The most common mistake: no scale factor"
    Placing raw pixel coordinates into a micron domain silently produces a tissue far too
    large for the domain, so nearly every cell lands out of bounds. If BIWT warns about
    out-of-bounds cells right after you clicked through the domain editor, go back and check
    the factor.

!!! warning "Multi-library arrays"
    BIWT uses the **first** library's scale factors. If your object merges several Visium
    captures, the factor may be wrong for all but one of them. Split them and import
    separately.

!!! note "Spots are not cells"
    Each Visium spot covers roughly 1–10 cells. With one label per spot you are placing one
    agent per spot, so your cell count is really a spot count and your density is lower than
    the tissue's. For a more realistic population, use
    [spot deconvolution](spot-deconvolution.md).

## What you get

One cell per spot, at true relative tissue positions, scaled into your domain. `z = 0` for
all of them.
