"""Revizia comparațiilor propuse păstrează sursele explicite."""

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from rdflib import Literal

import tests.session_context.characteristics.test_proposed_comparison as fixtures

from gui.proposed_comparison_view import ProposedComparisonView
from session_context.characteristics.graph import CTX
from session_context.persistence import (
    load_session_context,
    save_session_context,
)


class ProposedComparisonGUITest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ProposedComparisonTest()
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.context = self.base.context
        self.left_record = self.base.store(
            self.base.a, "frame-1"
        )
        self.right_record = self.base.store(
            self.base.b, "frame-2"
        )
        self.frame_pair = ["frame-1", "frame-2"]

        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

        self.view = ProposedComparisonView(
            self.root,
            get_context=lambda: self.context,
            get_frame_pair=lambda: (
                self.frame_pair[0], self.frame_pair[1]
            ),
            ontology=self.base.ontology,
            frame_labels={
                frame_id: frame_id
                for frame_id in self.context.frame_iris
            },
        )
        self.addCleanup(self.view.destroy)

    def select_records(self, *, right_record=None):
        chosen_right = (
            self.right_record
            if right_record is None
            else right_record
        )
        pairs = (
            (self.base.a, self.left_record),
            (self.base.b, chosen_right),
        )
        for side, pair in enumerate(pairs):
            self.view.choices[side].current(
                self.view.entries[side].index(pair)
            )
        self.view._selection_changed()

    def quads(self):
        return set(self.context.dataset.quads(
            (None, None, None, None)
        ))

    def test_explicit_comparison_preserves_context_and_proposal_status(self):
        self.assertEqual(-1, self.view.choices[0].current())
        self.assertEqual(-1, self.view.choices[1].current())
        self.select_records()
        before = self.quads()

        self.assertTrue(self.view.compare())

        result = self.view.last_result
        self.assertIsNotNone(result)
        self.assertEqual("proposal", result.status)
        self.assertEqual(self.left_record, result.left_record_iri)
        self.assertEqual(self.right_record, result.right_record_iri)
        self.assertEqual(before, self.quads())
        self.assertEqual(0, len(self.context.identities))

        row = self.view.tree.get_children()[0]
        values = self.view.tree.item(row, "values")
        self.assertEqual("albastru", values[0])
        self.assertEqual("roșu", values[2])
        self.assertEqual("Valori propuse diferite", values[4])

    def test_new_generation_does_not_replace_the_explicit_choice(self):
        self.select_records()
        self.assertTrue(self.view.compare())

        another = self.base.store(
            self.base.b,
            "frame-2",
            normalized_value=None,
        )
        self.view.refresh()

        self.assertIsNone(self.view.last_result)
        self.assertEqual(
            (self.base.b, self.right_record),
            self.view._selected_entry(1),
        )
        self.assertIn(
            (self.base.b, another),
            self.view.entries[1],
        )

        self.select_records(right_record=another)
        self.assertTrue(self.view.compare())
        row = self.view.tree.get_children()[0]
        values = self.view.tree.item(row, "values")

        self.assertEqual("Necunoscut", values[4])
        self.assertIn(
            "Lipsește cel puțin o valoare normalizată",
            self.view.details.get("1.0", "end"),
        )

    def test_invalidated_record_clears_the_previous_result(self):
        self.select_records()
        self.assertTrue(self.view.compare())
        self.context.dataset.graph(self.left_record).set((
            self.left_record,
            CTX.selectionStatus,
            Literal("accepted"),
        ))
        before = self.quads()

        self.assertFalse(self.view.compare())

        self.assertIsNone(self.view.last_result)
        self.assertEqual((), self.view.tree.get_children())
        self.assertEqual(before, self.quads())

        self.view.refresh()
        self.assertIsNone(self.view._selected_entry(0))
        self.assertIn(self.left_record, self.view.issues)

    def test_changing_frames_clears_unavailable_selections(self):
        self.select_records()
        self.assertTrue(self.view.compare())

        self.frame_pair[1] = "frame-3"
        self.view.refresh()

        self.assertIsNone(self.view.last_result)
        self.assertIsNone(self.view._selected_entry(1))
        self.assertFalse(self.view.compare())

    def test_comparison_reads_the_reloaded_context(self):
        self.select_records()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            self.context = load_session_context(path)

        self.view.refresh()
        before = self.quads()

        self.assertTrue(self.view.compare())
        self.assertEqual(
            self.right_record,
            self.view.last_result.right_record_iri,
        )
        self.assertEqual(before, self.quads())


if __name__ == "__main__":
    unittest.main()