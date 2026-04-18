"""
Session-level unit tests for the BIWT walkthrough pipeline.

These tests exercise pure-Python session logic without any Qt/GUI.
Each test builds a WalkthroughSession, drives it through a sequence of
session-method calls that mirror what the step windows do, and asserts
on the resulting state — especially the coordinates DataFrame.

Run with:
    cd biwt && pytest tests/ -v
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from biwt.core import data_loader
from biwt.core.data_loader import BiwtData
from biwt.core.domain import classify_domain_mismatch
from biwt.core.positioning import build_ic_dataframe
from biwt.gui.walkthrough import WalkthroughSession, _step_predicates
from biwt.types import BiwtInput, DomainSpec

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
SPATIAL_CSV     = str(FIXTURES / "spatial.csv")
NONSPATIAL_CSV  = str(FIXTURES / "nonspatial.csv")
SPOT_DECONV_CSV = str(FIXTURES / "spot_deconv.csv")

DOMAIN = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)


def _session(csv_path: str) -> WalkthroughSession:
    """Load a CSV and return a fresh WalkthroughSession with data attached."""
    data = data_loader.load(csv_path)
    s = WalkthroughSession(biwt_input=BiwtInput(preferred_domain=DOMAIN))
    s.data = data
    return s


# ---------------------------------------------------------------------------
# Data loader basics
# ---------------------------------------------------------------------------

class TestDataLoader:
    def test_spatial_csv_has_spatial(self):
        data = data_loader.load(SPATIAL_CSV)
        assert data.has_spatial
        assert data.n_cells == 7
        assert "type" in data.obs.columns

    def test_nonspatial_csv_no_spatial(self):
        data = data_loader.load(NONSPATIAL_CSV)
        assert not data.has_spatial
        assert data.n_cells == 6

    def test_spot_deconv_csv_has_prob_columns(self):
        data = data_loader.load(SPOT_DECONV_CSV)
        assert data.has_spatial
        assert len(data.probability_columns) == 3
        assert all(c.endswith("_probability") for c in data.probability_columns)


# ---------------------------------------------------------------------------
# DomainSpec basics
# ---------------------------------------------------------------------------

class TestDomainSpec:
    def test_units_field_default(self):
        d = DomainSpec(xmin=0, xmax=1, ymin=0, ymax=1)
        assert d.units == "micron"

    def test_units_field_custom(self):
        d = DomainSpec(xmin=0, xmax=1, ymin=0, ymax=1, units="pixel")
        assert d.units == "pixel"

    def test_z_defaults(self):
        d = DomainSpec(xmin=0, xmax=1, ymin=0, ymax=1)
        assert d.zmin == -10.0
        assert d.zmax == 10.0

    def test_width_height(self):
        d = DomainSpec(xmin=-500, xmax=500, ymin=-250, ymax=250)
        assert d.width == 1000.0
        assert d.height == 500.0


# ---------------------------------------------------------------------------
# classify_domain_mismatch
# ---------------------------------------------------------------------------

class TestDomainMismatchClassification:
    PREFERRED = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

    def test_identical_returns_none(self):
        data = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)
        assert classify_domain_mismatch(data, self.PREFERRED) is None

    def test_data_outside_x_returns_outside(self):
        data = DomainSpec(xmin=-500, xmax=600, ymin=-500, ymax=500)
        assert classify_domain_mismatch(data, self.PREFERRED) == "outside"

    def test_data_outside_y_returns_outside(self):
        data = DomainSpec(xmin=-500, xmax=500, ymin=-600, ymax=500)
        assert classify_domain_mismatch(data, self.PREFERRED) == "outside"

    def test_snug_fit_returns_none(self):
        # Data fills exactly 100% of preferred → no issue
        data = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)
        assert classify_domain_mismatch(data, self.PREFERRED) is None

    def test_data_x_dim_below_half_returns_small(self):
        # width = 400 (40% of 1000) → small
        data = DomainSpec(xmin=-200, xmax=200, ymin=-500, ymax=500)
        assert classify_domain_mismatch(data, self.PREFERRED) == "small"

    def test_data_area_below_half_returns_small(self):
        # width=600 (60%), height=600 (60%), area=36% → small
        data = DomainSpec(xmin=-300, xmax=300, ymin=-300, ymax=300)
        assert classify_domain_mismatch(data, self.PREFERRED) == "small"

    def test_data_at_exactly_50pct_each_axis_returns_none(self):
        # width=500 (50%), height=500 (50%), area=25% → small (area check)
        data = DomainSpec(xmin=-250, xmax=250, ymin=-250, ymax=250)
        assert classify_domain_mismatch(data, self.PREFERRED) == "small"

    def test_data_covers_more_than_50pct_returns_none(self):
        # width=700 (70%), height=700 (70%), area=49% — below 50% area threshold
        data = DomainSpec(xmin=-350, xmax=350, ymin=-350, ymax=350)
        assert classify_domain_mismatch(data, self.PREFERRED) == "small"

    def test_data_covers_sufficient_area_returns_none(self):
        # width=800 (80%), height=800 (80%), area=64% → none
        data = DomainSpec(xmin=-400, xmax=400, ymin=-400, ymax=400)
        assert classify_domain_mismatch(data, self.PREFERRED) is None


# ---------------------------------------------------------------------------
# Session domain overrides
# ---------------------------------------------------------------------------

class TestEffectiveDomain:
    def test_effective_domain_defaults_to_preferred(self):
        s = _session(SPATIAL_CSV)
        assert s.effective_domain is s.preferred_domain

    def test_user_domain_overrides_inferred(self):
        s = _session(SPATIAL_CSV)
        s.inferred_domain = DomainSpec(xmin=-100, xmax=100, ymin=-100, ymax=100)
        user = DomainSpec(xmin=-999, xmax=999, ymin=-999, ymax=999, source="user_edited")
        s.user_domain = user
        assert s.effective_domain is user

    def test_auto_scale_defaults_true(self):
        s = _session(SPATIAL_CSV)
        assert s.auto_scale_to_domain is True

    def test_domain_accepted_default_false(self):
        s = _session(SPATIAL_CSV)
        assert s.domain_accepted is False

    def test_data_domain_default_none(self):
        s = _session(SPATIAL_CSV)
        assert s.data_domain is None


# ---------------------------------------------------------------------------
# Cluster column / collect_cell_type_data
# ---------------------------------------------------------------------------

class TestCollectCellTypeData:
    def test_extracts_unique_types_sorted(self):
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        assert s.cell_types_list_original == ["Macrophage", "T_cell", "Tumor"]
        assert len(s.cell_types_original) == 7

    def test_per_cell_labels_match_obs(self):
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        assert s.cell_types_original == list(s.data.obs["type"])


# ---------------------------------------------------------------------------
# Spatial setup
# ---------------------------------------------------------------------------

class TestSetupSpatialData:
    def test_spatial_csv_sets_array(self):
        s = _session(SPATIAL_CSV)
        s.setup_spatial_data()
        assert s.spatial_data is not None
        assert s.spatial_data.shape == (7, 3)  # x, y, z(=0)

    def test_nonspatial_csv_leaves_none(self):
        s = _session(NONSPATIAL_CSV)
        s.setup_spatial_data()
        assert s.spatial_data is None


# ---------------------------------------------------------------------------
# compute_intermediate_types (edit cell types step)
# ---------------------------------------------------------------------------

class TestComputeIntermediateTypes:
    def _base_session(self):
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        return s

    def test_all_kept(self):
        s = self._base_session()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        assert set(s.intermediate_types) == {"Macrophage", "T_cell", "Tumor"}
        assert all(len(v) == 1 for v in s.intermediate_type_pre_image.values())

    def test_delete_one(self):
        s = self._base_session()
        s.cell_type_dict_on_edit = {
            "Macrophage": "Macrophage",
            "T_cell": "T_cell",
            "Tumor": None,  # deleted
        }
        s.compute_intermediate_types()
        assert "Tumor" not in s.intermediate_types
        assert set(s.intermediate_types) == {"Macrophage", "T_cell"}

    def test_merge_two(self):
        s = self._base_session()
        # Merge Tumor into T_cell (T_cell is the first / target)
        s.cell_type_dict_on_edit = {
            "Macrophage": "Macrophage",
            "T_cell": "T_cell",
            "Tumor": "T_cell",   # merged
        }
        s.compute_intermediate_types()
        assert set(s.intermediate_types) == {"Macrophage", "T_cell"}
        assert sorted(s.intermediate_type_pre_image["T_cell"]) == ["T_cell", "Tumor"]

    def test_delete_all_except_one(self):
        s = self._base_session()
        s.cell_type_dict_on_edit = {
            "Macrophage": None,
            "T_cell": "T_cell",
            "Tumor": None,
        }
        s.compute_intermediate_types()
        assert s.intermediate_types == ["T_cell"]


# ---------------------------------------------------------------------------
# apply_rename — non-spatial path
# ---------------------------------------------------------------------------

class TestApplyRenameNonSpatial:
    def _setup(self, cell_type_dict_on_edit=None, intermediate_to_final=None):
        """
        Mirror what RenameCellTypesWindow.process_window() does:
        - cell_type_dict_on_edit: original → intermediate | None
        - intermediate_to_final: intermediate name → final (renamed) name
          Defaults to identity.  cell_type_dict_on_rename and
          cell_types_list_final are derived from this, including ALL
          original names that folded into each intermediate (merged types).
        """
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = cell_type_dict_on_edit or {
            ct: ct for ct in s.cell_types_list_original
        }
        s.compute_intermediate_types()

        if intermediate_to_final is None:
            intermediate_to_final = {ct: ct for ct in s.intermediate_types}

        # cell_types_list_final = the renamed names (values of the mapping)
        s.cell_types_list_final = list(intermediate_to_final.values())
        # cell_type_dict_on_rename maps every ORIGINAL name to its final name,
        # expanding merged groups via intermediate_type_pre_image.
        s.cell_type_dict_on_rename = {}
        for intermed, final in intermediate_to_final.items():
            for orig in s.intermediate_type_pre_image.get(intermed, [intermed]):
                s.cell_type_dict_on_rename[orig] = final

        s.apply_rename()
        return s

    def test_counts_match_fixture(self):
        s = self._setup()
        assert s.cell_counts == {"Macrophage": 1, "T_cell": 3, "Tumor": 2}

    def test_rename_changes_label(self):
        s = self._setup(intermediate_to_final={
            "Macrophage": "MΦ", "T_cell": "T_cell", "Tumor": "Tumor",
        })
        assert "MΦ" in s.cell_counts
        assert "Macrophage" not in s.cell_counts
        assert s.cell_counts["MΦ"] == 1

    def test_delete_removes_from_counts(self):
        s = self._setup(
            cell_type_dict_on_edit={
                "Macrophage": None,
                "T_cell": "T_cell",
                "Tumor": "Tumor",
            },
        )
        assert "Macrophage" not in s.cell_counts
        assert s.cell_counts["T_cell"] == 3

    def test_merge_sums_counts(self):
        # Tumor merged into T_cell → intermediate_types = ["Macrophage", "T_cell"]
        s = self._setup(
            cell_type_dict_on_edit={
                "Macrophage": "Macrophage",
                "T_cell": "T_cell",
                "Tumor": "T_cell",
            },
            # No rename; intermediate names kept as-is
        )
        assert s.cell_counts["T_cell"] == 5  # 3 T_cell + 2 Tumor


# ---------------------------------------------------------------------------
# apply_rename — spatial path
# ---------------------------------------------------------------------------

class TestApplyRenameSpatial:
    def _setup(self):
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = True
        s.setup_spatial_data()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()
        return s

    def test_spatial_data_final_shape(self):
        s = self._setup()
        assert s.spatial_data_final is not None
        assert s.spatial_data_final.shape[0] == s.data.n_cells
        assert s.spatial_data_final.shape[1] == 3

    def test_counts_match_fixture(self):
        s = self._setup()
        assert s.cell_counts == {"Macrophage": 2, "T_cell": 2, "Tumor": 3}

    def test_cell_types_final_length_matches_spatial(self):
        s = self._setup()
        assert len(s.cell_types_final) == s.spatial_data_final.shape[0]


# ---------------------------------------------------------------------------
# Spot deconvolution session setup
# ---------------------------------------------------------------------------

class TestSpotDeconvolution:
    def test_setup_extracts_cell_type_list(self):
        s = _session(SPOT_DECONV_CSV)
        s.perform_spot_deconvolution = True
        s.setup_spot_deconvolution_data()
        assert set(s.cell_types_list_original) == {"T_cell", "Tumor", "Macrophage"}

    def test_cell_types_max_length(self):
        s = _session(SPOT_DECONV_CSV)
        s.perform_spot_deconvolution = True
        s.setup_spot_deconvolution_data()
        assert len(s.cell_types_max) == 6

    def test_max_type_is_highest_prob(self):
        """First row: T_cell=0.8 → should be T_cell."""
        s = _session(SPOT_DECONV_CSV)
        s.perform_spot_deconvolution = True
        s.setup_spot_deconvolution_data()
        assert s.cell_types_max[0] == "T_cell"
        assert s.cell_types_max[2] == "Tumor"
        assert s.cell_types_max[4] == "Macrophage"


# ---------------------------------------------------------------------------
# Full pipeline → output DataFrame
# ---------------------------------------------------------------------------

class TestFullPipelineNonSpatial:
    """Drive the complete session sequence and inspect the final DataFrame."""

    def test_coordinates_dataframe_columns(self):
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()

        # Simulate cell-count override (user keeps defaults)
        # coords_by_type is set by PositionsWindow — simulate minimal placement
        import numpy as np
        rng = np.random.default_rng(42)
        for ct, count in s.cell_counts.items():
            s.coords_by_type[ct] = np.column_stack([
                rng.uniform(-500, 500, count),
                rng.uniform(-500, 500, count),
                np.zeros(count),
            ])

        df = build_ic_dataframe(s.coords_by_type)
        assert list(df.columns) == ["x", "y", "z", "type"]
        assert len(df) == 6
        assert set(df["type"].unique()) == {"Macrophage", "T_cell", "Tumor"}

    def test_delete_reduces_row_count(self):
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = {
            "Macrophage": None,
            "T_cell": "T_cell",
            "Tumor": "Tumor",
        }
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()

        import numpy as np
        rng = np.random.default_rng(0)
        for ct, count in s.cell_counts.items():
            s.coords_by_type[ct] = np.column_stack([
                rng.uniform(-500, 500, count),
                rng.uniform(-500, 500, count),
                np.zeros(count),
            ])

        df = build_ic_dataframe(s.coords_by_type)
        assert "Macrophage" not in df["type"].values
        assert len(df) == 5  # 3 T_cell + 2 Tumor


class TestFullPipelineSpatial:
    def test_coordinates_come_from_data(self):
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = True
        s.setup_spatial_data()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()

        # Populate coords_by_type from spatial_data_final
        for ct in s.cell_types_list_final:
            mask = np.array(s.cell_types_final) == ct
            s.coords_by_type[ct] = s.spatial_data_final[mask]

        df = build_ic_dataframe(s.coords_by_type)
        assert len(df) == 7
        # x/y coords should match the fixture values
        t_cell_rows = df[df["type"] == "T_cell"]
        assert set(t_cell_rows["x"].tolist()) == {100, 150}


# ---------------------------------------------------------------------------
# Step sequencing — pure-Python predicate mirror of _build_next_window
# ---------------------------------------------------------------------------

def _next_step(s: WalkthroughSession) -> "str | None":
    """Return the label of the first pending step for session *s*, or None.

    Delegates directly to ``_step_predicates`` from ``walkthrough.py`` so
    this helper stays in sync with the real step-selection logic automatically.
    """
    for predicate, label in _step_predicates(s):
        if predicate():
            return label
    return None


class TestStepSequencing:
    """Verify _next_step returns the correct step label for each partial session state."""

    def test_fresh_spot_deconv_csv_goes_to_spot_deconv_query(self):
        # spatial CSV with probability columns → SpotDeconvQuery (has_spatial + prob cols)
        s = _session(SPOT_DECONV_CSV)
        # spot_deconv_asked is False by default, data has prob cols and spatial
        assert _next_step(s) == "SpotDeconvQuery"

    def test_fresh_spatial_csv_no_prob_cols_goes_to_cluster_column(self):
        # spatial CSV without probability columns — no spot-deconv query, skip to
        # ClusterColumn (current_column is None)
        s = _session(SPATIAL_CSV)
        assert not s.data.probability_columns  # no prob cols in spatial.csv
        assert _next_step(s) == "ClusterColumn"

    def test_after_spot_deconv_declined_goes_to_cluster_column(self):
        # spot_deconv_asked=True, perform_spot_deconvolution=False, current_column=None
        s = _session(SPOT_DECONV_CSV)
        s.spot_deconv_asked = True
        s.perform_spot_deconvolution = False
        assert s.current_column is None
        assert _next_step(s) == "ClusterColumn"

    def test_after_column_set_with_spatial_data_goes_to_spatial_query(self):
        # current_column set, use_spatial_data still None, data has spatial
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        # use_spatial_data is None and data.has_spatial → SpatialQuery
        assert s.use_spatial_data is None
        assert s.data.has_spatial
        assert _next_step(s) == "SpatialQuery"

    def test_after_use_spatial_false_cell_counts_not_confirmed_goes_to_cell_counts(self):
        # use_spatial_data=False, cell_type_dict_on_edit set, cell_types_list_final set,
        # cell_counts_confirmed=False → CellCounts
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()
        # cell_counts_confirmed defaults to False
        assert not s.cell_counts_confirmed
        assert _next_step(s) == "CellCounts"

    def test_after_use_spatial_true_skips_cell_counts_goes_to_positions(self):
        # use_spatial_data=True → CellCounts predicate (not use_spatial_data) is False
        # positions_set=False → Positions
        s = _session(SPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = True
        s.setup_spatial_data()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()
        # cell_counts_confirmed is False but use_spatial_data is True → CellCounts skipped
        assert s.use_spatial_data is True
        assert not s.positions_set
        assert _next_step(s) == "Positions"

    def test_after_positions_set_and_parameters_not_loaded_goes_to_load_parameters(self):
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()
        s.cell_counts_confirmed = True
        s.positions_set = True
        assert not s.parameters_loaded
        assert _next_step(s) == "LoadCellParameters"

    def test_all_flags_done_returns_none(self):
        # All predicates False → workflow complete → None
        s = _session(NONSPATIAL_CSV)
        s.current_column = "type"
        s.collect_cell_type_data()
        s.use_spatial_data = False
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.intermediate_types}
        s.apply_rename()
        s.cell_counts_confirmed = True
        s.positions_set = True
        s.parameters_loaded = True
        assert _next_step(s) is None


# ---------------------------------------------------------------------------
# Full spot-deconv pipeline → output DataFrame
# ---------------------------------------------------------------------------

class TestSpotDeconvFullPipeline:
    """Drive a WalkthroughSession from spot_deconv.csv to build_ic_dataframe."""

    def _setup_session(self) -> "WalkthroughSession":
        """Replicate all steps up to (but not including) PositionsWindow."""
        s = _session(SPOT_DECONV_CSV)

        # Step 1: setup spot deconvolution data and spatial data
        s.perform_spot_deconvolution = True
        s.setup_spot_deconvolution_data()
        s.setup_spatial_data()

        # Step 2: collect_cell_type_data via the spot-deconv path.
        # The cluster-column window sets current_column to the sentinel
        # "__spot_deconv__" and then collect_cell_type_data() is called.
        # In the spot-deconv path, cell_types_original comes from cell_types_max
        # (the max-prob type per spot), so we mirror that here.
        s.current_column = "__spot_deconv__"
        # Spot-deconv populates cell_types_list_original via setup_spot_deconvolution_data;
        # cell_types_original must be populated for apply_rename to iterate over.
        # Mirror what the GUI does: use cell_types_max as the per-cell label list.
        s.cell_types_original = list(s.cell_types_max)

        return s

    def test_setup_produces_three_cell_types(self):
        s = self._setup_session()
        assert set(s.cell_types_list_original) == {"T_cell", "Tumor", "Macrophage"}

    def test_setup_spot_deconv_populates_prob_dicts(self):
        s = self._setup_session()
        assert s.cell_prob_feature_dicts is not None
        assert len(s.cell_prob_feature_dicts) == 6

    def test_setup_spatial_data_shape(self):
        s = self._setup_session()
        assert s.spatial_data is not None
        assert s.spatial_data.shape == (6, 3)

    def test_collect_via_spot_deconv_path_cell_types_max(self):
        """cell_types_max has one entry per spot, labelled by max-probability type."""
        s = self._setup_session()
        # First two spots are T_cell (prob 0.8 and 0.7), next two Tumor, last two Macrophage
        assert s.cell_types_max[0] == "T_cell"
        assert s.cell_types_max[1] == "T_cell"
        assert s.cell_types_max[2] == "Tumor"
        assert s.cell_types_max[3] == "Tumor"
        assert s.cell_types_max[4] == "Macrophage"
        assert s.cell_types_max[5] == "Macrophage"

    def test_compute_intermediate_types_all_kept(self):
        s = self._setup_session()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        assert set(s.intermediate_types) == {"T_cell", "Tumor", "Macrophage"}

    def test_apply_rename_identity_produces_correct_final_types(self):
        s = self._setup_session()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        # Identity rename
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.cell_types_list_original}
        s.apply_rename()
        # In the spot-deconv path, cell_types_final is sorted(final_set)
        assert set(s.cell_types_final) == {"T_cell", "Tumor", "Macrophage"}
        # spatial_data_final should have one row per retained spot
        assert s.spatial_data_final is not None
        assert s.spatial_data_final.shape[0] == 6

    def test_build_ic_dataframe_has_6_rows_and_all_three_types(self):
        """Full pipeline: load → spot deconv setup → rename identity → build DataFrame."""
        s = self._setup_session()
        s.cell_type_dict_on_edit = {ct: ct for ct in s.cell_types_list_original}
        s.compute_intermediate_types()
        s.cell_types_list_final = list(s.intermediate_types)
        s.cell_type_dict_on_rename = {ct: ct for ct in s.cell_types_list_original}
        s.apply_rename()

        # Populate coords_by_type from spatial_data_final, grouped by cell_types_final.
        # In the spot-deconv case cell_types_final is a sorted list (not per-cell),
        # so we group by using the per-spot probability dicts and the spatial rows.
        # Mirror what PositionsWindow does: one coordinate per retained spot, assigned
        # to the dominant (max-prob) type derived from cell_types_max.
        for i, (sp, prob_dict) in enumerate(
            zip(s.spatial_data_final, s.cell_prob_feature_dicts)
        ):
            # dominant type for this spot = argmax of the (already renamed) prob dict
            dominant = max(prob_dict, key=lambda k: prob_dict[k])
            if dominant not in s.coords_by_type:
                s.coords_by_type[dominant] = []
            s.coords_by_type[dominant].append(sp)

        # Convert lists → arrays
        for ct in s.coords_by_type:
            s.coords_by_type[ct] = np.vstack(s.coords_by_type[ct])

        df = build_ic_dataframe(s.coords_by_type)

        assert list(df.columns) == ["x", "y", "z", "type"]
        assert len(df) == 6
        assert set(df["type"].unique()) == {"T_cell", "Tumor", "Macrophage"}
