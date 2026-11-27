"""Propunerile se păstrează separat și își verifică sursele."""

import tempfile
import unittest
from pathlib import Path

from rdflib import (
    Graph,
    Literal,
    OWL,
    RDF,
    URIRef,
)

import tests.session_context.characteristics.test_characteristic_selection as fixtures
from session_context.persistence import (
    load_session_context,
    save_session_context,
)
from session_context.characteristics.graph import (
    CTX,
    SelectionProvenance,
    read_characteristic_selection,
    record_characteristic_selection,
    read_characteristic_selections,
)


class SelectionGraphTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.CharacteristicSelectionTest()
        self.base.setUp()
        self.context = self.base.context
        self.ontology = self.base.ontology
        self.proposal = self.base.proposal(
            self.base.appearance(self.base.a)
        )

        frame = self.context.frame_iris["frame-1"]
        analysis = self.context.observations.value(
            frame, CTX.observation, any=False
        )
        analysis_id = self.context.observations.value(
            analysis, CTX.analysisId, any=False
        )

        self.provenance = SelectionProvenance(
            session_id=self.context.session_id,
            observations_sha256=self.context.source_sha256,
            observations_turtle_sha256="1" * 64,
            identities_turtle_sha256="2" * 64,
            frame_id="frame-1",
            analysis_id=str(analysis_id),
            population_graph_iri="urn:test:population:run-1:frame-1",
            provider="test",
            model="test-model",
            prompt_version="test-prompt",
            message_id="test-request",
            ontology_turtle_sha256="3" * 64,
        )

    def quads(self):
        return set(self.context.dataset.quads(
            (None, None, None, None)
        ))

    def record(self, *, proposal=None, provenance=None):
        return record_characteristic_selection(
            self.context,
            self.proposal if proposal is None else proposal,
            provenance=(
                self.provenance if provenance is None else provenance
            ),
            ontology=self.ontology,
        )

    def read(self, record, *, context=None, ontology=None):
        return read_characteristic_selection(
            self.context if context is None else context,
            record,
            ontology=self.ontology if ontology is None else ontology,
        )

    def test_preserves_sources_status_and_provenance(self):
        observations = set(self.context.observations)
        identities = set(self.context.identities)

        record = self.record()
        data = self.read(record)

        self.assertEqual("proposal", data.proposal.status)
        self.assertEqual(self.proposal, data.proposal)
        self.assertEqual(self.provenance, data.provenance)
        self.assertEqual(observations, set(self.context.observations))
        self.assertEqual(identities, set(self.context.identities))

    def test_repeated_record_does_not_duplicate_data(self):
        first = self.record()
        before = self.quads()

        self.assertEqual(first, self.record())
        self.assertEqual(before, self.quads())

    def test_distinct_population_runs_remain_separate(self):
        first = self.record()
        second = self.record(
            provenance=self.provenance.model_copy(update={
                "population_graph_iri": (
                    "urn:test:population:run-2:frame-1"
                ),
            })
        )

        self.assertNotEqual(first, second)
        self.assertEqual(self.proposal, self.read(first).proposal)
        self.assertEqual(self.proposal, self.read(second).proposal)

    def test_invalid_provenance_leaves_no_partial_record(self):
        for changes in (
            {"session_id": "another-session"},
            {"observations_sha256": "f" * 64},
            {"frame_id": "missing-frame"},
            {"frame_id": "frame-2"},
            {"analysis_id": "another-analysis"},
        ):
            with self.subTest(changes=changes):
                before = self.quads()

                with self.assertRaises(ValueError):
                    self.record(
                        provenance=self.provenance.model_copy(
                            update=changes
                        )
                    )

                self.assertEqual(before, self.quads())

    def test_missing_or_foreign_sources_are_rejected(self):
        invalid = (
            self.base.proposal(),
            self.base.proposal(
                self.base.appearance(self.base.b)
            ),
            self.base.proposal(
                self.base.appearance(
                    self.base.a,
                    [self.base.interpretation(self.base.b)],
                )
            ),
        )

        for proposal in invalid:
            with self.subTest(proposal=proposal):
                before = self.quads()

                with self.assertRaises(ValueError):
                    self.record(proposal=proposal)

                self.assertEqual(before, self.quads())

    def test_save_reload_preserves_record_and_validation(self):
        record = self.record()
        expected = self.read(record)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            restored = load_session_context(path)

        self.assertEqual(
            expected,
            self.read(record, context=restored),
        )

    def test_changed_ontology_is_rejected_on_read(self):
        record = self.record()
        changed = Graph()

        for triple in self.ontology:
            changed.add(triple)

        changed.add((
            URIRef("urn:test:additional-class"),
            RDF.type,
            OWL.Class,
        ))

        with self.assertRaises(ValueError):
            self.read(record, ontology=changed)

    def test_changed_observations_are_rejected_on_read(self):
        record = self.record()
        self.context.observations.add((
            self.base.a,
            CTX.features,
            Literal("Informație adăugată ulterior."),
        ))

        with self.assertRaises(ValueError):
            self.read(record)

    def test_modified_summary_or_payload_is_rejected(self):
        for predicate, value in (
            (CTX.selectionStatus, Literal("accepted")),
            (CTX.selectionData, Literal("{}", datatype=RDF.JSON)),
        ):
            with self.subTest(predicate=predicate):
                self.setUp()
                record = self.record()
                self.context.dataset.graph(record).set((
                    record, predicate, value,
                ))

                with self.assertRaises(ValueError):
                    self.read(record)


    def test_collection_preserves_distinct_generations_without_changes(self):
        first = self.record()
        second = self.record(
            provenance=self.provenance.model_copy(update={
                "population_graph_iri": "urn:test:population:another-run",
            })
        )
        before = self.quads()

        records, issues = read_characteristic_selections(
            self.context,
            ontology=self.ontology,
        )

        self.assertEqual({first, second}, set(records))
        self.assertEqual({}, issues)
        self.assertEqual(before, self.quads())

    def test_collection_reports_bad_record_and_keeps_valid_record(self):
        bad = self.record()
        good = self.record(
            provenance=self.provenance.model_copy(update={
                "population_graph_iri": "urn:test:population:another-run",
            })
        )
        self.context.dataset.graph(bad).set((
            bad,
            CTX.selectionStatus,
            Literal("accepted"),
        ))
        before = self.quads()

        records, issues = read_characteristic_selections(
            self.context,
            ontology=self.ontology,
        )

        self.assertEqual({good}, set(records))
        self.assertEqual({bad}, set(issues))
        self.assertEqual("proposal", records[good].proposal.status)
        self.assertEqual(before, self.quads())


if __name__ == "__main__":
    unittest.main()