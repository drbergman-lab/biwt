# User guide

The walkthrough is a sequence of small screens, each asking one question. This section covers
every screen: what it asks, what your answer changes downstream, and what happens at the
edges.

If you have not run the wizard at all yet, do
[your first walkthrough](../getting-started/first-walkthrough.md) first — it is much easier to
read this with the screens in mind.

## How steps are chosen

BIWT does not show a fixed sequence. Before each screen it walks an ordered list of
predicates and shows the first step whose condition is true. A step whose condition is false
is skipped entirely — you never see it.

| # | Step | Shown when |
|---|---|---|
| 1 | [Spot deconvolution](spot-deconvolution.md) | Data has probability columns **and** spatial coordinates, and you have not been asked yet |
| 2 | [Cluster column](cluster-column.md) | No column selected yet, and you are not doing spot deconvolution |
| 3 | [Spatial query](spatial-query.md) | Data has spatial coordinates and you have not answered yet |
| 4 | [Edit cell types](edit-cell-types.md) | The keep/merge/delete choices have not been made |
| 5 | [Rename cell types](rename-cell-types.md) | Final names have not been assigned |
| 6 | [Cell counts](cell-counts.md) | You are **not** using spatial data, and counts are unconfirmed |
| 7 | [Positions](positions.md) | Positions have not been set |
| 8 | [Cell parameters](cell-parameters.md) | Parameters have not been loaded |

When every condition is false, BIWT [assembles the result](result.md) and hands it to the
host.

Two consequences worth internalizing:

- **Your answers change which screens exist.** Saying "yes" at the spatial query removes the
  cell-counts screen, because spatial data already determines how many cells there are.
- **Going back can invalidate later choices.** If you navigate back and change an earlier
  answer, BIWT clears the downstream state that depended on it rather than leaving stale
  values in place. You will be asked those questions again.

## The two screens that aren't steps

[The domain editor](domain.md) is a dialog, not a step. It opens on its own the first time
the positions screen appears if BIWT detects a mismatch between your data's extent and the
host's domain, and it can be reopened at any time from the positions screen.

[Finishing up](result.md) describes what BIWT hands back — useful whether you are the person
running the wizard or the person receiving the output.

## A note on units

BIWT distinguishes **data units** (whatever is in your file — often Visium pixels) from
**host units** (what the simulation uses — microns, for PhysiCell). It never guesses a unit
name from your data. Where a conversion is needed, you supply or confirm a scale factor in
[the domain editor](domain.md). This matters most for imaging-derived coordinates, where the
raw numbers can be in the thousands while the domain is ±500.
