"""Consultarea comparațiilor bazate pe interpretări propuse."""

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from rdflib import Graph, RDFS, URIRef

from gui.characteristic_review import UNCERTAINTY, USES
from session_context.characteristics.graph import (
    CharacteristicSelectionRecord,
    read_characteristic_selections,
)
from session_context.characteristics.proposed_comparison import (
    ProposedOccurrenceComparison,
    compare_proposed_characteristics,
)
from session_context.models import SessionContext


STATUS_LABELS = {
    "same_proposed_value": "Aceeași valoare propusă",
    "different_proposed_values": "Valori propuse diferite",
    "unknown": "Necunoscut",
}
REASON_LABELS = {
    "interpretation_unresolved": "Interpretarea nu este clarificată.",
    "not_selected_for_comparison": (
        "Cel puțin o caracteristică nu este propusă pentru comparație."
    ),
    "missing_counterpart": (
        "Nu există o corespondență propusă pe ambele părți."
    ),
    "ambiguous_characteristics": (
        "Mai multe caracteristici au aceeași cheie de comparație."
    ),
    "uncertain": "Observația sau interpretarea este incertă.",
    "missing_normalized_value": (
        "Lipsește cel puțin o valoare normalizată propusă."
    ),
    "normalized_text_equal": "Valorile normalizate propuse coincid textual.",
    "conflicting_normalization": (
        "Aceeași valoare observată a primit normalizări diferite."
    ),
    "normalized_text_different": (
        "Valorile normalizate propuse diferă textual."
    ),
}


def _values(items, *, normalized=False):
    values = []
    for item in items:
        if normalized:
            value = item.interpretation.normalized_value
            value = value if value is not None else "Nedeterminată"
            uncertain = item.interpretation.uncertain
        else:
            value = item.observed.value
            uncertain = item.observed.uncertain is not False

        values.append(value + (" (incert)" if uncertain else ""))

    return "; ".join(values) or "Fără corespondență"


def _evidence_text(items, title):
    lines = [title]
    if not items:
        lines.append("Fără corespondență propusă în această grupă.")

    for item in items:
        observed = item.observed
        interpretation = item.interpretation
        lines.extend((
            f"Caracteristică sursă: {observed.iri}",
            f"Observat: {observed.name} = {observed.value}",
            f"Incertitudine observată: {UNCERTAINTY[observed.uncertain]}",
            f"Sens propus: {interpretation.meaning or 'Neclar'}",
            "Valoare normalizată propusă: "
            f"{interpretation.normalized_value or 'Nedeterminată'}",
            f"Țintă: {interpretation.target_kind}",
            f"Parte: {interpretation.part_name or '—'}",
            f"Utilizare propusă: {USES[interpretation.use]}",
            "Interpretare incertă: "
            f"{UNCERTAINTY[interpretation.uncertain]}",
            f"Justificare: {interpretation.reason}",
            "",
        ))

    return "\n".join(lines)


class ProposedComparisonView(ttk.Frame):
    def __init__(
        self,
        parent,
        *,
        get_context: Callable[[], SessionContext],
        get_frame_pair: Callable[[], tuple[str, str]],
        ontology: Graph,
        frame_labels: Mapping[str, str],
    ):
        super().__init__(parent)
        self.get_context = get_context
        self.get_frame_pair = get_frame_pair
        self.ontology = ontology
        self.frame_labels = dict(frame_labels)

        self.records: dict[
            URIRef, CharacteristicSelectionRecord
        ] = {}
        self.issues: dict[URIRef, str] = {}
        self.entries: list[list[tuple[URIRef, URIRef]]] = [[], []]
        self.details_by_row: dict[str, str] = {}
        self.last_result: ProposedOccurrenceComparison | None = None
        self.base_details = ""

        ttk.Label(
            self,
            text=(
                "Alege apariția și propunerea din fiecare cadru selectat "
                "mai sus. Rezultatele sunt propuneri pentru consultare; "
                "nu reprezintă decizii de identitate."
            ),
            wraplength=1100,
        ).pack(anchor="w", pady=(0, 8))

        controls = ttk.Frame(self)
        controls.pack(fill="x")
        controls.columnconfigure(1, weight=1)
        self.choices = []

        for side, label in enumerate((
            "Referință: apariție și propunere",
            "Cadru comparat: apariție și propunere",
        )):
            ttk.Label(controls, text=label).grid(
                row=side, column=0, sticky="w", pady=3
            )
            chooser = ttk.Combobox(
                controls, state="readonly", width=80
            )
            chooser.grid(
                row=side, column=1, sticky="ew", padx=(8, 0), pady=3
            )
            chooser.bind(
                "<<ComboboxSelected>>", self._selection_changed
            )
            self.choices.append(chooser)

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=6)
        ttk.Button(
            actions,
            text="Actualizează sursele",
            command=self.refresh,
        ).pack(side="left")
        self.issue_button = ttk.Button(
            actions,
            text="Probleme de citire",
            command=self.show_issues,
        )
        self.issue_button.pack(side="left", padx=6)
        self.compare_button = ttk.Button(
            actions,
            text="Compară propunerile alese",
            command=self.compare,
        )
        self.compare_button.pack(side="right")

        self.status = tk.StringVar(master=self)
        ttk.Label(
            self, textvariable=self.status, wraplength=1100
        ).pack(anchor="w", pady=(0, 6))

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table,
            columns=(
                "left_observed",
                "left_normalized",
                "right_observed",
                "right_normalized",
                "status",
            ),
            show="tree headings",
            height=9,
            selectmode="browse",
        )
        self.tree.heading("#0", text="Sens / țintă propusă")
        self.tree.column("#0", width=260)

        for column, title, width in (
            ("left_observed", "Referință: observat", 160),
            ("left_normalized", "Referință: normalizat", 160),
            ("right_observed", "Comparat: observat", 160),
            ("right_normalized", "Comparat: normalizat", 160),
            ("status", "Rezultat propus", 190),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)

        vertical = ttk.Scrollbar(table, command=self.tree.yview)
        vertical.pack(side="right", fill="y")
        horizontal = ttk.Scrollbar(
            table, orient="horizontal", command=self.tree.xview
        )
        horizontal.pack(side="bottom", fill="x")
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._show_details)

        ttk.Label(
            self, text="Explicație și sursele comparației:"
        ).pack(anchor="w", pady=(8, 3))
        self.details = ScrolledText(
            self, height=10, wrap="word", state="disabled"
        )
        self.details.pack(fill="both", expand=True)

        self.refresh()

    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _show_details(self, _event=None):
        selected = self.tree.selection()
        text = (
            self.details_by_row.get(selected[0], self.base_details)
            if selected
            else self.base_details
        )
        self._set_details(text)

    def _selected_entry(self, side):
        index = self.choices[side].current()
        return (
            self.entries[side][index]
            if 0 <= index < len(self.entries[side])
            else None
        )

    def _update_compare_button(self):
        ready = all(
            self._selected_entry(side) is not None
            for side in (0, 1)
        )
        self.compare_button.configure(
            state="normal" if ready else "disabled"
        )

    def _clear_result(self):
        self.last_result = None
        self.base_details = ""
        self.details_by_row.clear()
        self.tree.delete(*self.tree.get_children())
        self._set_details("")

    def _selection_changed(self, _event=None):
        self._clear_result()
        self._update_compare_button()
        self.status.set(
            "Compară propunerile alese pentru a obține rezultatul."
        )

    def refresh(self):
        previous = tuple(
            self._selected_entry(side) for side in (0, 1)
        )
        self._clear_result()

        context = self.get_context()
        self.records, self.issues = read_characteristic_selections(
            context, ontology=self.ontology
        )
        frame_pair = self.get_frame_pair()
        self.entries = [[], []]
        labels = [[], []]

        for number, (record_iri, record) in enumerate(
            self.records.items(), 1
        ):
            source = record.provenance
            for side, frame_id in enumerate(frame_pair):
                if source.frame_id != frame_id:
                    continue

                frame_title = self.frame_labels.get(
                    frame_id, frame_id
                )
                for index, appearance in enumerate(
                    record.proposal.appearances, 1
                ):
                    occurrence = URIRef(appearance.occurrence_iri)
                    name = context.observations.value(
                        occurrence, RDFS.label, any=False
                    )
                    self.entries[side].append((
                        occurrence, record_iri
                    ))
                    labels[side].append(
                        f"{frame_title} · "
                        f"{name if name is not None else 'Apariție'} "
                        f"[{index}] · propunerea {number} · {source.model}"
                    )

        for side, chooser in enumerate(self.choices):
            chooser.configure(values=tuple(labels[side]))
            chosen = previous[side]
            if chosen is not None and chosen in self.entries[side]:
                chooser.current(self.entries[side].index(chosen))
            else:
                chooser.set("")

        self.issue_button.configure(
            state="normal" if self.issues else "disabled"
        )
        self._update_compare_button()
        self.status.set(
            f"{len(self.entries[0])} opțiuni pentru referință; "
            f"{len(self.entries[1])} pentru cadrul comparat; "
            f"{len(self.issues)} înregistrări neconsultabile."
        )

    def show_issues(self):
        self._set_details(
            "\n\n".join(
                f"Înregistrare: {record}\nMotiv: {reason}"
                for record, reason in self.issues.items()
            ) or "Nu există probleme de citire."
        )

    def _record_text(self, entry, title):
        occurrence, record_iri = entry
        source = self.records[record_iri].provenance
        return "\n".join((
            title,
            f"Apariție: {occurrence}",
            f"Înregistrare: {record_iri}",
            f"Graf candidat: {source.population_graph_iri}",
            f"Furnizor: {source.provider}",
            f"Model: {source.model}",
            f"Versiune prompt: {source.prompt_version}",
            f"Cerere: {source.message_id}",
        ))

    def _insert_row(self, title, left, right, status, explanation):
        row = self.tree.insert(
            "",
            "end",
            text=title,
            values=(
                _values(left),
                _values(left, normalized=True),
                _values(right),
                _values(right, normalized=True),
                STATUS_LABELS[status],
            ),
        )
        self.details_by_row[row] = "\n\n".join((
            self.base_details,
            explanation,
            _evidence_text(left, "Caracteristici de referință"),
            _evidence_text(right, "Caracteristici din cadrul comparat"),
        ))

    def compare(self):
        self._clear_result()
        left = self._selected_entry(0)
        right = self._selected_entry(1)

        if left is None or right is None:
            self.status.set(
                "Alege o apariție și o propunere pentru fiecare cadru."
            )
            return False

        try:
            result = compare_proposed_characteristics(
                self.get_context(),
                left[0],
                right[0],
                left_record_iri=left[1],
                right_record_iri=right[1],
                ontology=self.ontology,
            )
        except ValueError as exc:
            self.status.set(f"Comparație indisponibilă. {exc}")
            self._set_details(str(exc))
            return False

        self.base_details = "\n\n".join((
            "Statut: propunere. Comparația nu stabilește identitatea.",
            self._record_text(left, "Sursa de referință"),
            self._record_text(right, "Sursa din cadrul comparat"),
        ))

        for item in result.characteristics:
            names = tuple(dict.fromkeys(
                evidence.interpretation.meaning
                or evidence.observed.name
                for evidence in item.left + item.right
            ))
            target = (
                "Entitate"
                if item.key.target_kind == "entity"
                else f"Parte: {item.key.part_name}"
            )
            explanation = "\n".join((
                REASON_LABELS.get(item.reason, item.reason),
                "Corespondență propusă prin "
                f"{'proprietate' if item.key.reference_kind == 'property' else 'sens'}: "
                f"{item.key.reference}",
                "Corespondența după denumirea unei părți "
                "nu confirmă identitatea fizică a părților.",
            ))
            self._insert_row(
                f"{' / '.join(names)} · {target}",
                item.left,
                item.right,
                item.status,
                explanation,
            )

        for side, items in (
            (0, result.unresolved_left),
            (1, result.unresolved_right),
        ):
            for item in items:
                self._insert_row(
                    f"{item.observed.name} · țintă sau sens neclar",
                    (item,) if side == 0 else (),
                    (item,) if side == 1 else (),
                    "unknown",
                    "Ținta sau sensul nu permit stabilirea "
                    "unei corespondențe propuse.",
                )

        self.last_result = result
        self.status.set(
            "Comparație propusă afișată. "
            f"{len(self.issues)} înregistrări neconsultabile."
        )
        rows = self.tree.get_children()
        if rows:
            self.tree.selection_set(rows[0])
        self._show_details()
        return True