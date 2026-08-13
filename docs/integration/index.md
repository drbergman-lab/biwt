# Embedding BIWT

BIWT is designed to be embedded. It ships a Qt widget and a two-type data contract, and
deliberately knows nothing about the application hosting it.

If you maintain an ABM tool and want a single-cell import path, this section is for you.

## The whole interface

```python
from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, BiwtResult, DomainSpec

widget = create_biwt_widget(
    BiwtInput(preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)),
    on_complete=my_handler,      # called with a BiwtResult
)
```

That is the entire surface. One factory function, one input type, one result type. Everything
else in `biwt` is internal and free to change.

`biwt.__version__` is also public — read it to show which BIWT your application is bundling, or to
record it alongside output you generate. The widget shows it on its own home screen too, which is
the only place a user can see it when BIWT is embedded as a tab.

## Three rules

### 1. The host owns all file I/O

BIWT never writes to disk. It hands you a `BiwtResult` in memory and your `on_complete` does
whatever your application does with output — write it, show a save dialog, keep it in memory,
push it to a server.

This is not an oversight to work around. It keeps BIWT usable from a notebook or a headless
script, and it means BIWT never has to know about your project layout, your file-overwrite
policy, or your undo system.

### 2. The widget does not close itself

When the workflow finishes, BIWT calls `on_complete` and stops. It does not hide, close, or
reset. If your application should dismiss the tab, do it in your handler.

Importing a new file resets the session, so the same widget instance can be reused for
another dataset.

## Optional inputs worth wiring up

`BiwtInput` has three fields beyond the domain that meaningfully improve the experience if
your application can supply them:

| Field | Effect |
|---|---|
| `host_cell_type_names` | Cell types your app already defines, so imported types can line up with them instead of duplicating them. At the [rename step](../guide/rename-cell-types.md) BIWT offers a match as placeholder text: a case-insensitive exact match first, else the first host name the matcher accepts. It is a hint, not a ranking. Two caveats: the placeholder only renders in an *empty* field, so it sits hidden behind the pre-filled original name; and pass nothing here and there are no suggestions at all. Also offered at the [cell-parameters step](../guide/cell-parameters.md), where assigning one comes back marked `HOST_SOURCE`. |
| `host_name` | Your application's name, used in the [domain editor](../guide/domain.md) UI ("Use Studio Domain"). Defaults to `"Host"`, which looks unfinished. |
| `cell_template_paths` | TOML files of parameter templates. BIWT ships none, so this *is* the library offered at the [cell parameters step](../guide/cell-parameters.md) — though the user can load more files there themselves. See [templates and name matching](templates-and-matching.md). |
| `name_matches` | Your own `(str, str) -> bool` for "do these name the same cell type?", replacing BIWT's default (and `name_match_cutoff`) for both rename suggestions and template pre-selection. See [templates and name matching](templates-and-matching.md). |

`domain_accepted=True` suppresses the automatic domain-mismatch dialog, if your application
already validates the domain itself.

If your host outlives one walkthrough, pass a **callable returning a `BiwtInput`** rather than an
instance: BIWT calls it at each import, so these fields do not freeze at build time. See
[when BIWT reads its input](api-contract.md#when-biwt-reads-it).

## Degrading gracefully when BIWT is absent

BIWT is an optional dependency for most hosts. The conventional pattern:

```python
try:
    from biwt.gui.walkthrough import create_biwt_widget
    from biwt.types import BiwtInput, DomainSpec
    HAVE_BIWT = True
except ImportError:
    HAVE_BIWT = False
```

...then branch on `HAVE_BIWT` when building the UI, and tell the user how to install it if
they reach for the feature.

## Read next

- **[The API contract](api-contract.md)** — `BiwtInput` and `BiwtResult` field by field,
  including what is reserved for future use.
- **[Templates and name matching](templates-and-matching.md)** — the two jobs BIWT hands back
  to you: supplying a parameter library and deciding when two names mean the same cell type.
- **[PhysiCell Studio](studio.md)** — a complete worked bridge, and the conventions it
  established.
- **[API reference](../reference/index.md)** — generated signatures and docstrings.
