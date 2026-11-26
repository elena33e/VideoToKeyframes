"""Revizia identităților folosind observațiile existente ale sesiunii."""

import hashlib
import tkinter as tk
from collections.abc import Collection, Mapping
from datetime import timezone
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageOps, ImageTk
from rdflib import DCTERMS, RDF, RDFS, Literal, Namespace
from rdflib.compare import isomorphic
from unicodedata import normalize

from interpretation.config import OBSERVATION_NAMESPACE
from session_context.graph import build_session_context, entities_for_frame
from session_context.identity import IdentityDecision, IdentityOutcome, TrackedObject
from session_context.identity_graph import (
    object_for_occurrence,
    record_identity_decision,
)
from session_context.matching import (
    AssociationAssessment,
    apply_automatic_associations,
    assess_frame_associations,
)
from session_context.models import SessionContext
from session_context.persistence import load_session_context, save_session_context


CTX = Namespace(OBSERVATION_NAMESPACE)
ACTIONS = {
    "automatic": "Asociere automată",
    "confirmation": "Schimbare de verificat",
    "unresolved": "Nerezolvat",
    "already_associated": "Asociat",
}
REASONS = {
    "existing_identity": "Identitate deja stabilită",
    "no_candidate": "Niciun candidat disponibil",
    "multiple_candidates": "Mai mulți candidați posibili",
    "previous_unresolved_decision": "Decizie amânată anterior",
    "characteristic_difference": "Diferență între caracteristicile observate",
    "unique_candidate_with_evidence": "Candidat unic și trăsături concordante",
    "insufficient_evidence": "Dovezi insuficiente",
    "competing_current_appearances": "Aceeași identitate este revendicată de mai multe apariții",
}
STATUSES = {
    "unchanged": "Concordant",
    "different": "Diferit",
    "unknown": "Necunoscut",
}
OUTCOMES = {
    "same_object": "Același obiect",
    "different_objects": "Obiecte diferite",
    "unresolved": "Nu pot decide",
}


class IdentityReviewWindow(tk.Toplevel):
    def __init__(
        self,
        parent,
        *,
        context: SessionContext,
        image_paths: Mapping[str, Path],
        protected_paths: Collection[Path] = (),
        dirty: bool = False,
    ):
        if len(context.frame_iris) < 2:
            raise ValueError("Sunt necesare cel puțin două cadre descrise.")
        super().__init__(parent)
        self.context = context
        self.source_sha256 = context.source_sha256
        self.session_id = context.session_id
        self.image_paths = {
            key: Path(value).expanduser().resolve()
            for key, value in image_paths.items()
        }
        self.protected_paths = {
            *(Path(value).expanduser().resolve() for value in protected_paths),
            *self.image_paths.values(),
        }
        self.dirty = dirty
        self.closed = False
        self.frame_ids = tuple(context.frame_iris)
        self.frame_labels = tuple(
            f"{index}. {self.image_paths[frame_id].name}"
            if frame_id in self.image_paths else f"{index}. {frame_id}"
            for index, frame_id in enumerate(self.frame_ids, 1)
        )
        self.rows: dict[str, AssociationAssessment] = {}
        self.selected: AssociationAssessment | None = None
        self.photos = []
        self.images_valid = False
        self.object_labels = {}
        self.actor = tk.StringVar(self)
        self.minimum = tk.StringVar(self, value="2")
        self.status = tk.StringVar(
            self, value="Alege cadrele și trăsăturile de identitate."
        )

        self.title("Identitatea obiectelor")
        self.geometry("1260x880")
        self.minsize(1080, 760)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._refresh_objects()
        self.minimum.trace_add("write", self._invalidate)

    def _build(self):
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill="x")
        ttk.Button(
            toolbar, text="Salvează contextul…", command=self.save
        ).pack(side="right")
        ttk.Button(
            toolbar, text="Încarcă un context salvat…", command=self.load
        ).pack(side="right", padx=8)
        ttk.Label(toolbar, text="Autorul deciziilor:").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.actor, width=24).pack(
            side="left", padx=8
        )

        settings = ttk.LabelFrame(self, text="Comparație", padding=10)
        settings.pack(fill="x", padx=10)
        ttk.Label(settings, text="Cadru de referință").grid(row=0, column=0, sticky="w")
        ttk.Label(settings, text="Cadru de comparat").grid(row=0, column=1, sticky="w")
        self.reference = ttk.Combobox(settings, values=self.frame_labels, state="readonly")
        self.current = ttk.Combobox(settings, values=self.frame_labels, state="readonly")
        self.reference.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.current.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        self.reference.current(0)
        self.current.current(1)
        for chooser in (self.reference, self.current):
            chooser.bind("<<ComboboxSelected>>", self._invalidate)
        ttk.Label(settings, text="Minim trăsături concordante").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Spinbox(
            settings, from_=1, to=100, textvariable=self.minimum, width=8
        ).grid(row=1, column=2, sticky="w")
        ttk.Button(
            settings, text="Evaluează asocierile", command=self.evaluate
        ).grid(row=1, column=3, padx=(12, 0))
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=1)

        traits = ttk.LabelFrame(
            self, text="Selectează trăsăturile folosite pentru identitate", padding=8
        )
        traits.pack(fill="x", padx=10, pady=8)
        self.traits = tk.Listbox(
            traits, selectmode="multiple", exportselection=False, height=4
        )
        self.traits.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(traits, command=self.traits.yview)
        scroll.pack(side="right", fill="y")
        self.traits.configure(yscrollcommand=scroll.set)
        names = {
            " ".join(normalize("NFC", str(value)).split()).casefold()
            for node in self.context.observations.subjects(
                RDF.type, CTX.CharacteristicObservation
            )
            for value in self.context.observations.objects(node, RDFS.label)
        }
        for name in sorted(names):
            self.traits.insert("end", name)
        self.traits.bind("<<ListboxSelect>>", self._invalidate)
        ttk.Label(
            self,
            text="Evaluarea folosește observațiile disponibile la deschidere. Diferențele textuale "
                 "pot proveni și din formulări diferite.",
        ).pack(anchor="w", padx=12)

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=8)
        review = ttk.Frame(tabs, padding=8)
        objects = ttk.Frame(tabs, padding=8)
        history = ttk.Frame(tabs, padding=8)
        tabs.add(review, text="Comparație")
        tabs.add(objects, text="Obiecte și apariții")
        tabs.add(history, text="Decizii")

        review.columnconfigure(0, weight=1, minsize=290)
        review.columnconfigure(1, weight=3)
        review.rowconfigure(0, weight=1)
        left = ttk.Frame(review)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.assessments = ttk.Treeview(
            left, columns=("name", "status", "object"),
            show="headings", selectmode="browse",
        )
        for column, title, width in (
            ("name", "Apariție", 130),
            ("status", "Rezultat", 160),
            ("object", "Identitate", 85),
        ):
            self.assessments.heading(column, text=title)
            self.assessments.column(column, width=width)
        vertical = ttk.Scrollbar(left, command=self.assessments.yview)
        vertical.pack(side="right", fill="y")
        horizontal = ttk.Scrollbar(
            left, orient="horizontal", command=self.assessments.xview
        )
        horizontal.pack(side="bottom", fill="x")
        self.assessments.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.assessments.pack(fill="both", expand=True)
        self.assessments.bind("<<TreeviewSelect>>", self._select)

        detail = ttk.Frame(review)
        detail.grid(row=0, column=1, sticky="nsew")
        pictures = ttk.Frame(detail)
        pictures.pack(fill="x")
        pictures.columnconfigure(0, weight=1)
        pictures.columnconfigure(1, weight=1)
        self.image_labels = []
        for column in range(2):
            label = ttk.Label(pictures, anchor="center", wraplength=320)
            label.grid(row=0, column=column, sticky="nsew", padx=4)
            self.image_labels.append(label)
            chooser = (self.reference, self.current)[column]
            label.bind(
                "<Double-Button-1>",
                lambda event, value=chooser: self._enlarge(value),
            )
        ttk.Label(
            detail, text="Dublu clic pe imagine pentru mărire."
        ).pack(anchor="w")
        self.caption = ttk.Label(detail, wraplength=720)
        self.caption.pack(fill="x", pady=6)
        self.candidate = ttk.Combobox(detail, state="disabled")
        self.candidate.pack(fill="x")
        self.candidate.bind("<<ComboboxSelected>>", self._show_comparison)
        self.comparison = ttk.Treeview(
            detail, columns=("name", "left", "right", "status"),
            show="headings", height=7,
        )
        for column, title, width in (
            ("name", "Trăsătură", 140),
            ("left", "Referință", 170),
            ("right", "Cadru comparat", 170),
            ("status", "Rezultat", 100),
        ):
            self.comparison.heading(column, text=title)
            self.comparison.column(column, width=width)
        self.comparison.pack(fill="both", expand=True, pady=6)
        ttk.Label(detail, text="Justificarea deciziei:").pack(anchor="w")
        self.justification = ScrolledText(detail, height=3, wrap="word")
        self.justification.pack(fill="x")
        decisions = ttk.Frame(detail)
        decisions.pack(fill="x", pady=(6, 0))
        self.decision_buttons = {}
        for outcome, title in OUTCOMES.items():
            button = ttk.Button(
                decisions, text=title, state="disabled",
                command=lambda value=outcome: self.decide(value),
            )
            button.pack(side="left", padx=(0, 6))
            self.decision_buttons[outcome] = button

        self.objects = ttk.Treeview(objects, show="tree")
        object_scroll = ttk.Scrollbar(objects, command=self.objects.yview)
        object_scroll.pack(side="right", fill="y")
        self.objects.configure(yscrollcommand=object_scroll.set)
        self.objects.pack(fill="both", expand=True)
        self.history = ScrolledText(history, wrap="word", state="disabled")
        self.history.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.status, wraplength=1150).pack(
            fill="x", padx=12, pady=(0, 10)
        )

    def _policy(self):
        names = tuple(self.traits.get(index) for index in self.traits.curselection())
        return (
            self.frame_ids[self.reference.current()],
            self.frame_ids[self.current.current()],
            names,
            int(self.minimum.get()),
        )

    def _invalidate(self, *_args):
        self.rows.clear()
        self.selected = None
        self.assessments.delete(*self.assessments.get_children())
        self.comparison.delete(*self.comparison.get_children())
        self.candidate.configure(values=(), state="disabled")
        self.candidate.set("")
        self.caption.configure(text="")
        self.photos.clear()
        self.images_valid = False
        for label in self.image_labels:
            label.configure(image="", text="")
        for button in self.decision_buttons.values():
            button.configure(state="disabled")
        self.status.set("Evaluează din nou după alegerea cadrelor sau a trăsăturilor.")

    def _label(self, occurrence):
        value = self.context.observations.value(occurrence, RDFS.label, any=False)
        return str(value) if value is not None else "Apariție"

    def _frame_title(self, frame_id):
        index = self.frame_ids.index(frame_id)
        return self.frame_labels[index]

    def evaluate(self):
        wanted = self.selected.occurrence_iri if self.selected else None
        try:
            reference, current, names, minimum = self._policy()
            decisions = apply_automatic_associations(
                self.context, reference, current,
                identity_names=names, min_matching=minimum,
            )
            if decisions:
                self.dirty = True
            result = assess_frame_associations(
                self.context, reference, current,
                identity_names=names, min_matching=minimum,
            )
            self._refresh_objects()
            self._invalidate()
            chosen = None
            for index, assessment in enumerate(result, 1):
                row = str(index)
                self.rows[row] = assessment
                target = object_for_occurrence(self.context, assessment.occurrence_iri)
                self.assessments.insert("", "end", iid=row, values=(
                    f"{self._label(assessment.occurrence_iri)} · {index}",
                    ACTIONS[assessment.action],
                    self.object_labels.get(target, "—"),
                ))
                if chosen is None or assessment.occurrence_iri == wanted:
                    chosen = row
            if chosen is not None:
                self.assessments.selection_set(chosen)
                self._select()
            self.status.set(
                f"{len(decisions)} asocieri automate noi. "
                f"{sum(item.action == 'confirmation' for item in result)} schimbări "
                "de verificat. Modificările contextului se salvează separat."
            )
            return True
        except Exception as exc:
            messagebox.showerror("Evaluare nereușită", str(exc), parent=self)
            return False

    def _image_bytes(self, frame_id):
        path = self.image_paths.get(frame_id)
        if path is None:
            raise ValueError("Calea imaginii nu este disponibilă.")
        analysis = self.context.observations.value(
            self.context.frame_iris[frame_id], CTX.observation, any=False
        )
        expected = self.context.observations.value(
            analysis, CTX.imageSha256, any=False
        )
        raw = path.read_bytes()
        if expected is None or hashlib.sha256(raw).hexdigest() != str(expected):
            raise ValueError("Imaginea diferă de cea folosită la analiză.")
        return raw

    def _show_images(self):
        self.photos.clear()
        self.images_valid = True
        for label, chooser in zip(self.image_labels, (self.reference, self.current)):
            frame_id = self.frame_ids[chooser.current()]
            try:
                raw = self._image_bytes(frame_id)
                with Image.open(BytesIO(raw)) as original:
                    with ImageOps.exif_transpose(original) as oriented:
                        with oriented.convert("RGB") as preview:
                            preview.thumbnail((340, 215), Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(preview, master=self)
                self.photos.append(photo)
                label.configure(image=photo, text="")
            except (OSError, ValueError, SyntaxError) as exc:
                self.images_valid = False
                label.configure(
                    image="", text=f"{self._frame_title(frame_id)}\n{exc}"
                )

    def _enlarge(self, chooser):
        try:
            frame_id = self.frame_ids[chooser.current()]
            raw = self._image_bytes(frame_id)
            dialog = tk.Toplevel(self)
            dialog.title(self._frame_title(frame_id))
            with Image.open(BytesIO(raw)) as original:
                with ImageOps.exif_transpose(original) as oriented:
                    with oriented.convert("RGB") as preview:
                        preview.thumbnail((
                            max(100, min(1200, self.winfo_screenwidth() - 100)),
                            max(100, min(900, self.winfo_screenheight() - 120)),
                        ), Image.Resampling.LANCZOS)
                        dialog.photo = ImageTk.PhotoImage(preview, master=dialog)
            ttk.Label(dialog, image=dialog.photo).pack()
        except (OSError, ValueError, SyntaxError) as exc:
            messagebox.showerror("Imagine indisponibilă", str(exc), parent=self)

    def _select(self, _event=None):
        selection = self.assessments.selection()
        self.selected = self.rows.get(selection[0]) if selection else None
        self.justification.delete("1.0", "end")
        self._show_images()
        if self.selected is None:
            return
        candidates = self.selected.candidates
        self.candidate.configure(
            values=tuple(
                f"Candidat {index}: {self._label(candidate.reference_iri)}"
                for index, candidate in enumerate(candidates, 1)
            ),
            state="readonly" if candidates else "disabled",
        )
        if candidates:
            self.candidate.current(0)
        else:
            self.candidate.set("")
        self._show_comparison()

    def _show_comparison(self, _event=None):
        self.comparison.delete(*self.comparison.get_children())
        for button in self.decision_buttons.values():
            button.configure(state="disabled")
        assessment = self.selected
        if assessment is None:
            return
        self.caption.configure(text=REASONS.get(assessment.reason, "Nerezolvat"))
        index = self.candidate.current()
        if index < 0 or index >= len(assessment.candidates):
            return
        candidate = assessment.candidates[index]
        location = self.context.observations.value(
            candidate.reference_iri, CTX.location, any=False
        )
        current_location = self.context.observations.value(
            assessment.occurrence_iri, CTX.location, any=False
        )
        self.caption.configure(
            text=f"{REASONS.get(assessment.reason, 'Nerezolvat')}\n"
                 f"Referință: {self._label(candidate.reference_iri)} "
                 f"({location or 'poziție nespecificată'}). "
                 f"Cadru comparat: {self._label(assessment.occurrence_iri)} "
                 f"({current_location or 'poziție nespecificată'})."
        )
        for item in candidate.comparison.characteristics:
            def values(evidence):
                return "; ".join(
                    value.value + (" (incert)" if value.uncertain is not False else "")
                    for value in evidence
                ) or "Neobservat"
            self.comparison.insert("", "end", values=(
                item.name, values(item.left), values(item.right), STATUSES[item.status]
            ))
        if self._reviewable(assessment):
            for outcome, button in self.decision_buttons.items():
                button.configure(
                    state="normal"
                    if outcome == "unresolved" or self.images_valid else "disabled"
                )

    @staticmethod
    def _reviewable(assessment):
        return (
            len(assessment.candidates) == 1
            and assessment.candidates[0].comparison.requires_confirmation
            and (
                assessment.action == "confirmation"
                or assessment.reason == "previous_unresolved_decision"
            )
        )

    def decide(self, outcome: IdentityOutcome):
        shown = self.selected
        if shown is None or not self._reviewable(shown):
            return False
        try:
            reference, current, names, minimum = self._policy()
            fresh = next(
                item for item in assess_frame_associations(
                    self.context, reference, current,
                    identity_names=names, min_matching=minimum,
                )
                if item.occurrence_iri == shown.occurrence_iri
            )
            if (
                not self._reviewable(fresh)
                or fresh.candidates[0].reference_iri != shown.candidates[0].reference_iri
            ):
                raise ValueError("Asocierea s-a schimbat. Evaluează din nou.")
            if outcome != "unresolved":
                self._image_bytes(reference)
                self._image_bytes(current)
            actor = self.actor.get().strip()
            justification = self.justification.get("1.0", "end").strip()
            if not actor or not justification:
                raise ValueError("Completează autorul și justificarea deciziei.")
            candidate = fresh.candidates[0]
            tracked = None
            object_id = None
            if outcome == "same_object":
                if candidate.object_iri is None:
                    tracked = TrackedObject(session_id=self.context.session_id)
                    object_id = tracked.object_id
                else:
                    identifier = self.context.identities.value(
                        candidate.object_iri, CTX.objectId, any=False
                    )
                    if not isinstance(identifier, Literal):
                        raise ValueError("Identificator de obiect invalid.")
                    object_id = str(identifier)
            decision = IdentityDecision(
                session_id=self.context.session_id,
                left_occurrence_iri=str(candidate.reference_iri),
                right_occurrence_iri=str(fresh.occurrence_iri),
                outcome=outcome,
                object_id=object_id,
                decided_by=actor,
                justification=justification,
            )
            record_identity_decision(self.context, decision, new_object=tracked)
            self.dirty = True
            self.evaluate()
            self.status.set(f"Decizie înregistrată: {OUTCOMES[outcome]}. Salvează contextul.")
            return True
        except Exception as exc:
            messagebox.showerror("Decizie neînregistrată", str(exc), parent=self)
            return False

    def _refresh_objects(self):
        graph = self.context.identities
        nodes = sorted(
            set(graph.subjects(RDF.type, CTX.TrackedObject)),
            key=lambda node: (str(graph.value(node, DCTERMS.created)), str(node)),
        )
        self.object_labels = {
            node: f"Obiect {index}" for index, node in enumerate(nodes, 1)
        }
        self.objects.delete(*self.objects.get_children())
        memberships = {
            occurrence: frame_id
            for frame_id in self.frame_ids
            for occurrence in entities_for_frame(self.context, frame_id)
        }
        grouped = set()
        for node in nodes:
            root = self.objects.insert("", "end", text=self.object_labels[node], open=True)
            for occurrence in sorted(graph.subjects(CTX.associatedObject, node), key=str):
                grouped.add(occurrence)
                self._add_occurrence(root, occurrence, memberships)
        unassigned = set(memberships) - grouped
        if unassigned:
            root = self.objects.insert("", "end", text="Apariții neasociate", open=True)
            for occurrence in sorted(unassigned, key=str):
                self._add_occurrence(root, occurrence, memberships)
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        decisions = sorted(
            set(graph.subjects(RDF.type, CTX.IdentityDecision)),
            key=lambda node: (str(graph.value(node, DCTERMS.created)), str(node)),
        )
        for node in decisions:
            created = graph.value(node, DCTERMS.created).toPython()
            moment = created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            outcome = str(graph.value(node, CTX.identityOutcome))
            actor = str(graph.value(node, CTX.decidedBy))
            left = graph.value(node, CTX.leftOccurrence)
            right = graph.value(node, CTX.rightOccurrence)
            left_frame = self._frame_title(memberships[left])
            right_frame = self._frame_title(memberships[right])
            justification = str(graph.value(node, CTX.justification))
            if actor == "automatic:frame-matching-v1":
                justification = "Asociere automată pe baza trăsăturilor concordante."
            self.history.insert(
                "end",
                f"{moment} · {OUTCOMES.get(outcome, outcome)} · {actor}\n"
                f"{self._label(left)} [{left_frame}] ↔ "
                f"{self._label(right)} [{right_frame}]\n{justification}\n\n",
            )
        self.history.configure(state="disabled")

    def _add_occurrence(self, parent, occurrence, memberships):
        frame_id = memberships[occurrence]
        row = self.objects.insert(
            parent, "end",
            text=f"{self._label(occurrence)} · {self._frame_title(frame_id)}",
        )
        graph = self.context.observations
        for characteristic in graph.objects(occurrence, CTX.characteristics):
            name = graph.value(characteristic, RDFS.label)
            value = graph.value(characteristic, CTX.characteristicValue)
            certain = graph.value(characteristic, CTX.uncertain) == Literal(False)
            self.objects.insert(
                row, "end",
                text=f"{name}: {value}" + ("" if certain else " (incert)"),
            )

    def save(self):
        filename = filedialog.asksaveasfilename(
            parent=self, title="Salvează contextul sesiunii",
            initialfile=f"context_{self.context.session_id}.trig",
            defaultextension=".trig", filetypes=[("Context de sesiune", "*.trig")],
        )
        if not filename:
            return False
        try:
            destination = Path(filename).expanduser().resolve()
            if destination in self.protected_paths:
                raise ValueError("Contextul nu poate înlocui un fișier sursă.")
            save_session_context(self.context, destination)
            self.dirty = False
            self.status.set(f"Context salvat: {destination.name}")
            return True
        except Exception as exc:
            messagebox.showerror("Salvare nereușită", str(exc), parent=self)
            return False

    def load(self):
        if self.dirty:
            answer = messagebox.askyesnocancel(
                "Context nesalvat", "Salvezi modificările înainte de încărcare?",
                parent=self,
            )
            if answer is None or (answer and not self.save()):
                return False
        filename = filedialog.askopenfilename(
            parent=self, title="Încarcă un context salvat",
            filetypes=[("Context de sesiune", "*.trig")],
        )
        if not filename:
            return False
        try:
            loaded = load_session_context(
                filename,
                expected_session_id=self.session_id,
                expected_source_sha256=self.source_sha256,
            )
            if (
                loaded.frame_iris != self.context.frame_iris
                or not isomorphic(loaded.observations, self.context.observations)
            ):
                raise ValueError("Observațiile din context diferă de cele deschise.")
            self.context = loaded
            self.dirty = False
            self._invalidate()
            self._refresh_objects()
            self.status.set("Context reîncărcat. Alege cadrele și evaluează asocierile.")
            return True
        except Exception as exc:
            messagebox.showerror("Încărcare nereușită", str(exc), parent=self)
            return False

    def close(self):
        if self.closed:
            return True
        if self.dirty:
            answer = messagebox.askyesnocancel(
                "Context nesalvat", "Salvezi contextul înainte de închidere?",
                parent=self,
            )
            if answer is None or (answer and not self.save()):
                return False
        self.closed = True
        self.destroy()
        return True


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Revizia identităților dintr-o sesiune.")
    parser.add_argument("session", type=Path, help="Exportul JSON-LD al sesiunii")
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    try:
        source = args.session.expanduser().resolve()
        document = json.loads(source.read_text(encoding="utf-8-sig"))
        context = build_session_context(document)
        paths = {}
        for frame in document.get("imported_frames", []):
            if frame["frame_id"] in context.frame_iris:
                path = Path(frame["image_path"]).expanduser()
                paths[frame["frame_id"]] = (
                    path if path.is_absolute() else source.parent / path
                ).resolve()
        protected = [source]
        extraction = document.get("extraction")
        if extraction is not None:
            base = Path(extraction["output_dir"]).expanduser()
            base = (base if base.is_absolute() else source.parent / base).resolve()
            for scene in extraction["scenes"]:
                if scene["status"] != "success":
                    continue
                for frame in scene["frames"]:
                    if frame["frame_id"] not in context.frame_iris:
                        continue
                    path = (base / frame["image_path"]).resolve()
                    if not path.is_relative_to(base):
                        raise ValueError("Imaginea este în afara directorului extragerii.")
                    paths[frame["frame_id"]] = path
            for name in ("input_video", "manifest"):
                if extraction.get(name):
                    path = Path(extraction[name]).expanduser()
                    protected.append(path if path.is_absolute() else source.parent / path)
        if document.get("ontology_path"):
            path = Path(document["ontology_path"]).expanduser()
            protected.append(path if path.is_absolute() else source.parent / path)
        window = IdentityReviewWindow(
            root, context=context, image_paths=paths, protected_paths=protected
        )
        window.transient("")
        window.deiconify()
        root.wait_window(window)
    except Exception as exc:
        messagebox.showerror("Revizie indisponibilă", str(exc), parent=root)
        return 1
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
