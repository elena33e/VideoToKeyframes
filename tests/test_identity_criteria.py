"""Evaluarea criteriilor păstrează diferențele și incertitudinea."""

import unittest

from pydantic import ValidationError
from rdflib import URIRef

from session_context.comparison import (
    CharacteristicComparison,
    CharacteristicEvidence,
    OccurrenceComparison,
)
from session_context.identity_criteria import (
    IdentityCriteria,
    assess_identity_characteristics,
)


def make_criteria(**changes):
    fields = {
        "criteria_id": "test-criteria",
        "version": "1",
        "scope_description": "Entitățile din scenariul de test.",
        "justification": "Criterii explicite pentru acest scenariu.",
        "validated_by": "test-reviewer",
        "characteristics": ("a", "b"),
        "required_characteristics": ("a",),
    }
    fields.update(changes)
    return IdentityCriteria(**fields)


def row(name, status):
    left = CharacteristicEvidence(
        iri=URIRef(f"urn:test:left:{name}"),
        name=name,
        value="value-1",
        uncertain=False,
    )

    right = (
        ()
        if status == "unknown"
        else (
            CharacteristicEvidence(
                iri=URIRef(f"urn:test:right:{name}"),
                name=name,
                value=(
                    "value-2"
                    if status == "different"
                    else "value-1"
                ),
                uncertain=False,
            ),
        )
    )

    return CharacteristicComparison(
        name=name,
        left=(left,),
        right=right,
        status=status,
        reason={
            "unchanged": "same_value",
            "different": "different_values",
            "unknown": "missing",
        }[status],
    )


def comparison(*rows):
    return OccurrenceComparison(
        left_occurrence_iri=URIRef("urn:test:left"),
        right_occurrence_iri=URIRef("urn:test:right"),
        characteristics=rows,
    )


class IdentityCriteriaTest(unittest.TestCase):
    def test_concordance_preserves_criteria_and_original_evidence(self):
        criteria = make_criteria()
        source = comparison(
            row("a", "unchanged"),
            row("b", "unchanged"),
        )

        result = assess_identity_characteristics(
            source,
            criteria=criteria,
        )

        self.assertEqual("consistent", result.status)
        self.assertIs(criteria, result.criteria)
        self.assertIs(source, result.comparison)

    def test_unknown_required_characteristic_blocks_concordance(self):
        result = assess_identity_characteristics(
            comparison(
                row("a", "unknown"),
                row("b", "unchanged"),
            ),
            criteria=make_criteria(),
        )

        self.assertEqual("insufficient_evidence", result.status)
        self.assertEqual(
            ("a",),
            result.unknown_required_characteristics,
        )
        self.assertEqual((), result.different_characteristics)

    def test_unknown_optional_characteristic_is_not_a_difference(self):
        result = assess_identity_characteristics(
            comparison(
                row("a", "unchanged"),
                row("b", "unknown"),
            ),
            criteria=make_criteria(),
        )

        self.assertEqual("consistent", result.status)
        self.assertEqual((), result.different_characteristics)

    def test_optional_difference_is_retained_with_missing_required_data(self):
        result = assess_identity_characteristics(
            comparison(
                row("a", "unknown"),
                row("b", "different"),
            ),
            criteria=make_criteria(),
        )

        self.assertEqual("difference_detected", result.status)
        self.assertEqual(("b",), result.different_characteristics)
        self.assertEqual(
            ("a",),
            result.unknown_required_characteristics,
        )

    def test_names_use_normalized_exact_matching(self):
        criteria = make_criteria(
            characteristics=("  A  ", "B"),
            required_characteristics=("a",),
        )

        result = assess_identity_characteristics(
            comparison(
                row("a", "unchanged"),
                row("b", "unchanged"),
            ),
            criteria=criteria,
        )

        self.assertEqual(("a", "b"), criteria.characteristics)
        self.assertEqual("consistent", result.status)

    def test_invalid_criteria_are_rejected(self):
        invalid = (
            {"characteristics": ()},
            {"required_characteristics": ()},
            {"characteristics": ("a", " A ")},
            {"required_characteristics": ("a", " A ")},
            {"required_characteristics": ("c",)},
            {"validated_by": "   "},
        )

        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    make_criteria(**changes)

    def test_incomplete_extra_or_duplicate_comparison_is_rejected(self):
        invalid = (
            comparison(row("a", "unchanged")),
            comparison(
                row("a", "unchanged"),
                row("b", "unchanged"),
                row("c", "unchanged"),
            ),
            comparison(
                row("a", "unchanged"),
                row(" A ", "unchanged"),
                row("b", "unchanged"),
            ),
        )

        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    assess_identity_characteristics(
                        source,
                        criteria=make_criteria(),
                    )


if __name__ == "__main__":
    unittest.main()