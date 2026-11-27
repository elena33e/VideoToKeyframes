"""Consultarea propunerilor păstrează sursele și statutul lor."""

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from rdflib import Literal

import tests.session_context.characteristics.test_selection_graph as fixtures

from gui.characteristic_review import CharacteristicProposalView
from session_context.characteristics.graph import CTX
from session_context.persistence import (
    load_session_context,
    save_session_context,
)


class CharacteristicReviewTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.SelectionGraphTest()
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.context = self.base.context

        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

        self.view = CharacteristicProposalView(
            self.root,
            get_context=lambda: self.context,
            ontology=self.base.ontology,
            frame_labels={
                frame_id: frame_id
                for frame_id in self.context.frame_iris
            },
        )
        self.addCleanup(self.view.destroy)

    def test_original_and_interpreted_values_are_shown_separately(self):
        source = self.base.base
        self.base.proposal = source.proposal(
            source.appearance(
                source.a,
                [source.interpretation(
                    source.a,
                    meaning="color",
                    normalized_value="blue",
                    target_kind="part",
                    part_name="componentă laterală",
                    uncertain=True,
                )],
            )
        )
        self.base.record()
        before = self.base.quads()

        self.view.refresh()

        root = self.view.tree.get_children()[0]
        appearance = self.view.tree.get_children(root)[0]
        characteristic = self.view.tree.get_children(appearance)[0]
        values = self.view.tree.item(characteristic, "values")

        self.assertEqual("albastru", values[0])
        self.assertEqual("color", values[1])
        self.assertEqual("blue", values[2])
        self.assertEqual("Parte: componentă laterală", values[3])

        self.view.tree.selection_set(characteristic)
        self.view._show_details()
        details = self.view.details.get("1.0", "end")

        self.assertIn("Statut: propunere", details)
        self.assertIn("Incertitudine observată: Nu", details)
        self.assertIn("Incertitudine interpretare: Da", details)
        self.assertEqual(before, self.base.quads())

    def test_unreadable_record_is_visible_with_its_reason(self):
        record = self.base.record()
        self.context.dataset.graph(record).set((
            record, CTX.selectionStatus, Literal("accepted")
        ))

        self.view.refresh()

        rows = self.view.tree.get_children()
        self.assertEqual(1, len(rows))
        self.assertIn(
            "Înregistrare neconsultabilă",
            self.view.tree.item(rows[0], "text"),
        )
        self.assertIn(
            "Rezumatul RDF",
            self.view.details.get("1.0", "end"),
        )

    def test_refresh_reads_the_reloaded_context(self):
        record = self.base.record()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            self.context = load_session_context(path)

        self.view.refresh()

        self.assertEqual(1, len(self.view.tree.get_children()))
        self.assertIn(
            str(record),
            self.view.details.get("1.0", "end"),
        )


if __name__ == "__main__":
    unittest.main()