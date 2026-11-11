import json
import unittest
from unittest.mock import patch

import httpx

from interpretation.contracts import (
    VLMError,
    VLMImage,
    VLMRequest,
)
from interpretation.strategies.gemini import GeminiStrategy
from interpretation.strategies.openrouter import OpenRouterStrategy
from interpretation.strategies.openai import OpenAIStrategy

HTTP_POST = (
    "interpretation.strategies._chat_completions.httpx.post"
)


class VLMStrategiesTest(unittest.TestCase):
    def setUp(self):
        self.request = VLMRequest(
            system_prompt="Descrie imaginile.",
            user_prompt="Context comun.",
            images=(
                VLMImage(
                    frame_id="frame-1",
                    mime_type="image/png",
                    data=b"imagine-simulata-1",
                ),
                VLMImage(
                    frame_id="frame-2",
                    mime_type="image/png",
                    data=b"imagine-simulata-2",
                ),
            ),
            response_schema={
                "type": "object",
                "properties": {
                    "frames": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["frames"],
                "additionalProperties": False,
            },
            max_output_tokens=8192,
        )

    def success_response(self):
        return httpx.Response(
            200,
            json={
                "id": "request-test",
                "model": "resolved-test-model",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"frames": []}',
                    },
                }],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    def test_strategies_use_the_same_contract(self):
        strategies = [
            GeminiStrategy(
                api_key="fake-key",
                model="gemini-test",
                reasoning_effort="low",
            ),
            OpenRouterStrategy(
                api_key="fake-key",
                model="provider/model-test",
                temperature=0.2,
                reasoning_enabled=False,
            ),
        ]

        for strategy in strategies:
            with self.subTest(provider=strategy.provider):
                with patch(
                    HTTP_POST,
                    return_value=self.success_response(),
                ) as post:
                    result = strategy.generate(self.request)

                payload = json.loads(
                    post.call_args.kwargs["content"]
                )

                self.assertEqual(
                    post.call_args.args[0],
                    strategy.ENDPOINT,
                )
                self.assertEqual(result.provider, strategy.provider)
                self.assertEqual(result.requested_model, strategy.model)
                self.assertEqual(result.resolved_model, "resolved-test-model")
                self.assertEqual(result.usage["total_tokens"], 120)
                self.assertEqual(payload["max_tokens"], 8192)

                parts = payload["messages"][1]["content"]
                images = [
                    part for part in parts
                    if part["type"] == "image_url"
                ]
                self.assertEqual(len(images), 2)

                if strategy.provider == "gemini":
                    self.assertEqual(payload["reasoning_effort"], "low")
                    self.assertNotIn("provider", payload)
                    self.assertNotIn("reasoning", payload)
                else:
                    self.assertTrue(
                        payload["provider"]["require_parameters"]
                    )
                    self.assertEqual(
                        payload["reasoning"], {"enabled": False}
                    )
                    self.assertNotIn("reasoning_effort", payload)

    def test_list_error_is_extracted_and_key_is_hidden(self):
        strategy = GeminiStrategy(
            api_key="fake-key",
            model="gemini-test",
        )
        response = httpx.Response(
            503,
            json=[{
                "error": {
                    "message": "High demand; fake-key",
                    "status": "UNAVAILABLE",
                },
            }],
        )

        with patch(HTTP_POST, return_value=response):
            with self.assertRaises(VLMError) as raised:
                strategy.generate(self.request)

        message = str(raised.exception)
        self.assertIn("503", message)
        self.assertIn("High demand", message)
        self.assertNotIn("fake-key", message)

    def test_truncated_response_is_rejected(self):
        strategy = OpenRouterStrategy(
            api_key="fake-key",
            model="provider/model-test",
        )
        response = httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"frames":'},
                }],
            },
        )

        with patch(HTTP_POST, return_value=response):
            with self.assertRaises(VLMError):
                strategy.generate(self.request)


    def test_openai_uses_correct_endpoint_and_parameters(self):
        strategy = OpenAIStrategy(
            api_key="fake-key",
            model="gpt-6.1-sol",
            reasoning_effort="low",
        )

        with patch(
            HTTP_POST,
            return_value=self.success_response(),
        ) as post:
            result = strategy.generate(self.request)

        payload = json.loads(post.call_args.kwargs["content"])

        self.assertEqual(
            post.call_args.args[0],
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer fake-key",
        )
        self.assertEqual(payload["max_completion_tokens"], 8192)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("provider", payload)
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertFalse(payload["store"])

        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"],
            self.request.response_schema,
        )

        images = [
            part
            for part in payload["messages"][1]["content"]
            if part["type"] == "image_url"
        ]
        self.assertEqual(len(images), 2)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(
            result.request_parameters["max_completion_tokens"],
            8192,
        )
        self.assertNotIn("fake-key", repr(result))


if __name__ == "__main__":
    unittest.main()