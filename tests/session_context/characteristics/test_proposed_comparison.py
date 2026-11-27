"""Comparațiile propuse păstrează sursele și incertitudinea."""

import unittest

from rdflib import Literal

import tests.session_context.characteristics.test_selection_graph as fixtures
import tests.session_context.characteristics.test_characteristic_selection as selection_fixtures

from session_context.characteristics.comparison import (
    characteristics_for_occurrence,
)
from session_context.characteristics.graph import (
    CTX,
    record_characteristic_selection,
)
from session_context.characteristics.proposed_comparison import (
    compare_proposed_characteristics,
)


class ProposedComparisonTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.SelectionGraphTest()
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()

        self.fixture = self.base.base
        self.context = self.base.context
        self.ontology = self.base.ontology
        self.a = self.fixture.a
        self.b = self.fixture.b
        self.c = self.fixture.c
        self.counter = 0

    def store(self, occurrence, frame_id, *, items=None, **changes):
        self.counter += 1
        analysis = self.context.observations.value(
            self.context.frame_iris[frame_id],
            CTX.observation,
            any=False,
        )
        analysis_id = self.context.observations.value(
            analysis, CTX.analysisId, any=False
        )

        provenance = self.base.provenance.model_copy(update={
            "frame_id": frame_id,
            "analysis_id": str(analysis_id),
            "population_graph_iri": (
                f"urn:test:population:comparison-{self.counter}"
            ),
        })
        if items is None:
            items = [
                self.fixture.interpretation(occurrence, **changes)
            ]

        proposal = self.fixture.proposal(
            self.fixture.appearance(occurrence, items)
        )
        return record_characteristic_selection(
            self.context,
            proposal,
            provenance=provenance,
            ontology=self.ontology,
        )

    def compare(self, left_record, right_record, *, right=None):
        return compare_proposed_characteristics(
            self.context,
            self.a,
            self.b if right is None else right,
            left_record_iri=left_record,
            right_record_iri=right_record,
            ontology=self.ontology,
        )

    def test_property_aligns_different_meanings_as_a_proposal(self):
        self.fixture.fixture._set_characteristics(
            self.b, ("colour", "blue", False)
        )
        property_iri = selection_fixtures.NS + "color"
        left = self.store(
            self.a,
            "frame-1",
            meaning="culoare",
            normalized_value="blue",
            property_iri=property_iri,
        )
        right = self.store(
            self.b,
            "frame-2",
            meaning="color",
            normalized_value="blue",
            property_iri=property_iri,
        )
        before = self.base.quads()

        result = self.compare(left, right)
        item = result.characteristics[0]

        self.assertEqual("proposal", result.status)
        self.assertEqual("same_proposed_value", item.status)
        self.assertEqual("property", item.key.reference_kind)
        self.assertEqual("albastru", item.left[0].observed.value)
        self.assertEqual("blue", item.right[0].observed.value)
        self.assertEqual(left, result.left_record_iri)
        self.assertEqual(right, result.right_record_iri)
        self.assertEqual(before, self.base.quads())
        self.assertEqual(0, len(self.context.identities))

    def test_different_values_remain_a_proposed_difference(self):
        left = self.store(self.a, "frame-1")
        right = self.store(self.b, "frame-2")

        result = self.compare(left, right)

        self.assertEqual(
            "different_proposed_values",
            result.characteristics[0].status,
        )
        self.assertEqual("proposal", result.status)
        self.assertEqual(0, len(self.context.identities))

    def test_entity_and_part_are_not_compared_as_the_same_target(self):
        left = self.store(self.a, "frame-1")
        right = self.store(
            self.b,
            "frame-2",
            target_kind="part",
            part_name="componentă laterală",
        )

        result = self.compare(left, right)

        self.assertEqual(2, len(result.characteristics))
        self.assertTrue(all(
            item.status == "unknown"
            and item.reason == "missing_counterpart"
            for item in result.characteristics
        ))

    def test_uncertain_observation_remains_unknown(self):
        left = self.store(self.a, "frame-1")
        right = self.store(self.c, "frame-3")

        result = self.compare(left, right, right=self.c)

        self.assertEqual("unknown", result.characteristics[0].status)
        self.assertEqual("uncertain", result.characteristics[0].reason)

    def test_missing_normalization_remains_unknown(self):
        left = self.store(self.a, "frame-1")
        right = self.store(
            self.b, "frame-2", normalized_value=None
        )

        result = self.compare(left, right)

        self.assertEqual("unknown", result.characteristics[0].status)
        self.assertEqual(
            "missing_normalized_value",
            result.characteristics[0].reason,
        )

    def test_state_or_unselected_traits_do_not_create_differences(self):
        for use in ("state", "not_selected"):
            with self.subTest(use=use):
                left = self.store(self.a, "frame-1")
                right = self.store(self.b, "frame-2", use=use)

                result = self.compare(left, right)
                item = result.characteristics[0]

                self.assertEqual("unknown", item.status)
                self.assertEqual(
                    "not_selected_for_comparison", item.reason
                )
                self.assertEqual(1, len(item.right))

    def test_unresolved_target_keeps_its_original_evidence(self):
        left = self.store(self.a, "frame-1")
        right = self.store(
            self.b,
            "frame-2",
            target_kind="unresolved",
            meaning=None,
            normalized_value=None,
            use="unresolved",
            uncertain=True,
        )

        result = self.compare(left, right)

        self.assertEqual(1, len(result.unresolved_right))
        self.assertEqual(
            "roșu", result.unresolved_right[0].observed.value
        )
        self.assertTrue(all(
            item.status == "unknown"
            for item in result.characteristics
        ))

    def test_equal_observations_with_conflicting_normalization_are_unknown(self):
        self.fixture.fixture._set_characteristics(
            self.b, ("culoare", "albastru", False)
        )
        left = self.store(
            self.a, "frame-1", normalized_value="blue"
        )
        right = self.store(
            self.b, "frame-2", normalized_value="red"
        )

        result = self.compare(left, right)

        self.assertEqual("unknown", result.characteristics[0].status)
        self.assertEqual(
            "conflicting_normalization",
            result.characteristics[0].reason,
        )

    def test_multiple_characteristics_with_the_same_meaning_are_ambiguous(self):
        self.fixture.fixture._set_characteristics(
            self.a,
            ("culoare zona 1", "albastru", False),
            ("culoare zona 2", "roșu", False),
        )
        sources = characteristics_for_occurrence(
            self.context, self.a
        )
        first = self.fixture.interpretation(
            self.a, meaning="culoare"
        )
        second = {
            **first,
            "source_characteristic_iri": str(sources[1].iri),
            "normalized_value": sources[1].value,
        }
        left = self.store(
            self.a, "frame-1", items=[first, second]
        )
        right = self.store(self.b, "frame-2")

        result = self.compare(left, right)
        item = result.characteristics[0]

        self.assertEqual("unknown", item.status)
        self.assertEqual("ambiguous_characteristics", item.reason)
        self.assertEqual(2, len(item.left))

    def test_wrong_record_or_modified_record_is_rejected(self):
        left = self.store(self.a, "frame-1")
        right = self.store(self.b, "frame-2")

        with self.assertRaises(ValueError):
            self.compare(right, right)

        self.context.dataset.graph(left).set((
            left, CTX.selectionStatus, Literal("accepted")
        ))

        with self.assertRaises(ValueError):
            self.compare(left, right)


if __name__ == "__main__":
    unittest.main()