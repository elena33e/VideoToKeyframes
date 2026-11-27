"""Evaluarea cadrelor păstrează alternativele și criteriile aplicate."""

import unittest

from rdflib import (
    Literal,
    RDF,
    RDFS,
    URIRef,
)

import tests.session_context.identity.test_session_identity as fixtures
from session_context.identity.criteria import IdentityCriteria
from session_context.identity.candidates import assess_frame_candidates
from session_context.type_alignment import SessionTypeMapper
from tests.ontology.test_ontology_alignment import make_source


CTX = fixtures.CTX

BODY = """
ex:A a owl:Class ;
    rdfs:label "element"@ro .

ex:B a owl:Class ;
    rdfs:label "element finisat"@ro ;
    rdfs:subClassOf ex:A .
"""


def make_criteria(name, identifier="test-criteria"):
    return IdentityCriteria(
        criteria_id=identifier,
        version="1",
        scope_description="Entitățile din scenariul de test.",
        justification="Criterii explicite pentru comparație.",
        validated_by="test-reviewer",
        characteristics=(name,),
        required_characteristics=(name,),
    )


class FrameCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SessionIdentityTest()
        self.fixture.setUp()

        self.context = self.fixture.context
        self.a = self.fixture.a
        self.b = self.fixture.b
        self.mapper = SessionTypeMapper(make_source(BODY))
        self.criteria = make_criteria("culoare")

        self.context.observations.set((
            self.a, RDFS.label, Literal("element"),
        ))
        self.context.observations.set((
            self.b, RDFS.label, Literal("element finisat"),
        ))

        for occurrence in (self.a, self.b):
            self.fixture._set_characteristics(
                occurrence,
                ("culoare", "albastru", False),
            )

    def add_occurrence(
        self,
        frame_id,
        identifier,
        characteristic,
        value,
    ):
        graph = self.context.observations

        analysis = graph.value(
            self.context.frame_iris[frame_id],
            CTX.observation,
        )
        image = graph.value(analysis, CTX.observation)

        occurrence = URIRef(
            f"{image}/candidate-test/{identifier}"
        )

        graph.add((image, CTX.entities, occurrence))
        graph.add((
            occurrence,
            RDF.type,
            CTX.EntityObservation,
        ))
        graph.add((
            occurrence,
            RDFS.label,
            Literal("element"),
        ))
        graph.add((
            occurrence,
            CTX.uncertain,
            Literal(False),
        ))

        self.fixture._set_characteristics(
            occurrence,
            (characteristic, value, False),
        )

        return occurrence

    def assess(self, criteria_by_occurrence=None):
        return assess_frame_candidates(
            self.context,
            "frame-1",
            "frame-2",
            mapper=self.mapper,
            criteria_by_occurrence=(
                {self.b: self.criteria}
                if criteria_by_occurrence is None
                else criteria_by_occurrence
            ),
            language="ro",
        )

    def test_different_names_are_compared_without_graph_changes(self):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        result = self.assess()

        self.assertEqual({self.b}, set(result))
        self.assertEqual(1, len(result[self.b]))

        pair = result[self.b][0]

        self.assertEqual(
            self.a,
            pair.type_comparison.left.occurrence_iri,
        )
        self.assertEqual(
            self.b,
            pair.type_comparison.right.occurrence_iri,
        )
        self.assertEqual(
            "consistent",
            pair.characteristics.status,
        )
        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

    def test_concordant_and_changed_alternatives_are_both_retained(self):
        other = self.add_occurrence(
            "frame-1",
            "other",
            "culoare",
            "roșu",
        )

        pairs = self.assess()[self.b]

        self.assertEqual(2, len(pairs))
        self.assertEqual(
            {self.a, other},
            {
                pair.type_comparison.left.occurrence_iri
                for pair in pairs
            },
        )
        self.assertEqual(
            {"consistent", "difference_detected"},
            {
                pair.characteristics.status
                for pair in pairs
            },
        )

    def test_current_appearances_can_use_different_criteria(self):
        other = self.add_occurrence(
            "frame-2",
            "other",
            "formă",
            "ovală",
        )
        other_criteria = make_criteria(
            "formă",
            identifier="shape-criteria",
        )

        result = self.assess({
            self.b: self.criteria,
            other: other_criteria,
        })

        self.assertIs(
            self.criteria,
            result[self.b][0].characteristics.criteria,
        )
        self.assertIs(
            other_criteria,
            result[other][0].characteristics.criteria,
        )
        self.assertEqual(
            "insufficient_evidence",
            result[other][0].characteristics.status,
        )

    def test_extraneous_criteria_are_rejected(self):
        for selected in (
                {self.a: self.criteria},
                {
                    self.a: self.criteria,
                    self.b: self.criteria,
                },
        ):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    self.assess(selected)

    def test_no_criteria_produces_no_pair_comparisons(self):
        self.assertEqual({}, self.assess({}))

    def test_invalid_frame_selection_is_rejected(self):
        for reference, current in (
            ("frame-1", "frame-1"),
            ("unknown", "frame-2"),
            ("frame-1", "unknown"),
        ):
            with self.subTest(
                reference=reference,
                current=current,
            ):
                with self.assertRaises(ValueError):
                    assess_frame_candidates(
                        self.context,
                        reference,
                        current,
                        mapper=self.mapper,
                        criteria_by_occurrence={
                            self.b: self.criteria,
                        },
                    )


if __name__ == "__main__":
    unittest.main()