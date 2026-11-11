"""Integration tests with a real Tk widget tree and a mocked HTTP boundary."""
import hashlib
import json
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from rdflib import Graph

from gui.workflow_app import WorkflowGUI
from ontology.catalog import load_ontology_with_source
from ontology.context import build_ontology_context_with_source
from workflow.models import WorkflowSession
from workflow.service import create_session_from_images

import httpx
NAMESPACE = "https://example.test/eggs#"
ONTOLOGY = """
@prefix ex: <https://example.test/eggs#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.test/eggs> a owl:Ontology .
ex:Ou a owl:Class ; rdfs:label "ou"@ro .
ex:OuIncondeiat a owl:Class ; rdfs:subClassOf ex:Ou .
"""
OBSERVATION = {
    "description": "Imagine de test.",
    "entities": [], "relations": [], "actions": [],
    "visible_text": [], "uncertainties": [],
}


class WorkflowGUITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.paths = []
        for index in range(2):
            path = self.folder / f"frame{index}.png"
            Image.new("RGB", (640, 360), (100 + index, 60, 30)).save(path)
            self.paths.append(path)
        self.ontology = self.folder / "ontology.ttl"
        self.ontology.write_text(ONTOLOGY, encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.app = WorkflowGUI(
            self.root,
            api_keys={
                "openrouter": "test-openrouter-key",
                "gemini": "test-gemini-key",
            },
            model_defaults={
                "openrouter": "test:free",
                "gemini": "gemini-test",
            },
            initial_provider="openrouter",
            output_dir=self.folder,
        )
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def destroy_root(self):
        self.root.after_cancel(self.app.poll_id)
        self.root.destroy()

    def import_frames(self):
        self.app._handle_event("result", ("images", create_session_from_images(self.paths)))
        self.app._handle_event("done", None)
        self.app._select(True)

    def prepare_context(self):
        self.app.use_ontology_var.set(True)
        self.app._handle_event(
            "result",
            ("ontology", load_ontology_with_source(self.ontology)),
        )
        self.assertEqual(self.app.namespace_var.get(), NAMESPACE)
        source, context = build_ontology_context_with_source(
            self.ontology,
            NAMESPACE,
            cached_source=self.app.ontology_source,
        )
        self.app._handle_event(
            "result",
            ("context", (source, context)),
        )
        self.app._handle_event("done", None)
        return context

    def run_description(self):
        def fake_post(url, **kwargs):
            payload = json.loads(kwargs["content"])
            parts = payload["messages"][1]["content"]

            frame_ids = [
                json.loads(part["text"][len("FRAME_ID: "):])
                for part in parts
                if (
                        part.get("type") == "text"
                        and part["text"].startswith("FRAME_ID: ")
                )
            ]

            result = {
                "frames": [
                    {
                        "frame_id": frame_id,
                        "observation": {
                            **OBSERVATION,
                            "description": (
                                f"Descriere pentru {frame_id}."
                            ),
                        },
                    }
                    for frame_id in reversed(frame_ids)
                ],
            }

            return httpx.Response(
                200,
                json={
                    "model": payload["model"],
                    "id": "mock-request",
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(result),
                        },
                    }],
                    "usage": {"total_tokens": 100},
                },
            )

        def launch(kind, operation):
            self.app.busy = kind
            self.app._sync_controls()

            result = operation(
                threading.Event(),
                self.app._handle_event,
            )

            self.app._handle_event(
                "result",
                (kind, result),
            )
            self.app._handle_event("done", None)

        with (
            patch(
                "gui.workflow_app.messagebox.showerror"
            ) as errors,
            patch.object(
                self.app,
                "_launch",
                side_effect=launch,
            ),
            patch(
                "interpretation.strategies."
                "_chat_completions.httpx.post",
                side_effect=fake_post,
            ) as post,
        ):
            self.app._describe()
            errors.assert_not_called()

        return post

    def test_navigation_selection_and_optional_context(self):
        self.assertEqual(len(self.app.tabs.tabs()), 4)
        self.assertEqual(str(self.app.describe_button["state"]), "disabled")
        self.assertFalse(self.app.advanced_panel.winfo_manager())
        self.assertFalse(self.app.ontology_panel.winfo_manager())
        self.app.source_mode.set("images")
        self.app._show_source_mode()
        self.assertEqual(self.app.images_panel.winfo_manager(), "pack")
        self.assertFalse(self.app.video_panel.winfo_manager())
        self.import_frames()
        self.assertEqual(self.app.tabs.select(), str(self.app.frames_tab))
        for tab in (self.app.config_tab, self.app.results_tab, self.app.frames_tab):
            self.app.tabs.select(tab)
        self.assertEqual(len(self.app.gallery.selected_ids()), 2)
        self.assertEqual(len(self.app.result_tree.get_children()), 2)
        self.assertEqual(str(self.app.describe_button["state"]), "normal")
        self.app.use_ontology_var.set(True)
        self.assertEqual(str(self.app.describe_button["state"]), "disabled")
        self.app.use_ontology_var.set(False)
        self.assertEqual(str(self.app.describe_button["state"]), "normal")
        self.app._select(False)
        self.assertEqual(str(self.app.describe_button["state"]), "disabled")
        self.root.update()
        self.assertFalse(self.errors)

    def test_context_invalidation_format_and_empty_namespace(self):
        self.import_frames()
        context = self.prepare_context()
        self.assertTrue(context.turtle.endswith("\n"))
        self.assertEqual(self.app._capture_settings().context_turtle, context.turtle)
        self.assertEqual(str(self.app.describe_button["state"]), "normal")
        self.app.namespace_var.set("https://example.test/other#")
        self.assertIsNone(self.app.ontology_context)
        self.assertEqual(str(self.app.describe_button["state"]), "disabled")
        self.prepare_context()
        self.app.ontology_format_var.set("RDF/XML")
        self.assertIsNone(self.app.ontology_context)
        self.app.namespace_var.set("")
        self.assertEqual(str(self.app.generate_context_button["state"]), "disabled")

    def test_batch_prompt_provenance_export_and_existing_results(self):
        self.import_frames()
        context = self.prepare_context()
        self.app.language_var.set("Română")

        post = self.run_description()

        self.assertEqual(post.call_count, 1)

        payload = json.loads(
            post.call_args.kwargs["content"]
        )
        content = payload["messages"][1]["content"]

        self.assertIn(
            json.dumps(context.turtle, ensure_ascii=False),
            content[0]["text"],
        )
        self.assertIn("Romanian", content[0]["text"])

        images = [
            part for part in content
            if part["type"] == "image_url"
        ]
        self.assertEqual(len(images), 2)

        observations = [
            state.observation
            for state in self.app.session.frames
        ]

        for state in self.app.session.frames:
            self.assertEqual(
                state.description_status,
                "completed",
            )
            self.assertEqual(
                state.observation.frame_id,
                state.frame_id,
            )
            self.assertEqual(
                state.observation.observation.description,
                f"Descriere pentru {state.frame_id}.",
            )

        group_ids = {
            observation.usage["request_group_id"]
            for observation in observations
        }
        self.assertEqual(len(group_ids), 1)

        first = observations[0]
        provenance = first.parameters["ontology_context"]

        self.assertEqual(
            provenance["turtle"],
            context.turtle,
        )
        self.assertEqual(
            provenance["context_sha256"],
            hashlib.sha256(
                context.turtle.encode("utf-8")
            ).hexdigest(),
        )

        self.assertEqual(first.provider, "openrouter")
        self.assertEqual(first.parameters["batch"]["size"], 2)
        self.assertEqual(first.usage["scope"], "request")
        self.assertEqual(
            first.usage["request_usage"]["total_tokens"],
            100,
        )

        self.assertEqual(
            self.app.tabs.select(),
            str(self.app.results_tab),
        )
        self.assertEqual(
            self.app.result_tree.item(
                first.frame_id,
                "values",
            ),
            ("Descris",),
        )

        # Observațiile existente sunt păstrate fără alte apeluri.
        self.assertEqual(
            self.run_description().call_count,
            0,
        )

        # Regenerăm același grup fără context ontologic.
        self.app.regenerate_var.set(True)
        self.app.use_ontology_var.set(False)

        self.assertEqual(
            self.run_description().call_count,
            1,
        )
        self.assertIsNone(
            self.app.session.frames[0]
            .observation.parameters["ontology_context"]
        )

        # Obiectul anterior capturat nu a fost modificat.
        self.assertEqual(
            first.parameters["ontology_context"]["turtle"],
            context.turtle,
        )

        destination = self.folder / "session.jsonld"

        with patch(
            "gui.workflow_app.filedialog.asksaveasfilename",
            return_value=str(destination),
        ):
            self.app._save()

        text = destination.read_text(encoding="utf-8")
        exported = json.loads(text)
        settings = exported["interpretation_settings"]

        self.assertEqual(settings["provider"], "openrouter")
        self.assertEqual(settings["batch_size"], 3)
        self.assertEqual(
            settings["context_turtle"],
            context.turtle,
        )
        self.assertFalse(settings["use_ontology"])

        self.assertNotIn("test-openrouter-key", text)
        self.assertNotIn("test-gemini-key", text)

        self.assertGreater(
            len(Graph().parse(destination, format="json-ld")),
            0,
        )
        self.assertFalse(self.app.dirty)

    def test_changed_source_blocks_description_before_network(self):
        self.import_frames()
        self.prepare_context()
        self.ontology.write_text(ONTOLOGY + "\n# changed", encoding="utf-8")
        with patch("gui.workflow_app.messagebox.showerror") as error, patch(
                        "interpretation.strategies._chat_completions.httpx.post"
        ) as post:
            self.app._describe()
        error.assert_called_once()
        post.assert_not_called()
        self.assertIsNone(self.app.ontology_context)

    def test_busy_navigation_keeps_snapshot_and_disables_editing(self):
        self.import_frames()
        self.prepare_context()
        self.app.busy = "description"
        self.app._sync_controls()
        self.assertEqual(str(self.app.namespace_combo["state"]), "disabled")
        self.assertEqual(str(self.app.save_button["state"]), "disabled")
        self.assertEqual(str(self.app.cancel_button["state"]), "normal")
        self.app.tabs.select(self.app.config_tab)
        self.app._cancel()
        self.assertTrue(self.app.cancel_event.is_set())
        self.assertEqual(str(self.app.cancel_button["state"]), "disabled")
        self.app._handle_event("done", None)
        self.assertEqual(str(self.app.save_button["state"]), "normal")

    def test_legacy_session_gets_default_settings(self):
        self.import_frames()
        data = self.app.session.model_dump()
        data.pop("interpretation_settings")
        data["schema_version"] = "2.1"
        restored = WorkflowSession.model_validate(data)
        self.assertFalse(restored.interpretation_settings.use_ontology)

    def test_provider_switch_uses_correct_key_and_preserves_models(self):
        self.import_frames()

        self.app.model_var.set("custom-openrouter-model")

        openrouter_post = self.run_description()

        self.assertEqual(openrouter_post.call_count, 1)
        self.assertEqual(
            openrouter_post.call_args.args[0],
            "https://openrouter.ai/api/v1/chat/completions",
        )
        self.assertEqual(
            openrouter_post.call_args.kwargs[
                "headers"
            ]["Authorization"],
            "Bearer test-openrouter-key",
        )

        previous = self.app.session.frames[0].observation
        self.assertEqual(previous.provider, "openrouter")

        self.app.provider_var.set("gemini")

        self.assertEqual(
            self.app.model_var.get(),
            "gemini-test",
        )

        # Schimbarea furnizorului nu regenerează automat.
        self.assertEqual(
            self.run_description().call_count,
            0,
        )

        self.app.regenerate_var.set(True)
        gemini_post = self.run_description()

        self.assertEqual(gemini_post.call_count, 1)
        self.assertEqual(
            gemini_post.call_args.args[0],
            "https://generativelanguage.googleapis.com"
            "/v1beta/openai/chat/completions",
        )
        self.assertEqual(
            gemini_post.call_args.kwargs[
                "headers"
            ]["Authorization"],
            "Bearer test-gemini-key",
        )

        current = self.app.session.frames[0].observation

        self.assertEqual(current.provider, "gemini")
        self.assertEqual(current.requested_model, "gemini-test")
        self.assertEqual(previous.provider, "openrouter")

        # Revenirea la OpenRouter restaurează modelul introdus.
        self.app.provider_var.set("openrouter")

        self.assertEqual(
            self.app.model_var.get(),
            "custom-openrouter-model",
        )
        self.assertEqual(
            str(self.app.provider_combo["state"]),
            "readonly",
        )

    def test_context_reuses_unchanged_source_without_parsing(self):
        source, _ = load_ontology_with_source(self.ontology)

        with patch(
            "ontology.reader.Graph.parse",
            side_effect=AssertionError("Sursa nu trebuie reparsată."),
        ):
            reused, context = build_ontology_context_with_source(
                self.ontology,
                NAMESPACE,
                cached_source=source,
            )

        self.assertIs(reused, source)
        self.assertEqual(
            context.report["source_sha256"],
            source.source_sha256,
        )


if __name__ == "__main__":
    unittest.main()