"""
Shared data contracts between biwt.core, biwt.gui, and the host application (e.g. Studio).

Three types form the public API boundary:

    DomainSpec  — spatial domain description passed IN to BIWT from the host.
    BiwtInput   — everything the host provides at launch time.
    BiwtResult  — everything BIWT returns to the host on completion.

Keeping these in one file makes the Studio ↔ package interface easy to audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

@dataclass
class DomainSpec:
    """Spatial domain dimensions.

    The ``units`` field records the coordinate system (default ``"micron"``
    for PhysiCell).  When BIWT is embedded in another host the units may
    differ — comparison logic uses this to flag potential mismatches.

    The ``source`` field records how this spec was determined so the host can
    decide whether to adopt the inferred bounds:
        "preferred"         — passed in explicitly by the host (Studio config).
        "anndata_metadata"  — read from AnnData/Seurat spatial metadata.
        "data_range"        — computed from min/max of coordinate columns.
        "default"           — fallback hardcoded values.
    """
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float = -10.0
    zmax: float = 10.0
    source: str = "preferred"
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
        """±500 µm × ±10 µm — the PhysiCell xml_defaults values."""
        return cls(xmin=-500.0, xmax=500.0, ymin=-500.0, ymax=500.0,
                   zmin=-10.0, zmax=10.0, source="default")


# ---------------------------------------------------------------------------
# Host → BIWT
# ---------------------------------------------------------------------------

@dataclass
class BiwtInput:
    """Everything the host application supplies when launching BIWT.

    Parameters
    ----------
    preferred_domain:
        Domain spec from the host's current configuration.  BIWT will use
        this unless it discovers richer spatial metadata in the imported data.
    host_cell_type_names:
        Cell type names currently defined in the host (e.g. Studio cell-def
        tab).  Passed as hints for renaming suggestions; BIWT does not
        require them.
    """
    preferred_domain: DomainSpec
    host_cell_type_names: list = field(default_factory=list)
    domain_accepted: bool = False   # True → skip auto domain-check at positions step
    host_name: str = "Host"         # used in domain editor UI ("Use <host_name> Domain")


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
    output_csv_path:
        Path where BIWT wrote the cells.csv, or ``None`` if the host is
        responsible for writing.

    Future expansion (not yet populated — reserved field names):
        substrate_data     : Optional[pd.DataFrame]
        gene_expression    : Optional[pd.DataFrame]
        spatial_metadata   : dict
    """
    coordinates: pd.DataFrame       # columns: x, y, z, type
    cell_type_map: dict              # original_label → final_name | None
    domain_used: DomainSpec
    output_csv_path: Optional[str] = None
    cell_definitions_xml: Optional[str] = None   # serialized PhysiCell cell-defs XML

    def to_csv(self, path: str) -> None:
        """Write ``coordinates`` to a PhysiCell-compatible cells.csv."""
        self.coordinates[["x", "y", "z", "type"]].to_csv(path, index=False)
        self.output_csv_path = path
