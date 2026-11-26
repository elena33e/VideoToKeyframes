"""Teste locale pentru selecția candidaților și asocierea automată."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import RDF, RDFS, Literal, URIRef

import test_session_identity as fixtures
from session_context.identity_graph import (
    object_for_occurrence,
    record_identity_decision,
)
from session_context.matching import (
    apply_automatic_associations,
    assess_frame_associations,
)
from session_context.persistence import load_session_context, save_session_context


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

    def test_concordant_candidate_has_priority_over_a_changed_alternative(self):
        other = self.add("frame-1", "other")
        self.chars(other, "roșu")
        result = self.assess()[0]
        self.assertEqual("automatic", result.action)
        self.assertEqual(self.a, result.candidates[0].reference_iri)

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
            "session_context.matching.record_identity_decision",
            side_effect=fail_second,
        ):
            with self.assertRaises(ValueError):
                self.apply()
        self.assertEqual(2, len(calls))
        self.assertEqual(
            before, set(self.context.dataset.quads((None, None, None, None)))
        )


if __name__ == "__main__":
    unittest.main()
