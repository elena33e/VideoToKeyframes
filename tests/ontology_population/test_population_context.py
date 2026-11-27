"""Selecțiile din populare ajung în context cu sursele păstrate."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import tests.ontology_population.test_population_sources as fixtures

from ontology.reader import read_ontology_source
from ontology_population.context import record_population_report
from ontology_population.review import build_review_frames
from ontology_population.revision import GraphRevision
from ontology_population.session import iter_population_reports
from ontology_population.storage import save_review_report
from session_context.characteristics.graph import (
    read_characteristic_selection,
)
from session_context.graph import build_session_context
from rdflib import Graph, Literal, URIRef

from session_context.identity.analysis import IdentityAnalysisProposal
from session_context.identity.analysis_graph import (
    CTX,
    read_identity_analysis,
    read_identity_analyses,
)
from session_context.persistence import (
    load_session_context,
    save_session_context,
)

class PopulationContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

        ontology_path = self.folder / "ontology.ttl"
        ontology_path.write_text(fixtures.ONTOLOGY, encoding="utf-8")
        self.ontology = read_ontology_source(
            ontology_path, rdf_format="turtle"
        )

        self.base = fixtures.PopulationSourcesTest()
        self.base.setUp()
        observations = [
            self.base.observation("frame-1"),
            self.base.observation("frame-2", color="roșu"),
        ]
        result = self.base.populate(observations)

        self.session = self.base.session_document()
        self.context = build_session_context(self.session)
        self.report = {
            "ontology_source_sha256": self.ontology.source_sha256,
            "provider": "test",
            "requested_model": "test-model",
            "sources": {
                analysis_id: {
                    "frame_id": saved["frame_id"],
                    "image_path": None,
                    "image_sha256": saved["image_sha256"],
                }
                for analysis_id, saved in self.base.saved.items()
            },
            **asdict(result),
        }

    def quads(self):
        return set(self.context.dataset.quads(
            (None, None, None, None)
        ))

    def record(self, report=None):
        return record_population_report(
            self.context,
            self.report if report is None else report,
            ontology_source=self.ontology,
        )

    def test_records_selection_with_real_report_provenance(self):
        observations = set(self.context.observations)
        identities = set(self.context.identities)

        records = self.record()

        self.assertEqual(2, len(records))
        for analysis_id, record in records.items():
            data = read_characteristic_selection(
                self.context,
                record,
                ontology=self.ontology.graph,
            )
            self.assertEqual("proposal", data.proposal.status)
            self.assertEqual(analysis_id, data.provenance.analysis_id)
            self.assertEqual(
                self.report["graphs"][analysis_id]["jsonld"]["@id"],
                data.provenance.population_graph_iri,
            )
            self.assertEqual(
                self.report["context_provenance"][
                    "identities_turtle_sha256"
                ],
                data.provenance.identities_turtle_sha256,
            )

        self.assertEqual(observations, set(self.context.observations))
        self.assertEqual(identities, set(self.context.identities))
        self.assertEqual(1, self.base.client.generate.call_count)

    def test_reimport_does_not_duplicate_records(self):
        expected = self.record()
        before = self.quads()

        self.assertEqual(expected, self.record())
        self.assertEqual(before, self.quads())

    def test_invalid_second_selection_leaves_no_partial_import(self):
        report = deepcopy(self.report)
        second = list(report["graphs"].values())[1]
        second["characteristic_selection"]["appearances"][0][
            "characteristics"
        ].pop()
        before = self.quads()

        with self.assertRaises(ValueError):
            self.record(report)

        self.assertEqual(before, self.quads())

    def test_wrong_context_or_image_is_rejected(self):
        wrong_context = deepcopy(self.report)
        wrong_context["context_provenance"][
            "observations_sha256"
        ] = "f" * 64

        wrong_image = deepcopy(self.report)
        first_source = next(iter(wrong_image["sources"].values()))
        first_source["image_sha256"] = "f" * 64

        for report in (wrong_context, wrong_image):
            with self.subTest(report=report):
                before = self.quads()

                with self.assertRaises(ValueError):
                    self.record(report)

                self.assertEqual(before, self.quads())

    def test_legacy_report_creates_no_selection_records(self):
        report = deepcopy(self.report)
        for candidate in report["graphs"].values():
            candidate.pop("characteristic_selection")
            candidate.pop("identity_analysis")

        before = self.quads()
        self.assertEqual({}, self.record(report))
        self.assertEqual(before, self.quads())

    def test_saved_review_can_reuse_the_same_records(self):
        expected = self.record()
        before = self.quads()
        frames = build_review_frames(self.session, self.report)
        path = self.folder / "review.json"

        save_review_report(
            path,
            frames,
            {
                frame.analysis_id: GraphRevision(frame.graph)
                for frame in frames
            },
        )
        restored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(expected, self.record(restored))
        self.assertEqual(before, self.quads())

    def test_population_iterator_updates_its_working_context(self):
        self.base.client.generate.reset_mock()
        observations = set(self.context.observations)

        reports = list(iter_population_reports(
            self.session,
            ontology_source=self.ontology,
            client=self.base.client,
            provider="test",
            requested_model="test-model",
            batch_size=2,
            context=self.context,
        ))

        self.assertEqual(1, len(reports))
        self.assertEqual(1, self.base.client.generate.call_count)
        records = reports[0]["characteristic_selection_records"]
        self.assertEqual(2, len(records))

        for record in records.values():
            data = read_characteristic_selection(
                self.context,
                record,
                ontology=self.ontology.graph,
            )
            self.assertEqual("proposal", data.proposal.status)

        self.assertEqual(observations, set(self.context.observations))

    def test_records_identity_analysis_with_sources_and_provenance(self):
        observations = set(self.context.observations)
        identities = set(self.context.identities)

        self.record()

        records, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )

        self.assertEqual({}, issues)
        self.assertEqual(2, len(records))
        self.assertEqual(
            set(self.report["graphs"]),
            {
                data.provenance.analysis_id
                for data in records.values()
            },
        )

        for data in records.values():
            analysis_id = data.provenance.analysis_id
            candidate = self.report["graphs"][analysis_id]
            expected = IdentityAnalysisProposal.model_validate(
                candidate["identity_analysis"]
            )

            self.assertEqual(expected, data.proposal)
            self.assertEqual("proposal", data.proposal.status)
            self.assertEqual(
                candidate["jsonld"]["@id"],
                data.provenance.population_graph_iri,
            )
            self.assertEqual(
                self.report["context_provenance"][
                    "identities_turtle_sha256"
                ],
                data.provenance.identities_turtle_sha256,
            )

        self.assertEqual(
            observations, set(self.context.observations)
        )
        self.assertEqual(
            identities, set(self.context.identities)
        )
        self.assertEqual(1, self.base.client.generate.call_count)

    def test_invalid_second_identity_analysis_prevents_whole_import(self):
        report = deepcopy(self.report)
        second = list(report["graphs"].values())[1]
        second["identity_analysis"]["appearances"].pop()
        before = self.quads()

        with self.assertRaises(ValueError):
            self.record(report)

        self.assertEqual(before, self.quads())

    def test_identity_analysis_can_be_imported_without_selection(self):
        report = deepcopy(self.report)
        for candidate in report["graphs"].values():
            candidate.pop("characteristic_selection")

        self.assertEqual({}, self.record(report))

        records, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )
        self.assertEqual({}, issues)
        self.assertEqual(2, len(records))

    def test_identity_analyses_survive_context_save_and_reload(self):
        self.record()
        expected, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )
        self.assertEqual({}, issues)

        path = self.folder / "context.trig"
        save_session_context(self.context, path)
        restored = load_session_context(path)

        actual, issues = read_identity_analyses(
            restored,
            ontology=self.ontology.graph,
        )

        self.assertEqual({}, issues)
        self.assertEqual(expected, actual)

    def test_changed_ontology_invalidates_identity_analysis_on_read(self):
        self.record()
        records, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )
        self.assertEqual({}, issues)
        record = next(iter(records))

        changed = Graph()
        for triple in self.ontology.graph:
            changed.add(triple)
        changed.add((
            URIRef("urn:test:additional-subject"),
            URIRef("urn:test:additional-property"),
            Literal("Informație ontologică suplimentară."),
        ))

        with self.assertRaises(ValueError):
            read_identity_analysis(
                self.context,
                record,
                ontology=changed,
            )

    def test_bad_identity_record_does_not_hide_valid_records(self):
        self.record()
        records, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )
        self.assertEqual({}, issues)

        bad = next(iter(records))
        self.context.dataset.graph(bad).set((
            bad,
            CTX.analysisStatus,
            Literal("accepted"),
        ))
        before = self.quads()

        valid, issues = read_identity_analyses(
            self.context,
            ontology=self.ontology.graph,
        )

        self.assertEqual(set(records) - {bad}, set(valid))
        self.assertEqual({bad}, set(issues))
        self.assertEqual(before, self.quads())


if __name__ == "__main__":
    unittest.main()