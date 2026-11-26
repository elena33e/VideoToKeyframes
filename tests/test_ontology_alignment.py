"""Teste pentru propuneri lexicale de clase, fără fișiere sau apeluri AI."""

import unittest
from hashlib import sha256
from pathlib import Path

from rdflib import Graph
from rdflib.namespace import RDFS

from ontology.alignment import ALIGNMENT_VERSION, ClassAligner
from ontology.reader import OntologySource


NS = "https://example.test/a#"


def make_source(body, namespace=NS):
    content = (
        f"@prefix ex: <{namespace}> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix obo: <http://www.geneontology.org/formats/oboInOwl#> .\n"
        + body
    )

    return OntologySource(
        path=Path("synthetic.ttl").resolve(),
        graph=Graph().parse(data=content, format="turtle"),
        rdf_format="turtle",
        source_sha256=sha256(
            content.encode("utf-8")
        ).hexdigest(),
    )


class OntologyAlignmentTest(unittest.TestCase):
    def test_full_iri_is_matched_exactly(self):
        aligner = ClassAligner(
            make_source("ex:Mixed a owl:Class .")
        )

        result = aligner.propose(NS + "Mixed")

        self.assertEqual("unique", result.status)
        self.assertEqual(
            NS + "Mixed",
            result.candidates[0].class_iri,
        )
        self.assertEqual(
            "iri",
            result.candidates[0].evidence[0].method,
        )

    def test_iri_case_is_not_normalized(self):
        aligner = ClassAligner(
            make_source("ex:Mixed a owl:Class .")
        )

        self.assertEqual(
            "unmapped",
            aligner.propose(NS + "mixed").status,
        )

    def test_label_normalizes_case_spaces_and_unicode(self):
        source = make_source(
            'ex:Alpha a owl:Class ; '
            'rdfs:label "piesă simplă"@ro .'
        )

        result = ClassAligner(source).propose(
            "  PIESA\u0306   SIMPLĂ ",
            language="ro",
        )

        self.assertEqual("unique", result.status)
        self.assertEqual(
            NS + "Alpha",
            result.candidates[0].class_iri,
        )

    def test_exact_synonyms_are_proposals(self):
        source = make_source(
            'ex:Alpha a owl:Class ; '
            'rdfs:label "principal"@ro ; '
            'skos:altLabel "alternativ"@ro ; '
            'obo:hasExactSynonym "echivalent"@ro .'
        )

        for query in ("alternativ", "echivalent"):
            with self.subTest(query=query):
                result = ClassAligner(source).propose(
                    query,
                    language="ro",
                )

                self.assertEqual("unique", result.status)
                self.assertEqual(
                    "exact_synonym",
                    result.candidates[0].evidence[0].method,
                )

    def test_nonexact_synonyms_are_not_equivalences(self):
        source = make_source(
            'ex:Alpha a owl:Class ; '
            'obo:hasBroadSynonym "larg" ; '
            'obo:hasRelatedSynonym "asociat" ; '
            'obo:hasNarrowSynonym "îngust" .'
        )
        aligner = ClassAligner(source)

        for query in ("larg", "asociat", "îngust"):
            with self.subTest(query=query):
                self.assertEqual(
                    "unmapped",
                    aligner.propose(query).status,
                )

    def test_label_does_not_hide_a_rival_exact_synonym(self):
        source = make_source(
            'ex:Alpha a owl:Class ; rdfs:label "comun"@ro . '
            'ex:Beta a owl:Class ; '
            'obo:hasExactSynonym "comun"@ro .'
        )

        result = ClassAligner(source).propose("comun")

        self.assertEqual("ambiguous", result.status)
        self.assertEqual(
            {NS + "Alpha", NS + "Beta"},
            {
                candidate.class_iri
                for candidate in result.candidates
            },
        )

    def test_multiple_annotations_of_one_class_do_not_create_ambiguity(self):
        source = make_source(
            'ex:Alpha a owl:Class ; '
            'rdfs:label "piesă"@ro ; '
            'skos:prefLabel "piesă"@ro .'
        )

        result = ClassAligner(source).propose("piesă")

        self.assertEqual("unique", result.status)
        self.assertEqual(
            2,
            len(result.candidates[0].evidence),
        )

    def test_language_filter_preserves_untagged_alternatives(self):
        source = make_source(
            'ex:Alpha a owl:Class ; rdfs:label "comun"@ro . '
            'ex:Beta a owl:Class ; rdfs:label "comun"@en . '
            'ex:Gamma a owl:Class ; rdfs:label "comun" .'
        )
        aligner = ClassAligner(source)

        self.assertEqual(
            3,
            len(aligner.propose("comun").candidates),
        )

        result = aligner.propose("comun", language="ro")

        self.assertEqual("ambiguous", result.status)
        self.assertEqual(
            {NS + "Alpha", NS + "Gamma"},
            {
                candidate.class_iri
                for candidate in result.candidates
            },
        )

    def test_local_name_is_only_a_fallback_for_unlabelled_classes(self):
        source = make_source(
            'ex:Opaque_123 a owl:Class . '
            'ex:Beta a owl:Class ; rdfs:label "termen" .'
        )
        aligner = ClassAligner(source)

        result = aligner.propose("Opaque_123")

        self.assertEqual(
            "local_name",
            result.candidates[0].evidence[0].method,
        )
        self.assertEqual(
            "unmapped",
            aligner.propose("Opaque 123").status,
        )
        self.assertEqual(
            "unmapped",
            aligner.propose("Beta").status,
        )

    def test_individuals_and_skos_concepts_are_not_classes(self):
        source = make_source(
            'ex:Alpha a owl:Class ; rdfs:label "clasă" . '
            'ex:Instance a ex:Alpha ; rdfs:label "individ" . '
            'ex:Concept a skos:Concept ; '
            'skos:prefLabel "concept" .'
        )
        aligner = ClassAligner(source)

        for query in ("individ", "concept"):
            self.assertEqual(
                "unmapped",
                aligner.propose(query).status,
            )

    def test_declared_imports_are_reported_without_loading_them(self):
        source = make_source(
            'ex:Ontology a owl:Ontology ; '
            'owl:imports <https://example.invalid/base> . '
            'ex:Alpha a owl:Class .'
        )

        result = ClassAligner(source).propose("absent")

        self.assertEqual("unmapped", result.status)
        self.assertEqual(
            ("https://example.invalid/base",),
            result.imports_not_loaded,
        )
        self.assertTrue(result.warnings)

    def test_provenance_is_preserved_without_modifying_the_graph(self):
        source = make_source(
            'ex:Alpha a owl:Class ; rdfs:label "piesă"@ro .'
        )
        before = set(source.graph)

        result = ClassAligner(source).propose(
            "piesă",
            language="ro",
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
            ALIGNMENT_VERSION,
            result.alignment_version,
        )

        evidence = result.candidates[0].evidence[0]
        self.assertEqual(str(RDFS.label), evidence.predicate)
        self.assertEqual("ro", evidence.language)
        self.assertEqual("piesă", evidence.value)

    def test_renaming_vocabulary_and_namespace_preserves_behaviour(self):
        for namespace, label in (
            ("https://example.test/first#", "componentă"),
            ("urn:example:second:", "recipient"),
        ):
            with self.subTest(namespace=namespace):
                source = make_source(
                    f'ex:Alpha a owl:Class ; '
                    f'rdfs:label "{label}" .',
                    namespace=namespace,
                )

                result = ClassAligner(source).propose(label)

                self.assertEqual("unique", result.status)
                self.assertEqual(
                    namespace + "Alpha",
                    result.candidates[0].class_iri,
                )

    def test_empty_query_and_invalid_language_are_rejected(self):
        aligner = ClassAligner(
            make_source("ex:Alpha a owl:Class .")
        )

        for query in ("", "   "):
            with self.assertRaises(ValueError):
                aligner.propose(query)

        with self.assertRaises(ValueError):
            aligner.propose("Alpha", language=" ")


if __name__ == "__main__":
    unittest.main()