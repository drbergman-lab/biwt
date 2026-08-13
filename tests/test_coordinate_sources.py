"""Which numbers in a file are coordinates, and what happens to them.

Qt-free. Four rules, each of which a real file had already broken:

* an obsm entry is coordinates only if it is 2 or 3 columns wide,
* the y-flip belongs to ``imagerow``/``imagecol`` and to nothing else,
* the data→host factor applies to z only when the file supplied z,
* a probability outside ``[0, inf)`` is worth zero, not a deleted cell type.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from biwt.core.data_loader import _find_probability_columns, clamp_probabilities
from biwt.core.domain import (
    build_obs_coords,
    data_has_z,
    infer_domain,
    resolve_obs_coord_cols,
    _find_spatial_key,
)
from biwt.types import DomainSource


class TestWhichObsmEntryIsCoordinates:
    """A name alone is not enough — the array has to be the right shape."""

    def test_a_connectivity_matrix_is_not_coordinates(self):
        # spatial_connectivities is (N, N); reading its first three columns as
        # x/y/z produced a plausible-looking domain out of adjacency weights.
        obsm = {"X_umap": np.zeros((6, 2)),
                "spatial_connectivities": np.arange(36.0).reshape(6, 6)}
        assert _find_spatial_key(obsm) is None

    def test_a_wide_embedding_named_spatial_is_rejected(self):
        assert _find_spatial_key({"spatial_pca": np.zeros((6, 50))}) is None

    def test_a_single_column_named_spatial_is_rejected(self):
        assert _find_spatial_key({"spatial": np.zeros((6, 1))}) is None

    @pytest.mark.parametrize("width", [2, 3])
    def test_two_and_three_columns_are_accepted(self, width):
        assert _find_spatial_key({"spatial": np.zeros((6, width))}) == "spatial"

    def test_a_named_priority_key_of_the_wrong_shape_does_not_win(self):
        """The priority list used to return on the name before looking."""
        obsm = {"spatial": np.zeros((6, 9)), "spatial_coords": np.zeros((6, 2))}
        assert _find_spatial_key(obsm) == "spatial_coords"

    def test_a_ragged_entry_is_skipped_rather_than_raising(self):
        assert _find_spatial_key({"spatial": "not an array at all"}) is None

    def test_good_obs_columns_win_over_a_bogus_obsm_key(self):
        """The consequence that mattered: a rejected obsm key must fall through.

        Before the shape check the connectivity matrix was chosen and the real
        coordinates in obs were never looked at.
        """
        # Six cells, so the (N, N) matrix is wider than a coordinate array. With
        # two or three cells the two are the same shape and nothing can tell them
        # apart — an accepted limit of a shape check.
        obs = pd.DataFrame({"imagecol": np.linspace(0, 30, 6),
                            "imagerow": np.linspace(0, 30, 6),
                            "type": list("ABCDEF")})
        obsm = {"spatial_connectivities": np.arange(36.0).reshape(6, 6)}
        d = infer_domain(preferred=None, obs=obs, obsm=obsm)
        assert d.source == DomainSource.DATA
        assert (d.xmin, d.xmax) == (0.0, 30.0)


class TestTheYFlipBelongsToImageColumns:
    """Flip iff the columns are imagerow/imagecol, wherever they live."""

    def test_image_columns_are_flipped(self):
        obs = pd.DataFrame({"imagecol": [0.0, 10.0], "imagerow": [0.0, 30.0]})
        x, y, z, is_image = resolve_obs_coord_cols(list(obs.columns))
        assert is_image
        coords = build_obs_coords(obs, x, y, z, is_image)
        # Image rows increase downward, so the largest row becomes the smallest y.
        assert list(coords[:, 1]) == [30.0, 0.0]

    def test_plain_xy_columns_are_not_flipped(self):
        obs = pd.DataFrame({"x": [0.0, 10.0], "y": [0.0, 30.0]})
        x, y, z, is_image = resolve_obs_coord_cols(list(obs.columns))
        assert not is_image
        assert list(build_obs_coords(obs, x, y, z, is_image)[:, 1]) == [0.0, 30.0]

    def test_xy_columns_win_over_image_columns(self):
        obs = pd.DataFrame({"x": [1.0], "y": [2.0],
                            "imagecol": [3.0], "imagerow": [4.0]})
        assert resolve_obs_coord_cols(list(obs.columns)) == ("x", "y", None, False)

    def test_an_obsm_array_is_never_flipped(self):
        """An obsm array has no column names, so the rule cannot fire on it.

        Its numbers are taken as given — which is why a file offering both
        routes is not expected to agree with itself.
        """
        coords = np.array([[0.0, 0.0], [10.0, 30.0]])
        d = infer_domain(preferred=None, obs=None, obsm={"spatial": coords})
        assert (d.ymin, d.ymax) == (0.0, 30.0)


class TestWhetherTheFileSuppliedZ:
    def test_three_column_obsm_has_z(self):
        assert data_has_z(obsm={"spatial": np.zeros((4, 3))}) is True

    def test_two_column_obsm_has_no_z(self):
        assert data_has_z(obsm={"spatial": np.zeros((4, 2))}) is False

    def test_a_z_column_in_obs_counts(self):
        obs = pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0]})
        assert data_has_z(obs=obs, obsm={}) is True

    def test_xy_columns_alone_do_not(self):
        obs = pd.DataFrame({"x": [1.0], "y": [2.0]})
        assert data_has_z(obs=obs, obsm={}) is False

    def test_image_columns_have_no_z_axis(self):
        obs = pd.DataFrame({"imagecol": [1.0], "imagerow": [2.0]})
        assert data_has_z(obs=obs, obsm={}) is False

    def test_nothing_at_all_has_no_z(self):
        assert data_has_z(obs=None, obsm=None) is False

    def test_obsm_is_consulted_before_obs_just_as_infer_domain_does(self):
        """The two must not disagree, or z is scaled against the wrong axis."""
        obs = pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0]})
        obsm = {"spatial": np.zeros((1, 2))}
        assert data_has_z(obs=obs, obsm=obsm) is False
        assert infer_domain(preferred=None, obs=obs, obsm=obsm).zmin == -10.0


class TestScalingZ:
    """The factor converts data units; a synthesized slab is not in data units."""

    @staticmethod
    def _domain():
        from biwt.types import DomainSpec
        return DomainSpec(xmin=0, xmax=10, ymin=0, ymax=20, zmin=-4, zmax=4)

    def test_a_real_z_is_scaled_with_x_and_y(self):
        from biwt.gui.walkthrough import _scale_domain
        d = _scale_domain(self._domain(), 3.0, scale_z=True)
        assert (d.xmax, d.ymax, d.zmin, d.zmax) == (30.0, 60.0, -12.0, 12.0)

    def test_a_synthesized_z_is_left_alone(self):
        from biwt.gui.walkthrough import _scale_domain
        d = _scale_domain(self._domain(), 3.0, scale_z=False)
        assert (d.xmax, d.ymax, d.zmin, d.zmax) == (30.0, 60.0, -4.0, 4.0)

    def test_not_scaling_is_the_default(self):
        from biwt.gui.walkthrough import _scale_domain
        assert _scale_domain(self._domain(), 3.0).zmax == 4.0


class TestProbabilitiesOutsideTheRange:
    """Clamp to [0, inf) rather than discarding the cell type."""

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, -1.0, -0.001])
    def test_every_out_of_range_value_becomes_zero(self, bad):
        assert list(clamp_probabilities([0.5, bad])) == [0.5, 0.0]

    def test_values_in_range_are_untouched(self):
        assert list(clamp_probabilities([0.0, 0.25, 7.0])) == [0.0, 0.25, 7.0]

    def test_one_nan_no_longer_deletes_the_cell_type(self):
        obs = pd.DataFrame({
            "A_probability": [np.nan, 0.9],      # used to drop A entirely
            "B_probability": [0.5, 0.1],
        })
        assert _find_probability_columns(obs) == ["A_probability", "B_probability"]

    def test_a_column_with_no_surviving_mass_is_dropped(self):
        obs = pd.DataFrame({"A_probability": [0.0, np.nan, -3.0],
                            "B_probability": [0.5, 0.5, 0.5]})
        assert _find_probability_columns(obs) == ["B_probability"]

    def test_a_nan_no_longer_wins_the_per_spot_maximum(self):
        """``argmax`` returns the NaN's index, so the bad column was declared the
        spot's dominant type and the NaN reached the weights."""
        import numpy as np

        from biwt.gui.walkthrough import WalkthroughSession
        from biwt.core.data_loader import BiwtData

        obs = pd.DataFrame({
            "A_probability": [np.nan, 0.1],
            "B_probability": [0.4, 0.9],
        })
        s = WalkthroughSession.__new__(WalkthroughSession)
        s.data = BiwtData(obs=obs, probability_columns=["A_probability",
                                                       "B_probability"])
        WalkthroughSession.setup_spot_deconvolution_data(s)

        assert s.cell_types_max == ["B", "B"]
        assert s.cell_prob_feature_dicts[0] == {"A": 0.0, "B": 0.4}
        assert all(np.isfinite(v) for d in s.cell_prob_feature_dicts
                   for v in d.values())


class TestPickingAnObjectFromAnRWorkspace:
    """``base::ls()`` sorts, so the first name was an alphabetical accident.

    Driven against a stub environment: the picker only ever asks an object for
    its ``rclass``, so this needs no R and runs everywhere.
    """

    class _Env:
        """Stands in for an R environment: name → object with an ``rclass``."""

        def __init__(self, **objects):
            self._objects = {
                name: type("RObj", (), {"rclass": (cls,)})()
                for name, cls in objects.items()
            }

        def __getitem__(self, name):
            return self._objects[name]

        def names(self):
            return sorted(self._objects)          # as base::ls() returns them

    def _pick(self, **objects):
        from biwt.core.data_loader import _pick_workspace_object

        env = self._Env(**objects)
        return _pick_workspace_object(env, env.names(), "ws.rda")

    def test_the_dataset_wins_over_an_alphabetically_earlier_object(self):
        # The reported shape: "annotations" sorts first and used to be imported.
        assert self._pick(annotations="data.frame", seurat_obj="Seurat") == "seurat_obj"

    def test_a_lone_dataset_is_used_whatever_it_is_called(self):
        assert self._pick(zzz="SingleCellExperiment") == "zzz"

    def test_a_spatial_experiment_counts_as_a_dataset(self):
        assert self._pick(notes="character", sp="SpatialExperiment") == "sp"

    def test_no_dataset_says_so_and_lists_what_was_there(self):
        from biwt.core.data_loader import LoadError

        with pytest.raises(LoadError) as e:
            self._pick(annotations="data.frame", counts="matrix")
        msg = str(e.value)
        assert "no Seurat or SingleCellExperiment" in msg
        assert "annotations" in msg and "counts" in msg

    def test_two_datasets_are_refused_rather_than_guessed(self):
        from biwt.core.data_loader import LoadError

        with pytest.raises(LoadError) as e:
            self._pick(first="Seurat", second="SingleCellExperiment")
        msg = str(e.value)
        assert "more than one dataset" in msg
        assert "first" in msg and "second" in msg
        # Says what to do about it, not just what went wrong.
        assert "saveRDS" in msg or "save(" in msg

    def test_an_object_that_cannot_be_inspected_is_skipped(self):
        from biwt.core.data_loader import _pick_workspace_object

        class Env:
            def __getitem__(self, name):
                if name == "broken":
                    raise RuntimeError("cannot materialise")
                return type("RObj", (), {"rclass": ("Seurat",)})()

        assert _pick_workspace_object(Env(), ["broken", "obj"], "ws.rda") == "obj"
