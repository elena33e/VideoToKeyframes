"""Teste pentru identitate, fără imagini locale sau apeluri API."""

import unittest
from dataclasses import replace

from rdflib import (
    Dataset,
    Literal,
    Namespace,
    OWL,
    RDF,
    RDFS,
    URIRef,
)
from rdflib.compare import isomorphic

from interpretation.config import OBSERVATION_NAMESPACE
from interpretation.observations import FrameObservation
from session_context.graph import (
    build_session_context,
    entities_for_frame,
)
from session_context.identity.models import (
    IdentityDecision,
    TrackedObject,
)
from session_context.identity.graph import (
    object_for_occurrence,
    record_identity_decision,
)

import tempfile
from pathlib import Path
from unittest.mock import patch

from session_context.persistence import (
    load_session_context,
    save_session_context,
)
from session_context.characteristics.comparison import compare_occurrences

CTX = Namespace(OBSERVATION_NAMESPACE)


class SessionIdentityTest(unittest.TestCase):
    def setUp(self):
        frames = []

        for index, color in enumerate(
            ("albastru", "roșu", "verde"), 1
        ):
            frame_id = f"frame-{index}"

            saved = FrameObservation.model_validate({
                "schema_version": "1.2",
                "frame_id": frame_id,
                "scene_index": None,
                "image_sha256": "0" * 64,
                "created_at": "2026-01-01T00:00:00+00:00",
                "prompt_version": "test",
                "requested_model": "test",
                "resolved_model": "test",
                "provider": "test",
                "api_request_id": None,
                "elapsed_seconds": 0.0,
                "parameters": {},
                "usage": {},
                "observation": {
                    "description": "Cadru sintetic.",
                    "entities": [{
                        "id": "e1",
                        "name": "obiect",
                        "characteristics": [{
                            "name": "culoare",
                            "value": color,
                            "uncertain": index == 3,
                        }],
                        "location": "centru",
                        "visibility": "partial",
                        "uncertain": False,
                    }],
                    "relations": [],
                    "actions": [],
                    "visible_text": [],
                    "uncertainties": (
                        ["Culoare neclară."] if index == 3 else []
                    ),
                },
            }).to_jsonld()

            frames.append({
                "frame_id": frame_id,
                "description_status": "completed",
                "observation": saved,
            })

        self.context = build_session_context({
            "session_id": "identity-test",
            "frames": frames,
        })

        self.a, self.b, self.c = (
            entities_for_frame(
                self.context, f"frame-{index}"
            )[0]
            for index in range(1, 4)
        )

        self.original_observations = set(
            self.context.observations
        )
        self.tracked = TrackedObject(
            session_id=self.context.session_id
        )

    def decision(self, left, right, outcome, **kwargs):
        return IdentityDecision(
            session_id=self.context.session_id,
            left_occurrence_iri=str(left),
            right_occurrence_iri=str(right),
            outcome=outcome,
            decided_by="test_user",
            justification="Decizie manuală de test.",
            **kwargs,
        )

    def confirm(self, left, right):
        decision = self.decision(
            left,
            right,
            "same_object",
            object_id=self.tracked.object_id,
        )
        record_identity_decision(
            self.context,
            decision,
            new_object=self.tracked,
        )
        return decision

    def assert_rejected(self, decision, **kwargs):
        before = set(self.context.identities)

        with self.assertRaises(ValueError):
            record_identity_decision(
                self.context, decision, **kwargs
            )

        self.assertEqual(
            before, set(self.context.identities)
        )
        self.assertEqual(
            self.original_observations,
            set(self.context.observations),
        )

    def test_confirmation_preserves_observed_states(self):
        self.confirm(self.a, self.b)
        target = object_for_occurrence(
            self.context, self.a
        )

        self.assertIsNotNone(target)
        self.assertEqual(
            target,
            object_for_occurrence(self.context, self.b),
        )

        record_identity_decision(
            self.context,
            self.decision(
                self.b,
                self.c,
                "same_object",
                object_id=self.tracked.object_id,
            ),
        )

        self.assertEqual(
            target,
            object_for_occurrence(self.context, self.c),
        )
        self.assertEqual(
            self.original_observations,
            set(self.context.observations),
        )
        self.assertFalse(list(
            self.context.identities.triples(
                (None, OWL.sameAs, None)
            )
        ))

    def test_different_and_unresolved_do_not_create_associations(self):
        for outcome in ("different_objects", "unresolved"):
            with self.subTest(outcome=outcome):
                decision_iri = record_identity_decision(
                    self.context,
                    self.decision(self.a, self.b, outcome),
                )

                self.assertIn(
                    (
                        decision_iri,
                        CTX.identityOutcome,
                        Literal(outcome),
                    ),
                    self.context.identities,
                )
                self.assertIsNone(
                    object_for_occurrence(self.context, self.a)
                )
                self.assertIsNone(
                    object_for_occurrence(self.context, self.b)
                )
                self.assertFalse(list(
                    self.context.identities.subjects(
                        RDF.type, CTX.TrackedObject
                    )
                ))

    def test_unresolved_does_not_revoke_an_existing_association(self):
        self.confirm(self.a, self.b)
        target = object_for_occurrence(
            self.context, self.a
        )

        record_identity_decision(
            self.context,
            self.decision(self.a, self.b, "unresolved"),
        )

        self.assertEqual(
            target,
            object_for_occurrence(self.context, self.a),
        )
        self.assertEqual(
            target,
            object_for_occurrence(self.context, self.b),
        )

    def test_replay_is_idempotent_and_record_cannot_be_overwritten(self):
        decision = self.confirm(self.a, self.b)
        before = set(self.context.identities)

        record_identity_decision(self.context, decision)

        self.assertEqual(
            before, set(self.context.identities)
        )

        changed = IdentityDecision.model_validate({
            **decision.model_dump(),
            "justification": "Alt conținut cu același identificator.",
        })
        self.assert_rejected(changed)

    def test_direct_conflicts_leave_no_partial_changes(self):
        self.confirm(self.a, self.b)

        self.assert_rejected(
            self.decision(
                self.a, self.b, "different_objects"
            )
        )

        other = TrackedObject(
            session_id=self.context.session_id
        )
        self.assert_rejected(
            self.decision(
                self.b,
                self.c,
                "same_object",
                object_id=other.object_id,
            ),
            new_object=other,
        )

    def test_rejected_pair_blocks_indirect_association(self):
        record_identity_decision(
            self.context,
            self.decision(
                self.a, self.c, "different_objects"
            ),
        )
        self.confirm(self.a, self.b)

        for left, right in (
            (self.b, self.c),
            (self.c, self.b),
        ):
            with self.subTest(left=left, right=right):
                self.assert_rejected(
                    self.decision(
                        left,
                        right,
                        "same_object",
                        object_id=self.tracked.object_id,
                    )
                )

    def test_invalid_references_and_sessions_are_rejected(self):
        base = self.decision(
            self.a, self.b, "unresolved"
        )

        for changes in (
            {"session_id": "another-session"},
            {"right_occurrence_iri": "urn:test:unknown"},
        ):
            with self.subTest(changes=changes):
                invalid = IdentityDecision.model_validate({
                    **base.model_dump(),
                    **changes,
                })
                self.assert_rejected(invalid)

        self.assert_rejected(
            self.decision(
                self.a,
                self.b,
                "same_object",
                object_id=self.tracked.object_id,
            )
        )

        foreign = TrackedObject(
            session_id="another-session"
        )
        self.assert_rejected(
            self.decision(
                self.a,
                self.b,
                "same_object",
                object_id=foreign.object_id,
            ),
            new_object=foreign,
        )

    def test_rdf_round_trip_preserves_identifiers_and_graphs(self):
        decision = self.confirm(self.a, self.b)

        dataset = Dataset().parse(
            data=self.context.dataset.serialize(format="trig"),
            format="trig",
        )
        restored = replace(
            self.context, dataset=dataset
        )

        self.assertTrue(isomorphic(
            self.context.observations,
            restored.observations,
        ))
        self.assertEqual(
            set(self.context.identities),
            set(restored.identities),
        )
        self.assertEqual(
            object_for_occurrence(self.context, self.a),
            object_for_occurrence(restored, self.a),
        )

        before = set(restored.identities)

        record_identity_decision(restored, decision)
        record_identity_decision(
            restored,
            decision,
            new_object=self.tracked,
        )

        self.assertEqual(
            before, set(restored.identities)
        )

    def test_context_file_preserves_graphs_and_identifiers(self):
        decision = self.confirm(self.a, self.b)
        record_identity_decision(
            self.context,
            self.decision(self.b, self.c, "unresolved"),
        )
        record_identity_decision(
            self.context,
            self.decision(self.a, self.c, "different_objects"),
        )
        before = set(self.context.dataset.quads((None, None, None, None)))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            restored = load_session_context(
                path,
                expected_session_id=self.context.session_id,
                expected_source_sha256=self.context.source_sha256,
            )

            for expected in (
                {"expected_session_id": "another-session"},
                {"expected_source_sha256": "f" * 64},
            ):
                with self.subTest(expected=expected):
                    with self.assertRaises(ValueError):
                        load_session_context(path, **expected)

        self.assertEqual(self.context.frame_iris, restored.frame_iris)
        self.assertEqual(
            self.context.observations_iri, restored.observations_iri
        )
        self.assertEqual(
            self.context.identities_iri, restored.identities_iri
        )
        self.assertTrue(isomorphic(
            self.context.observations, restored.observations
        ))
        self.assertEqual(
            set(self.context.identities), set(restored.identities)
        )
        self.assertEqual(
            before, set(self.context.dataset.quads((None, None, None, None)))
        )
        self.assertEqual(
            object_for_occurrence(self.context, self.a),
            object_for_occurrence(restored, self.b),
        )

        record_identity_decision(
            restored, decision, new_object=self.tracked
        )
        self.assertEqual(
            set(self.context.identities), set(restored.identities)
        )

    def test_context_file_rejects_invalid_association(self):
        self.confirm(self.a, self.b)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            dataset = Dataset().parse(
                data=path.read_text(encoding="utf-8"), format="trig"
            )
            dataset.graph(self.context.identities_iri).add((
                self.a, CTX.associatedObject, URIRef("urn:test:unknown")
            ))
            path.write_text(
                dataset.serialize(format="trig"), encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                load_session_context(path)

    def test_context_failed_replacement_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            before = path.read_bytes()

            with patch("pathlib.Path.replace", side_effect=OSError("test")):
                with self.assertRaises(OSError):
                    save_session_context(self.context, path)

            self.assertEqual(before, path.read_bytes())
            self.assertEqual(
                [], list(Path(directory).glob(".session_context_*.tmp"))
            )


    def _set_characteristics(self, occurrence, *items):
        graph = self.context.observations
        graph.remove((occurrence, CTX.characteristics, None))

        for index, (name, value, uncertain) in enumerate(items):
            node = URIRef(f"{occurrence}/comparison-test/{index}")
            graph.remove((node, None, None))

            graph.add((occurrence, CTX.characteristics, node))
            graph.add((node, RDF.type, CTX.CharacteristicObservation))
            graph.add((node, RDFS.label, Literal(name)))
            graph.add((node, CTX.characteristicValue, Literal(value)))

            if uncertain is not None:
                graph.add((node, CTX.uncertain, Literal(uncertain)))

    def compare(self, names=("culoare",)):
        return compare_occurrences(
            self.context,
            self.a,
            self.b,
            identity_names=names,
        )

    def test_comparison_reports_difference_with_evidence(self):
        result = self.compare()

        self.assertTrue(result.requires_confirmation)
        self.assertTrue(result.has_comparable_evidence)

        item = result.characteristics[0]
        self.assertEqual("different", item.status)
        self.assertEqual("albastru", item.left[0].value)
        self.assertEqual("roșu", item.right[0].value)

        self.assertIn(
            (self.a, CTX.characteristics, item.left[0].iri),
            self.context.observations,
        )

    def test_comparison_normalizes_spacing_and_unicode(self):
        self._set_characteristics(
            self.a, ("  FORMĂ ", " ovală ", False)
        )
        self._set_characteristics(
            self.b, ("forma\u0306", "ovala\u0306", False)
        )

        result = self.compare(("formă",))

        self.assertEqual(
            "unchanged", result.characteristics[0].status
        )
        self.assertFalse(result.requires_confirmation)
        self.assertTrue(result.has_comparable_evidence)

    def test_comparison_missing_values_are_unknown(self):
        self._set_characteristics(self.b)
        result = self.compare()

        self.assertEqual("missing", result.characteristics[0].reason)
        self.assertFalse(result.requires_confirmation)
        self.assertFalse(result.has_comparable_evidence)

    def test_comparison_uncertain_values_are_unknown(self):
        for marker in (True, None):
            with self.subTest(marker=marker):
                self._set_characteristics(
                    self.b, ("culoare", "roșu", marker)
                )
                result = self.compare()

                self.assertEqual(
                    "uncertain", result.characteristics[0].reason
                )
                self.assertFalse(result.requires_confirmation)
                self.assertFalse(result.has_comparable_evidence)

    def test_comparison_conflicting_duplicate_values_are_unknown(self):
        self._set_characteristics(
            self.a,
            ("culoare", "albastru", False),
            ("culoare", "verde", False),
        )

        result = self.compare()

        self.assertEqual(
            "multiple_values", result.characteristics[0].reason
        )
        self.assertFalse(result.requires_confirmation)

    def test_comparison_uses_only_selected_identity_characteristics(self):
        self._set_characteristics(
            self.a,
            ("culoare", "albastru", False),
            ("poziție", "stânga", False),
        )
        self._set_characteristics(
            self.b,
            ("culoare", "albastru", False),
            ("poziție", "dreapta", False),
        )

        result = self.compare()

        self.assertEqual(1, len(result.characteristics))
        self.assertEqual(
            "unchanged", result.characteristics[0].status
        )
        self.assertFalse(result.requires_confirmation)

    def test_comparison_preserves_case_sensitive_markings(self):
        self._set_characteristics(
            self.a, ("marcaj", "AB", False)
        )
        self._set_characteristics(
            self.b, ("marcaj", "ab", False)
        )

        self.assertTrue(
            self.compare(("marcaj",)).requires_confirmation
        )

    def test_comparison_does_not_modify_observations_or_decisions(self):
        self.confirm(self.a, self.b)
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        self.compare()

        self.assertEqual(
            before,
            set(self.context.dataset.quads((None, None, None, None))),
        )

    def test_comparison_rejects_invalid_inputs(self):
        for names in ((), (" ",), "culoare"):
            with self.subTest(names=names):
                with self.assertRaises(ValueError):
                    self.compare(names)

        for right in (self.a, URIRef("urn:test:unknown")):
            with self.subTest(right=right):
                with self.assertRaises(ValueError):
                    compare_occurrences(
                        self.context,
                        self.a,
                        right,
                        identity_names=("culoare",),
                    )

    def test_uncertain_entity_does_not_invalidate_clear_characteristics(self):
        self._set_characteristics(
            self.b, ("culoare", "albastru", False)
        )
        self.context.observations.set((
            self.b, CTX.uncertain, Literal(True)
        ))

        result = self.compare()

        self.assertEqual(
            "unchanged", result.characteristics[0].status
        )
        self.assertFalse(result.requires_confirmation)

    def test_legacy_features_do_not_become_certain_characteristics(self):
        for occurrence in (self.a, self.b):
            self._set_characteristics(occurrence)
            self.context.observations.add((
                occurrence,
                CTX.features,
                Literal("culoare albastră"),
            ))

        result = self.compare()

        self.assertEqual(
            "unknown", result.characteristics[0].status
        )
        self.assertFalse(result.requires_confirmation)
        self.assertFalse(result.has_comparable_evidence)


if __name__ == "__main__":
    unittest.main()