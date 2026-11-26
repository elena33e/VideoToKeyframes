"""Teste pentru căi între clase, fără raționator OWL sau apeluri AI."""

import unittest

from rdflib.namespace import OWL, RDFS

from ontology.type_relations import (
    ClassRelationIndex,
    RELATIONS_VERSION,
)
from test_ontology_alignment import NS, make_source


DECLARATIONS = """
ex:A a owl:Class .
ex:B a owl:Class .
ex:C a owl:Class .
"""


def make_index(body=""):
    return ClassRelationIndex(
        make_source(DECLARATIONS + body)
    )


class TypeRelationsTest(unittest.TestCase):
    def test_direct_subclass_keeps_direction_and_statement(self):
        result = make_index(
            "ex:A rdfs:subClassOf ex:B ."
        ).inspect(NS + "A", NS + "B")

        self.assertEqual(1, len(result.left_to_right))
        self.assertIsNone(result.right_to_left)

        step = result.left_to_right[0]

        self.assertEqual(
            (
                NS + "A",
                str(RDFS.subClassOf),
                NS + "B",
            ),
            step.statement,
        )
        self.assertFalse(step.reverse)

    def test_transitive_subclass_path_preserves_every_step(self):
        result = make_index(
            "ex:A rdfs:subClassOf ex:B . "
            "ex:B rdfs:subClassOf ex:C ."
        ).inspect(NS + "A", NS + "C")

        self.assertEqual(
            [
                (NS + "A", NS + "B"),
                (NS + "B", NS + "C"),
            ],
            [
                (step.start, step.end)
                for step in result.left_to_right
            ],
        )
        self.assertIsNone(result.right_to_left)

    def test_equivalence_can_be_traversed_in_reverse_without_rewriting_evidence(self):
        result = make_index(
            "ex:B owl:equivalentClass ex:A ."
        ).inspect(NS + "A", NS + "B")

        self.assertTrue(result.left_to_right[0].reverse)
        self.assertFalse(result.right_to_left[0].reverse)

        self.assertEqual(
            (
                NS + "B",
                str(OWL.equivalentClass),
                NS + "A",
            ),
            result.left_to_right[0].statement,
        )

    def test_equivalence_and_subclass_can_form_one_path(self):
        result = make_index(
            "ex:B owl:equivalentClass ex:A . "
            "ex:B rdfs:subClassOf ex:C ."
        ).inspect(NS + "A", NS + "C")

        self.assertEqual(2, len(result.left_to_right))
        self.assertTrue(result.left_to_right[0].reverse)
        self.assertEqual(
            str(RDFS.subClassOf),
            result.left_to_right[1].statement[1],
        )

    def test_cycles_terminate_and_keep_a_valid_path(self):
        result = make_index(
            "ex:A rdfs:subClassOf ex:B . "
            "ex:B rdfs:subClassOf ex:A, ex:C ."
        ).inspect(NS + "A", NS + "C")

        self.assertEqual(2, len(result.left_to_right))
        self.assertIsNone(result.right_to_left)

    def test_direct_disjointness_is_reported_in_both_query_orders(self):
        index = make_index(
            "ex:B owl:disjointWith ex:A ."
        )
        expected = (
            (
                NS + "B",
                str(OWL.disjointWith),
                NS + "A",
            ),
        )

        for left, right in (("A", "B"), ("B", "A")):
            with self.subTest(left=left):
                result = index.inspect(
                    NS + left,
                    NS + right,
                )

                self.assertEqual(
                    expected,
                    result.declared_disjoint,
                )
                self.assertIsNone(result.left_to_right)
                self.assertIsNone(result.right_to_left)

    def test_common_ancestor_does_not_create_an_inclusion_between_siblings(self):
        result = make_index(
            "ex:A rdfs:subClassOf ex:C . "
            "ex:B rdfs:subClassOf ex:C ."
        ).inspect(NS + "A", NS + "B")

        self.assertTrue(
            result.left_known and result.right_known
        )
        self.assertIsNone(result.left_to_right)
        self.assertIsNone(result.right_to_left)
        self.assertEqual((), result.declared_disjoint)

    def test_skos_links_are_not_used_as_class_inclusions(self):
        result = make_index(
            "ex:A skos:broader ex:B ; "
            "skos:exactMatch ex:B ."
        ).inspect(NS + "A", NS + "B")

        self.assertIsNone(result.left_to_right)
        self.assertIsNone(result.right_to_left)

    def test_inclusion_does_not_hide_a_disjointness_declaration(self):
        result = make_index(
            "ex:A rdfs:subClassOf ex:B ; "
            "owl:disjointWith ex:B ."
        ).inspect(NS + "A", NS + "B")

        self.assertEqual(1, len(result.left_to_right))
        self.assertEqual(1, len(result.declared_disjoint))

    def test_same_iri_is_distinct_from_recognition_as_a_class(self):
        index = make_index()

        known = index.inspect(NS + "A", NS + "A")

        self.assertTrue(
            known.same_iri and known.left_known
        )
        self.assertEqual((), known.left_to_right)
        self.assertEqual((), known.right_to_left)

        missing = index.inspect(
            NS + "Missing",
            NS + "Missing",
        )

        self.assertTrue(missing.same_iri)
        self.assertFalse(
            missing.left_known or missing.right_known
        )
        self.assertIsNone(missing.left_to_right)

    def test_missing_imports_are_reported_without_inventing_paths(self):
        result = make_index(
            "ex:Ontology a owl:Ontology ; "
            "owl:imports <https://example.invalid/base> ."
        ).inspect(NS + "A", NS + "B")

        self.assertEqual(
            ("https://example.invalid/base",),
            result.imports_not_loaded,
        )
        self.assertIsNone(result.left_to_right)
        self.assertTrue(result.warnings)

    def test_anonymous_restriction_is_not_flattened_into_a_subclass_edge(self):
        result = make_index("""
            ex:A rdfs:subClassOf [
                a owl:Restriction ;
                owl:onProperty ex:p ;
                owl:someValuesFrom ex:B
            ] .
        """).inspect(NS + "A", NS + "B")

        self.assertIsNone(result.left_to_right)
        self.assertTrue(result.warnings)

    def test_iris_are_exact_and_invalid_inputs_are_rejected(self):
        index = make_index(
            "ex:A rdfs:subClassOf ex:B ."
        )

        result = index.inspect(NS + "a", NS + "B")

        self.assertFalse(result.left_known)
        self.assertIsNone(result.left_to_right)

        for invalid in ("A", "", " " + NS + "A"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    index.inspect(invalid, NS + "B")

    def test_vocabulary_renaming_and_provenance_without_graph_mutation(self):
        for namespace in (
            "https://example.test/first#",
            "urn:example:second:",
        ):
            with self.subTest(namespace=namespace):
                source = make_source(
                    DECLARATIONS
                    + "ex:A rdfs:subClassOf ex:B .",
                    namespace=namespace,
                )
                before = set(source.graph)

                result = ClassRelationIndex(source).inspect(
                    namespace + "A",
                    namespace + "B",
                )

                self.assertEqual(
                    1,
                    len(result.left_to_right),
                )
                self.assertEqual(before, set(source.graph))
                self.assertEqual(
                    source.source_sha256,
                    result.ontology_source_sha256,
                )
                self.assertEqual(
                    str(source.path),
                    result.ontology_source,
                )
                self.assertEqual(
                    RELATIONS_VERSION,
                    result.relations_version,
                )


if __name__ == "__main__":
    unittest.main()