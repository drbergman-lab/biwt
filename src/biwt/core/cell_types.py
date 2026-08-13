"""
Cell-type configuration logic — purely data, no Qt.

The walkthrough gathers user decisions (keep / merge / delete / rename) and
stores them as ``CellTypeAction`` objects inside a ``CellTypeConfig``.
``CellTypeConfig.resolve()`` collapses those decisions into a flat
original_label → final_name mapping that ``positioning.py`` can consume.

Whether two strings name the same cell type is the host's decision, so it can
supply a predicate via ``BiwtInput.name_matches``.  ``default_name_matches`` is
the fallback BIWT ships, and ``best_match`` is the one selection routine that
both ``suggest_name_mappings`` (rename hints) and the cell-parameters step use.
Future: replace / augment with a cell-type registry / ontology lookup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Optional


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

def alpha_key(name: str):
    """Sort key for names shown to a user: ``AaBbCc``, not ``ABCabc``.

    Plain ``sorted`` orders by code point, which files every capitalized name
    ahead of every lowercase one — so ``iCAF`` and ``myCAF`` land after ``Stellate``
    instead of next to their alphabetical neighbours.  The exact name is the
    tie-break, so two names differing only in case still have a stable order.
    """
    return (name.casefold(), name)


DEFAULT_NAME_MATCH_CUTOFF = 0.85

_DIGIT_RUN = re.compile(r"\d+")


def default_name_matches(a: str, b: str, cutoff: float = DEFAULT_NAME_MATCH_CUTOFF) -> bool:
    """Whether *a* and *b* plausibly name the same cell type.

    Two rules, in order:

    1. **Digits must agree.**  A number in a cell-type name tells types apart;
       it is not a spelling variation.  ``M1 Macrophage`` and ``M2 Macrophage``
       are different types, as are ``CD4``/``CD8 T Cell`` and ``Layer 2``/
       ``Layer 6`` — yet similarity alone rates them 0.92, 0.90 and 0.86, above
       any useful cutoff.  So the digit runs are compared first, and any
       difference is disqualifying.
    2. **Then similarity**, ``difflib.SequenceMatcher`` ratio on the casefolded
       strings, which must reach *cutoff*.  This is what lets ``Fibroblast``/
       ``Fibroblasts`` (0.95) and ``Tumor``/``tumour`` (0.91) through.

    Known limitation: pairs distinguished by a *non-numeric* qualifier are not
    caught — ``PD-1hi CD137lo CD8 T Cell`` and ``PD-1lo CD137lo CD8 T Cell``
    hold the same digits (1, 137, 8) and score 0.92, so they match.  Any host
    curating names of that shape should supply its own predicate.

    Hosts that want different behavior pass their own predicate as
    ``BiwtInput.name_matches``, which replaces this function *and* the cutoff.
    """
    a_folded, b_folded = a.casefold(), b.casefold()
    if _DIGIT_RUN.findall(a_folded) != _DIGIT_RUN.findall(b_folded):
        return False
    return SequenceMatcher(None, a_folded, b_folded).ratio() >= cutoff


def best_match(
    name: str,
    candidates,
    matches: Optional[Callable[[str, str], bool]] = None,
    exact_only: bool = False,
) -> Optional[str]:
    """Return the candidate that names the same cell type as *name*, or None.

    A case-insensitive exact match always wins.  Otherwise the first candidate
    accepted by *matches* in sorted order wins — a predicate offers no way to
    rank, and sorting keeps the result independent of how the candidates were
    collected (file order, dict order).

    *exact_only* stops after the exact pass.  A caller with candidates from
    several sources uses it to try every source at the exact tier before letting
    any source answer with a mere similarity: match quality outranks provenance.

    *matches* defaults to :func:`default_name_matches`.
    """
    matches = matches or default_name_matches
    ordered = sorted(candidates, key=alpha_key)

    folded = name.casefold()
    for candidate in ordered:
        if candidate.casefold() == folded:
            return candidate
    if exact_only:
        return None

    for candidate in ordered:
        if matches(name, candidate):
            return candidate
    return None


def suggest_name_mappings(
    data_labels: list[str],
    host_names: list[str],
    matches: Optional[Callable[[str, str], bool]] = None,
) -> dict[str, Optional[str]]:
    """Suggest a host cell-type name for each data label.

    Delegates to :func:`best_match`, so the notion of "same cell type" is the
    one the host chose — see ``BiwtInput.name_matches``.

    Returns a dict ``{data_label: host_name | None}``.
    ``None`` means no suggestion was found.

    These are only hints for pre-populating the GUI; the user can overwrite any
    of them.  A future version will query a cell-type ontology / registry.
    """
    return {
        label: best_match(label, host_names, matches=matches)
        for label in data_labels
    }
