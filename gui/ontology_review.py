"""Fereastra de revizie a grafurilor candidate."""

import argparse
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Any

from PIL import Image, ImageOps, ImageTk
from urllib.parse import unquote

from rdflib import Graph, RDFS, URIRef, RDF
from ontology_population.revision import GraphRevision, Relation

from ontology_population.review import (
    ReviewFrame,
    individuals_by_class,
    load_review_frames,
)


def _label(graph: Graph, iri: URIRef) -> str:
    label = graph.value(iri, RDFS.label)
    if label is not None:
        return str(label)

    local_name = str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return unquote(local_name) or str(iri)

def _source_text(observation: dict[str, Any]) -> str:
    names = {
        entity["id"]: entity["name"] + (
            " (identificare incertă)" if entity.get("uncertain") is True else ""
        )
        for entity in observation["entities"]
    }
    entities = [
        (
                        f"{' — '.join([entity['name'], *entity['features']])}\n"
            f"  Poziție: {entity['location']} · Vizibilitate: {entity['visibility']}",
            entity.get("uncertain"),
        )
        for entity in observation["entities"]
    ]
    relations = [
        (
            f"{names[relation['subject_id']]} — {relation['predicate']} — "
            f"{names[relation['object_id']]}",
            relation.get("uncertain"),
        )
        for relation in observation["relations"]
    ]
    actions = [
        (
            action["description"] + (
                "\n  Participanți: "
                + ", ".join(names[entity_id] for entity_id in action["entity_ids"])
                if action["entity_ids"] else ""
            ),
            action.get("uncertain"),
        )
        for action in observation["actions"]
    ]

    lines = [observation["description"]]
    hypotheses = []
    for title, entries in (
        ("Obiecte", entities),
        ("Relații", relations),
        ("Acțiuni", actions),
    ):
        lines.extend(["", title])
        for text, uncertain in entries:
            if uncertain is True:
                hypotheses.append(f"• {text}")
            else:
                marker = " (nemarcat)" if uncertain is None else ""
                lines.append(f"• {text}{marker}")

    if observation["visible_text"]:
        lines.extend(["", "Text vizibil", *observation["visible_text"]])

    hypotheses.extend(f"• {text}" for text in observation["uncertainties"])
    lines.extend(["", "Ipoteze de verificat"])
    lines.extend(hypotheses or ["Nicio ipoteză în observația sursă."])
    return "\n".join(lines)


class OntologyReview(ttk.Frame):
    def __init__(self, parent: tk.Misc, frames: list[ReviewFrame]) -> None:
        super().__init__(parent, padding=12)
        self.frames: list[ReviewFrame] = []
        self.individuals_by_row: dict[str, URIRef] = {}

        self.revisions: dict[str, GraphRevision] = {}
        self.relations_by_row: dict[str, Relation] = {}

        ttk.Label(self, text="Cadru").pack(anchor="w")
        self.selector = ttk.Combobox(self, state="readonly")
        self.selector.pack(fill="x", pady=(4, 12))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        tree_panel = ttk.Frame(body)
        body.add(tree_panel, weight=2)
        self.tree = ttk.Treeview(tree_panel, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Clasă / individ")
        tree_scroll = ttk.Scrollbar(
            tree_panel, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        tabs = ttk.Notebook(body)
        body.add(tabs, weight=3)

        detail_panel = ttk.Frame(tabs, padding=8)
        tabs.add(detail_panel, text="Fișa individului")
        self.details = ScrolledText(detail_panel, wrap="word", state="disabled", width=45, height=6)
        self.details.pack(fill="both", expand=True)

        relations_panel = ttk.Frame(detail_panel)
        relations_panel.pack(fill="both", expand=True, pady=(8, 0))
        self.relation_table = ttk.Treeview(
            relations_panel,
            columns=("property", "target"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        self.relation_table.heading("property", text="Proprietate")
        self.relation_table.heading("target", text="Individ țintă")
        self.relation_table.column("property", width=175)
        self.relation_table.column("target", width=180)
        scroll = ttk.Scrollbar(
            relations_panel, orient="vertical", command=self.relation_table.yview
        )
        self.relation_table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.relation_table.pack(side="left", fill="both", expand=True)
        self.relation_table.bind("<<TreeviewSelect>>", self._sync_edit_buttons)

        actions = ttk.Frame(detail_panel)
        actions.pack(fill="x", pady=(6, 0))
        self.remove_button = ttk.Button(
            actions, text="Elimină relația", state="disabled",
            command=self._remove_selected_relation,
        )
        self.remove_button.pack(side="left")

        self.change_target_button = ttk.Button(
            actions, text="Schimbă ținta…", state="disabled",
            command=self._change_relation_target,
        )
        self.change_target_button.pack(side="left", padx=(6, 0))

        self.undo_button = ttk.Button(
            actions, text="Anulează ultima modificare", state="disabled",
            command=self._undo_relation_removal,
        )
        self.undo_button.pack(side="left", padx=(6, 0))

        source_panel = ttk.Frame(tabs, padding=8)
        tabs.add(source_panel, text="Imagine și observație")
        self.source_photo = None
        self.source_image = ttk.Label(source_panel, anchor="center")
        self.source_image.pack(fill="x", pady=(0, 8))
        self.source_text = ScrolledText(
            source_panel, wrap="word", state="disabled", width=45, height=12
        )
        self.source_text.pack(fill="both", expand=True)

        check_panel = ttk.Frame(tabs, padding=8)
        tabs.add(check_panel, text="Vocabular și IRI-uri")
        self.check_text = ScrolledText(
            check_panel, wrap="word", state="disabled", width=45
        )
        self.check_text.pack(fill="both", expand=True)

        self.selector.bind("<<ComboboxSelected>>", self._show_frame)
        self.tree.bind("<<TreeviewSelect>>", self._show_individual)
        self.add_frames(frames)

    def add_frames(self, frames: list[ReviewFrame]) -> None:
        first_load = not self.frames
        self.frames.extend(frames)
        self.revisions.update({
            frame.analysis_id: GraphRevision(frame.graph) for frame in frames
        })
        self.selector.configure(values=[
            f"{index}. {frame.image_path.name if frame.image_path else frame.frame_id}"
            for index, frame in enumerate(self.frames, start=1)
        ])
        if first_load and self.frames:
            self.selector.current(0)
            self._show_frame()

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _show_frame(self, _event=None) -> None:
        frame = self.frames[self.selector.current()]
        graph = frame.graph
        self._show_source(frame)
        issues = frame.vocabulary_issues

        if issues is None:
            text = "Verificarea vocabularului și a IRI-urilor nu a fost rulată."
        elif issues:
            text = "\n".join(f"• {issue}" for issue in issues)
        else:
            text = "Vocabularul și IRI-urile au trecut verificarea."

        self._set_text(
            self.check_text,
            "Rezultatul pentru graful candidat inițial.\n\n" + text,
        )
        self.tree.delete(*self.tree.get_children())
        self.individuals_by_row.clear()

        groups = individuals_by_class(graph)
        for class_iri in sorted(groups, key=lambda iri: (_label(graph, iri).casefold(), iri)):
            class_row = self.tree.insert("", "end", text=_label(graph, class_iri), open=True)
            for individual in sorted(
                groups[class_iri], key=lambda iri: (_label(graph, iri).casefold(), iri)
            ):
                row = self.tree.insert(class_row, "end", text=_label(graph, individual))
                self.individuals_by_row[row] = individual

        self._set_text(self.details,(
            "Selectează un individ din arbore."
            if groups else "Graful nu conține indivizi clasificați."
        ))

    def _show_source(self, frame: ReviewFrame) -> None:
        self.source_photo = None
        self.source_image.configure(image="", text="Imagine indisponibilă.")
        if frame.image_path is not None:
            try:
                with Image.open(frame.image_path) as original:
                    preview = ImageOps.exif_transpose(original)
                    preview.thumbnail((420, 300))
                    self.source_photo = ImageTk.PhotoImage(preview, master=self)
            except (OSError, ValueError):
                pass

        if self.source_photo is not None:
            self.source_image.configure(image=self.source_photo, text="")

        self._set_text(self.source_text, _source_text(frame.observation))

    def _current_revision(self) -> GraphRevision:
        frame = self.frames[self.selector.current()]
        return self.revisions[frame.analysis_id]

    def _show_individual(self, _event=None) -> None:
        self.relation_table.delete(*self.relation_table.get_children())
        self.relations_by_row.clear()

        selected = self.tree.selection()
        individual = self.individuals_by_row.get(selected[0]) if selected else None

        if individual is None:
            text = (
                "Selectează un individ din arbore."
                if self.individuals_by_row else "Graful nu conține indivizi clasificați."
            )
            self._set_text(self.details, text)
            self._sync_edit_buttons()
            return

        graph = self._current_revision().graph
        lines = [_label(graph, individual), str(individual), ""]
        for predicate, value in sorted(graph.predicate_objects(individual)):
            if (
                    predicate != RDF.type
                    and isinstance(predicate, URIRef)
                    and isinstance(value, URIRef)
            ):
                row = self.relation_table.insert("", "end", values=(
                    _label(graph, predicate), _label(graph, value),
                ))
                self.relations_by_row[row] = (individual, predicate, value)
            else:
                text = _label(graph, value) if isinstance(value, URIRef) else str(value)
                lines.append(f"{_label(graph, predicate)}: {text}")

        self._set_text(self.details, "\n".join(lines))
        self._sync_edit_buttons()

    def _sync_edit_buttons(self, _event=None) -> None:
        selected = self.relation_table.selection()
        can_remove = bool(selected and selected[0] in self.relations_by_row)
        self.remove_button.configure(state="normal" if can_remove else "disabled")

        self.change_target_button.configure(
            state="normal" if can_remove else "disabled"
        )

        can_undo = self.selector.current() >= 0 and self._current_revision().can_undo
        self.undo_button.configure(state="normal" if can_undo else "disabled")

    def _remove_selected_relation(self) -> None:
        selected = self.relation_table.selection()
        if selected and (relation := self.relations_by_row.get(selected[0])) is not None:
            if self._current_revision().remove_relation(relation):
                self._show_individual()

    def _change_relation_target(self) -> None:
        selected = self.relation_table.selection()
        relation = self.relations_by_row.get(selected[0]) if selected else None
        if relation is None:
            return

        revision = self._current_revision()
        graph = revision.graph
        subject, predicate, _ = relation
        candidates = {
            iri
            for individuals in individuals_by_class(graph).values()
            for iri in individuals
            if (subject, predicate, iri) not in graph
        }
        targets = sorted(candidates, key=lambda iri: (_label(graph, iri).casefold(), iri))
        if not targets:
            messagebox.showinfo(
                "Schimbă ținta",
                "Nu există altă țintă disponibilă în graful acestui cadru.",
                parent=self,
            )
            return

        dialog = tk.Toplevel(self)
        dialog.title("Schimbă ținta")
        dialog.transient(self.winfo_toplevel())
        form = ttk.Frame(dialog, padding=12)
        form.pack(fill="both", expand=True)
        ttk.Label(
            form, text=f"{_label(graph, subject)} → {_label(graph, predicate)}"
        ).pack(anchor="w")

        choice = ttk.Combobox(
            form, state="readonly", width=48,
            values=[
                f"{index}. {_label(graph, iri)}"
                for index, iri in enumerate(targets, start=1)
            ],
        )
        choice.pack(fill="x", pady=6)
        iri_text = tk.StringVar(master=dialog)
        ttk.Label(form, textvariable=iri_text, wraplength=400).pack(anchor="w")

        def show_iri(_event=None) -> None:
            iri_text.set(str(targets[choice.current()]))

        def apply() -> None:
            if revision.replace_relation_target(relation, targets[choice.current()]):
                dialog.destroy()
                self._show_individual()

        choice.bind("<<ComboboxSelected>>", show_iri)
        choice.current(0)
        show_iri()
        actions = ttk.Frame(form)
        actions.pack(anchor="e", pady=(8, 0))
        ttk.Button(actions, text="Renunță", command=dialog.destroy).pack(side="left")
        ttk.Button(actions, text="Aplică", command=apply).pack(side="left", padx=(6, 0))
        dialog.grab_set()
        choice.focus_set()

    def _undo_relation_removal(self) -> None:
        if self._current_revision().undo():
            self._show_individual()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--ontology", type=Path)
    args = parser.parse_args()

    try:
        frames = load_review_frames(
            args.session, args.report, ontology_path=args.ontology
        )
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))

    if not frames:
        parser.error("Raportul nu conține grafuri candidate.")

    root = tk.Tk()
    root.title("Revizie ontologică")
    root.geometry("1000x650")
    root.minsize(700, 420)
    OntologyReview(root, frames).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()