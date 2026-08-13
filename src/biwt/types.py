"""
Shared data contracts between biwt.core, biwt.gui, and the host application.

Three types form the public API boundary:

    DomainSpec  — spatial domain description passed IN to BIWT from the host.
    BiwtInput   — everything the host provides at launch time.
    BiwtResult  — everything BIWT returns to the host on completion.

Keeping these in one file makes the host ↔ package interface easy to audit.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Union
import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

class DomainSource:
    """Where a :class:`DomainSpec`'s bounds came from.

    Three answers matter to a host — its own domain, the data's, or the user's —
    so those are the three values.  ``DEFAULT`` is the fourth because "nobody
    supplied one" is not the same as any of them: BIWT invents a box so the
    walkthrough can proceed, and it also marks a data domain as *not real*, which
    is how the positions step knows there is no mismatch worth asking about.
    """

    HOST = "host"          # the domain the host passed in
    DATA = "data"          # the data's own extent, however it was found
    USER = "user"          # bounds the user typed in the domain editor
    DEFAULT = "default"    # none supplied, or the one supplied was unusable

@dataclass
class DomainSpec:
    """Spatial domain dimensions.

    The ``units`` field records the coordinate system (default ``"micron"``,
    which is what PhysiCell uses).  When BIWT is embedded in another host the
    units may differ.  BIWT labels the domain editor with it and stamps it onto
    ``BiwtResult.domain_used``; it neither converts nor compares units.

    The ``source`` field records where these bounds came from, so the host can
    tell whether its own domain survived — see :class:`DomainSource`.
    """
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float = -10.0
    zmax: float = 10.0
    source: str = DomainSource.HOST
    units: str = "micron"

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def depth(self) -> float:
        return self.zmax - self.zmin

    @property
    def is_2d(self) -> bool:
        """True when the z extent is ≤ one default PhysiCell voxel (20 µm)."""
        return self.depth <= 20.0

    @classmethod
    def default(cls) -> "DomainSpec":
        """±500 µm × ±10 µm — a last-resort box for when the host names none."""
        return cls(xmin=-500.0, xmax=500.0, ymin=-500.0, ymax=500.0,
                   zmin=-10.0, zmax=10.0, source=DomainSource.DEFAULT)


def _usable_domain(domain: DomainSpec) -> DomainSpec:
    """*domain*, or a repaired one, so placement cannot divide by zero.

    The domain editor gates OK on the user's numbers; a host's arrive unchecked,
    and a degenerate box fails several steps later inside the counts or plot code
    rather than at the boundary.

    Inverted x or y is swapped — the intent is unambiguous, and left alone it
    stacks every cell on one line.  A non-finite or flat extent has no intent to
    recover, so BIWT's own box stands in, reported as ``DEFAULT``.  Flat *z* is
    left alone: a 2-D host domain is legitimate, and only x and y divide.
    """
    bounds = (domain.xmin, domain.xmax, domain.ymin, domain.ymax,
              domain.zmin, domain.zmax)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds):
        log.warning("Host domain has non-finite bounds; using BIWT's default box.")
        return DomainSpec.default()

    fixed = replace(domain)
    for lo, hi in (("xmin", "xmax"), ("ymin", "ymax"), ("zmin", "zmax")):
        if getattr(fixed, lo) > getattr(fixed, hi):
            log.warning("Host domain has %s > %s; swapping them.", lo, hi)
            setattr(fixed, lo, getattr(domain, hi))
            setattr(fixed, hi, getattr(domain, lo))
    if fixed.width == 0 or fixed.height == 0:
        log.warning("Host domain has zero width or height; using BIWT's default box.")
        return DomainSpec.default()
    return fixed


# ---------------------------------------------------------------------------
# Host → BIWT
# ---------------------------------------------------------------------------

@dataclass
class BiwtInput:
    """Everything the host application supplies when launching BIWT.

    A long-lived host builds the widget once but the user may not run the
    walkthrough until much later, so BIWT resolves its input **at the start of
    every run** — the moment the user imports a file — and holds a
    :meth:`snapshot` of it until that run completes.  A host whose values can
    change in the meantime passes a callable rather than an instance; see
    :data:`BiwtInputSource`.

    Parameters
    ----------
    preferred_domain:
        Domain spec from the host's current configuration.  BIWT will use
        this unless it discovers richer spatial metadata in the imported data.
    host_cell_type_names:
        Cell type names currently defined in the host (e.g. a cell-definitions
        tab).  BIWT does not require them, and never constrains the user to them.
        Used twice: as rename suggestions, and as candidates at the
        cell-parameters step — assigning one means "the host already has this cell
        type", which comes back marked with :data:`HOST_SOURCE` rather than a file
        path.  They match on equal footing with templates from files.
    domain_accepted:
        Seeds the "Skip domain validation" checkbox.  The checkbox,
        not this field, decides the outcome — the user stays in control.  Read
        only when the widget is built, since the checkbox is on screen from then
        on: a different value from a later resolution is deliberately ignored.
    host_name:
        Your application's name, shown in BIWT's UI — the domain editor's
        "Use <host_name> Domain" button, and the tag on your own cell types at the
        cell-parameters step.  Blank is replaced with ``"Host"``.
    cell_template_paths:
        Paths to ``.toml`` files of cell-parameter templates, each mapping a
        template name to an opaque content string (for a PhysiCell host, an XML
        ``<phenotype>`` block).  Loaded at the cell-parameters step, where the
        user assigns at most one template per cell type and can load further
        files.  BIWT ships no templates and never parses the contents: with no
        paths here and nothing loaded at the step, every type stays unassigned.
    name_matches:
        Predicate deciding whether two strings name the same cell type, used
        for rename suggestions and template pre-selection.  Supplying it
        replaces BIWT's default **and** ``name_match_cutoff``.  ``None`` means
        use ``biwt.core.cell_types.default_name_matches``.

        Must be deterministic and free of side effects: it is called once per
        (cell type, candidate) pair whenever matches are resolved, from inside
        widget construction and Qt signal handlers, and the total number of
        calls is not part of the contract.
    name_match_cutoff:
        Similarity threshold for that default only; ignored when
        ``name_matches`` is supplied.
    """
    preferred_domain: DomainSpec = field(default_factory=lambda: DomainSpec.default())
    host_cell_type_names: list = field(default_factory=list)
    domain_accepted: bool = False
    host_name: str = "Host"
    cell_template_paths: list = field(default_factory=list)
    name_matches: Optional[Callable[[str, str], bool]] = None
    name_match_cutoff: float = 0.85

    def __post_init__(self):
        """Normalize the host's input, or refuse it.

        Runs again on every ``dataclasses.replace``, so :meth:`snapshot` inherits
        it and a field the host mutated after construction is normalized too.

        Repairs rather than refuses, because every case has an unambiguous reading:
        a bare string is one entry rather than a list of its characters, and a
        walkthrough on a substituted domain beats no walkthrough.  Anything it
        cannot repair raises, and ``_resolve_host_input`` catches that — this is
        reached from a Qt slot, which must not let an exception escape.
        """
        for field_name in ("host_cell_type_names", "cell_template_paths"):
            value = getattr(self, field_name)
            setattr(self, field_name,
                    [value] if isinstance(value, (str, bytes)) else list(value))

        # Dropped, not coerced: str(None) would become a cell type named "None".
        self.host_cell_type_names = [
            n for n in self.host_cell_type_names if isinstance(n, str) and n.strip()
        ]
        # host_name reaches the screen — the domain editor's "Use <host_name>
        # Domain", and the tag on the host's own cell types — so it cannot be blank.
        self.host_name = self.host_name.strip() or "Host"
        self.preferred_domain = _usable_domain(self.preferred_domain)

    def snapshot(self) -> "BiwtInput":
        """A copy BIWT can hold for a whole run without it moving underneath.

        ``replace`` re-runs ``__post_init__``, which copies both lists; the domain
        is copied here because it is a mutable dataclass of its own.  A host that
        edits its own objects would otherwise rewrite ``BiwtResult.domain_used``
        after the cells were placed against the old numbers.

        ``name_matches`` passes through unchanged: behavior cannot be copied, which
        is why its contract asks for determinism.
        """
        return replace(self, preferred_domain=replace(self.preferred_domain))


HOST_SOURCE = "<host>"
"""Reserved stand-in for a source path, meaning **the host already defines this
cell type**.

It appears as the first element of a ``BiwtResult.cell_templates`` value when the
user assigned a cell type one of the names the host passed in
``BiwtInput.host_cell_type_names`` rather than a template from a file.  There is no
template content in that case — the host holds the definition already — so the
third element is the empty string.

Deliberately not a usable path: no filesystem accepts ``<`` or ``>``, so a host that
forgets to check it fails at once rather than reading a file that happens to exist.
Compare against this constant, not against the literal::

    from biwt.types import HOST_SOURCE

    for cell_type, (path, name, content) in result.cell_templates.items():
        if path == HOST_SOURCE:
            reuse_existing_definition(cell_type, name)   # `name` is your own
        else:
            build_definition_from(cell_type, content)

What "reuse" means is the host's call.  BIWT only reports the match.
"""


BiwtInputSource = Union[BiwtInput, Callable[[], BiwtInput]]
"""What a host hands to :func:`biwt.gui.create_biwt_widget`: a :class:`BiwtInput`,
or a zero-argument callable returning one.

Pass the callable when the host's domain or cell definitions can change after the
widget is built — an embedded tab rather than a one-shot popup.  BIWT calls it at
the start of each run, so the host never has to find a lifecycle hook to push
updates through, and never has to defend a getter against being read mid-edit.
"""


# ---------------------------------------------------------------------------
# BIWT → Host
# ---------------------------------------------------------------------------

@dataclass
class BiwtResult:
    """Everything BIWT returns to the host on workflow completion.

    Parameters
    ----------
    coordinates:
        DataFrame with columns ``["x", "y", "z", "type"]``.
        One row per placed cell.
    cell_type_map:
        Maps each original data label to the final name used in
        ``coordinates``.  Values are ``None`` for deleted types.
    domain_used:
        The DomainSpec that was actually applied when placing cells.
        ``domain_used.source`` tells the host whether this differs from
        what it passed in.
    cell_templates:
        Maps a final cell-type name to the parameter template chosen for it:
        ``(path, name, content)`` — the absolute path of the ``.toml`` file it
        came from, its key in that file, and that key's value **verbatim**,
        surrounding whitespace included.

        ``content`` is opaque.  BIWT reads it as text and never parses,
        validates or wraps it, so a PhysiCell host receives exactly the
        ``<phenotype>`` block its own template file holds and owns every
        decision about assembling a config from it.

        Cell types the user left unassigned are **absent**, so ``{}`` is the
        normal result when the step was skipped: check membership per type
        rather than assuming full coverage.  Two types may carry the same
        ``name`` from different files — ``path`` and ``name`` together identify
        a template, ``name`` alone does not.

    Notes
    -----
    Reserved for future expansion — these are **not** currently attributes and
    hosts must not code against them: ``substrate_data`` (DataFrame),
    ``gene_expression`` (DataFrame), ``spatial_metadata`` (dict).
    """
    coordinates: pd.DataFrame       # columns: x, y, z, type
    cell_type_map: dict              # original_label → final_name | None
    domain_used: DomainSpec
    # final cell-type name → (toml path, template name, template content)
    cell_templates: dict = field(default_factory=dict)

    def to_csv(self, path: str) -> None:
        """Write ``coordinates`` to *path* as a four-column ``x,y,z,type`` CSV.

        A convenience for the host, which owns the output location: the path is
        not recorded on the result.  BIWT does not choose where anything goes.
        """
        self.coordinates[["x", "y", "z", "type"]].to_csv(path, index=False)
