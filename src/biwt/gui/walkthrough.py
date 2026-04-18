"""
BioinformaticsWalkthrough — top-level popup widget (new package interface).

This is the main controller for the BIWT workflow.  It owns:
  - The step-window stack (windows are built lazily on demand).
  - A ``WalkthroughSession`` dataclass that accumulates all data decisions
    (no Qt objects stored there — purely plain data).
  - The ``BiwtResult`` that is handed back to the host via ``on_complete``.

Host usage (e.g. from Studio's ICs tab):
-----------------------------------------
    from biwt import BiwtInput, DomainSpec
    from biwt.gui import create_biwt_widget

    biwt_input = BiwtInput(
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500),
        host_cell_type_names=celldef_tab.get_cell_type_names(),
        output_csv_path="./config/cells.csv",   # or None
    )
    widget = create_biwt_widget(biwt_input, on_complete=my_callback)
    widget.show()

``my_callback`` receives a ``BiwtResult`` when the user finishes the workflow.

Migration status
----------------
The step windows listed in ``_WINDOW_SEQUENCE`` are progressively migrated
from ``bin/biwt_tab.py``.  Windows not yet migrated fall back to the legacy
implementation via ``_legacy_window_fallback``.  Each migrated window is
removed from the fallback list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Callable, Type
import logging

import numpy as np
import pandas as pd

from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox,
    QFileDialog, QMessageBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator

from biwt.types import DomainSpec, BiwtInput, BiwtResult
from biwt.core import data_loader
from biwt.core.data_loader import BiwtData, LoadError
from biwt.core import domain as domain_module
from biwt.core.cell_types import CellTypeConfig, CellTypeAction, suggest_name_mappings
from biwt.core.positioning import build_ic_dataframe
from biwt.gui.widgets import QHLine, QLineEdit_custom, SectionHeader

log = logging.getLogger(__name__)

_LE_STYLE = (
    "background-color: white; border: 1px solid #555;"
    " border-radius: 2px; padding: 1px 4px;"
)


# ---------------------------------------------------------------------------
# Domain editor dialog
# ---------------------------------------------------------------------------

class DomainEditorDialog(QDialog):
    """Pop-up for reviewing / editing domain bounds after data import.

    Shown when the data-inferred domain does not match the preferred domain.
    Returns ``(DomainSpec, auto_scale)`` via :pymethod:`result` after
    ``exec_()`` returns ``QDialog.Accepted``.
    """

    def __init__(
        self,
        parent: QWidget,
        data_domain: DomainSpec,
        preferred_domain: DomainSpec,
        context_message: str = "",
        initial_domain: Optional[DomainSpec] = None,
        host_name: str = "Host",
    ):
        super().__init__(parent)
        self.setWindowTitle("Domain Settings")
        self.setMinimumWidth(420)

        self._data_domain = data_domain
        self._preferred_domain = preferred_domain
        self._initial_domain = initial_domain  # pre-set values to show on open (user_domain if revisiting)

        layout = QVBoxLayout(self)

        # --- context-sensitive header (shown only when non-empty) ---
        if context_message:
            lbl = QLabel(context_message)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        layout.addWidget(QLabel("Edit the domain below, or use one of the presets."))

        # --- coordinate fields ---
        grid = QGridLayout()
        dv = QDoubleValidator()
        self._fields: dict[str, QLineEdit] = {}
        for row, (label, attr) in enumerate([
            ("X min", "xmin"), ("X max", "xmax"),
            ("Y min", "ymin"), ("Y max", "ymax"),
            ("Z min", "zmin"), ("Z max", "zmax"),
        ]):
            grid.addWidget(QLabel(label), row, 0)
            le = QLineEdit_custom(ndigits=2)
            le.setValidator(dv)
            le.setStyleSheet(_LE_STYLE)
            self._fields[attr] = le
            grid.addWidget(le, row, 1)
        layout.addLayout(grid)

        # --- units ---
        initial_units = (initial_domain.units if initial_domain is not None
                         else preferred_domain.units)
        units_hbox = QHBoxLayout()
        units_hbox.addWidget(QLabel("Units:"))
        self._units_edit = QLineEdit(initial_units)
        self._units_edit.setStyleSheet(_LE_STYLE)
        self._units_edit.setMaximumWidth(120)
        units_hbox.addWidget(self._units_edit)
        units_hbox.addStretch()
        layout.addLayout(units_hbox)

        # --- auto-scale checkbox ---
        self._auto_scale_cb = QCheckBox("Auto-scale data to fill domain (preserving aspect ratio)")
        self._auto_scale_cb.setChecked(True)
        layout.addWidget(self._auto_scale_cb)

        # --- preset buttons ---
        preset_hbox = QHBoxLayout()
        data_btn = QPushButton("Use Data Domain")
        data_btn.clicked.connect(self._fill_data)
        preferred_btn = QPushButton(f"Use {host_name} Domain")
        preferred_btn.clicked.connect(self._fill_preferred)
        preset_hbox.addWidget(data_btn)
        preset_hbox.addWidget(preferred_btn)
        layout.addLayout(preset_hbox)

        # --- OK / Cancel ---
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # Auto-populate: show user-set values if revisiting, otherwise data domain.
        if self._initial_domain is not None:
            self._fill_domain(self._initial_domain)
        else:
            self._fill_data()

    # ------------------------------------------------------------------

    def _fill_domain(self, d: DomainSpec) -> None:
        for attr, le in self._fields.items():
            le.setText(str(getattr(d, attr)))

    def _fill_data(self) -> None:
        d = self._data_domain
        if abs(d.zmax - d.zmin) < 1e-6:
            d = DomainSpec(d.xmin, d.xmax, d.ymin, d.ymax,
                           -10.0, 10.0, d.source, d.units)
        self._fill_domain(d)

    def _fill_preferred(self) -> None:
        self._fill_domain(self._preferred_domain)

    # ------------------------------------------------------------------

    def result(self) -> tuple[DomainSpec, bool]:
        """Return ``(DomainSpec, auto_scale_to_domain)`` from the dialog fields."""
        vals = {attr: float(le.text() or "0") for attr, le in self._fields.items()}
        domain = DomainSpec(
            xmin=vals["xmin"], xmax=vals["xmax"],
            ymin=vals["ymin"], ymax=vals["ymax"],
            zmin=vals["zmin"], zmax=vals["zmax"],
            source="user_edited",
            units=self._units_edit.text().strip() or "micron",
        )
        return domain, self._auto_scale_cb.isChecked()


def _build_mismatch_message(
    kind: str, data: DomainSpec, preferred: DomainSpec, host_name: str = "Host"
) -> str:
    """Return a human-readable header for DomainEditorDialog based on mismatch kind."""
    data_str = (
        f"Data range: [{data.xmin:.1f}, {data.xmax:.1f}] \u00d7 "
        f"[{data.ymin:.1f}, {data.ymax:.1f}]"
    )
    pref_str = (
        f"{host_name}: [{preferred.xmin:.1f}, {preferred.xmax:.1f}] \u00d7 "
        f"[{preferred.ymin:.1f}, {preferred.ymax:.1f}]"
    )
    if kind == "outside":
        return (
            f"<b>Warning:</b> Some data coordinates fall outside the {host_name} domain "
            "\u2014 those cells would be excluded from the simulation.\n\n"
            f"{data_str}\n{pref_str}"
        )
    if kind == "small":
        return (
            f"<b>Note:</b> The data covers a significantly smaller area than the {host_name} "
            "domain \u2014 cells may appear very sparse.\n\n"
            f"{data_str}\n{pref_str}"
        )
    return ""


# ---------------------------------------------------------------------------
# Session — plain-data accumulator (no Qt)
# ---------------------------------------------------------------------------

@dataclass
class WalkthroughSession:
    """Accumulates all data decisions made during the BIWT workflow.

    This object is the single source of truth shared between the walkthrough
    controller and all step windows.  No Qt objects are stored here.

    Fields are populated progressively as the user advances through steps.
    ``None`` means "not yet determined".
    """
    biwt_input: BiwtInput

    # ---- after file import -----------------------------------------------
    data: Optional[BiwtData] = None
    inferred_domain: Optional[DomainSpec] = None

    # ---- domain editor overrides (set by DomainEditorDialog) -------------
    user_domain: Optional[DomainSpec] = None     # user-edited domain; overrides inferred
    auto_scale_to_domain: bool = True            # scale data coords to fill domain box
    data_domain: Optional[DomainSpec] = None     # raw data bounding box computed at import
    domain_accepted: bool = False                # True once user has resolved domain dialog

    # ---- spatial data (extracted from data after import) -----------------
    # spatial_data: raw (N, 2-or-3) coordinate array in data units
    # spatial_data_final: post-rename/filter coords, same shape, in data units
    spatial_data: Optional[np.ndarray] = None
    spatial_data_final: Optional[np.ndarray] = None
    use_spatial_data: Optional[bool] = None   # None = not yet asked

    # ---- spot deconvolution (optional) -----------------------------------
    spot_deconv_asked: bool = False                  # True once the query window is passed
    perform_spot_deconvolution: bool = False
    cell_types_max: Optional[list] = None            # max-prob type per spot
    cell_prob_feature_dicts: Optional[list] = None   # per-spot {type: prob} dicts

    # ---- after cluster-column selection ----------------------------------
    current_column: Optional[str] = None             # obs column chosen by user
    cell_types_original: Optional[list] = None       # per-cell type labels
    cell_types_list_original: Optional[list] = None  # unique sorted labels

    # ---- after edit-cell-types step --------------------------------------
    # Mirrors the original biwt_tab intermediate representation
    cell_type_dict_on_edit: Optional[dict] = None    # original → intermediate | None
    intermediate_types: Optional[list] = None        # post-edit type names
    intermediate_type_pre_image: Optional[dict] = None   # intermediate → [originals]

    # ---- after rename step -----------------------------------------------
    cell_types_list_final: Optional[list] = None     # final display names
    cell_type_dict_on_rename: Optional[dict] = None  # original → final
    cell_types_final: Optional[list] = None          # per-cell final types
    cell_counts: Optional[dict] = None               # type → int count
    cell_counts_confirmed: bool = False              # True after CellCountsWindow
    cell_volume: Optional[dict] = None               # type → float µm³

    # ---- after positions step --------------------------------------------
    coords_by_type: dict = field(default_factory=dict)  # type → (N,3) ndarray
    plotted_cell_types_per_spot: list = field(default_factory=list)  # spot-deconv records
    positions_set: bool = False

    # ---- XML built in _finish() ------------------------------------------
    cell_definitions_xml: Optional[str] = None   # in-memory XML; passed to BiwtResult

    # ---- after load-cell-parameters step ---------------------------------
    cell_definitions_registry: dict = field(default_factory=dict)
    parameters_loaded: bool = False

    # ---- legacy CellTypeConfig (new-style, not yet fully wired) ----------
    cell_type_config: CellTypeConfig = field(default_factory=CellTypeConfig)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def preferred_domain(self) -> DomainSpec:
        return self.biwt_input.preferred_domain

    @property
    def effective_domain(self) -> DomainSpec:
        """Domain to use for coordinate placement.

        Priority: user_domain (from editor) > inferred_domain > preferred_domain.
        """
        if self.user_domain is not None:
            return self.user_domain
        return self.inferred_domain or self.preferred_domain

    # ------------------------------------------------------------------
    # Data-logic helpers (pure Python, no Qt)
    # ------------------------------------------------------------------

    def collect_cell_type_data(self) -> None:
        """Extract unique cell types from the selected obs column."""
        col_data = self.data.obs[self.current_column]
        self.cell_types_original = col_data.tolist()
        self.cell_types_list_original = sorted(set(str(ct) for ct in self.cell_types_original))

    def setup_spot_deconvolution_data(self) -> None:
        """Build per-spot probability dicts from probability columns."""
        prob_cols = self.data.probability_columns
        self.cell_types_list_original = sorted(set(
            c.replace("_probability", "") for c in prob_cols
        ))
        prob_matrix = self.data.obs[prob_cols].values
        max_indices = prob_matrix.argmax(axis=1)
        cell_types = [c.replace("_probability", "") for c in prob_cols]
        self.cell_types_max = [cell_types[i] for i in max_indices]
        self.cell_prob_feature_dicts = [
            {c.replace("_probability", ""): self.data.obs[c].iloc[i]
             for c in prob_cols}
            for i in range(len(self.data.obs))
        ]

    def setup_spatial_data(self) -> None:
        """Extract raw spatial coordinates into self.spatial_data."""
        from biwt.core.domain import _find_spatial_key, _find_coord_col
        if self.data.obsm:
            key = _find_spatial_key(self.data.obsm)
            if key:
                arr = np.asarray(self.data.obsm[key])
                if arr.ndim == 2 and arr.shape[1] == 2:
                    arr = np.column_stack([arr, np.zeros(len(arr))])
                self.spatial_data = arr
                return
        cols = list(self.data.obs.columns)
        x_col = _find_coord_col(cols, "x") or _find_coord_col(cols, "imagerow")
        y_col = _find_coord_col(cols, "y") or _find_coord_col(cols, "imagecol")
        if x_col and y_col:
            z_col = _find_coord_col(cols, "z")
            xy = np.column_stack([
                self.data.obs[x_col].values,
                self.data.obs[y_col].values,
            ])
            if z_col:
                xy = np.column_stack([xy, self.data.obs[z_col].values])
            else:
                xy = np.column_stack([xy, np.zeros(len(xy))])
            self.spatial_data = xy

    def compute_intermediate_types(self) -> None:
        """Derive intermediate_types from cell_type_dict_on_edit."""
        self.intermediate_types = []
        self.intermediate_type_pre_image = {}
        for orig in sorted(self.cell_type_dict_on_edit):
            intermed = self.cell_type_dict_on_edit[orig]
            if intermed is None:
                continue
            if intermed not in self.intermediate_types:
                self.intermediate_types.append(intermed)
                self.intermediate_type_pre_image[intermed] = [orig]
            else:
                self.intermediate_type_pre_image[intermed].append(orig)

    def apply_rename(self) -> None:
        """Build cell_types_final, spatial_data_final, counts, and volumes."""
        mapping = self.cell_type_dict_on_rename
        if self.perform_spot_deconvolution:
            updated_dicts, spatial_rows = [], []
            final_set = set()
            for prob_dict, sp in zip(self.cell_prob_feature_dicts, self.spatial_data):
                new_dict = {}
                for orig, prob in prob_dict.items():
                    if orig not in mapping:
                        continue
                    renamed = mapping[orig]
                    new_dict[renamed] = new_dict.get(renamed, 0.0) + prob
                    final_set.add(renamed)
                if sum(new_dict.values()) > 0:
                    updated_dicts.append(new_dict)
                    spatial_rows.append(sp)
            self.cell_prob_feature_dicts = updated_dicts
            self.spatial_data_final = np.vstack(spatial_rows) if spatial_rows else np.empty((0, 3))
            self.cell_types_final = sorted(final_set)
        else:
            pairs = [
                (mapping[ct], pos)
                for ct, pos in zip(self.cell_types_original,
                                   self.spatial_data if self.use_spatial_data else [None] * len(self.cell_types_original))
                if ct in mapping
            ]
            if self.use_spatial_data:
                self.cell_types_final = [p[0] for p in pairs]
                self.spatial_data_final = np.vstack([p[1] for p in pairs])
            else:
                self.cell_types_final = [mapping[ct] for ct in self.cell_types_original if ct in mapping]

        self._count_final_cell_types()
        self._compute_cell_volumes()

    def _count_final_cell_types(self) -> None:
        self.cell_counts = {ct: 0 for ct in self.cell_types_list_final}
        for ct in self.cell_types_final:
            if ct in self.cell_counts:
                self.cell_counts[ct] += 1

    def _compute_cell_volumes(self) -> None:
        """Default volume 2494 µm³ (PhysiCell default).
        TODO: accept host cell volumes via BiwtInput."""
        self.cell_volume = {ct: 2494.0 for ct in self.cell_types_list_final}


# ---------------------------------------------------------------------------
# Step-predicate table (pure Python, no Qt — importable by tests)
# ---------------------------------------------------------------------------

def _step_predicates(s: "WalkthroughSession") -> list:
    """Return ``[(predicate, label), ...]`` in walkthrough order.

    Each *predicate* is a zero-arg callable returning ``bool``.
    Each *label* is a stable string identifier for the step.

    This function is the single source of truth for step-selection logic.
    ``BioinformaticsWalkthrough._build_next_window`` maps each label to its
    factory; tests import this function directly so they never duplicate the
    predicate logic.
    """
    return [
        (
            lambda: not s.spot_deconv_asked
                    and bool(s.data and s.data.probability_columns)
                    and bool(s.data and s.data.has_spatial),
            "SpotDeconvQuery",
        ),
        (
            lambda: s.current_column is None and not s.perform_spot_deconvolution,
            "ClusterColumn",
        ),
        (
            lambda: s.use_spatial_data is None
                    and s.data is not None and s.data.has_spatial,
            "SpatialQuery",
        ),
        (
            lambda: s.cell_type_dict_on_edit is None,
            "EditCellTypes",
        ),
        (
            lambda: s.cell_types_list_final is None,
            "RenameCellTypes",
        ),
        (
            lambda: not s.use_spatial_data and not s.cell_counts_confirmed,
            "CellCounts",
        ),
        (
            lambda: not s.positions_set,
            "Positions",
        ),
        (
            lambda: not s.parameters_loaded,
            "LoadCellParameters",
        ),
    ]


# ---------------------------------------------------------------------------
# Downstream-invalidation tables (used by advance() to centralize resets)
# ---------------------------------------------------------------------------

_STEP_ORDER = [
    "SpotDeconvQuery", "ClusterColumn", "SpatialQuery",
    "EditCellTypes", "RenameCellTypes", "CellCounts",
    "Positions", "LoadCellParameters",
]

# For each step label: (session_field, reset_value) pairs.
# advance() resets the fields of every step AFTER the current one when
# stale_futures is True, so predicates are re-evaluated on fresh state.
_STEP_FIELDS: dict[str, list] = {
    "SpotDeconvQuery": [
        ("spot_deconv_asked", False),
        ("perform_spot_deconvolution", False),
        ("cell_types_max", None),
        ("cell_prob_feature_dicts", None),
    ],
    "ClusterColumn": [
        ("current_column", None),
        ("cell_types_original", None),
        ("cell_types_list_original", None),
    ],
    "SpatialQuery": [
        ("use_spatial_data", None),
    ],
    "EditCellTypes": [
        ("cell_type_dict_on_edit", None),
        ("intermediate_types", None),
        ("intermediate_type_pre_image", None),
    ],
    "RenameCellTypes": [
        ("cell_types_list_final", None),
        ("cell_type_dict_on_rename", None),
        ("cell_types_final", None),
        ("cell_counts", None),
        ("cell_volume", None),
    ],
    "CellCounts": [
        ("cell_counts_confirmed", False),
    ],
    "Positions": [
        ("positions_set", False),
        ("coords_by_type", {}),
        ("plotted_cell_types_per_spot", []),
    ],
    "LoadCellParameters": [
        ("parameters_loaded", False),
        ("cell_definitions_registry", {}),
        ("cell_definitions_xml", None),
    ],
}


# ---------------------------------------------------------------------------
# Main walkthrough widget
# ---------------------------------------------------------------------------

class BioinformaticsWalkthrough(QWidget):
    """Top-level BIWT popup controller.

    Parameters
    ----------
    biwt_input:
        Everything the host supplies at launch (domain, cell-type names, etc.)
    on_complete:
        Callback receiving a ``BiwtResult`` when the user finishes.
        Called with ``None`` if the user cancels.
    """

    def __init__(
        self,
        biwt_input: BiwtInput,
        on_complete: Optional[Callable[[Optional[BiwtResult]], None]] = None,
    ):
        super().__init__()
        self.setWindowTitle("BioInformatics WalkThrough (BIWT)")
        self.setWindowFlags(Qt.Window)

        self.on_complete = on_complete or (lambda result: None)
        self.session = WalkthroughSession(biwt_input=biwt_input)

        # Window stack management.
        # Two-list model mirrors the original biwt_tab.py design:
        #
        #   window_history — windows already visited (most-recent last).
        #                    Going back pops from the end of this list.
        #   window_future  — windows that were visited but are still valid
        #                    (not stale).  Going forward reuses these instead
        #                    of rebuilding, so a back→forward without any
        #                    user change preserves window state.
        #   stale_futures  — set to True by any widget that changes session
        #                    state.  When True, going forward discards
        #                    window_future and builds fresh windows instead.
        self.window_history: list[QWidget] = []
        self.window_future: list[QWidget] = []
        self.stale_futures: bool = False
        self.current_window_idx: int = -1
        self.window: Optional[QWidget] = None

        self._build_home_ui()

    # ------------------------------------------------------------------
    # Home screen
    # ------------------------------------------------------------------

    def _build_home_ui(self) -> None:
        vbox = QVBoxLayout(self)

        # Title
        title = QLabel(
            '<p style="font-size:28px; text-decoration:underline;">'
            '<b>B</b>io<b>I</b>nformatics <b>W</b>alk<b>T</b>hrough (BIWT)'
            "</p>"
        )
        title.setAlignment(Qt.AlignCenter)
        vbox.addWidget(title)
        vbox.addStretch(1)

        # Import section
        vbox.addWidget(SectionHeader("Import"))
        hbox_import = QHBoxLayout()

        self.import_button = QPushButton("Import file…")
        self.import_button.setStyleSheet("QPushButton {background-color: lightgreen; color: black;}")
        self.import_button.clicked.connect(self._import_cb)
        hbox_import.addWidget(self.import_button)

        hbox_import.addWidget(QLabel("Default cell-type column:"))
        self.column_line_edit = QLineEdit("type")
        self.column_line_edit.setStyleSheet(_LE_STYLE)
        hbox_import.addWidget(self.column_line_edit)
        vbox.addLayout(hbox_import)

        vbox.addWidget(QLabel(
            "Supported formats: .h5ad (AnnData), .rds / .rda / .rdata (Seurat / SCE), .csv"
        ))

        self._domain_accepted_cb = QCheckBox("Skip domain validation on import")
        self._domain_accepted_cb.setToolTip(
            "When checked, the domain editor will not appear automatically at the positions step."
        )
        vbox.addWidget(self._domain_accepted_cb)

        vbox.addWidget(QHLine())

        vbox.addStretch(1)

    # ------------------------------------------------------------------
    # File import
    # ------------------------------------------------------------------

    def _import_cb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import single-cell data",
            "",
            "Supported files (*.h5ad *.rds *.rda *.rdata *.csv);;All files (*)",
        )
        if not path:
            return
        try:
            bdata = data_loader.load(path)
        except LoadError as e:
            QMessageBox.critical(self, "Import failed", str(e))
            return

        # Reset session so stale state from a previous run doesn't survive reimport.
        self.session = WalkthroughSession(biwt_input=self.session.biwt_input)
        self.session.data = bdata

        # Infer domain — preferred always wins; otherwise use data metadata/range.
        # microns_per_pixel is non-None only for platforms where we know the
        # physical scale (currently 10x Visium).
        preferred = self.session.biwt_input.preferred_domain
        inferred = domain_module.infer_domain(
            preferred=preferred,
            obs=bdata.obs,
            obsm=bdata.obsm,
            microns_per_pixel=bdata.microns_per_pixel,
        )
        self.session.inferred_domain = inferred

        # Compute and store data-range domain for later mismatch check at positions step.
        data_domain = domain_module.infer_domain(
            preferred=None,
            obs=bdata.obs,
            obsm=bdata.obsm,
            microns_per_pixel=bdata.microns_per_pixel,
        )
        self.session.data_domain = data_domain

        # domain_accepted: host can pre-accept, or user can check the checkbox.
        self.session.domain_accepted = (
            self.session.biwt_input.domain_accepted
            or self._domain_accepted_cb.isChecked()
        )

        log.info(
            "Loaded %d cells from '%s'. Domain source: %s.",
            bdata.n_cells, path, inferred.source,
        )
        self._start_walkthrough()

    # ------------------------------------------------------------------
    # Step-window management
    # ------------------------------------------------------------------

    def _start_walkthrough(self) -> None:
        """Begin the step-window sequence after successful file import."""
        self.window_history.clear()
        self.window_future.clear()
        self.current_window_idx = -1
        self.stale_futures = True   # first advance always builds fresh
        self.advance()

    def _invalidate_downstream_of(self, label: str) -> None:
        """Reset all session fields for every step strictly after *label*.

        Called by ``advance()`` when ``stale_futures`` is True so that
        step predicates are re-evaluated against a clean state.  Individual
        window classes no longer need to maintain their own invalidation lists.
        """
        import copy as _copy
        try:
            idx = _STEP_ORDER.index(label)
        except ValueError:
            return
        s = self.session
        for step in _STEP_ORDER[idx + 1:]:
            for field_name, default in _STEP_FIELDS.get(step, []):
                setattr(s, field_name, _copy.copy(default))

    def advance(self) -> None:
        """Move forward one step.

        If ``stale_futures`` is True (user changed something on the current
        step), reset all downstream session fields and build a fresh window.
        If ``stale_futures`` is False and cached future windows exist, reuse
        the next one so that back→forward without changes preserves state.
        """
        if self.window is not None:
            self.window_history.append(self.window)
            self.window.hide()

        if self.stale_futures or not self.window_future:
            if self.stale_futures:
                label = getattr(self.window, "_step_label", None)
                if label:
                    self._invalidate_downstream_of(label)
                self.window_future.clear()
            next_win = self._build_next_window()
            if next_win is None:
                self._finish()
                return
        else:
            # Reuse cached future — user went back without changing anything
            next_win = self.window_future.pop(0)

        self.stale_futures = False
        self.current_window_idx += 1
        self.window = next_win
        self.window.show()

    def go_back_to_prev_window(self) -> None:
        """Return to the previous step.

        If the current window has been marked stale (user changed something),
        discard all future windows — they must be rebuilt when the user
        advances again.  Otherwise, save the current window to the front of
        ``window_future`` so it can be reused on the next forward step.
        """
        if not self.window_history:
            return

        if self.window is not None:
            self.window.hide()
            if self.stale_futures:
                self.window_future.clear()
            else:
                # Current window is still valid — preserve as next future
                self.window_future.insert(0, self.window)

        self.stale_futures = False   # future list (if any) is now clean
        self.current_window_idx -= 1
        self.window = self.window_history.pop()
        self.window.show()

    def _build_next_window(self) -> Optional[QWidget]:
        """Return the next step window determined by current session state.

        Steps are checked in order; the first whose predicate is True is built
        and returned.  Predicates are re-evaluated on every advance so that
        optional steps (SpatialQuery, CellCounts) are included or skipped based
        on the data and earlier user choices.

        Flow:
          import → [SpotDeconvQuery?] → ClusterColumn → [SpatialQuery?]
               → EditCellTypes → RenameCellTypes → [CellCounts?]
               → Positions → LoadCellParameters → done (host writes output)
        """
        # Lazy imports keep startup fast and avoid circular imports at module level.
        from biwt.gui.windows.spot_deconvolution import SpotDeconvolutionQueryWindow
        from biwt.gui.windows.cluster_column import ClusterColumnWindow
        from biwt.gui.windows.spatial_query import SpatialQueryWindow
        from biwt.gui.windows.edit_cell_types import EditCellTypesWindow
        from biwt.gui.windows.rename_cell_types import RenameCellTypesWindow
        from biwt.gui.windows.cell_counts import CellCountsWindow
        from biwt.gui.windows.positions import PositionsWindow
        from biwt.gui.windows.load_cell_parameters import LoadCellParametersWindow

        s = self.session

        def _make_spatial_query():
            s.setup_spatial_data()
            return SpatialQueryWindow(self)

        def _make_edit_cell_types():
            if s.cell_types_list_original is None:
                s.collect_cell_type_data()
            return EditCellTypesWindow(self)

        _factories = {
            "SpotDeconvQuery":    lambda: SpotDeconvolutionQueryWindow(self),
            "ClusterColumn":      lambda: ClusterColumnWindow(self),
            "SpatialQuery":       _make_spatial_query,
            "EditCellTypes":      _make_edit_cell_types,
            "RenameCellTypes":    lambda: RenameCellTypesWindow(self),
            "CellCounts":         lambda: CellCountsWindow(self),
            "Positions":          lambda: PositionsWindow(self),
            "LoadCellParameters": lambda: LoadCellParametersWindow(self),

        }

        for predicate, label in _step_predicates(s):
            if predicate():
                win = _factories[label]()
                win._step_label = label
                return win
        return None

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        """Assemble BiwtResult and call on_complete. The host writes all output."""
        import copy
        import xml.etree.ElementTree as ET
        from biwt.core.parameters.xml_defaults import xml_defaults

        coords_df = build_ic_dataframe(self.session.coords_by_type)
        mapping = self.session.cell_type_config.resolve()
        s = self.session

        # Build cell-definitions XML if the parameters step populated the registry.
        if s.cell_definitions_registry:
            root = ET.Element("PhysiCell_settings", version="devel-version")
            for key, xml_str in xml_defaults.items():
                wrapped = f"<{key}>{xml_str.strip()}</{key}>"
                root.append(ET.fromstring(wrapped))
            cell_defs = ET.SubElement(root, "cell_definitions")
            for template_elem in s.cell_definitions_registry.values():
                cell_defs.append(copy.deepcopy(template_elem))
            s.cell_definitions_xml = ET.tostring(
                root, encoding="unicode", xml_declaration=False
            )

        result = BiwtResult(
            coordinates=coords_df,
            cell_type_map=mapping,
            domain_used=s.effective_domain,
            cell_definitions_xml=s.cell_definitions_xml,
        )

        self.on_complete(result)
        self.close()


# ---------------------------------------------------------------------------
# Factory function — the primary host entry point
# ---------------------------------------------------------------------------

def create_biwt_widget(
    biwt_input: BiwtInput,
    on_complete: Optional[Callable[[Optional[BiwtResult]], None]] = None,
) -> BioinformaticsWalkthrough:
    """Create and return a ready-to-show BIWT walkthrough popup.

    Parameters
    ----------
    biwt_input:
        Constructed by the host with domain and optional cell-type hints.
    on_complete:
        Callback called with ``BiwtResult`` (or ``None`` on cancel) when the
        user finishes the workflow.

    Example
    -------
    ::

        from biwt import BiwtInput, DomainSpec
        from biwt.gui import create_biwt_widget

        widget = create_biwt_widget(
            BiwtInput(
                preferred_domain=DomainSpec(xmin=-500, xmax=500,
                                            ymin=-500, ymax=500),
                host_cell_type_names=["default", "tumor", "immune"],
                output_csv_path="./config/cells.csv",
            ),
            on_complete=lambda result: print(result.coordinates.head()),
        )
        widget.show()
    """
    return BioinformaticsWalkthrough(biwt_input=biwt_input, on_complete=on_complete)
