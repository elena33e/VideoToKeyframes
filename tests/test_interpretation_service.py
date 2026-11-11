import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from interpretation.config import InterpretationConfig
from interpretation.contracts import (
    FrameInput,
    VLMError,
    VLMResponse,
)
from interpretation.service import BatchInterpretationService
from interpretation.strategies.base import VLMStrategy


class InterpretationServiceTest(unittest.TestCase):
    def setUp(self):
        self.strategy = Mock(spec=VLMStrategy)

        self.config = InterpretationConfig(
            language="Romanian",
            ontology_context="CONTEXT_TEST_UNIC",
        )

        self.service = BatchInterpretationService(
            self.strategy,
            self.config,
        )

        # Citirea imaginilor este simulată; folosim o cale existentă.
        path = Path(__file__).resolve()

        self.frames = [
            FrameInput(path, "frame-a"),
            FrameInput(path, "frame-b"),
        ]

        reader = patch(
            "interpretation.service.read_validated_image",
            return_value=(b"image-bytes", "image/png"),
        )
        reader.start()
        self.addCleanup(reader.stop)

    def make_item(self, frame_id):
        return {
            "frame_id": frame_id,
            "observation": {
                "description": f"Descriere pentru {frame_id}.",
                "entities": [],
                "relations": [],
                "actions": [],
                "visible_text": [],
                "uncertainties": [],
            },
        }

    def configure_response(self, items, finish_reason="stop"):
        self.strategy.generate.return_value = VLMResponse(
            content=json.dumps({"frames": items}),
            requested_model="test-model",
            resolved_model="test-model",
            provider="test-provider",
            api_request_id="request-test",
            finish_reason=finish_reason,
            elapsed_seconds=0.5,
            usage={"total_tokens": 120},
            request_parameters={"max_tokens": 8192},
        )

    def test_results_are_matched_by_id_and_usage_is_shared(self):
        self.configure_response([
            self.make_item("frame-b"),
            self.make_item("frame-a"),
        ])

        results = self.service.describe_batch(self.frames)

        self.assertEqual(
            results["frame-a"].observation.description,
            "Descriere pentru frame-a.",
        )
        self.assertEqual(
            results["frame-b"].observation.description,
            "Descriere pentru frame-b.",
        )

        request = self.strategy.generate.call_args.args[0]

        self.assertEqual(len(request.images), 2)
        self.assertEqual(request.max_output_tokens, 8192)
        self.assertEqual(
            request.user_prompt.count("CONTEXT_TEST_UNIC"),
            1,
        )

        first_usage = results["frame-a"].usage
        second_usage = results["frame-b"].usage

        self.assertEqual(
            first_usage["request_group_id"],
            second_usage["request_group_id"],
        )
        self.assertEqual(first_usage["scope"], "request")
        self.assertEqual(
            first_usage["request_usage"]["total_tokens"],
            120,
        )

        # Consumul nu este prezentat drept total per imagine.
        self.assertNotIn("total_tokens", first_usage)

    def test_missing_duplicate_and_unknown_ids_are_rejected(self):
        cases = [
            ["frame-a"],
            ["frame-a", "frame-a"],
            ["frame-a", "unknown"],
        ]

        for ids in cases:
            with self.subTest(ids=ids):
                self.configure_response([
                    self.make_item(frame_id)
                    for frame_id in ids
                ])

                with self.assertRaises(VLMError):
                    self.service.describe_batch(self.frames)

    def test_invalid_entity_reference_is_rejected(self):
        item = self.make_item("frame-a")
        item["observation"]["relations"] = [{
            "subject_id": "e1",
            "predicate": "lângă",
            "object_id": "e2",
        }]

        self.configure_response([
            item,
            self.make_item("frame-b"),
        ])

        with self.assertRaises(VLMError):
            self.service.describe_batch(self.frames)

    def test_duplicate_input_ids_do_not_call_strategy(self):
        duplicate_frames = [
            self.frames[0],
            self.frames[0],
        ]

        with self.assertRaises(ValueError):
            self.service.describe_batch(duplicate_frames)

        self.strategy.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()