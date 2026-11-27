"""Selecția păstrează sursele, modificările și incertitudinea."""

import unittest

from pydantic import ValidationError
from rdflib import Graph

import test_session_identity as fixtures
from session_context.characteristic_selection import (
    CharacteristicSelectionProposal,
    check_selection_proposal,
)
from session_context.comparison import characteristics_for_occurrence


NS = "https://example.test/selection#"

ONTOLOGY = """
@prefix ex: <https://example.test/selection#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

ex:Item a owl:Class .
ex:color a owl:DatatypeProperty .
"""


class CharacteristicSelectionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SessionIdentityTest()
        self.fixture.setUp()
        self.context = self.fixture.context
        self.a = self.fixture.a
        self.b = self.fixture.b
        self.c = self.fixture.c
        self.ontology = Graph().parse(
            data=ONTOLOGY,
            format="turtle",
        )

    def interpretation(self, occurrence, **changes):
        source = characteristics_for_occurrence(
            self.context,
            occurrence,
        )[0]

        data = {
            "source_characteristic_iri": str(source.iri),
            "meaning": source.name,
            "normalized_value": source.value,
            "target_kind": "entity",
            "part_name": None,
            "use": "comparison_and_state",
            "reason": (
                "Trăsătură observată, utilă comparației "
                "și descrierii stării."
            ),
            "uncertain": source.uncertain is not False,
            "property_iri": None,
            "ontology_reference_iris": [],
        }
        data.update(changes)
        return data

    def appearance(self, occurrence, characteristics=None):
        return {
            "occurrence_iri": str(occurrence),
            "characteristics": (
                [self.interpretation(occurrence)]
                if characteristics is None
                else characteristics
            ),
        }

    def proposal(self, *appearances):
        return CharacteristicSelectionProposal.model_validate({
            "appearances": list(appearances),
        })

    def check(self, proposal, expected):
        return check_selection_proposal(
            proposal,
            context=self.context,
            expected_occurrences=expected,
            ontology=self.ontology,
        )

    def test_checked_result_remains_a_proposal_without_graph_changes(self):
        proposal = self.proposal(self.appearance(self.a))
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        result = self.check(proposal, (self.a,))

        self.assertIs(proposal, result)
        self.assertEqual("proposal", result.status)
        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

    def test_different_observed_values_can_both_be_selected(self):
        proposal = self.proposal(
            self.appearance(self.a),
            self.appearance(self.b),
        )

        result = self.check(proposal, (self.a, self.b))

        values = {
            appearance.characteristics[0].normalized_value
            for appearance in result.appearances
        }

        self.assertEqual({"albastru", "roșu"}, values)
        self.assertTrue(all(
            appearance.characteristics[0].use
            == "comparison_and_state"
            for appearance in result.appearances
        ))

    def test_missing_or_duplicate_appearance_is_rejected(self):
        row = self.appearance(self.a)

        for rows in ((), (row, row)):
            with self.subTest(rows=rows):
                proposal = self.proposal(*rows)

                with self.assertRaises(ValueError):
                    self.check(proposal, (self.a,))

    def test_missing_or_duplicate_characteristic_is_rejected(self):
        item = self.interpretation(self.a)

        for items in ([], [item, item]):
            with self.subTest(items=items):
                proposal = self.proposal(
                    self.appearance(self.a, items)
                )

                with self.assertRaises(ValueError):
                    self.check(proposal, (self.a,))

    def test_characteristic_from_another_appearance_is_rejected(self):
        proposal = self.proposal(
            self.appearance(
                self.a,
                [self.interpretation(self.b)],
            )
        )

        with self.assertRaises(ValueError):
            self.check(proposal, (self.a,))

    def test_unknown_or_wrong_kind_of_ontology_reference_is_rejected(self):
        invalid = (
            {"property_iri": NS + "missing"},
            {"property_iri": NS + "Item"},
            {"ontology_reference_iris": [NS + "missing"]},
        )

        for changes in invalid:
            with self.subTest(changes=changes):
                proposal = self.proposal(
                    self.appearance(
                        self.a,
                        [self.interpretation(self.a, **changes)],
                    )
                )

                with self.assertRaises(ValueError):
                    self.check(proposal, (self.a,))

        valid = self.proposal(
            self.appearance(
                self.a,
                [self.interpretation(
                    self.a,
                    property_iri=NS + "color",
                    ontology_reference_iris=[NS + "color"],
                )],
            )
        )
        self.check(valid, (self.a,))

    def test_source_uncertainty_cannot_be_removed(self):
        proposal = self.proposal(
            self.appearance(
                self.c,
                [self.interpretation(
                    self.c,
                    uncertain=False,
                )],
            )
        )

        with self.assertRaises(ValueError):
            self.check(proposal, (self.c,))

    def test_part_and_unresolved_interpretations_require_consistency(self):
        invalid = (
            {"target_kind": "part", "part_name": None},
            {"target_kind": "entity", "part_name": "mâner"},
            {"use": "unresolved", "uncertain": False},
            {"meaning": None},
        )

        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    self.proposal(
                        self.appearance(
                            self.a,
                            [self.interpretation(self.a, **changes)],
                        )
                    )

        with self.assertRaises(ValidationError):
            CharacteristicSelectionProposal.model_validate({
                "status": "accepted",
                "appearances": [],
            })

    def test_appearance_without_characteristics_keeps_empty_selection(self):
        self.fixture._set_characteristics(self.a)

        proposal = self.proposal(
            self.appearance(self.a, [])
        )

        result = self.check(proposal, (self.a,))

        self.assertEqual(
            (),
            result.appearances[0].characteristics,
        )


if __name__ == "__main__":
    unittest.main()