# Templates and name matching

Two host responsibilities that are easy to miss, because BIWT deliberately declines both:

- **Parameter templates.** BIWT ships none and generates no config. It presents whatever
  library you give it and reports what the user picked.
- **Deciding whether two names mean the same cell type.** BIWT has a default, but the decision
  is yours to take over.

Neither is required. A host that wires up neither still gets coordinates and a cell-type map.

## Supplying a template library

A template file is TOML mapping a template name to its content:

```toml
"Epithelial Tumor" = """
<phenotype>
  <cycle code="6" name="Flow cytometry model (separated)">
  ...
</phenotype>
"""

"Fibroblast" = """
<phenotype>
  ...
</phenotype>
"""
```

The content is **opaque to BIWT**: read as text, never parsed, validated or wrapped. The
example above is PhysiCell XML because that is what the reference host uses, but nothing in
BIWT requires XML.

Point BIWT at your files when you build the widget:

```python
create_biwt_widget(
    BiwtInput(preferred_domain=domain, host_name="My App"),
    on_complete=save,
    cell_template_paths=["/path/to/my_templates.toml"],
)
```

Rules worth knowing:

- **Every value must be a string.** A `[section]` header nests the keys that follow it into a
  table, which BIWT rejects with a message naming the key.
- **Duplicate keys raise**, per the TOML spec.
- **A malformed or unreadable file warns and is skipped.** The step still opens; the user is
  told which file failed.
- **The user controls which libraries are loaded**, adding files of their own and removing yours.
  Do not assume every returned template came from your files, which is why the result reports
  each template's source path (see below).
- **Two files defining the same `default` cancel it out.** The step's "assign the default
  template" action is withdrawn, and the auto-match fallback tier with it, rather than resolving
  the ambiguity by file order. Templates stay individually selectable.
- **Pass nothing and the step still works.** Every dropdown offers only `(none)` and the result
  carries no templates.

!!! note "Remote and streamed sessions"
    The step accepts dropped `.toml` files, but a drop only ever hands over a path **on the machine
    running BIWT**. If your host streams the GUI from elsewhere — a Galaxy interactive tool, a
    container behind noVNC — the user's own files never reach it and no drop arrives; the file
    dialog browses the *server's* filesystem, not theirs. Drag-and-drop is an accelerator, never
    the only route. But in that environment the library should come from you:
    stage the file server-side (in Galaxy, `galaxy_ie_helpers.get(dataset_id)` fetches it into the
    working directory) and pass the path in `cell_template_paths`.

## Consuming what comes back

`BiwtResult.cell_templates` maps each final cell-type name to a `(path, name, content)` triple:

```python
result.cell_templates == {
    "tumor":  ("/abs/path/my_templates.toml", "Epithelial Tumor", "<phenotype>…</phenotype>"),
    "CD8 T":  ("/abs/path/users_own.toml",    "CD8 T Cell",       "<phenotype>…</phenotype>"),
}
```

Content is opaque and complete: you get exactly what your template file holds, so never resolve
`name` against your own library to recover it — the user may have loaded a file you do not know
about. Two more rules bind a host here, on the field's own page:
[`BiwtResult.cell_templates`](api-contract.md#biwtresult-biwt-to-host).

Assembly is yours. For a PhysiCell-style host, that is one `<cell_definition>` per type
wrapping the content:

```python
import xml.etree.ElementTree as ET

from biwt.types import HOST_SOURCE

def on_complete(result):
    cell_defs = ET.Element("cell_definitions")
    for i, (cell_type, (path, name, content)) in enumerate(result.cell_templates.items()):
        if path == HOST_SOURCE:
            continue                     # you already define this type; no content to parse
        cd = ET.SubElement(cell_defs, "cell_definition", name=cell_type, ID=str(i))
        cd.append(ET.fromstring(content))
    # ...merge into your config, then write it wherever your app writes things
```

## Owning the name-match rule

BIWT asks "do these two strings name the same cell type?" in two places: pre-filling
[rename suggestions](../guide/rename-cell-types.md) from `host_cell_type_names`, and
pre-selecting a candidate per cell type at the cell-parameters step — where the candidates are your
template names *and* those same `host_cell_type_names`, pooled and matched on equal footing. One
rule serves all of it, and you can replace it:

```python
BiwtInput(
    name_matches=my_matcher,      # Callable[[str, str], bool]
    # name_match_cutoff is ignored entirely when name_matches is supplied
)
```

**The contract.** A callable taking two strings and returning `bool`. It must be
**deterministic** — the same pair always gets the same answer — and **free of side effects**: it
runs inside widget construction and Qt signal handlers, and BIWT does not promise how many times
it calls it. One call per (cell type, candidate) pair each time matches are resolved, and they
are re-resolved on every template-file load and auto-match. BIWT short-circuits a
case-insensitive exact match before consulting it, so you never have to handle that case.
Among the candidates your predicate accepts, BIWT takes the first in sorted order.

**The default**, if you supply nothing, is `default_name_matches` (see
[`biwt.core.cell_types`](../reference/core.md)): digit runs must be equal, then
`difflib.SequenceMatcher` ratio on the casefolded strings must reach `name_match_cutoff`
(0.85).

Numbers in a cell-type name distinguish types instead of spelling them differently, and
similarity alone cannot tell:

| Pair | Ratio | With the digit gate |
|---|---|---|
| `M1 Macrophage` / `M2 Macrophage` | 0.92 | rejected |
| `CD4 T Cell` / `CD8 T Cell` | 0.90 | rejected |
| `M0 Macrophage` / `M1 Macrophage` | 0.87 | rejected |
| `Layer 2` / `Layer 6` | 0.86 | rejected |
| `Fibroblast` / `Fibroblasts` | 0.95 | accepted |
| `Tumor` / `tumour` | 0.91 | accepted |

**Known gap:** pairs distinguished by a *non-numeric* qualifier are not caught.
`PD-1hi CD137lo CD8 T Cell` and `PD-1lo CD137lo CD8 T Cell` hold the same digits (1, 137, 8)
and score 0.92, so they match. If your library names types that way, supply a predicate that
compares those qualifiers too.

If you only want to tighten the threshold, leave `name_matches` alone and raise
`name_match_cutoff`. And if you want the default plus a rule of your own, import it rather than
reimplementing it:

```python
from biwt.core.cell_types import default_name_matches

def my_matcher(a: str, b: str) -> bool:
    return default_name_matches(a, b) and _qualifiers_agree(a, b)
```
