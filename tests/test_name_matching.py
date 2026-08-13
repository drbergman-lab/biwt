"""Whether two strings name the same cell type.

The host owns that decision (``BiwtInput.name_matches``); these tests pin the
default BIWT ships and the one selection routine both callers go through.
Pure Python — no Qt.
"""
from __future__ import annotations

import pytest

from biwt.core.cell_types import (
    DEFAULT_NAME_MATCH_CUTOFF,
    alpha_key,
    best_match,
    default_name_matches,
    suggest_name_mappings,
)


# Pairs whose similarity clears the 0.85 cutoff but which are different cell
# types, told apart only by their digits.  Without the digit rule every one of
# these would match (scores 0.92, 0.87, 0.90 and 0.86 respectively).
DIGIT_DISTINGUISHED = [
    ("M1 Macrophage", "M2 Macrophage"),
    ("M0 Macrophage", "M1 Macrophage"),
    ("CD4 T Cell", "CD8 T Cell"),
    ("Layer 2", "Layer 6"),
]

# Spelling variations of one type, which must still match.
SAME_TYPE = [
    ("Fibroblast", "Fibroblasts"),
    ("Tumor", "tumour"),
    ("T_cell", "T_Cell"),
]


class TestDefaultNameMatches:
    def test_identical_names_match(self):
        assert default_name_matches("Tumor", "Tumor")

    def test_case_is_ignored(self):
        assert default_name_matches("TUMOR", "tumor")

    def test_symmetric(self):
        for a, b in DIGIT_DISTINGUISHED + SAME_TYPE:
            assert default_name_matches(a, b) == default_name_matches(b, a)

    @pytest.mark.parametrize("a,b", DIGIT_DISTINGUISHED)
    def test_differing_digits_never_match(self, a, b):
        assert not default_name_matches(a, b)

    @pytest.mark.parametrize("a,b", SAME_TYPE)
    def test_spelling_variations_match(self, a, b):
        assert default_name_matches(a, b)

    def test_equal_digits_still_compared_by_similarity(self):
        # Same digit run, so the digit rule abstains and similarity decides.
        assert default_name_matches("M1 Macrophage", "M1 Macrophages")
        assert not default_name_matches("M1 Macrophage", "M1 Fibroblast")

    def test_digits_must_agree_in_order_and_count(self):
        assert not default_name_matches("Layer 2 3", "Layer 3 2")
        assert not default_name_matches("Layer 2", "Layer 2 2")

    def test_unrelated_names_do_not_match(self):
        assert not default_name_matches("Tumor", "Epithelial Tumor")

    def test_non_numeric_qualifiers_are_a_known_gap(self):
        # Documented limitation, not an oversight: these hold the same digits
        # (1, 137, 8) and differ only by hi/lo, so similarity (0.92) accepts
        # them.  A host curating names of this shape supplies its own predicate.
        assert default_name_matches(
            "PD-1hi CD137lo CD8 T Cell", "PD-1lo CD137lo CD8 T Cell"
        )

    def test_a_higher_cutoff_narrows_matches(self):
        assert default_name_matches("Tumor", "tumour")
        assert not default_name_matches("Tumor", "tumour", cutoff=0.95)

    def test_default_cutoff_constant_is_the_signature_default(self):
        assert DEFAULT_NAME_MATCH_CUTOFF == 0.85


class TestBestMatch:
    def test_exact_match_wins_over_a_similar_candidate(self):
        # "Fibroblasts" would match "Fibroblast" fuzzily and sorts first.
        assert best_match("Fibroblasts", ["Fibroblast", "Fibroblasts"]) == "Fibroblasts"

    def test_exact_match_is_case_insensitive(self):
        assert best_match("t_cell", ["Macrophage", "T_cell"]) == "T_cell"

    def test_falls_back_to_a_fuzzy_match(self):
        assert best_match("Fibroblasts", ["Macrophage", "Fibroblast"]) == "Fibroblast"

    def test_none_when_nothing_matches(self):
        assert best_match("Tumor", ["Macrophage", "Fibroblast"]) is None

    def test_none_for_no_candidates(self):
        assert best_match("Tumor", []) is None

    def test_ties_resolve_in_sorted_order_regardless_of_input_order(self):
        # Both candidates match "Fibroblast"; the sorted-first one wins either way.
        forward = best_match("Fibroblast", ["Fibroblasts", "Fibroblastic"])
        reverse = best_match("Fibroblast", ["Fibroblastic", "Fibroblasts"])
        assert forward == reverse == "Fibroblastic"

    def test_host_predicate_replaces_the_default_permissively(self):
        # The default would reject this outright (differing digits).
        assert best_match(
            "M1 Macrophage", ["M2 Macrophage"], matches=lambda a, b: True
        ) == "M2 Macrophage"

    def test_host_predicate_replaces_the_default_restrictively(self):
        # A never-match predicate cannot suppress an exact match...
        assert best_match("Tumor", ["Tumor"], matches=lambda a, b: False) == "Tumor"
        # ...but nothing else survives it.
        assert best_match("Tumor", ["tumour"], matches=lambda a, b: False) is None

    def test_host_predicate_is_asked_about_every_candidate(self):
        asked = []

        def spy(a, b):
            asked.append((a, b))
            return False

        best_match("Tumor", ["b_type", "a_type"], matches=spy)
        assert asked == [("Tumor", "a_type"), ("Tumor", "b_type")]


class TestSuggestNameMappings:
    def test_exact_match_is_suggested(self):
        out = suggest_name_mappings(["Tumor"], ["Macrophage", "Tumor"])
        assert out == {"Tumor": "Tumor"}

    def test_case_insensitive_exact_match_is_suggested(self):
        out = suggest_name_mappings(["tumor"], ["Tumor"])
        assert out == {"tumor": "Tumor"}

    def test_unmatched_label_maps_to_none(self):
        out = suggest_name_mappings(["Neutrophil"], ["Macrophage", "Tumor"])
        assert out == {"Neutrophil": None}

    def test_containment_alone_is_no_longer_a_match(self):
        # The old rule suggested any host name contained in the label (or the
        # reverse), so "T" or "Tumor" matched "Epithelial Tumor".  Similarity
        # replaces that: 0.48 and 0.15 are far below the cutoff.
        out = suggest_name_mappings(["Epithelial Tumor"], ["Tumor", "T"])
        assert out == {"Epithelial Tumor": None}

    def test_digit_distinguished_host_name_is_not_suggested(self):
        out = suggest_name_mappings(["M1 Macrophage"], ["M2 Macrophage"])
        assert out == {"M1 Macrophage": None}

    def test_host_predicate_is_honored(self):
        out = suggest_name_mappings(
            ["M1 Macrophage"], ["M2 Macrophage"], matches=lambda a, b: True
        )
        assert out == {"M1 Macrophage": "M2 Macrophage"}

    def test_every_label_appears_in_the_result(self):
        labels = ["Tumor", "Neutrophil", "Macrophage"]
        out = suggest_name_mappings(labels, ["Tumor"])
        assert set(out) == set(labels)


class TestAlphaKey:
    """Names are shown to people, so they sort AaBbCc — not ABCabc."""

    def test_case_does_not_file_lowercase_names_last(self):
        names = ["Stellate", "myCAF", "Fibroblast", "iCAF", "B cell"]
        assert sorted(names, key=alpha_key) == [
            "B cell", "Fibroblast", "iCAF", "myCAF", "Stellate"
        ]

    def test_plain_sorted_is_what_this_replaces(self):
        # The behavior being fixed: capitals ahead of everything lowercase.
        names = ["Stellate", "myCAF", "iCAF"]
        assert sorted(names) == ["Stellate", "iCAF", "myCAF"]
        assert sorted(names, key=alpha_key) == ["iCAF", "myCAF", "Stellate"]

    def test_names_differing_only_in_case_have_a_stable_order(self):
        assert sorted(["cd8", "CD8"], key=alpha_key) == ["CD8", "cd8"]
        assert sorted(["CD8", "cd8"], key=alpha_key) == ["CD8", "cd8"]

    def test_a_template_library_sorts_the_way_a_reader_expects(self):
        names = ["default", "Macrophage", "t_cell", "Tumor"]
        assert sorted(names, key=alpha_key) == names
