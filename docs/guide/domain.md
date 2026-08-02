# The domain editor

Not a step — a dialog. It opens automatically the first time the
[positions](positions.md) screen appears if BIWT detects a mismatch, and you can open it any
time from that screen with **Domain Settings…**.

This is the most conceptually dense part of BIWT, because it is where two coordinate systems
meet.

<figure markdown>
  ![The domain editor, opened on an "outside" mismatch](../assets/screenshots/domain.png)
  <figcaption>Opened automatically because the data extends past the host domain. The scale
  factor here was read from the file's Visium metadata; the two bounds columns stay in sync
  through it.</figcaption>
</figure>

## Data units vs host units

Your file has coordinates in whatever the instrument or analysis produced — often Visium
pixels, sometimes microns, sometimes an arbitrary embedding. BIWT calls these **data units**
and deliberately refuses to guess what they mean.

Your simulation has a domain in **host units** — microns, for PhysiCell.

These are not the same thing, and conflating them is the single most common way to get a
nonsensical initial condition. A Visium array spanning 8,000 pixels is not 8,000 µm across.

## The scale factor

The bridge between the two is one number: **host units per data unit**. The field is labeled
as a ratio using the host's own unit — `micron/data unit` for PhysiCell.

- For **10x Visium** data, BIWT reads µm-per-pixel out of the file and pre-fills it. A reset
  button (enabled only when you have changed the value) restores the file's number.
- For **everything else** — CSV, Seurat objects, non-Visium — there is no factor in the file.
  The field shows a `none found in file` placeholder and you supply one if you need it.

## The two bounds columns

The dialog shows your domain bounds twice, side by side: once in data units, once in host
units. They stay in sync through the factor — edit either column and the other updates
(×F or ÷F).

With no factor set, the data-units column is disabled and you work purely in host units. The
host-units column is always the one that gets stored.

Two buttons fill the columns for you:

- **Use Data Domain** — data-units gets your raw data bounds; host-units gets raw × factor
  (or raw, with no factor).
- **Use \<host\> Domain** — host-units gets the host's bounds verbatim.

The z bounds are host-units only and are never scaled.

## Apply scale factor to data

A checkbox, on by default.

- **On** — cells are scaled by the factor when placed. Data extent × F becomes the size the
  cells occupy.
- **Off** — cells are placed at their raw numeric extent, centered in the domain. The factor
  field stays live and the columns still sync; only placement ignores it.

Turning it off is useful when your coordinates are already in host units and the factor is
there for reference, or when you want to see the raw extent before deciding.

## Why the dialog opened by itself

BIWT compares the data extent to the domain, in host units, and classifies the fit:

| Classification | Meaning |
|---|---|
| **outside** | A data boundary exceeds the domain — cells would fall outside and be excluded |
| **small** | Data fits, but covers less than 50% of an axis or less than 50% of the 2D area — cells would be a small island in a large box |
| *(none)* | Close enough; no dialog |

The 50% threshold was picked against real data: a typical spatial dataset spanning
[-278, 285] × [-497, 499] inside a ±500 domain covers about 56% of each axis, and correctly
does *not* trigger the dialog.

No dialog appears when the domain came from the fallback default, since there is nothing
meaningful to compare against.

## Suppressing it

Three ways, in increasing scope:

1. Dismiss it — OK or Cancel both mark the domain accepted, so it will not re-trigger when
   you navigate back and forward.
2. Tick **Skip domain validation** on the import screen before importing.
3. A host can set `BiwtInput.domain_accepted = True` to suppress it for every session.

## What gets saved

On **OK**: the host-units bounds become the domain used for placement, and the factor and
checkbox state are remembered. On **Cancel**: the host's preferred domain is used unchanged.

Either way the positions preview redraws, and the change is undoable from the
[positions](positions.md) screen.

!!! warning "Known limitation: non-micron host units"
    The auto-detected Visium factor is in µm per pixel. If the host works in different units
    — nanometers, say — the seeded value is not converted and will be wrong by that
    conversion factor. Override it manually until this is fixed.
