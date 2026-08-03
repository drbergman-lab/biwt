# Rename cell types

**Shown when:** always.

## The question

Each cell type that survived the [edit step](edit-cell-types.md) gets a text field,
pre-filled with its first original name. Change any of them, or accept them all.

<figure markdown>
  ![Rename cell types](../assets/screenshots/rename-cell-types.png)
  <figcaption>Original name on the left, the name that will reach your simulation on the
  right.</figcaption>
</figure>

The names you set here are what appear in the `type` column of the output and in the
generated PhysiCell cell-definitions XML. They are the names your simulation config will use.

## Why bother

Two reasons.

**Cluster IDs are not names.** If you selected a `seurat_clusters` column, your types are
currently `0`, `1`, `2`. A config full of `<cell_definition name="7">` is unreadable and
unmaintainable.

**Matching the host's existing definitions.** If your simulation config already defines a
`tumor` cell type, naming yours `tumor` lets them line up instead of creating a near-duplicate.

## Suggestions from the host

If the host application passed BIWT its current cell-type names — Studio does this from its
cell-definitions tab — BIWT looks for a match and offers it as **placeholder text** in each
field.

The matching is deliberately simple, not fuzzy: a case-insensitive exact match first, then
the first host name that either contains your label or is contained by it — so `CD8` matches
a host `CD8_T_cell`. There is no scoring or ranking, so if several host names could match by
containment you get whichever the host listed first, not the best one.

Placeholder text only shows in an *empty* field, and every field arrives pre-filled with your
original name — so in practice the suggestion sits hidden behind it. Clear a field and it
appears, greyed out, as `Suggestion: <host name>`.

It is a hint either way: nothing is filled in for you, so if you want the suggested name you
have to type it. Note that an empty field is accepted as an empty name — only duplicates are
blocked — so do not leave one cleared just to keep the hint in view.

## Naming rules

**Exact duplicates are blocked.** Two types cannot share a name; BIWT warns and keeps you on
the screen.

**Case matters.** `CD8` and `cd8` are treated as different names and both are allowed,
because PhysiCell treats them as distinct. This is easy to do by accident — if you meant them
to be the same type, merge them at the [previous step](edit-cell-types.md) instead.

!!! tip "Pick names your config can live with"
    Avoid spaces and punctuation if your downstream tooling is picky about XML attribute
    values. `CD8_T_cell` travels better than `CD8+ T cell (exhausted)`.

## Next

[Cell counts →](cell-counts.md) if you are not using spatial data; otherwise
[positions →](positions.md).
