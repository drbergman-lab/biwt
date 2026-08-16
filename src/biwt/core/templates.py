"""
Cell template files.

A template file is a TOML mapping of ``template_name = "content"``.  The content
is **opaque to BIWT**: it is read as text, never parsed, validated or wrapped,
and reaches the host verbatim in ``BiwtResult.cell_templates``.  For a PhysiCell
host the content happens to be an XML ``<phenotype>`` block, but nothing here
knows or cares about that.

BIWT ships no templates of its own.  Files come from the landing screen's library
— seeded by the host at widget construction, edited by the user — or from the
user at the cell-templates step.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from typing import Callable, Optional

from biwt.core.cell_types import alpha_key, best_match

log = logging.getLogger(__name__)

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


def normalize_template_paths(paths) -> list[str]:
    """*paths* as absolute path strings: deduped, ordered, and nothing else.

    Repairs rather than refuses, because each case has one reading: a bare string
    is one path rather than a list of its characters, and a ``pathlib.Path`` is a
    path.  Anything that is neither a string nor ``os.PathLike`` is dropped with a
    warning — these reach ``os.path.abspath`` from a Qt slot, where a ``TypeError``
    would take the host process with it.

    Absolute, so a relative path is resolved once, against the working directory
    of the moment it was named, rather than differently at every later read.
    """
    if isinstance(paths, (str, bytes)) or isinstance(paths, os.PathLike):
        paths = [paths]

    resolved = []
    for entry in paths:
        try:
            path = os.fspath(entry)
        except TypeError:
            log.warning("Ignoring a cell template path that is not a path: %r", entry)
            continue
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = path.strip()
        if path:
            resolved.append(os.path.abspath(path))
    return list(dict.fromkeys(resolved))


def minimal_unique_suffixes(filepaths: list[str]) -> dict[str, str]:
    """Return the shortest path suffix that uniquely identifies each filepath.

    Paths are shortened to the minimal trailing suffix (basename, then
    parent/basename, etc.) that avoids collisions within this group.

    Shared, so the landing screen's library list and the cell-templates step
    name the same file the same way.
    """
    if not filepaths:
        return {}

    parts = {fp: list(reversed(fp.replace("\\", "/").split("/"))) for fp in filepaths}
    max_depth = max(len(p) for p in parts.values())

    for depth in range(1, max_depth + 1):
        candidate = {fp: "/".join(reversed(ps[:depth])) for fp, ps in parts.items()}
        if max(Counter(candidate.values()).values()) == 1:
            return candidate

    return {fp: fp for fp in filepaths}      # fallback: full paths


def matched_candidates(
    cell_types: list[str],
    template_names: list[str],
    matches: Optional[Callable[[str, str], bool]] = None,
    host_names: Optional[list[str]] = None,
) -> dict[str, Optional[str]]:
    """Per cell type, the candidate that names it, or ``None``.

    *host_names* are the cell types the host already defines
    (``BiwtInput.host_cell_type_names``).  They rank ahead of the templates, so
    the host wins where both name a type equally well — but only within a match
    tier, so an exact template match still beats a merely similar host name.

    ``None`` means nothing named this cell type.  What to do then — fall back to a
    ``default``, leave the type unassigned — is the caller's: it depends on which
    source supplies the baseline, and only the caller knows sources.
    """
    hosts = set(host_names or [])
    pool = list(hosts) + list(template_names)

    def rank(name: str):
        return (name not in hosts, alpha_key(name))

    return {ct: best_match(ct, pool, matches=matches, sort_key=rank)
            for ct in cell_types}
