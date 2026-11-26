"""Verificări ale ferestrei de revizie, fără apeluri AI."""

import hashlib
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from rdflib import Literal

import test_session_identity as fixtures
from gui.identity_review import IdentityReviewWindow
from session_context.identity_graph import object_for_occurrence


CTX = fixtures.CTX


class SessionIdentityGUITest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SessionIdentityTest()
        self.fixture.setUp()
        self.context = self.fixture.context
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        paths = {}
        for index, color in enumerate(("blue", "red", "green"), 1):
            frame_id = f"frame-{index}"
            path = Path(self.directory.name) / f"{frame_id}.png"
            with Image.new("RGB", (40, 40), color=color) as image:
                image.save(path)
            analysis = self.context.observations.value(
                self.context.frame_iris[frame_id], CTX.observation
            )
            self.context.observations.set((
                analysis, CTX.imageSha256,
                Literal(hashlib.sha256(path.read_bytes()).hexdigest()),
            ))
            paths[frame_id] = path
        self.paths = paths
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.window = IdentityReviewWindow(
            self.root, context=self.context, image_paths=paths
        )
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.window.minimum.set("1")
        self.window.traits.selection_set(0)
        self.window.actor.set("test_user")
        self.error_patch = patch(
            "gui.identity_review.messagebox.showerror",
            side_effect=AssertionError("A apărut o eroare GUI neașteptată."),
        )
        self.error_patch.start()
        self.addCleanup(self.error_patch.stop)

    def test_manual_confirmation_preserves_observations(self):
        before = set(self.context.observations)
        self.assertTrue(self.window.evaluate())
        self.assertEqual("confirmation", self.window.selected.action)
        self.assertEqual(
            "normal",
            str(self.window.decision_buttons["same_object"]["state"]),
        )
        self.window.justification.insert("1.0", "Același obiect, cu o culoare nouă.")
        self.assertTrue(self.window.decide("same_object"))
        self.assertEqual(
            object_for_occurrence(self.context, self.fixture.a),
            object_for_occurrence(self.context, self.fixture.b),
        )
        self.assertIsNotNone(object_for_occurrence(self.context, self.fixture.b))
        self.assertEqual(before, set(self.context.observations))
        self.assertTrue(self.window.dirty)

    def test_changed_image_blocks_confirmation_and_unknown_traits_do_not_prompt(self):
        self.paths["frame-2"].write_bytes(b"changed")
        self.assertTrue(self.window.evaluate())
        for outcome in ("same_object", "different_objects"):
            self.assertEqual(
                "disabled", str(self.window.decision_buttons[outcome]["state"])
            )
        self.assertEqual(
            "normal", str(self.window.decision_buttons["unresolved"]["state"])
        )
        with patch("gui.identity_review.messagebox.showerror") as error:
            self.assertFalse(self.window.decide("same_object"))
            error.assert_called_once()
        self.fixture._set_characteristics(
            self.fixture.b, ("culoare", "roșu", True)
        )
        self.assertTrue(self.window.evaluate())
        self.assertEqual("unresolved", self.window.selected.action)
        self.assertTrue(all(
            str(button["state"]) == "disabled"
            for button in self.window.decision_buttons.values()
        ))
        self.assertEqual(0, len(self.context.identities))

    def test_save_load_and_cancel_close_preserve_decisions(self):
        self.assertTrue(self.window.evaluate())
        self.window.justification.insert("1.0", "Dovezi insuficiente pentru decizie.")
        self.assertTrue(self.window.decide("unresolved"))
        expected = set(self.window.context.identities)
        path = Path(self.directory.name) / "context.trig"
        with patch(
            "gui.identity_review.filedialog.asksaveasfilename",
            return_value=str(path),
        ):
            self.assertTrue(self.window.save())
        self.assertFalse(self.window.dirty)
        self.window.context.identities.remove((None, None, None))
        with patch(
            "gui.identity_review.filedialog.askopenfilename",
            return_value=str(path),
        ):
            self.assertTrue(self.window.load())
        self.assertEqual(expected, set(self.window.context.identities))
        self.assertIn(
            "Dovezi insuficiente pentru decizie.",
            self.window.history.get("1.0", "end"),
        )
        self.window.dirty = True
        with patch(
            "gui.identity_review.messagebox.askyesnocancel", return_value=None
        ):
            self.assertFalse(self.window.close())
        self.assertFalse(self.window.closed)


if __name__ == "__main__":
    unittest.main()
