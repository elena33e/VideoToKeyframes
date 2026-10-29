"""Interfață de test pentru descrierea imaginilor și inspectarea ontologiei."""

import json
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from PIL import Image, ImageOps, ImageTk

from interpretation.describe import DescriptionConfig, OpenRouterImageDescriber
from interpretation.models import OntologyCatalog
from interpretation.observations import FrameObservation
from interpretation.ontology import load_ontology


DEFAULT_FREE_MODEL = "nvidia/nemotron-3.5-super-vl:free"


def format_observation(result: FrameObservation) -> str:
    """Transformă observația într-un text pentru previzualizare."""
    observation = result.observation
    names = {entity.id: entity.name for entity in observation.entities}
    lines = [observation.description, "", "OBIECTE ȘI ELEMENTE"]
    visibility = {
        "clear": "clar",
        "partial": "parțial vizibil",
        "unclear": "neclar",
    }
    for entity in observation.entities:
        lines.append(f"• {entity.name} — {visibility[entity.visibility]}")
        lines.append(f"  Poziție: {entity.location}")
        lines.extend(f"  • {feature}" for feature in entity.features)
    if not observation.entities:
        lines.append("Niciun element identificat.")
    lines.extend(["", "RELAȚII"])
    for relation in observation.relations:
        lines.append(
            f"• {names[relation.subject_id]} — {relation.predicate} — "
            f"{names[relation.object_id]}"
        )
    if not observation.relations:
        lines.append("Nicio relație raportată.")
    lines.extend(["", "ACȚIUNI SAU POSTURI"])
    for action in observation.actions:
        suffix = " (incert)" if action.uncertain else ""
        lines.append(f"• {action.description}{suffix}")
    if not observation.actions:
        lines.append("Nicio acțiune sau postură raportată.")
    lines.extend(["", "TEXT VIZIBIL"])
    lines.extend(f"• {text}" for text in observation.visible_text)
    if not observation.visible_text:
        lines.append("Niciun text lizibil raportat.")
    lines.extend(["", "INCERTITUDINI"])
    lines.extend(f"• {item}" for item in observation.uncertainties)
    if not observation.uncertainties:
        lines.append("Modelul nu a raportat incertitudini.")
    lines.extend(["", f"Model: {result.resolved_model}"])
    lines.append(f"Durata apelului: {result.elapsed_seconds:.2f} secunde")
    return "\n".join(lines)


class InterpretationGUI:
    def __init__(
        self,
        root: tk.Tk,
        *,
        api_key: str,
        model: str,
        output_dir: Path,
    ):
        self.root = root
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.events = Queue()
        self.running = False
        self.image_path: Path | None = None
        self.ontology_path: Path | None = None
        self.result: FrameObservation | None = None
        self.catalog: OntologyCatalog | None = None
        self.preview_photo = None

        self.model_var = tk.StringVar(value=model or DEFAULT_FREE_MODEL)
        self.image_var = tk.StringVar(value="Nicio imagine selectată")
        self.ontology_var = tk.StringVar(value="Nicio ontologie încărcată")
        self.status_var = tk.StringVar(value="Alege un keyframe pentru test.")

        root.title("Interpretare keyframes — test")
        root.geometry("1120x800")
        root.minsize(900, 650)
        self._build_ui()
        self._update_controls()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(100, self._poll_events)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        settings = ttk.LabelFrame(main, text="Configurare", padding=10)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Model OpenRouter:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.model_entry = ttk.Entry(settings, textvariable=self.model_var)
        self.model_entry.grid(row=0, column=1, sticky="ew")
        key_status = (
            "Cheia API este disponibilă în configurație."
            if self.api_key.strip()
            else "Cheia API lipsește. Completează .env și repornește interfața."
        )
        ttk.Label(settings, text=key_status).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        ttk.Label(
            settings,
            text=(
                "Pentru endpointul gratuit NVIDIA, folosește imagini fără "
                "date personale sau informații confidențiale."
            ),
            wraplength=850,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        source = ttk.Frame(main)
        source.grid(row=1, column=0, sticky="ew", pady=10)
        source.columnconfigure(0, weight=1)
        ttk.Entry(source, textvariable=self.image_var, state="readonly").grid(
            row=0, column=0, sticky="ew"
        )
        self.choose_image_button = ttk.Button(
            source, text="Alege imaginea…", command=self._choose_image
        )
        self.choose_image_button.grid(row=0, column=1, padx=(8, 0))

        tabs = ttk.Notebook(main)
        tabs.grid(row=2, column=0, sticky="nsew")

        description_tab = ttk.Frame(tabs, padding=10)
        tabs.add(description_tab, text="Descrierea imaginii")
        description_tab.rowconfigure(0, weight=1)
        description_tab.columnconfigure(0, weight=1)
        description_tab.columnconfigure(1, weight=2)

        image_frame = ttk.LabelFrame(
            description_tab, text="Keyframe selectat", padding=8
        )
        image_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.preview_label = ttk.Label(
            image_frame, text="Previzualizarea imaginii", anchor="center"
        )
        self.preview_label.pack(fill="both", expand=True)

        result_tabs = ttk.Notebook(description_tab)
        result_tabs.grid(row=0, column=1, sticky="nsew")
        self.description_text = self._add_text_tab(result_tabs, "Observație")
        self.json_text = self._add_text_tab(result_tabs, "JSON")

        ontology_tab = ttk.Frame(tabs, padding=10)
        tabs.add(ontology_tab, text="Inspectarea ontologiei")
        ontology_tab.columnconfigure(0, weight=1)
        ontology_tab.rowconfigure(3, weight=1)
        ttk.Label(
            ontology_tab,
            text=(
                "Aici verifici catalogul ontologiei. În această versiune, "
                "descrierea imaginii nu folosește încă ontologia pentru mapare."
            ),
            wraplength=900,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ontology_line = ttk.Frame(ontology_tab)
        ontology_line.grid(row=1, column=0, sticky="ew")
        ontology_line.columnconfigure(0, weight=1)
        ttk.Entry(
            ontology_line, textvariable=self.ontology_var, state="readonly"
        ).grid(row=0, column=0, sticky="ew")
        self.choose_ontology_button = ttk.Button(
            ontology_line, text="Încarcă ontologia…", command=self._choose_ontology
        )
        self.choose_ontology_button.grid(row=0, column=1, padx=(8, 0))
        self.catalog_summary = ttk.Label(
            ontology_tab, text="Catalogul nu este încă încărcat.", wraplength=900
        )
        self.catalog_summary.grid(row=2, column=0, sticky="w", pady=8)
        table_frame = ttk.Frame(ontology_tab)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.concepts_table = ttk.Treeview(
            table_frame, columns=("label", "kind", "iri"), show="headings"
        )
        for column, title, width in (
            ("label", "Denumire", 220),
            ("kind", "Tip", 140),
            ("iri", "Identificator", 480),
        ):
            self.concepts_table.heading(column, text=title)
            self.concepts_table.column(column, width=width, minwidth=80)
        self.concepts_table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.concepts_table.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.concepts_table.configure(yscrollcommand=scrollbar.set)
        self.save_catalog_button = ttk.Button(
            ontology_tab, text="Salvează catalogul JSON…", command=self._save_catalog
        )
        self.save_catalog_button.grid(row=4, column=0, sticky="w", pady=(8, 0))

        actions = ttk.Frame(main)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.describe_button = ttk.Button(
            actions, text="Descrie imaginea", command=self._describe
        )
        self.describe_button.pack(side="left")
        self.save_result_button = ttk.Button(
            actions, text="Salvează observația JSON…", command=self._save_result
        )
        self.save_result_button.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        ttk.Label(main, textvariable=self.status_var, wraplength=1050).grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

    @staticmethod
    def _add_text_tab(notebook, title):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        text = ScrolledText(frame, wrap="word", width=45, height=18)
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")
        return text

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _update_controls(self):
        state = "disabled" if self.running else "normal"
        for control in (
            self.model_entry, self.choose_image_button, self.choose_ontology_button
        ):
            control.configure(state=state)
        self.describe_button.configure(
            state="normal" if (
                not self.running and self.image_path and self.api_key.strip()
            ) else "disabled"
        )
        self.save_result_button.configure(
            state="normal" if not self.running and self.result else "disabled"
        )
        self.save_catalog_button.configure(
            state="normal" if not self.running and self.catalog else "disabled"
        )

    def _choose_image(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Alege un keyframe",
            filetypes=[("Imagini", "*.jpg *.jpeg *.png *.webp")],
        )
        if not filename:
            return
        try:
            path = Path(filename).resolve()
            with Image.open(path) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Folosește o imagine JPEG, PNG sau WEBP.")
                preview = ImageOps.exif_transpose(source).convert("RGB")
            preview.thumbnail((380, 400), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(preview, master=self.root)
        except Exception as exc:
            messagebox.showerror("Imagine invalidă", str(exc), parent=self.root)
            return
        self.image_path = path
        self.image_var.set(str(path))
        self.preview_photo = photo
        self.preview_label.configure(image=photo, text="")
        self.result = None
        self._set_text(self.description_text, "")
        self._set_text(self.json_text, "")
        self.status_var.set("Imagine pregătită pentru descriere.")
        self._update_controls()

    def _choose_ontology(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Alege ontologia",
            filetypes=[
                ("Ontologii RDF", "*.owl *.rdf *.xml *.ttl *.n3 *.nt *.jsonld *.json-ld"),
                ("Toate fișierele", "*.*"),
            ],
        )
        if filename:
            path = Path(filename).resolve()
            self._start_job(
                "ontology", lambda: (path, load_ontology(path)),
                "Se încarcă ontologia…",
            )

    def _describe(self):
        if self.running or self.image_path is None:
            return
        try:
            model = self.model_var.get().strip()
            if not model.endswith(":free"):
                raise ValueError(
                    "Această interfață de test acceptă doar modele cu sufixul :free."
                )
            config = DescriptionConfig(api_key=self.api_key, model=model)
            image_path = self.image_path
            describer = OpenRouterImageDescriber(config)
        except ValueError as exc:
            messagebox.showerror("Configurare invalidă", str(exc), parent=self.root)
            return
        self.result = None
        self._set_text(self.description_text, "")
        self._set_text(self.json_text, "")
        self._start_job(
            "description",
            lambda: describer.describe(image_path, frame_id=image_path.name),
            "Se descrie imaginea. Așteaptă răspunsul modelului…",
        )

    def _start_job(self, kind: str, operation: Callable, status: str):
        if self.running:
            return
        self.running = True
        self.status_var.set(status)
        self._update_controls()
        self.progress.start(12)
        threading.Thread(
            target=self._worker, args=(kind, operation), daemon=True
        ).start()

    def _worker(self, kind: str, operation: Callable):
        # Firul de lucru comunică exclusiv prin coadă, fără acces la Tkinter.
        try:
            self.events.put((kind, operation()))
        except Exception as exc:
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _poll_events(self):
        try:
            kind, value = self.events.get_nowait()
        except Empty:
            pass
        else:
            self.running = False
            self.progress.stop()
            try:
                if kind == "description":
                    self.result = value
                    self._set_text(self.description_text, format_observation(value))
                    self._set_text(self.json_text, value.model_dump_json(indent=2))
                    self.status_var.set(
                        "Descriere finalizată. Poți inspecta și salva observația."
                    )
                elif kind == "ontology":
                    self.ontology_path, self.catalog = value
                    self.ontology_var.set(str(self.ontology_path))
                    self._show_catalog()
                    self.status_var.set("Ontologie încărcată.")
                else:
                    self.status_var.set("Operația a eșuat. Consultă mesajul de eroare.")
                    messagebox.showerror("Procesare nereușită", value, parent=self.root)
            finally:
                self._update_controls()
        self.root.after(100, self._poll_events)

    def _show_catalog(self):
        for item in self.concepts_table.get_children():
            self.concepts_table.delete(item)
        for concept in self.catalog.concepts[:500]:
            self.concepts_table.insert(
                "", "end",
                values=(
                    concept.preferred_label(),
                    ", ".join(kind.value for kind in concept.kinds),
                    concept.iri,
                ),
            )
        summary = self.catalog.summary()
        text = (
            f"Concepte: {summary['total_concepts']} | "
            f"Fără denumiri: {summary['without_labels']} | "
            f"Fără definiții: {summary['without_definitions']}. "
            "Tabelul afișează cel mult 500 de concepte."
        )
        if self.catalog.warnings:
            text += "\n" + "\n".join(self.catalog.warnings)
        self.catalog_summary.configure(text=text)

    def _save_json(self, data: str, filename: str):
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvează rezultatul",
            initialdir=str(self.output_dir if self.output_dir.is_dir() else Path.cwd()),
            initialfile=filename,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not destination:
            return
        try:
            target = Path(destination).resolve()
            if target in {self.image_path, self.ontology_path}:
                raise ValueError("Rezultatul nu poate înlocui un fișier sursă.")
            target.write_text(data + "\n", encoding="utf-8")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Salvare nereușită", str(exc), parent=self.root)
            return
        self.status_var.set(f"Rezultat salvat: {target}")

    def _save_result(self):
        if self.result is not None:
            self._save_json(
                self.result.model_dump_json(indent=2), "frame_observation.json"
            )

    def _save_catalog(self):
        if self.catalog is not None:
            self._save_json(
                json.dumps(self.catalog.to_dict(), ensure_ascii=False, indent=2),
                "ontology_catalog.json",
            )

    def _close(self):
        if self.running:
            messagebox.showinfo(
                "Procesare în desfășurare",
                "Așteaptă încheierea operației înainte de a închide interfața.",
                parent=self.root,
            )
            return
        self.root.destroy()


def launch_interpretation_gui(
    *, api_key: str, model: str = DEFAULT_FREE_MODEL, output_dir: Path
):
    root = tk.Tk()
    InterpretationGUI(root, api_key=api_key, model=model, output_dir=output_dir)
    root.mainloop()
