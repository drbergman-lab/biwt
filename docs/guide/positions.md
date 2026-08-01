# 8. Positions

**Shown when:** always. This is where cells actually get coordinates, and where you see the
result before committing to it.

## What you see

A preview plot of every placed cell, colored by type, inside the simulation domain. Alongside
it: a **Show Legend** button, a **Domain Settings…** button that opens
[the domain editor](domain.md), and undo controls.

## How placement works

### With spatial data

Cells are placed at their recorded coordinates, transformed by a **uniform scale and a
translation** — nothing else. Specifically:

1. Coordinates are multiplied by the effective scale factor (see
   [the domain editor](domain.md)).
2. The resulting bounding box is centered in the domain.

Because the scale is uniform, aspect ratio is always preserved. A circular tumor stays
circular. Distances between any two cells scale by the same amount.

!!! note "The cells may not fill the domain"
    If your data's aspect ratio differs from the domain's, the cells occupy a
    correctly-proportioned region inside it rather than stretching to the edges. That is
    deliberate — distorting tissue geometry to fill a box would corrupt exactly the spatial
    relationships you chose to preserve.

    Resizing the domain changes the container, not the cell scale. To change how large the
    cells are relative to the domain, change the scale factor.

### Without spatial data

Cells are distributed at random within the domain, in the counts you set at the
[cell counts](cell-counts.md) step. Each type is placed independently; there is no clustering
or exclusion.

## The domain editor may open on its own

The first time this screen appears, BIWT compares your data's extent to the domain and opens
[the domain editor](domain.md) if the fit looks wrong in one of two ways:

- **outside** — some cells fall beyond the domain boundary and would be excluded
- **small** — the cells fit but cover less than half of an axis or half the area, so they
  would sit as a small island in a large empty box

It opens once. Navigating back and forward does not re-trigger it, and you can suppress it
entirely with the **Skip domain validation** checkbox on the import screen.

## Out-of-bounds cells

If cells end up outside the domain, BIWT warns and offers to either clear the placement or
keep it. Keeping out-of-bounds cells is legitimate — some hosts cull them, some clamp them —
but you should decide rather than discover it later.

## Undo

Domain changes and placement edits are undoable. Changing the domain recomputes the default
placement while preserving any manual edit you made as an undo step, so experimenting with
domain sizes does not silently discard your work.

## Next

[Cell parameters →](cell-parameters.md).
