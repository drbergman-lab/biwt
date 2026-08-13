# The API contract

Three dataclasses in `biwt.types` define everything that crosses the host boundary.

For generated signatures see the [API reference](../reference/types.md).

## `DomainSpec` — the simulation box

```python
DomainSpec(
    xmin=-500.0, xmax=500.0,
    ymin=-500.0, ymax=500.0,
    zmin=-10.0,  zmax=10.0,
    source="host",
    units="micron",
)
```

Passed **in** as `BiwtInput.preferred_domain` and returned **out** as
`BiwtResult.domain_used`.

### `units`

Defaults to `"micron"`, the PhysiCell convention. BIWT uses this for two things: labelling
the [domain editor](../guide/domain.md) fields (`micron/data unit`), and flagging
potential mismatches.

!!! warning "Non-micron hosts: a known gap"
    The Visium scale factor BIWT auto-detects is in **µm per pixel**. If your `units` is
    something else, that seeded value is not converted and will be wrong. Users can override
    it manually. Until this is fixed, consider setting `domain_accepted=True` and validating
    the domain yourself if you work in other units.

### `source`

Records how the spec was determined, so you can tell whether your domain survived:

`biwt.types.DomainSource` names the values, so you need not hand-type strings:

| `DomainSource` | Value | Meaning |
|---|---|---|
| `HOST` | `"host"` | The domain you passed in |
| `DATA` | `"data"` | The data's own extent, however it was found |
| `USER` | `"user"` | Bounds the user typed in the [domain editor](../guide/domain.md) |
| `DEFAULT` | `"default"` | No usable domain: none was passed, or the one passed was degenerate or non-finite and BIWT substituted its ±500 µm × ±10 µm box |

Check `result.domain_used.source` in your handler. If it is not `HOST`, the domain changed during
the walkthrough and your application's configured domain no longer matches the initial conditions
you just received.

The domain editor derives this from the bounds rather than asserting it: `HOST` if they match the
domain you passed, `DATA` if they are the data's own extent, `USER` only if they are neither. The
dialog pre-fills the data extent whenever the data's coordinates are in use, so accepting it
unchanged reports `DATA`.

### Convenience members

`width`, `height`, `depth` are derived properties. `is_2d` is true when the z extent is at
most one default PhysiCell voxel (20 µm). `DomainSpec.default()` builds the fallback.

## `BiwtInput` — host to BIWT

```python
BiwtInput(
    preferred_domain=domain,              # optional; defaults to ±500 × ±500 × ±10 µm
    host_cell_type_names=[],              # optional
    domain_accepted=False,                # optional
    host_name="Host",                     # optional
    cell_template_paths=[],               # optional
    name_matches=None,                    # optional
    name_match_cutoff=0.85,               # optional
)
```

Every field has a default, so `BiwtInput()` is valid.

### When BIWT reads it

BIWT resolves its input at each import and holds a copy for that run, so a host change mid-run is
not seen until the next one.

If your host outlives one run — an embedded tab rather than a popup — pass a zero-argument callable
returning a `BiwtInput` ([`BiwtInputSource`][biwt.types.BiwtInputSource]) instead of an instance,
and you need no refresh hook:

```python
def host_input():
    return BiwtInput(preferred_domain=my_app.current_domain(),
                     host_cell_type_names=my_app.cell_type_names(),
                     host_name="My App")

widget = create_biwt_widget(host_input, on_complete=save)
```

Keep it cheap and free of side effects; it runs inside the import path. If it raises, or returns
anything that is not a `BiwtInput`, BIWT logs it and **refuses the import** — nothing is loaded, and
the user is told your application could not supply its settings.
`domain_accepted` is the exception to all of this — read once at construction, since the checkbox it
seeds is authoritative from then on.

**`preferred_domain`** is the domain BIWT places into unless the user overrides it in the
[domain editor](../guide/domain.md). It defaults to `DomainSpec.default()` — the ±500 µm ×
±10 µm box from the PhysiCell XML defaults, the same fallback BIWT already used internally
when it could not infer a domain from the data. Pass your own if your application has a
meaningful one.

**`host_cell_type_names`** — the cell types your application already defines; optional, and never
binding on the user. Used for [rename suggestions](../guide/rename-cell-types.md) and as candidates
at the [cell-parameters step](../guide/cell-parameters.md), where assigning one comes back marked
`HOST_SOURCE` (see `cell_templates` below). A name defined both ways resolves to the host.

**`domain_accepted`** — set `True` to pre-tick **Skip domain validation** on the import screen,
suppressing the automatic domain-mismatch dialog. This sets the checkbox's default; the user
can untick it and get the dialog back.

**`host_name`** — appears in the domain editor as `Use <host_name> Domain`. Set it; the
default `"Host"` reads like a placeholder.

**`cell_template_paths`** — paths to TOML files, each mapping a template name to its content.
The content is opaque to BIWT: read as text, never parsed, handed back verbatim.

**BIWT ships no templates**, so these files are the parameter library — pass them if you want
the [cell parameters step](../guide/cell-parameters.md) to offer anything. The user can also
load further files there at runtime, which is why the result reports each template's source
path. A non-string value in the file (a stray `[section]` header, a number) is rejected with a
message naming the key. [Templates and name matching](templates-and-matching.md) covers the
file rules and a worked assembly example.

**`name_matches`** — a `Callable[[str, str], bool]` deciding whether two strings name the same
cell type. Used for rename suggestions and template pre-selection. Supplying it replaces
BIWT's default **and** `name_match_cutoff`.

BIWT calls it once per (cell type, candidate) pair every time it resolves matches — at the
cell-parameters step that is one call per cell type per template — and it re-resolves whenever a
template file is loaded or an auto-match button is pressed. Two requirements follow:

- **Deterministic.** The same pair must always get the same answer — the call count is not part
  of the contract, so anything varying between calls can make two identical rows disagree.
- **No side effects.** It runs inside widget construction and Qt signal handlers, so mutating
  the session, showing UI, or doing I/O from it fires at moments you did not choose.

**`name_match_cutoff`** — similarity threshold for BIWT's default matcher only; ignored when
`name_matches` is given. [Templates and name matching](templates-and-matching.md) spells that
default out, with the cases it rejects and the one gap it does not cover.

## `BiwtResult` — BIWT to host

```python
BiwtResult(
    coordinates=df,                  # DataFrame: x, y, z, type
    cell_type_map={...},             # original label -> final name | None
    domain_used=domain,              # DomainSpec actually applied
    cell_templates={},               # cell type -> (path, name, content)
)
```

**`coordinates`** — one row per placed cell, columns `["x", "y", "z", "type"]`. The header is
`type`, not `cell_type`, matching PhysiCell's CSV convention. 2D data has `z = 0.0`.

**`cell_type_map`** — every original label mapped to its final name, with `None` for deleted types.

**`domain_used`** — see `source` above.

**`cell_templates`** — the [templates](../guide/cell-parameters.md) the user assigned, mapping
each final cell-type name to `(path, name, content)`: the absolute path of the `.toml` file it
came from, its key in that file, and that key's value verbatim, surrounding whitespace
included.

One value of `path` is not a path: [`HOST_SOURCE`][biwt.types.HOST_SOURCE] (`"<host>"`) means the
user picked one of the names you passed in `host_cell_type_names`, i.e. *a cell type you already
define*. `content` is then `""`, so check the marker before using it — see
[`HOST_SOURCE`][biwt.types.HOST_SOURCE] for the check to write.

Assembling anything out of that is yours to do — BIWT generates no XML; see
[templates and name matching](templates-and-matching.md) for a worked example. Types the user left
unassigned are **absent**, so `{}` is normal (the step has a Skip button and a per-type
`(none)` option): check membership per type rather than assuming full coverage. Two types may
carry the same `name` from different files, so `path` and `name` together identify a template
while `name` alone does not.

### `to_csv(path)`

A convenience for hosts that just want the file written:

```python
result.to_csv("config/cells.csv")
```

Writes only the four PhysiCell columns, no index. The result carries no path field: BIWT
does not choose an output location.

### Reserved fields

`substrate_data`, `gene_expression`, and `spatial_metadata` are named in the docstring as
future expansion but are **not populated and not currently attributes**. Do not code against
them yet.

## A complete minimal host

```python
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow

from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSource, DomainSpec


def on_complete(result):
    print(f"{len(result.coordinates)} cells, "
          f"{result.coordinates['type'].nunique()} types")

    if result.domain_used.source != DomainSource.HOST:
        print(f"note: domain changed to {result.domain_used.source}")

    result.to_csv("cells.csv")
    for cell_type, (path, name, content) in result.cell_templates.items():
        print(f"{cell_type}: template {name!r} from {path}")


app = QApplication(sys.argv)
window = QMainWindow()
window.setCentralWidget(create_biwt_widget(
    BiwtInput(
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500),
        host_cell_type_names=["default", "tumor", "immune"],
        host_name="My App",
    ),
    on_complete=on_complete,
))
window.show()
sys.exit(app.exec_())
```

## Stability

`biwt.types` and `create_biwt_widget` are the public API and changes to them will be treated
as breaking. Everything under `biwt.core` and `biwt.gui.windows` is internal — useful to read,
but not a contract.
