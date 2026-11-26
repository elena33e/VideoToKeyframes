"""Legătura dintre apariții, propuneri de clase și relațiile lor."""

import unittest
from dataclasses import replace

from rdflib import Literal, RDFS, URIRef

import test_session_identity as fixtures
from ontology.type_relations import RELATIONS_VERSION
from session_context.type_alignment import SessionTypeMapper
from test_ontology_alignment import NS, make_source


CTX = fixtures.CTX

BODY = """
ex:A a owl:Class ; rdfs:label "element"@ro .
ex:B a owl:Class ; rdfs:subClassOf ex:A ;
    rdfs:label "element finisat"@ro .
"""


class SessionTypeAlignmentTest(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SessionIdentityTest()
        fixture.setUp()

        self.context = fixture.context
        self.a, self.b = fixture.a, fixture.b

        self.rename(self.a, "element")
        self.rename(self.b, "element finisat")

        self.source = make_source(BODY)
        self.mapper = SessionTypeMapper(self.source)

    def rename(self, occurrence, name):
        self.context.observations.set((
            occurrence,
            RDFS.label,
            Literal(name),
        ))

    def proposals(self, mapper=None):
        selected = (
            mapper
            if mapper is not None
            else self.mapper
        )

        return (
            selected.propose(
                self.context,
                self.a,
                language="ro",
            ),
            selected.propose(
                self.context,
                self.b,
                language="ro",
            ),
        )

    def test_proposal_keeps_the_occurrence_and_lexical_provenance(self):
        proposal = self.mapper.propose(
            self.context,
            self.a,
            language="ro",
        )

        self.assertEqual(self.a, proposal.occurrence_iri)
        self.assertEqual("frame-1", proposal.frame_id)
        self.assertEqual(
            self.context.session_id,
            proposal.session_id,
        )
        self.assertEqual(
            self.context.source_sha256,
            proposal.observations_sha256,
        )
        self.assertEqual("element", proposal.observed_name)
        self.assertFalse(proposal.uncertain)
        self.assertEqual("ro", proposal.requested_language)
        self.assertEqual("unique", proposal.alignment.status)
        self.assertEqual(
            NS + "A",
            proposal.alignment.candidates[0].class_iri,
        )
        self.assertEqual(
            self.source.source_sha256,
            proposal.alignment.ontology_source_sha256,
        )

    def test_comparison_keeps_the_direction_and_relational_evidence(self):
        left, right = self.proposals()

        result = self.mapper.compare(left, right)

        self.assertEqual(1, len(result.class_relations))

        report = result.class_relations[0]

        self.assertIsNone(report.left_to_right)
        self.assertEqual(1, len(report.right_to_left))
        self.assertEqual(
            (
                NS + "B",
                str(RDFS.subClassOf),
                NS + "A",
            ),
            report.right_to_left[0].statement,
        )
        self.assertEqual(
            RELATIONS_VERSION,
            report.relations_version,
        )
        self.assertEqual(0, len(self.context.identities))

    def test_ambiguous_candidates_are_all_preserved(self):
        mapper = SessionTypeMapper(make_source(
            BODY
            + 'ex:C a owl:Class ; rdfs:label "element"@ro .'
        ))

        left, right = self.proposals(mapper)
        result = mapper.compare(left, right)

        self.assertEqual(
            "ambiguous",
            result.left.alignment.status,
        )
        self.assertEqual(
            {
                (NS + "A", NS + "B"),
                (NS + "C", NS + "B"),
            },
            {
                (item.left_iri, item.right_iri)
                for item in result.class_relations
            },
        )
        self.assertEqual(0, len(self.context.identities))

    def test_unmapped_name_is_preserved_without_inventing_a_relation(self):
        self.rename(self.a, "necatalogat")

        left, right = self.proposals()
        result = self.mapper.compare(left, right)

        self.assertEqual(
            "unmapped",
            result.left.alignment.status,
        )
        self.assertEqual((), result.class_relations)
        self.assertEqual(
            "necatalogat",
            result.left.observed_name,
        )

    def test_uncertainty_is_not_removed_by_a_unique_lexical_match(self):
        graph = self.context.observations

        for marker in (True, None):
            with self.subTest(marker=marker):
                graph.remove((self.a, CTX.uncertain, None))

                if marker is not None:
                    graph.add((
                        self.a,
                        CTX.uncertain,
                        Literal(marker),
                    ))

                result = self.mapper.propose(
                    self.context,
                    self.a,
                )

                self.assertEqual(
                    "unique",
                    result.alignment.status,
                )
                self.assertIs(marker, result.uncertain)

    def test_unknown_or_multiply_owned_occurrence_is_rejected(self):
        for occurrence in (
            URIRef("urn:test:missing"),
            "relative",
        ):
            with self.assertRaises(ValueError):
                self.mapper.propose(
                    self.context,
                    occurrence,
                )

        graph = self.context.observations
        analysis = graph.value(
            self.context.frame_iris["frame-2"],
            CTX.observation,
        )
        image = graph.value(analysis, CTX.observation)
        graph.add((image, CTX.entities, self.a))

        with self.assertRaises(ValueError):
            self.mapper.propose(self.context, self.a)

    def test_invalid_label_and_uncertainty_marker_are_rejected(self):
        graph = self.context.observations
        graph.set((self.a, RDFS.label, Literal(42)))

        with self.assertRaises(ValueError):
            self.mapper.propose(self.context, self.a)

        self.rename(self.a, "element")
        graph.set((
            self.a,
            CTX.uncertain,
            Literal("false"),
        ))

        with self.assertRaises(ValueError):
            self.mapper.propose(self.context, self.a)

    def test_proposals_from_another_ontology_revision_are_rejected(self):
        left, _ = self.proposals()

        other = SessionTypeMapper(make_source(
            BODY
            + 'ex:A rdfs:comment "altă versiune" .'
        ))
        right = other.propose(self.context, self.b)

        with self.assertRaises(ValueError):
            self.mapper.compare(left, right)

    def test_source_location_and_format_are_checked_too(self):
        left, _ = self.proposals()

        for changes in (
            {
                "path": self.source.path.with_name(
                    "other.ttl"
                ),
            },
            {"rdf_format": "n3"},
        ):
            with self.subTest(changes=changes):
                other = SessionTypeMapper(
                    replace(self.source, **changes)
                )
                right = other.propose(
                    self.context,
                    self.b,
                )

                with self.assertRaises(ValueError):
                    self.mapper.compare(left, right)

    def test_different_sessions_and_observation_versions_are_rejected(self):
        left, right = self.proposals()

        for changes in (
            {"session_id": "another-session"},
            {"observations_sha256": "f" * 64},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.mapper.compare(
                        left,
                        replace(right, **changes),
                    )

    def test_propose_and_compare_do_not_modify_either_graph(self):
        observations = set(
            self.context.dataset.quads(
                (None, None, None, None)
            )
        )
        ontology = set(self.source.graph)

        self.mapper.compare(*self.proposals())

        self.assertEqual(
            observations,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )
        self.assertEqual(
            ontology,
            set(self.source.graph),
        )

    def test_indexes_use_the_same_initial_ontology_snapshot(self):
        self.source.graph.remove((
            URIRef(NS + "B"),
            RDFS.subClassOf,
            URIRef(NS + "A"),
        ))

        result = self.mapper.compare(*self.proposals())

        self.assertEqual(
            1,
            len(result.class_relations[0].right_to_left),
        )


if __name__ == "__main__":
    unittest.main()