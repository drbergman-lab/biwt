"""
Cell-type configuration logic — purely data, no Qt.

The walkthrough gathers user decisions (keep / merge / delete / rename) and
stores them as ``CellTypeAction`` objects inside a ``CellTypeConfig``.
``CellTypeConfig.resolve()`` collapses those decisions into a flat
original_label → final_name mapping that ``positioning.py`` can consume.

``suggest_name_mappings`` provides lightweight heuristic hints to the GUI
so it can pre-populate rename fields when Studio cell-type names are available.
Future: replace / augment with a cell-type registry / ontology lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CellTypeAction:
    """Decision for one cell-type label discovered in the imported data.

    Parameters
    ----------
    original_name:
        The raw label as it appears in the data (e.g. ``"CD8+LAG3= T cell"``).
    action:
        One of ``"keep"``, ``"merge"``, ``"delete"``.
    merge_target:
        Required when ``action == "merge"``.  The ``original_name`` of the
        cell type to merge into.  Transitively resolved by ``CellTypeConfig``.
    final_name:
        Override the displayed name.  ``None`` means keep ``original_name``.
    """
    original_name: str
    action: str = "keep"                    # "keep" | "merge" | "delete"
    merge_target: Optional[str] = None      # only when action == "merge"
    final_name: Optional[str] = None        # None → use original_name


@dataclass
class CellTypeConfig:
    """Complete cell-type decision set for one BIWT walkthrough session.

    Usage
    -----
    config = CellTypeConfig()
    config.add(CellTypeAction("T cell", action="keep", final_name="tcell"))
    config.add(CellTypeAction("CD8 T cell", action="merge", merge_target="T cell"))
    config.add(CellTypeAction("Unknown", action="delete"))

    mapping = config.resolve()
    # → {"T cell": "tcell", "CD8 T cell": "tcell", "Unknown": None}
    """
    actions: dict = field(default_factory=dict)   # original_name → CellTypeAction

    def add(self, action: CellTypeAction) -> None:
        self.actions[action.original_name] = action

    def resolve_name(self, original: str, _seen: Optional[set] = None) -> Optional[str]:
        """Return the final cell-type name for *original*, or ``None`` if deleted.

        Handles transitive merges (A→B→C) and detects cycles defensively.
        """
        if _seen is None:
            _seen = set()
        if original in _seen:
            # Cycle guard — fall back to original
            return original
        _seen.add(original)

        a = self.actions.get(original)
        if a is None:
            return original
        if a.action == "delete":
            return None
        if a.action == "merge":
            if a.merge_target is None:
                return original
            return self.resolve_name(a.merge_target, _seen)
        # action == "keep"
        return a.final_name if a.final_name else original

    def resolve(self) -> dict[str, Optional[str]]:
        """Build a flat ``{original_label: final_name | None}`` mapping."""
        return {name: self.resolve_name(name) for name in self.actions}

    @property
    def kept_names(self) -> list[str]:
        """Unique final names that are not deleted."""
        seen, result = set(), []
        for final in self.resolve().values():
            if final is not None and final not in seen:
                seen.add(final)
                result.append(final)
        return result


# ---------------------------------------------------------------------------
# Name-suggestion heuristics
# ---------------------------------------------------------------------------

def suggest_name_mappings(
    data_labels: list[str],
    host_names: list[str],
) -> dict[str, Optional[str]]:
    """Suggest a Studio cell-type name for each data label.

    Strategy (in priority order):
      1. Exact match (case-insensitive).
      2. Studio name is a substring of the data label (or vice-versa).

    Returns a dict ``{data_label: studio_name | None}``.
    ``None`` means no suggestion was found.

    This is deliberately simple — good enough for pre-populating the GUI.
    A future version will query a cell-type ontology / registry.
    """
    host_lower = {n.lower(): n for n in host_names}
    suggestions: dict[str, Optional[str]] = {}

    for label in data_labels:
        label_lower = label.lower()
        match: Optional[str] = None

        # 1. Exact
        if label_lower in host_lower:
            match = host_lower[label_lower]
        else:
            # 2. Substring
            for sl, sn in host_lower.items():
                if sl in label_lower or label_lower in sl:
                    match = sn
                    break

        suggestions[label] = match

    return suggestions
