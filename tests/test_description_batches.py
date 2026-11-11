"""Teste pentru anulare, regenerare și păstrarea rezultatelor."""

import hashlib
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import workflow.description_batch as batch_module
from interpretation.observations import FrameObservation, ImageObservation
from workflow.models import ImportedFrame, KeyframeState, WorkflowSession


class DescriptionBatchTest(unittest.TestCase):
    def setUp(self):
        # Testăm coordonarea procesării, nu decodarea imaginilor.
        # Fișierele existente simulează sursele cadrelor.
        paths = [
            Path(__file__).resolve(),
            Path(batch_module.__file__).resolve(),
        ]
        frames = tuple(
            ImportedFrame(frame_id=f"frame-{i}", image_path=path)
            for i, path in enumerate(paths)
        )

        self.session = WorkflowSession(
            imported_frames=frames,
            frames=tuple(
                KeyframeState(frame_id=frame.frame_id, selected=True)
                for frame in frames
            ),
        )
        self.describer = Mock()
        self.describer.describe_batch.side_effect = self.make_results

    def make_results(self, group):
        return {
            frame.frame_id: FrameObservation(
                schema_version="1.0",
                frame_id=frame.frame_id,
                scene_index=frame.scene_index,
                image_sha256=hashlib.sha256(
                    frame.image_path.read_bytes()
                ).hexdigest(),
                created_at="2026-01-01T00:00:00+00:00",
                prompt_version="test",
                requested_model="test",
                resolved_model="test",
                provider="test",
                api_request_id=None,
                elapsed_seconds=0.0,
                parameters={},
                usage={},
                observation=ImageObservation(
                    description=f"Descriere pentru {frame.frame_id}.",
                    entities=[],
                    relations=[],
                    actions=[],
                    visible_text=[],
                    uncertainties=[],
                ),
            )
            for frame in group
        }

    def run_batch(self, session=None, **options):
        options = {
            "batch_size": 1,
            "min_interval_seconds": 0.0,
            **options,
        }
        return list(
            batch_module.describe_selected_batches(
                self.session if session is None else session,
                self.describer,
                **options,
            )
        )

    def test_cancel_before_request_keeps_pending_frames(self):
        cancel = Event()
        cancel.set()

        events = self.run_batch(cancel_event=cancel)

        self.describer.describe_batch.assert_not_called()
        self.assertEqual(events[-1].kind, "batch_cancelled")
        self.assertTrue(
            all(
                state.description_status == "pending"
                for state in events[-1].session.frames
            )
        )

    def test_cancel_before_call_restores_state(self):
        cancel = Event()
        events = []

        for event in batch_module.describe_selected_batches(
            self.session,
            self.describer,
            batch_size=1,
            min_interval_seconds=0.0,
            cancel_event=cancel,
        ):
            events.append(event)
            if event.kind == "frame_started":
                cancel.set()

        self.describer.describe_batch.assert_not_called()
        self.assertEqual(events[-1].kind, "batch_cancelled")
        self.assertTrue(
            all(
                state.description_status == "pending"
                for state in events[-1].session.frames
            )
        )

        # Revenirea la starea inițială nu modifică un eveniment anterior.
        started = next(
            event for event in events if event.kind == "frame_started"
        )
        self.assertEqual(
            started.session.frames[0].description_status,
            "running",
        )

    def test_cancel_during_call_preserves_received_result(self):
        cancel = Event()

        def respond(group):
            results = self.make_results(group)
            cancel.set()
            return results

        self.describer.describe_batch.side_effect = respond

        events = self.run_batch(cancel_event=cancel)

        self.assertEqual(self.describer.describe_batch.call_count, 1)
        self.assertEqual(events[-1].kind, "batch_cancelled")
        self.assertEqual(events[-1].processed, 1)

        first, second = events[-1].session.frames
        self.assertEqual(first.description_status, "completed")
        self.assertIsNotNone(first.observation)
        self.assertEqual(second.description_status, "pending")

        # Sesiunea primită inițial nu este modificată.
        self.assertTrue(
            all(
                state.description_status == "pending"
                for state in self.session.frames
            )
        )

    def test_failed_regeneration_preserves_previous_observations(self):
        previous = self.run_batch()[-1].session
        self.describer.describe_batch.side_effect = RuntimeError(
            "Eroare simulată"
        )

        events = self.run_batch(previous, regenerate=True)

        self.assertEqual(events[-1].failed, 2)

        for before, after in zip(
            previous.frames,
            events[-1].session.frames,
        ):
            self.assertEqual(before.description_status, "completed")
            self.assertEqual(after.description_status, "failed")
            self.assertEqual(after.observation, before.observation)
            self.assertIn("Eroare simulată", after.error)

    def test_existing_observations_skip_api_calls(self):
        previous = self.run_batch()[-1].session
        self.describer.describe_batch.reset_mock()

        events = self.run_batch(previous)

        self.describer.describe_batch.assert_not_called()
        self.assertEqual(events[-1].skipped, 2)
        self.assertEqual(events[-1].session.frames, previous.frames)

    def test_invalid_result_rejects_entire_group(self):
        def respond(group):
            results = self.make_results(group)
            invalid = results[group[1].frame_id].model_dump()
            invalid["scene_index"] = 999
            results[group[1].frame_id] = invalid
            return results

        self.describer.describe_batch.side_effect = respond

        events = self.run_batch(batch_size=2)

        self.assertEqual(events[-1].failed, 2)
        self.assertFalse(
            any(event.kind == "frame_completed" for event in events)
        )
        self.assertTrue(
            all(
                state.observation is None
                for state in events[-1].session.frames
            )
        )


if __name__ == "__main__":
    unittest.main()