# `biwt.core`

Pure-Python logic with no Qt dependency: loading files, inferring the domain, placing cells,
and reconciling cell-type edits.

!!! warning "Internal"
    These are not part of the public API. They are documented because reading them is the
    fastest way to understand what BIWT actually does, but signatures may change between
    releases. If you are embedding BIWT, work through [`biwt.types`](types.md) and
    `create_biwt_widget` instead.

## `biwt.core.data_loader`

Reads `.h5ad`, `.rds`/`.rda`/`.rdata`, and `.csv` into a single `BiwtData` shape, so nothing
downstream needs to know the source format.

::: biwt.core.data_loader
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - BiwtData
        - LoadError
        - load

## `biwt.core.domain`

Domain inference and the two-tier mismatch classification that decides whether
[the domain editor](../guide/domain.md) opens on its own.

::: biwt.core.domain
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - infer_domain
        - classify_domain_mismatch
        - resolve_obs_coord_cols
        - build_obs_coords

## `biwt.core.positioning`

Coordinate scaling and assembly of the final cells DataFrame.

::: biwt.core.positioning
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - compute_spatial_placement
        - build_ic_dataframe

## `biwt.core.cell_types`

Keep / merge / delete bookkeeping, and the name matching behind the rename suggestions and the
template pre-selection. A host owns the "same cell type?" decision via
[`BiwtInput.name_matches`][biwt.types.BiwtInput]; `default_name_matches` is what BIWT falls
back to.

::: biwt.core.cell_types
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - CellTypeConfig
        - CellTypeAction
        - default_name_matches
        - best_match
        - suggest_name_mappings

## `biwt.core.templates`

Reading cell-parameter template files, and choosing a starting template per cell type. BIWT
ships no templates of its own and never parses their content.

::: biwt.core.templates
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - load_templates_from_file
        - default_template_choices
