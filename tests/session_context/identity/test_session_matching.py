"""Teste locale pentru selecția candidaților și asocierea automată."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import (
    RDF,
    RDFS,
    Literal,
    URIRef,
)

import tests.session_context.identity.test_session_identity as fixtures
from session_context.identity.graph import (
    object_for_occurrence,
    record_identity_decision,
)
from session_context.identity.associations import (
    apply_automatic_associations,
    assess_frame_associations,
)
from session_context.persistence import (
    load_session_context,
    save_session_context,
)
from session_context.identity.associations import (
    apply_automatic_associations,
    assess_frame_associations,
)
from session_context.identity.candidates import assess_identity_candidate
from session_context.identity.criteria import IdentityCriteria
from session_context.type_alignment import SessionTypeMapper
from tests.ontology.test_ontology_alignment import (
    NS,
    make_source,
)

CTX = fixtures.CTX
NAMES = ("culoare", "formă")


class SessionMatchingTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SessionIdentityTest()
        self.fixture.setUp()
        self.context = self.fixture.context
        self.a, self.b, self.c = self.fixture.a, self.fixture.b, self.fixture.c
        self.prepare()

    def chars(self, occurrence, color="albastru"):
        self.fixture._set_characteristics(
            occurrence, ("culoare", color, False), ("formă", "ovală", False)
        )
        self.context.observations.set((occurrence, CTX.uncertain, Literal(False)))

    def prepare(self):
        self.chars(self.a)
        self.chars(self.b)

    def add(self, frame_id, identifier, name="obiect"):
        graph = self.context.observations
        analysis = graph.value(self.context.frame_iris[frame_id], CTX.observation)
        image = graph.value(analysis, CTX.observation)
        occurrence = URIRef(f"{image}/matching-test/{identifier}")
        graph.add((image, CTX.entities, occurrence))
        graph.add((occurrence, RDF.type, CTX.EntityObservation))
        graph.add((occurrence, RDFS.label, Literal(name)))
        self.chars(occurrence)
        return occurrence

    def assess(self, reference="frame-1", current="frame-2", **kwargs):
        return assess_frame_associations(
            self.context, reference, current, identity_names=NAMES, **kwargs
        )

    def apply(self, reference="frame-1", current="frame-2"):
        return apply_automatic_associations(
            self.context, reference, current, identity_names=NAMES
        )

    def test_assessment_is_read_only(self):
        before = set(self.context.dataset.quads((None, None, None, None)))
        result = self.assess()
        self.assertEqual("automatic", result[0].action)
        self.assertEqual(self.a, result[0].candidates[0].reference_iri)
        self.assertEqual(
            before, set(self.context.dataset.quads((None, None, None, None)))
        )

    def test_automatic_association_preserves_provenance_and_survives_reload(self):
        observations = set(self.context.observations)
        decisions = self.apply()
        self.assertEqual(1, len(decisions))
        target = object_for_occurrence(self.context, self.a)
        self.assertIsNotNone(target)
        self.assertEqual(target, object_for_occurrence(self.context, self.b))
        self.assertEqual(observations, set(self.context.observations))
        self.assertEqual(
            Literal("automatic:frame-matching-v1"),
            self.context.identities.value(decisions[0], CTX.decidedBy),
        )
        proof = json.loads(str(
            self.context.identities.value(decisions[0], CTX.justification)
        ))
        self.assertEqual(2, proof["min_matching"])
        self.assertEqual(2, len(proof["evidence"]))
        self.assertTrue(all(item["left"] and item["right"] for item in proof["evidence"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            restored = load_session_context(path)
        self.assertEqual(target, object_for_occurrence(restored, self.b))
        self.assertEqual(
            set(self.context.identities), set(restored.identities)
        )
        self.assertEqual((), self.apply())
        self.assertEqual("already_associated", self.assess()[0].action)

    def test_existing_identity_is_extended_after_manual_resolution(self):
        record_identity_decision(
            self.context, self.fixture.decision(self.a, self.b, "unresolved")
        )
        self.fixture.confirm(self.a, self.b)
        self.chars(self.c)
        target = object_for_occurrence(self.context, self.b)
        self.assertEqual(1, len(self.apply("frame-2", "frame-3")))
        self.assertEqual(target, object_for_occurrence(self.context, self.c))
        self.assertEqual(
            1, len(set(self.context.identities.subjects(RDF.type, CTX.TrackedObject)))
        )

    def test_changed_characteristic_requires_confirmation_without_writing(self):
        self.chars(self.b, "roșu")
        result = self.assess()
        self.assertEqual("confirmation", result[0].action)
        self.assertTrue(result[0].candidates[0].comparison.requires_confirmation)
        self.assertEqual((), self.apply())
        self.assertEqual(0, len(self.context.identities))

    def test_missing_uncertain_and_insufficient_evidence_remain_unresolved(self):
        for case in ("missing", "uncertain", "insufficient", "entity_uncertain"):
            with self.subTest(case=case):
                self.prepare()
                if case == "missing":
                    self.fixture._set_characteristics(self.b)
                elif case == "uncertain":
                    self.fixture._set_characteristics(
                        self.b,
                        ("culoare", "roșu", True),
                        ("formă", "ovală", False),
                    )
                elif case == "insufficient":
                    self.fixture._set_characteristics(
                        self.b, ("culoare", "albastru", False)
                    )
                else:
                    self.context.observations.set((self.b, CTX.uncertain, Literal(True)))
                self.assertEqual("unresolved", self.assess()[0].action)
                self.assertEqual((), self.apply())

    def test_matching_and_unknown_alternatives_both_block_uniqueness(self):
        other = self.add("frame-1", "other")
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                if unknown:
                    self.fixture._set_characteristics(other)
                result = self.assess()[0]
                self.assertEqual("unresolved", result.action)
                self.assertEqual(2, len(result.candidates))
                self.assertEqual((), self.apply())

    def test_two_current_appearances_cannot_claim_the_same_identity(self):
        self.add("frame-2", "other")
        result = self.assess()
        self.assertEqual(2, len(result))
        self.assertTrue(all(
            item.reason == "competing_current_appearances" for item in result
        ))
        self.assertEqual((), self.apply())

    def test_rejections_and_unresolved_decisions_are_respected(self):
        for outcome in ("different_objects", "unresolved"):
            with self.subTest(outcome=outcome):
                self.setUp()
                record_identity_decision(
                    self.context, self.fixture.decision(self.a, self.b, outcome)
                )
                self.assertEqual("unresolved", self.assess()[0].action)
                self.assertEqual((), self.apply())
        self.setUp()
        self.fixture.confirm(self.a, self.b)
        self.chars(self.c)
        record_identity_decision(
            self.context,
            self.fixture.decision(self.a, self.c, "different_objects"),
        )
        self.assertEqual("no_candidate", self.assess("frame-2", "frame-3")[0].reason)
        self.assertEqual((), self.apply("frame-2", "frame-3"))

    def test_identity_already_present_in_current_frame_cannot_be_reused(self):
        self.fixture.confirm(self.a, self.b)
        other = self.add("frame-2", "other")
        result = {item.occurrence_iri: item for item in self.assess()}
        self.assertEqual("already_associated", result[self.b].action)
        self.assertEqual("unresolved", result[other].action)
        self.assertEqual((), self.apply())
        self.assertIsNone(object_for_occurrence(self.context, other))

    def test_changed_alternative_blocks_automatic_association(self):
        other = self.add("frame-1", "other")
        self.chars(other, "roșu")

        before = set(self.context.identities)
        result = self.assess()[0]

        self.assertEqual("unresolved", result.action)
        self.assertEqual("multiple_candidates", result.reason)
        self.assertEqual(
            {self.a, other},
            {
                candidate.reference_iri
                for candidate in result.candidates
            },
        )
        self.assertTrue(any(
            candidate.comparison.requires_confirmation
            for candidate in result.candidates
        ))

        self.assertEqual((), self.apply())
        self.assertEqual(before, set(self.context.identities))

    def test_invalid_frames_and_policy_are_rejected(self):
        for reference, current in (("frame-1", "frame-1"), ("unknown", "frame-2")):
            with self.assertRaises(ValueError):
                self.assess(reference, current)
        for minimum in (0, True, 3):
            with self.assertRaises(ValueError):
                self.assess(min_matching=minimum)
        for names in ((), "culoare", (" ",)):
            with self.assertRaises(ValueError):
                assess_frame_associations(
                    self.context, "frame-1", "frame-2", identity_names=names
                )

    def test_batch_validation_failure_leaves_no_partial_association(self):
        self.add("frame-1", "other", name="alt obiect")
        self.add("frame-2", "other", name="alt obiect")
        before = set(self.context.dataset.quads((None, None, None, None)))
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("Eroare simulată.")
            return record_identity_decision(*args, **kwargs)

        with patch(
            "session_context.identity.associations.record_identity_decision",
            side_effect=fail_second,
        ):
            with self.assertRaises(ValueError):
                self.apply()
        self.assertEqual(2, len(calls))
        self.assertEqual(
            before, set(self.context.dataset.quads((None, None, None, None)))
        )


    def assess_candidate(
        self,
        ontology_body,
        left_name="element",
        right_name="element finisat",
    ):
        self.context.observations.set((
            self.a,
            RDFS.label,
            Literal(left_name),
        ))
        self.context.observations.set((
            self.b,
            RDFS.label,
            Literal(right_name),
        ))

        mapper = SessionTypeMapper(
            make_source(ontology_body)
        )
        criteria = IdentityCriteria(
            criteria_id="test-criteria",
            version="1",
            scope_description="Entitățile din scenariul de test.",
            justification="Criterii explicite pentru comparație.",
            validated_by="test-reviewer",
            characteristics=NAMES,
            required_characteristics=NAMES,
        )

        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        result = assess_identity_candidate(
            self.context,
            self.a,
            self.b,
            mapper=mapper,
            criteria=criteria,
            language="ro",
        )

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

        return result

    def test_candidate_with_different_names_keeps_subclass_evidence(self):
        result = self.assess_candidate("""
            ex:A a owl:Class ;
                rdfs:label "element"@ro .

            ex:B a owl:Class ;
                rdfs:label "element finisat"@ro ;
                rdfs:subClassOf ex:A .
        """)

        types = result.type_comparison

        self.assertEqual(
            NS + "A",
            types.left.alignment.candidates[0].class_iri,
        )
        self.assertEqual(
            NS + "B",
            types.right.alignment.candidates[0].class_iri,
        )
        self.assertEqual(1, len(types.class_relations))

        relation = types.class_relations[0]

        self.assertIsNone(relation.left_to_right)
        self.assertEqual(1, len(relation.right_to_left))
        self.assertEqual(
            "consistent",
            result.characteristics.status,
        )

    def test_unmapped_types_do_not_remove_characteristic_evidence(self):
        result = self.assess_candidate("""
            ex:Other a owl:Class ;
                rdfs:label "alt concept"@ro .
        """)

        types = result.type_comparison

        self.assertEqual("unmapped", types.left.alignment.status)
        self.assertEqual("unmapped", types.right.alignment.status)
        self.assertEqual((), types.class_relations)

        self.assertEqual(
            "consistent",
            result.characteristics.status,
        )
        self.assertEqual(
            self.a,
            result.characteristics.comparison.left_occurrence_iri,
        )
        self.assertEqual(
            self.b,
            result.characteristics.comparison.right_occurrence_iri,
        )

    def test_ambiguous_types_keep_all_class_pairs(self):
        result = self.assess_candidate("""
            ex:A a owl:Class ;
                rdfs:label "element"@ro .
            ex:B a owl:Class ;
                rdfs:label "element"@ro .

            ex:C a owl:Class ;
                rdfs:label "element finisat"@ro .
            ex:D a owl:Class ;
                rdfs:label "element finisat"@ro .
        """)

        types = result.type_comparison

        self.assertEqual("ambiguous", types.left.alignment.status)
        self.assertEqual("ambiguous", types.right.alignment.status)
        self.assertEqual(
            {
                (NS + "A", NS + "C"),
                (NS + "A", NS + "D"),
                (NS + "B", NS + "C"),
                (NS + "B", NS + "D"),
            },
            {
                (report.left_iri, report.right_iri)
                for report in types.class_relations
            },
        )

    def test_declared_disjointness_is_preserved_with_visual_concordance(self):
        result = self.assess_candidate("""
            ex:A a owl:Class ;
                rdfs:label "element"@ro ;
                owl:disjointWith ex:B .

            ex:B a owl:Class ;
                rdfs:label "element finisat"@ro .
        """)

        relation = result.type_comparison.class_relations[0]

        self.assertEqual(1, len(relation.declared_disjoint))
        self.assertEqual(
            "consistent",
            result.characteristics.status,
        )


if __name__ == "__main__":
    unittest.main()
