"""Reading template files, and picking a starting template per cell type.

Template content is opaque to BIWT, so the fixtures hold deliberately non-XML
values: anything that round-trips proves BIWT is not interpreting it.
Pure Python — no Qt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biwt.core.templates import (
    DEFAULT_TEMPLATE_NAME,
    load_templates_from_file,
    matched_candidates,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATES_A = str(FIXTURES / "templates_a.toml")
TEMPLATES_B = str(FIXTURES / "templates_b.toml")


class TestLoadTemplatesFromFile:
    def test_reads_name_to_content_mapping(self):
        data = load_templates_from_file(TEMPLATES_A)
        assert set(data) == {"default", "Tumor", "Macrophage"}
        assert data["Tumor"] == "OPAQUE-A-TUMOR"

    def test_content_is_returned_verbatim(self):
        # Indentation and the trailing newline are part of the value; BIWT must
        # not tidy them, since the host receives what the file holds.  (The
        # newline directly after the opening \"\"\" is trimmed by TOML itself,
        # before BIWT ever sees the value.)
        assert load_templates_from_file(TEMPLATES_A)["default"] == (
            "    OPAQUE-A-DEFAULT\n"
        )

    def test_missing_file_raises(self):
        with pytest.raises(OSError):
            load_templates_from_file(str(FIXTURES / "no_such_templates.toml"))

    def test_empty_file_gives_empty_dict(self, tmp_path):
        path = tmp_path / "empty.toml"
        path.write_text("")
        assert load_templates_from_file(str(path)) == {}

    def test_malformed_toml_raises(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text('"Tumor" = ')
        with pytest.raises(Exception):
            load_templates_from_file(str(path))

    def test_duplicate_key_raises(self, tmp_path):
        path = tmp_path / "dupe.toml"
        path.write_text('"Tumor" = "one"\n"Tumor" = "two"\n')
        with pytest.raises(Exception):
            load_templates_from_file(str(path))

    def test_nested_table_value_raises_naming_the_key(self, tmp_path):
        # A '[section]' header nests everything after it, which is the usual way
        # a template file ends up with a non-string value.
        path = tmp_path / "nested.toml"
        path.write_text('"Tumor" = "ok"\n\n[Macrophage]\ncycle = "x"\n')
        with pytest.raises(ValueError) as exc:
            load_templates_from_file(str(path))
        assert "Macrophage" in str(exc.value)
        assert "Tumor" not in str(exc.value)

    def test_int_value_raises(self, tmp_path):
        path = tmp_path / "int.toml"
        path.write_text('"Tumor" = 42\n')
        with pytest.raises(ValueError) as exc:
            load_templates_from_file(str(path))
        assert "Tumor (int)" in str(exc.value)

class TestMatchedCandidates:
    """Which candidate names a cell type.  Nothing about baselines or fallbacks.

    ``matched_candidates`` returns ``None`` when nothing matched; what to do then
    depends on which source supplies the ``default`` baseline, which only the
    cell-templates window knows.  Its tests cover that half.
    """

    NAMES = ["default", "Tumor", "Macrophage"]

    def test_exact_name_match_is_chosen(self):
        assert matched_candidates(["Tumor"], self.NAMES) == {"Tumor": "Tumor"}

    def test_match_is_case_insensitive(self):
        out = matched_candidates(["T_cell"], ["t_cell", "default"])
        assert out == {"T_cell": "t_cell"}

    def test_fuzzy_match_is_chosen(self):
        out = matched_candidates(["Macrophages"], self.NAMES)
        assert out == {"Macrophages": "Macrophage"}

    def test_a_name_matching_nothing_is_none(self):
        # Not "default": the baseline is the caller's decision, not this one's.
        assert matched_candidates(["Neutrophil"], self.NAMES) == {"Neutrophil": None}

    def test_a_duplicated_name_is_returned_once(self):
        out = matched_candidates(["Tumor"], ["Tumor", "Tumor", "default"])
        assert out == {"Tumor": "Tumor"}

    def test_no_candidates_at_all_gives_none_for_every_type(self):
        assert matched_candidates(["Tumor", "T_cell"], []) == {
            "Tumor": None, "T_cell": None,
        }

    def test_no_cell_types_gives_empty_mapping(self):
        assert matched_candidates([], self.NAMES) == {}

    def test_result_is_independent_of_candidate_order(self):
        types = ["Tumor", "Neutrophil"]
        forward = matched_candidates(types, ["Tumor", "Tumour", "default"])
        reverse = matched_candidates(types, ["default", "Tumour", "Tumor"])
        assert forward == reverse

    def test_a_digit_distinguished_name_is_not_chosen(self):
        out = matched_candidates(["M1 Macrophage"], ["M2 Macrophage", "default"])
        assert out == {"M1 Macrophage": None}

    def test_host_predicate_is_honored(self):
        out = matched_candidates(
            ["M1 Macrophage"], ["M2 Macrophage"], matches=lambda a, b: True
        )
        assert out == {"M1 Macrophage": "M2 Macrophage"}

    def test_every_cell_type_appears_in_the_result(self):
        types = ["Tumor", "Neutrophil", "Macrophage"]
        assert set(matched_candidates(types, self.NAMES)) == set(types)

    def test_the_baseline_name_is_still_named_here(self):
        # The window needs the convention; only the choosing moved.
        assert DEFAULT_TEMPLATE_NAME == "default"


class TestHostNamesRankFirst:
    """Quality first, then provenance.

    ``host_names`` are tried before the templates *within* each match tier, so the
    host wins where both name a type equally well — but a tier is never skipped, so
    an exact template match still beats a merely similar host name.
    """

    def test_a_host_name_matches_when_no_template_does(self):
        assert matched_candidates(["Tumor"], [], host_names=["Tumor"]) == {
            "Tumor": "Tumor",
        }

    def test_host_names_and_templates_share_one_pool(self):
        out = matched_candidates(
            ["Tumor", "Macrophage"], ["Macrophage"], host_names=["Tumor"],
        )
        assert out == {"Tumor": "Tumor", "Macrophage": "Macrophage"}

    def test_the_host_wins_an_equally_exact_match(self):
        # The case that prompted the tiering: 'tumor' and 'Tumor' are both
        # case-insensitive exact matches, so the host's must win.
        out = matched_candidates(["tumor"], ["Tumor"], host_names=["tumor"])
        assert out == {"tumor": "tumor"}

    def test_the_host_wins_even_spelled_differently(self):
        out = matched_candidates(["tumor"], ["tumor"], host_names=["Tumor"])
        assert out == {"tumor": "Tumor"}

    def test_an_exact_template_beats_a_similar_host_name(self):
        out = matched_candidates(["Tumor"], ["Tumor"], host_names=["Tumour"])
        assert out == {"Tumor": "Tumor"}

    def test_the_host_wins_the_similarity_tier_too(self):
        out = matched_candidates(["Tumors"], ["Tumour"], host_names=["Tumor"])
        assert out == {"Tumors": "Tumor"}

    def test_omitting_host_names_changes_nothing(self):
        assert matched_candidates(["Tumor"], ["Tumor"]) == (
            matched_candidates(["Tumor"], ["Tumor"], host_names=None)
        )

    def test_the_host_predicate_governs_host_names_too(self):
        out = matched_candidates(["M1 Macrophage"], [], host_names=["M2 Macrophage"])
        assert out == {"M1 Macrophage": None}          # digit gate rejects it
        out = matched_candidates(
            ["M1 Macrophage"], [], host_names=["M2 Macrophage"],
            matches=lambda a, b: True,
        )
        assert out == {"M1 Macrophage": "M2 Macrophage"}
