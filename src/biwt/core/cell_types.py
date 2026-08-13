"""
Deciding whether two strings name the same cell type — purely data, no Qt.

The decision is the host's: it can supply a predicate via
``BiwtInput.name_matches``.  ``default_name_matches`` is the fallback BIWT ships,
and ``best_match`` is the one selection routine used by both rename hints
(``suggest_name_mappings``) and the cell-parameters step.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Name-suggestion heuristics
# ---------------------------------------------------------------------------

def alpha_key(name: str):
    """Sort key for names shown to a user: ``AaBbCc``, not ``ABCabc``.

    Exact name as tie-break, so case-only variants keep a stable order.
    """
    return (name.casefold(), name)


DEFAULT_NAME_MATCH_CUTOFF = 0.85

_DIGIT_RUN = re.compile(r"\d+")


def default_name_matches(a: str, b: str, cutoff: float = DEFAULT_NAME_MATCH_CUTOFF) -> bool:
    """Whether *a* and *b* plausibly name the same cell type.

    Digit runs must be equal, then ``SequenceMatcher`` ratio on the casefolded
    strings must reach *cutoff*.  Digits distinguish types rather than spell them
    (``M1``/``M2 Macrophage`` scores 0.92), so they gate similarity instead of
    feeding it.  A *non-numeric* qualifier is not caught (``PD-1hi …``/``PD-1lo
    …``); a host curating such names supplies its own predicate.

    Hosts replace this wholesale — and the cutoff with it — via
    ``BiwtInput.name_matches``.  Rationale and the rejection table:
    docs/integration/templates-and-matching.md.
    """
    a_folded, b_folded = a.casefold(), b.casefold()
    if _DIGIT_RUN.findall(a_folded) != _DIGIT_RUN.findall(b_folded):
        return False
    return SequenceMatcher(None, a_folded, b_folded).ratio() >= cutoff


def names_match(a: str, b: str,
                matches: Optional[Callable[[str, str], bool]] = None) -> bool:
    """Whether *a* and *b* name the same cell type: exact, else the predicate.

    The one definition, so anything that reports a match scores it the same way
    ``best_match`` selects one.
    """
    return a.casefold() == b.casefold() or (matches or default_name_matches)(a, b)


def best_match(
    name: str,
    candidates,
    matches: Optional[Callable[[str, str], bool]] = None,
    sort_key=alpha_key,
) -> Optional[str]:
    """Return the candidate that names the same cell type as *name*, or None.

    A case-insensitive exact match always wins — every candidate is tried at that
    tier before any is accepted on similarity alone.  Within a tier the first in
    *sort_key* order wins: a predicate offers no way to rank, and sorting keeps
    the result independent of how the candidates were collected.

    Pass *sort_key* to express a preference among candidates, e.g. one source
    before another.  *matches* defaults to :func:`default_name_matches`.
    """
    matches = matches or default_name_matches
    ordered = sorted(candidates, key=sort_key)

    folded = name.casefold()
    for candidate in ordered:
        if candidate.casefold() == folded:
            return candidate
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
