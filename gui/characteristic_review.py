"""Consultarea interpretărilor propuse pentru caracteristici."""

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from rdflib import Graph, RDFS

from session_context.characteristics.comparison import (
    characteristics_for_occurrence,
)
from session_context.characteristics.graph import (
    read_characteristic_selections,
)
from session_context.models import SessionContext


USES = {
    "comparison": "Comparație",
    "state": "Stare",
    "comparison_and_state": "Comparație și stare",
    "not_selected": "Neselectată",
    "unresolved": "Neclară",
}
UNCERTAINTY = {
    True: "Da",
    False: "Nu",
    None: "Necunoscută",
}


class CharacteristicProposalView(ttk.Frame):
    def __init__(
        self,
        parent,
        *,
        get_context: Callable[[], SessionContext],
        ontology: Graph,
        frame_labels: Mapping[str, str],
    ):
        super().__init__(parent)

        self.get_context = get_context
        self.ontology = ontology
        self.frame_labels = dict(frame_labels)
        self.details_by_row: dict[str, str] = {}

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        ttk.Button(
            toolbar,
            text="Actualizează propunerile",
            command=self.refresh,
        ).pack(side="right")

        self.status = tk.StringVar(master=self)
        ttk.Label(
            toolbar,
            textvariable=self.status,
            wraplength=850,
        ).pack(side="left", fill="x", expand=True)

        ttk.Label(
            self,
            text=(
                "Interpretările sunt propuneri ale modelului. "
                "Consultarea lor nu acceptă identitatea obiectelor. "
                "Actualizează lista pentru rezultate primite între timp."
            ),
            wraplength=1100,
        ).pack(anchor="w", pady=6)

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            table,
            columns=(
                "observed",
                "meaning",
                "normalized",
                "target",
                "use",
                "uncertain",
            ),
            show="tree headings",
            selectmode="browse",
            height=10,
        )
        self.tree.heading("#0", text="Propunere / apariție / caracteristică")
        self.tree.column("#0", width=290)

        for column, title, width in (
            ("observed", "Valoare observată", 150),
            ("meaning", "Sens propus", 150),
            ("normalized", "Valoare normalizată", 150),
            ("target", "Țintă propusă", 150),
            ("use", "Utilizare propusă", 160),
            ("uncertain", "Interpretare incertă", 130),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)

        vertical = ttk.Scrollbar(table, command=self.tree.yview)
        vertical.pack(side="right", fill="y")
        horizontal = ttk.Scrollbar(
            table,
            orient="horizontal",
            command=self.tree.xview,
        )
        horizontal.pack(side="bottom", fill="x")
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure(
            "unavailable", foreground="#9a3c15"
        )
        self.tree.bind("<<TreeviewSelect>>", self._show_details)

        ttk.Label(
            self, text="Detalii și proveniență:"
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
            self.details_by_row.get(selected[0], "")
            if selected
            else ""
        )
        self._set_details(text)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.details_by_row.clear()
        self._set_details("")

        context = self.get_context()
        records, issues = read_characteristic_selections(
            context,
            ontology=self.ontology,
        )

        for index, (record_iri, record) in enumerate(
            records.items(), 1
        ):
            source = record.provenance
            frame_title = self.frame_labels.get(
                source.frame_id, source.frame_id
            )
            root = self.tree.insert(
                "",
                "end",
                text=(
                    f"Propunerea {index} · {frame_title} · "
                    f"{source.model}"
                ),
                open=True,
            )
            provenance = "\n".join((
                "Statut: propunere",
                "Verificarea surselor nu certifică interpretarea semantică.",
                f"Cadru: {frame_title}",
                f"Furnizor: {source.provider}",
                f"Model: {source.model}",
                f"Versiune prompt: {source.prompt_version}",
                f"Cerere: {source.message_id}",
                f"Analiză sursă: {source.analysis_id}",
                f"Graf candidat: {source.population_graph_iri}",
                f"Înregistrare: {record_iri}",
                f"Amprenta observațiilor: {source.observations_sha256}",
                f"Amprenta ontologiei trimise: {source.ontology_turtle_sha256}",
                "Amprenta identităților trimise: "
                f"{source.identities_turtle_sha256}",
            ))
            self.details_by_row[root] = provenance

            for appearance in record.proposal.appearances:
                occurrence = appearance.occurrence_iri
                from rdflib import URIRef

                occurrence_node = URIRef(occurrence)
                label = context.observations.value(
                    occurrence_node, RDFS.label, any=False
                )
                appearance_row = self.tree.insert(
                    root,
                    "end",
                    text=str(label) if label is not None else "Apariție",
                    open=True,
                )
                appearance_details = (
                    provenance + f"\n\nApariție sursă: {occurrence}"
                )
                self.details_by_row[appearance_row] = appearance_details

                sources = {
                    str(item.iri): item
                    for item in characteristics_for_occurrence(
                        context, occurrence_node
                    )
                }

                if not appearance.characteristics:
                    self.details_by_row[appearance_row] += (
                        "\nFără caracteristici structurate în observația sursă."
                    )

                for item in appearance.characteristics:
                    observed = sources[item.source_characteristic_iri]
                    target = (
                        f"Parte: {item.part_name}"
                        if item.target_kind == "part"
                        else (
                            "Entitate"
                            if item.target_kind == "entity"
                            else "Neclară"
                        )
                    )
                    meaning = item.meaning or "Neclar"
                    normalized = (
                        item.normalized_value
                        if item.normalized_value is not None
                        else "Nedeterminată"
                    )
                    row = self.tree.insert(
                        appearance_row,
                        "end",
                        text=observed.name,
                        values=(
                            observed.value,
                            meaning,
                            normalized,
                            target,
                            USES[item.use],
                            UNCERTAINTY[item.uncertain],
                        ),
                    )
                    references = (
                        "\n".join(item.ontology_reference_iris)
                        or "Nu sunt propuse"
                    )
                    self.details_by_row[row] = (
                        appearance_details
                        + "\n\n"
                        + "\n".join((
                            f"Caracteristică sursă: {observed.iri}",
                            f"Denumire observată: {observed.name}",
                            f"Valoare observată: {observed.value}",
                            "Incertitudine observată: "
                            f"{UNCERTAINTY[observed.uncertain]}",
                            f"Sens propus: {meaning}",
                            f"Valoare normalizată: {normalized}",
                            f"Țintă propusă: {target}",
                            f"Utilizare propusă: {USES[item.use]}",
                            "Incertitudine interpretare: "
                            f"{UNCERTAINTY[item.uncertain]}",
                            f"Justificare: {item.reason}",
                            "Proprietate ontologică propusă: "
                            f"{item.property_iri or 'Nu este propusă'}",
                            f"Referințe ontologice:\n{references}",
                        ))
                    )

        for index, (record_iri, reason) in enumerate(
            issues.items(), 1
        ):
            row = self.tree.insert(
                "",
                "end",
                text=f"Înregistrare neconsultabilă {index}",
                tags=("unavailable",),
            )
            self.details_by_row[row] = (
                f"Înregistrare: {record_iri}\n\n"
                "Nu poate fi consultată cu contextul și ontologia curente.\n"
                f"Motiv: {reason}"
            )

        self.status.set(
            f"{len(records)} propuneri verificate; "
            f"{len(issues)} înregistrări neconsultabile."
            if records or issues
            else "Nu există propuneri de selecție în context."
        )

        rows = self.tree.get_children()
        if rows:
            self.tree.selection_set(rows[0])
            self._show_details()