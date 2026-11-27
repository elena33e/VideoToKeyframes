"""Integrarea propunerilor în contextul activ al interfeței."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rdflib import RDF

import tests.gui.test_workflow_gui as workflow_fixtures
import tests.ontology_population.test_population_sources as population_fixtures

from session_context.characteristics.graph import CTX
from session_context.graph import (
    entities_for_frame,
    snapshot_session_context,
)
from session_context.identity.graph import record_identity_decision
from session_context.identity.models import (
    IdentityDecision,
    TrackedObject,
)
from workflow.jsonld import session_to_jsonld


class PopulationContextGUITest(unittest.TestCase):
    def setUp(self):
        self.base = workflow_fixtures.WorkflowGUITest()
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.base.prepare_identity_session()

        self.app = self.base.app
        self.context = self.app._get_identity_context()
        self.source = self.app.ontology_source

        self.fake = population_fixtures.PopulationSourcesTest()
        self.fake.setUp()

        self.app._open_ontology()
        self.window = self.app.ontology_window
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.generating = False
        self.window.context_errors.clear()
        self.window.close()

    def records(self, context):
        return {
            subject
            for subject, _, _, _ in context.dataset.quads((
                None,
                RDF.type,
                CTX.CharacteristicSelectionProposal,
                None,
            ))
        }

    def confirm_identity(self, context):
        left, right = (
            entities_for_frame(context, frame_id)[0]
            for frame_id in context.frame_iris
        )
        tracked = TrackedObject(session_id=context.session_id)

        record_identity_decision(
            context,
            IdentityDecision(
                session_id=context.session_id,
                left_occurrence_iri=str(left),
                right_occurrence_iri=str(right),
                outcome="same_object",
                object_id=tracked.object_id,
                decided_by="test-user",
                justification="Confirmare manuală de test.",
            ),
            new_object=tracked,
        )

    def generate(self):
        context = self.app._current_population_context()
        self.window.generating = True

        with patch.dict(
            "gui.ontology.window.PROVIDERS",
            {
                "test": (
                    "TEST",
                    "test-model",
                    lambda **kwargs: self.fake.client,
                ),
            },
        ):
            self.window._generate(
                session_to_jsonld(self.app.session),
                str(self.source.path),
                "test",
                "test-model",
                2,
                snapshot_session_context(context),
            )

        batch = self.window.events.get_nowait()
        done = self.window.events.get_nowait()
        self.assertEqual("batch", batch[0])
        self.assertEqual("done", done[0])

        self.window.events.put(batch)
        self.window.events.put(done)
        return batch[1][1]

    def poll_once(self):
        if self.window.poll_id is not None:
            self.window.after_cancel(self.window.poll_id)
            self.window.poll_id = None
        self.window._poll()

    def test_received_report_preserves_decisions_made_after_generation(self):
        observations = set(self.context.observations)
        self.generate()

        # Decizia apare după realizarea copiei pentru generare.
        self.confirm_identity(self.context)
        identities = set(self.context.identities)

        self.poll_once()
        self.poll_once()

        self.assertIs(self.context, self.app.session_context)
        self.assertEqual(2, len(self.records(self.context)))
        self.assertEqual(observations, set(self.context.observations))
        self.assertEqual(identities, set(self.context.identities))
        self.assertTrue(self.app.session_context_dirty)
        self.assertFalse(self.window.generating)
        self.assertEqual([], self.window.context_errors)
        self.assertEqual(1, self.fake.client.generate.call_count)

    def test_active_identity_context_is_used_and_marked_dirty(self):
        replacement = snapshot_session_context(self.context)
        identity = SimpleNamespace(
            context=replacement,
            dirty=False,
            winfo_exists=lambda: True,
        )
        self.app.identity_window = identity
        self.addCleanup(
            setattr, self.app, "identity_window", None
        )

        report = self.generate()
        self.poll_once()
        self.poll_once()

        self.assertIs(replacement, self.app.session_context)
        self.assertEqual(set(), self.records(self.context))
        self.assertEqual(2, len(self.records(replacement)))
        self.assertTrue(identity.dirty)
        self.assertTrue(self.app.session_context_dirty)

        # Reimportarea aceluiași raport nu creează modificări noi.
        identity.dirty = False
        self.app.session_context_dirty = False
        before = set(replacement.dataset.quads(
            (None, None, None, None)
        ))

        self.app._receive_population_report(report, self.source)

        self.assertEqual(
            before,
            set(replacement.dataset.quads(
                (None, None, None, None)
            )),
        )
        self.assertFalse(identity.dirty)
        self.assertFalse(self.app.session_context_dirty)

    def test_changed_observations_keep_results_out_of_old_context(self):
        self.generate()
        before = set(self.context.dataset.quads(
            (None, None, None, None)
        ))

        self.app.regenerate_var.set(True)
        self.base.run_description()

        self.poll_once()
        self.poll_once()

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )
        self.assertEqual(2, self.window.received)
        self.assertIsNotNone(self.window.review)
        self.assertEqual(1, len(self.window.context_errors))
        self.assertIn(
            "Contextul nu a fost actualizat",
            self.window.status.get(),
        )

    def test_start_copies_current_context_and_blocks_main_close(self):
        replacement = snapshot_session_context(self.context)
        self.confirm_identity(replacement)
        self.app.session_context = replacement

        with patch("gui.ontology.window.Thread") as thread:
            self.window._start()

        copied = thread.call_args.kwargs["args"][-1]
        self.assertIsNot(copied, replacement)
        self.assertEqual(
            set(replacement.identities),
            set(copied.identities),
        )

        with (
            patch.object(self.base.root, "destroy") as destroy,
            patch("gui.workflow_app.messagebox.showinfo") as info,
        ):
            self.app._close()

        destroy.assert_not_called()
        info.assert_called_once()

    def test_popup_close_waits_for_received_reports(self):
        self.generate()
        self.window.close()

        self.assertTrue(self.window.winfo_exists())

        self.poll_once()
        self.poll_once()
        self.window.close()

        self.assertEqual(2, len(self.records(self.context)))
        self.assertTrue(self.app.session_context_dirty)
        self.assertFalse(self.window.winfo_exists())

if __name__ == "__main__":
    unittest.main()