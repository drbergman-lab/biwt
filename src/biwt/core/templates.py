"""
Cell-parameter template files.

A template file is a TOML mapping of ``template_name = "content"``.  The content
is **opaque to BIWT**: it is read as text, never parsed, validated or wrapped,
and reaches the host verbatim in ``BiwtResult.cell_templates``.  For a PhysiCell
host the content happens to be an XML ``<phenotype>`` block, but nothing here
knows or cares about that.

BIWT ships no templates of its own.  Files come from the host via
``BiwtInput.cell_template_paths``, or from the user at the cell-parameters step.
"""

from __future__ import annotations

from typing import Callable, Optional

from biwt.core.cell_types import best_match

# A candidate with this name is the baseline for a cell type whose name matches
# nothing.  Purely a convention: BIWT never creates one.  Which source's
# ``default`` wins is decided where sources are known, not here.
DEFAULT_TEMPLATE_NAME = "default"


def load_templates_from_file(path: str) -> dict[str, str]:
    """Load a TOML template file and return ``{name: content}``.

    Raises ``ValueError`` if any value is not a string — a stray table or number
    would otherwise travel all the way to the host and fail there, long after
    the file that caused it is out of sight.
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]  # 3.9/3.10 fallback
        except ImportError as exc:
            raise ImportError(
                "Python < 3.11 requires 'tomli' to load template files. "
                "Install it with: pip install tomli"
            ) from exc
    with open(path, "rb") as f:
        data = tomllib.load(f)

    bad = {k: type(v).__name__ for k, v in data.items() if not isinstance(v, str)}
    if bad:
        listed = ", ".join(f"{k} ({t})" for k, t in sorted(bad.items()))
        raise ValueError(
            "Every value in a template file must be a string; these are not: "
            f"{listed}. A '[section]' header makes the keys that follow it "
            "nested tables, which is the usual cause."
        )
    return data


def matched_candidates(
    cell_types: list[str],
    template_names: list[str],
    matches: Optional[Callable[[str, str], bool]] = None,
    host_names: Optional[list[str]] = None,
) -> dict[str, Optional[str]]:
    """Per cell type, the candidate that names it, or ``None``.

    *host_names* are the cell types the host already defines
    (``BiwtInput.host_cell_type_names``).  They are tried **before** templates at
    each match tier, so where the host and a library name a type equally well the
    host wins: an existing definition beats a template for building one.  Tiers
    still come first — an exact template match beats a merely similar host name.

    ``None`` means nothing named this cell type.  What to do then — fall back to a
    ``default``, leave the type unassigned — is the caller's, because it depends on
    which source supplies the baseline and only the caller knows sources.
    """
    hosts = list(host_names or [])
    names = list(template_names)

    def pick(cell_type: str) -> Optional[str]:
        for pool in (hosts, names):                     # host first, per tier
            hit = best_match(cell_type, pool, matches=matches, exact_only=True)
            if hit is not None:
                return hit
        for pool in (hosts, names):
            hit = best_match(cell_type, pool, matches=matches)
            if hit is not None:
                return hit
        return None

    return {ct: pick(ct) for ct in cell_types}
