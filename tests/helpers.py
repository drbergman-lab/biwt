"""Shared test setup that is not a fixture.

Fixtures live in ``conftest.py``; these are plain functions, because most callers
need them inside a module-level helper rather than as a test argument.

The step sequence below is the single copy of "what the windows do to the session
in order".  It was written out in four modules, so a session-field rename had to be
chased through all four — and a missed one built a window against a stale session
instead of failing.
"""
from __future__ import annotations

from pathlib import Path

from biwt.core import data_loader
from biwt.types import BiwtInput, DomainSpec

FIXTURES = Path(__file__).parent / "fixtures"
DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

TEMPLATES_A = str(FIXTURES / "templates_a.toml")
TEMPLATES_B = str(FIXTURES / "templates_b.toml")

# Set up on the widget, not read off BiwtInput: the user edits them, so a per-run
# re-read would undo that.  Split out here so a test can pass either kind.
WIDGET_KWARGS = ("cell_template_paths",)


def walkthrough_with_data(csv: str = "nonspatial.csv", **kwargs):
    """A real walkthrough whose session has *csv* loaded and nothing else done."""
    from biwt.gui.walkthrough import BioinformaticsWalkthrough

    widget_kwargs = {
        name: kwargs.pop(name) for name in WIDGET_KWARGS if name in kwargs
    }
    kwargs.setdefault("preferred_domain", DOMAIN)
    w = BioinformaticsWalkthrough(BiwtInput(**kwargs), **widget_kwargs)
    w.session.data = data_loader.load(str(FIXTURES / csv))
    # What an import does: the landing screen's library is the run's seed.
    w.session.template_library_paths = list(w._library_paths)
    return w


def pick_column(session, column: str = "type"):
    """What ClusterColumnWindow commits."""
    session.current_column = column
    session.collect_cell_type_data()
    return session


def keep_all(session, *, spatial: bool = False):
    """What EditCellTypesWindow commits when the user keeps every type."""
    session.spatial_query_answer = spatial
    session.cell_type_dict_on_edit = {
        ct: ct for ct in session.cell_types_list_original
    }
    session.compute_intermediate_types()
    return session


def rename_to(session, mapping=None):
    """What RenameCellTypesWindow commits; *mapping* renames some final types."""
    mapping = mapping or {}
    renamed = {ct: mapping.get(ct, ct) for ct in session.intermediate_types}
    session.cell_types_list_final = list(renamed.values())
    session.cell_type_dict_on_rename = renamed
    session.apply_rename()
    return session


def session_through_rename(session, *, column: str = "type", spatial: bool = False,
                           rename=None):
    """Drive *session* through column → keep-all → rename, as the windows do."""
    pick_column(session, column)
    keep_all(session, spatial=spatial)
    return rename_to(session, rename)


def window_at_rename(csv: str = "nonspatial.csv", *, rename=None, **kwargs):
    """A walkthrough driven to just past the rename step, ready for a later window.

    The non-spatial fixture's final cell types are Macrophage, T_cell and Tumor.
    """
    w = walkthrough_with_data(csv, **kwargs)
    session_through_rename(w.session, rename=rename)
    return w
