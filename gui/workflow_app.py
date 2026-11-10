"""Interfață comună pentru extragere, selecție și descriere."""

import hashlib
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from copy import deepcopy


from PIL import Image, ImageOps, ImageTk

from extraction.factory import create_pipeline
from extraction.pipeline import PipelineError
from interpretation.config import InterpretationConfig
from interpretation.service import BatchInterpretationService
from interpretation.strategies.factory import create_strategy
from ontology.catalog import load_ontology_with_source
from ontology.context import build_ontology_context_with_source
from workflow.description_batch import describe_selected_batches
from workflow.models import InterpretationSettings, WorkflowSession
from workflow.service import (
    create_session,
    create_session_from_images,
    get_frame_path,
    set_selection,
)
from gui.keyframe_gallery import KeyframeGallery
from workflow.persistence import save_session_jsonld
from extraction.models import ExtractionSettings
from ontology.namespaces import suggest_namespaces
from gui.formatting import observation_text

from interpretation.config import (
    DEFAULT_LANGUAGE,
    DEFAULT_DOMAIN_CONTEXT,
)
from interpretation.contracts import MAX_GROUP_SIZE

STATUS_LABELS = {
    "pending": "Nedescris",
    "running": "În procesare",
    "completed": "Descris",
    "failed": "Eroare",
}


class WorkflowGUI:
    def __init__(
        self,
        root,
        *,
        api_keys,
        model_defaults,
        initial_provider,
        output_dir,
    ):
        self.root = root

        if initial_provider not in {"gemini", "openrouter", "openai"}:
            raise ValueError(
                f"Furnizor necunoscut: {initial_provider}"
            )

        self.api_keys = dict(api_keys)
        self._models = dict(model_defaults)
        self._active_provider = initial_provider

        self.session = None
        self.ontology_path = None
        self.ontology_context = None
        self.selection_preview_photo = None
        self.advanced_open = False
        self.context_details_open = False

        self.events = Queue()
        self.cancel_event = threading.Event()
        self.busy = None
        self.dirty = False

        self.controls = []
        self.frames_by_id = {}
        self.active_frame_id = None
        self.preview_id = None
        self.preview_photo = None

        self.video_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(output_dir))
        self.seconds_var = tk.StringVar(value="15")
        self.limit_var = tk.StringVar()
        self.threshold_var = tk.StringVar(value="27")
        self.workers_var = tk.StringVar(
            value=str(min(2, os.cpu_count() or 1))
        )
        self.provider_var = tk.StringVar(value=initial_provider)

        self.model_var = tk.StringVar(
            value=self._models.get(initial_provider, "")
        )
        self.batch_size_var = tk.StringVar(value="3")
        self.regenerate_var = tk.BooleanVar(value=False)
        self.source_mode = tk.StringVar(value="video")
        self.domain_var = tk.StringVar(value=DEFAULT_DOMAIN_CONTEXT)
        self.language_var = tk.StringVar(
            value={"English": "Engleză", "Romanian": "Română"}.get(DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        self.ontology_source = None
        self.use_ontology_var = tk.BooleanVar(value=False)
        self.namespace_var = tk.StringVar()
        self.ontology_format_var = tk.StringVar(value="După extensie")
        self.ontology_file_var = tk.StringVar(value="Nicio ontologie încărcată.")
        self.context_status_var = tk.StringVar(value="Încarcă ontologia și alege namespace-ul.")
        self.summary_var = tk.StringVar()
        self.readiness_var = tk.StringVar()

        self.status_var = tk.StringVar(
            value="Încarcă un video sau imagini pentru a începe."
        )
        self.selection_var = tk.StringVar(value="0 cadre selectate")

        root.title("Video → keyframes → descrieri")
        root.geometry("1250x850")
        root.minsize(1050, 720)

        self._build_ui()
        for variable in (self.namespace_var, self.ontology_format_var):
            variable.trace_add("write", self._invalidate_context)
        for variable in (
                self.model_var,
                self.language_var,
                self.domain_var,
                self.batch_size_var,
                self.use_ontology_var,
                self.regenerate_var,
        ):
            variable.trace_add("write", self._settings_changed)

        self.provider_var.trace_add(
            "write",
            self._provider_changed,
        )
        self._sync_controls()

        root.protocol("WM_DELETE_WINDOW", self._close)
        self.poll_id = root.after(100, self._poll_events)

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        return button

    def _entry(self, parent, variable, width=40):
        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=width,
        )
        self.controls.append(entry)
        return entry

    @staticmethod
    def _text(parent):
        widget = ScrolledText(
            parent,
            wrap="word",
            height=12,
            state="disabled",
        )
        widget.pack(fill="both", expand=True)
        return widget

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _build_ui(self):
        style = ttk.Style(self.root)
        style.configure("StepTitle.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("StepHint.TLabel", foreground="#526274")
        style.configure("Primary.TButton", padding=(16, 9))
        style.configure("TNotebook.Tab", padding=(14, 9))

        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        self.tabs = ttk.Notebook(main)
        self.source_tab = ttk.Frame(self.tabs, padding=16)
        self.frames_tab = ttk.Frame(self.tabs, padding=16)
        self.config_tab = ttk.Frame(self.tabs, padding=16)
        self.results_tab = ttk.Frame(self.tabs, padding=16)
        for tab, title in (
            (self.source_tab, "1. Sursă"),
            (self.frames_tab, "2. Selectare imagini"),
            (self.config_tab, "3. Configurare interpretare"),
            (self.results_tab, "4. Rezultate"),
        ):
            self.tabs.add(tab, text=title)

        self._build_source_step()
        self._build_selection_step()
        self._build_configuration_step()
        self._build_results_step()

        footer = ttk.Frame(main)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        self.save_button = self._button(
            footer, "Salvează sesiunea…", self._save
        )
        self.save_button.pack(side="left")
        self.cancel_button = ttk.Button(
            footer,
            text="Oprește după operația curentă",
            command=self._cancel,
        )
        self.cancel_button.pack(side="left", padx=10)
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(side="right", fill="x", expand=True, padx=(20, 0))
        ttk.Label(
            main, textvariable=self.status_var, wraplength=1050,
        ).pack(side="bottom", fill="x", pady=(8, 0))
        self.tabs.pack(fill="both", expand=True)

    def _heading(self, parent, title, hint):
        ttk.Label(parent, text=title, style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(
            parent, text=hint, style="StepHint.TLabel", wraplength=950,
        ).pack(anchor="w", pady=(4, 16))

    def _primary(self, parent, text, command):
        button = self._button(parent, text, command)
        button.configure(style="Primary.TButton")
        return button

    def _field(self, parent, row, label, variable, width=45):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=6
        )
        entry = self._entry(parent, variable, width)
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        return entry

    def _build_source_step(self):
        self._heading(
            self.source_tab, "Cu ce vrei să începi?",
            "Alege un videoclip pentru extragerea cadrelor sau încarcă imaginile existente.",
        )
        choices = ttk.Frame(self.source_tab)
        choices.pack(fill="x", pady=(0, 18))
        for value, label in (
            ("video", "Pornesc de la un videoclip"),
            ("images", "Am deja imagini"),
        ):
            radio = ttk.Radiobutton(
                choices, text=label, value=value,
                variable=self.source_mode, command=self._show_source_mode,
            )
            radio.pack(side="left", padx=(0, 30))
            self.controls.append(radio)

        self.video_panel = ttk.Frame(self.source_tab)
        self.video_panel.pack(fill="x")
        fields = ttk.Frame(self.video_panel)
        fields.pack(fill="x")
        fields.columnconfigure(1, weight=1)
        for row, label, variable in (
            (0, "Videoclip", self.video_var),
            (1, "Directorul rezultatelor", self.output_var),
            (2, "Secunde de scenă / cadru solicitat", self.seconds_var),
            (3, "Număr maxim de cadre (opțional)", self.limit_var),
        ):
            self._field(fields, row, label, variable)
        self._button(fields, "Alege video…", self._choose_video).grid(
            row=0, column=2, padx=(12, 0)
        )
        self._button(fields, "Alege director…", self._choose_output).grid(
            row=1, column=2, padx=(12, 0)
        )
        ttk.Label(
            self.video_panel,
            text="Cadrele sunt alese după conținut; intervalul controlează numărul solicitat.",
            style="StepHint.TLabel", wraplength=900,
        ).pack(anchor="w", pady=8)
        self.advanced_button = self._button(
            self.video_panel, "▸ Setări avansate de extragere", self._toggle_advanced
        )
        self.advanced_button.pack(anchor="w", pady=6)
        self.advanced_panel = ttk.Frame(self.video_panel)
        self.advanced_panel.columnconfigure(1, weight=1)
        self._field(self.advanced_panel, 0, "Prag detectare scene", self.threshold_var)
        self._field(self.advanced_panel, 1, "Procese Katna", self.workers_var)
        self.extract_button = self._primary(
            self.video_panel, "Extrage cadrele", self._extract
        )
        self.extract_button.pack(anchor="e", pady=16)

        self.images_panel = ttk.Frame(self.source_tab)
        ttk.Label(
            self.images_panel,
            text="Poți selecta mai multe imagini JPEG, PNG sau WEBP.\n"
                 "După încărcare, alegi imaginile pe care vrei să le descrii.",
        ).pack(anchor="w", pady=10)
        self._primary(
            self.images_panel, "Încarcă imaginile…", self._choose_images
        ).pack(anchor="e", pady=16)

    def _build_selection_step(self):
        self._heading(
            self.frames_tab, "Alege imaginile relevante",
            "Bifează imaginile pentru analiză. Apasă pe o miniatură pentru previzualizare.",
        )
        body = ttk.Frame(self.frames_tab)
        body.columnconfigure(0, weight=1, minsize=380)
        body.columnconfigure(1, weight=1, minsize=440)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.gallery = KeyframeGallery(
            left,
            on_selection=self._selection_changed,
            on_preview=self._show_selection_frame,
        )
        self.gallery.grid(row=0, column=0, sticky="nsew")
        selection = ttk.Frame(left)
        selection.grid(row=1, column=0, sticky="ew", pady=8)
        self._button(selection, "Selectează toate", lambda: self._select(True)).pack(side="left")
        self._button(selection, "Deselectează toate", lambda: self._select(False)).pack(
            side="left", padx=8
        )
        viewer = ttk.Frame(body)
        viewer.grid(row=0, column=1, sticky="nsew")
        self.selection_picture = ttk.Label(
            viewer, text="Încarcă mai întâi un video sau imagini în pasul 1.",
            anchor="center", wraplength=430,
        )
        self.selection_picture.pack(fill="both", expand=True)
        self.selection_caption = ttk.Label(viewer, wraplength=470)
        self.selection_caption.pack(fill="x", pady=10)

        bottom = ttk.Frame(self.frames_tab)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        self._button(bottom, "Înapoi la sursă", lambda: self.tabs.select(self.source_tab)).pack(side="left")
        ttk.Label(bottom, textvariable=self.selection_var).pack(side="left", padx=18)
        self.continue_button = self._primary(
            bottom, "Selectează imagini pentru a continua",
            lambda: self.tabs.select(self.config_tab),
        )
        self.continue_button.pack(side="right")
        body.pack(fill="both", expand=True)

    def _build_configuration_step(self):
        self._heading(
            self.config_tab, "Pregătește interpretarea",
            "Verifică modelul, limba și contextul înainte să pornești analiza.",
        )
        # Zona centrală se poate derula inclusiv pe ecrane mai mici.
        canvas = tk.Canvas(self.config_tab, highlightthickness=0)
        scroll = ttk.Scrollbar(self.config_tab, orient="vertical", command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas, padding=(0, 0, 14, 0))
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        self.config_canvas = canvas
        self.root.bind("<MouseWheel>", self._configuration_wheel, add="+")

        fields = ttk.Frame(content)
        fields.pack(fill="x")
        fields.columnconfigure(1, weight=1)
        self._field(fields, 0, "Domeniul analizat", self.domain_var)
        ttk.Label(fields, text="Limba descrierilor").grid(row=1, column=0, sticky="w")
        language = ttk.Combobox(fields, textvariable=self.language_var, values=("Română", "Engleză"))
        language.grid(row=1, column=1, sticky="ew", pady=6)
        self.controls.append(language)
        ttk.Label(
            fields,
            text="Furnizor",
        ).grid(row=2, column=0, sticky="w")

        self.provider_combo = ttk.Combobox(
            fields,
            textvariable=self.provider_var,
            values=("openrouter", "gemini", "openai"),
            state="readonly",
        )
        self.provider_combo.grid(
            row=2,
            column=1,
            sticky="ew",
            pady=6,
        )
        self.controls.append(self.provider_combo)

        self._field(fields, 3, "Model", self.model_var)

        ttk.Label(
            fields,
            text="Imagini per apel",
        ).grid(row=4, column=0, sticky="w")

        self.batch_size_combo = ttk.Combobox(
            fields,
            textvariable=self.batch_size_var,
            values=tuple(str(size) for size in range(1, MAX_GROUP_SIZE + 1)),
            state="readonly",
        )
        self.batch_size_combo.grid(
            row=4,
            column=1,
            sticky="ew",
            pady=6,
        )
        self.controls.append(self.batch_size_combo)

        ttk.Label(
            fields,
            text=(
                "Context comun; descriere separată pentru "
                "fiecare imagine."
            ),
            style="StepHint.TLabel",
        ).grid(row=5, column=1, sticky="w")

        use = ttk.Checkbutton(
            content, text="Ghidează descrierea folosind o ontologie",
            variable=self.use_ontology_var,
        )
        use.pack(anchor="w", pady=8)
        self.controls.append(use)

        self.ontology_panel = ttk.LabelFrame(content, text="Contextul ontologic", padding=12)
        file_row = ttk.Frame(self.ontology_panel)
        file_row.pack(fill="x")
        self._button(file_row, "Încarcă ontologia…", self._choose_ontology).pack(side="left")
        ttk.Label(
            file_row, textvariable=self.ontology_file_var, wraplength=650,
        ).pack(side="left", padx=12)
        ns_row = ttk.Frame(self.ontology_panel)
        ns_row.pack(fill="x", pady=8)
        ns_row.columnconfigure(1, weight=1)
        ttk.Label(ns_row, text="Namespace propriu").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.namespace_combo = ttk.Combobox(ns_row, textvariable=self.namespace_var)
        self.namespace_combo.grid(row=0, column=1, sticky="ew")
        self.controls.append(self.namespace_combo)
        ttk.Label(
            self.ontology_panel, text="Prefixul IRI al termenilor proprii; verifică valoarea propusă.",
            style="StepHint.TLabel",
        ).pack(anchor="w")
        format_row = ttk.Frame(self.ontology_panel)
        format_row.pack(fill="x", pady=8)
        ttk.Label(format_row, text="Formatul fișierului").pack(side="left")
        self.format_combo = ttk.Combobox(
            format_row, textvariable=self.ontology_format_var, width=18,
            values=("După extensie", "RDF/XML", "Turtle", "N-Triples"), state="readonly",
        )
        self.format_combo.pack(side="left", padx=12)
        self.controls.append(self.format_combo)
        self.generate_context_button = self._button(
            format_row, "Pregătește contextul", self._generate_context
        )
        self.generate_context_button.pack(side="right")
        ttk.Label(
            self.ontology_panel, textvariable=self.context_status_var, wraplength=850,
        ).pack(anchor="w", pady=6)
        self.context_details_button = self._button(
            self.ontology_panel, "▸ Vezi contextul și detaliile", self._toggle_context_details
        )
        self.context_details_button.pack(anchor="w")
        self.context_details_panel = ttk.Frame(self.ontology_panel)
        details = ttk.Notebook(self.context_details_panel)
        details.pack(fill="both", expand=True)
        turtle_tab, report_tab = ttk.Frame(details), ttk.Frame(details)
        details.add(turtle_tab, text="Context Turtle")
        details.add(report_tab, text="Raport")
        self.context_widget = self._text(turtle_tab)
        self.context_widget.configure(height=8)
        self.ontology_widget = self._text(report_tab)
        self.ontology_widget.configure(height=8)
        self.export_context_button = self._button(
            self.context_details_panel, "Exportă contextul Turtle…", self._export_context
        )
        self.export_context_button.pack(anchor="e", pady=(6, 0))

        self.config_summary = ttk.Label(content, textvariable=self.summary_var, wraplength=900)
        self.config_summary.pack(anchor="w", pady=(18, 5))
        ttk.Label(
            content, textvariable=self.readiness_var, wraplength=900, style="StepHint.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(0, 12))
        self._button(
            actions, "Înapoi la selecție", lambda: self.tabs.select(self.frames_tab)
        ).pack(side="left")
        self.describe_button = self._primary(actions, "Descrie imaginile", self._describe)
        self.describe_button.pack(side="right")

    def _build_results_step(self):
        self._heading(
            self.results_tab, "Examinează rezultatele",
            "Alege o imagine din listă pentru a vedea descrierea și datele asociate.",
        )
        body = ttk.Frame(self.results_tab)
        body.columnconfigure(0, weight=1, minsize=270)
        body.columnconfigure(1, weight=3, minsize=500)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self.result_tree = ttk.Treeview(
            left, columns=("status",), show="tree headings", selectmode="browse", height=12
        )
        self.result_tree.heading("#0", text="Imagine")
        self.result_tree.heading("status", text="Stare")
        self.result_tree.column("#0", width=180, minwidth=120)
        self.result_tree.column("status", width=95, minwidth=75, stretch=False)
        tree_scroll = ttk.Scrollbar(left, orient="vertical", command=self.result_tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.result_tree.pack(fill="both", expand=True)
        self.result_tree.configure(yscrollcommand=tree_scroll.set)
        self.result_tree.bind("<<TreeviewSelect>>", self._result_selected)
        viewer = ttk.Frame(body)
        viewer.grid(row=0, column=1, sticky="nsew")
        self.picture = ttk.Label(
            viewer, text="Rezultatele vor apărea după pornirea analizei din pasul 3.",
            anchor="center", wraplength=600,
        )
        self.picture.pack(fill="x")
        self.caption = ttk.Label(viewer, wraplength=620)
        self.caption.pack(fill="x", pady=6)
        result_tabs = ttk.Notebook(viewer)
        result_tabs.pack(fill="both", expand=True)
        observation_tab, json_tab = ttk.Frame(result_tabs), ttk.Frame(result_tabs)
        result_tabs.add(observation_tab, text="Descriere")
        result_tabs.add(json_tab, text="JSON-LD")
        self.observation_widget = self._text(observation_tab)
        self.json_widget = self._text(json_tab)

        options = ttk.Frame(self.results_tab)
        regenerate = ttk.Checkbutton(
            options, text="Regenerează și descrierile existente la următoarea analiză",
            variable=self.regenerate_var,
        )
        regenerate.pack(side="left")
        self.controls.append(regenerate)
        actions = ttk.Frame(self.results_tab)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        options.pack(side="bottom", fill="x", pady=(12, 0))
        self._button(
            actions, "Configurează o nouă analiză", lambda: self.tabs.select(self.config_tab)
        ).pack(side="left")
        self.results_save_button = self._primary(
            actions, "Salvează rezultatele…", self._save
        )
        self.results_save_button.pack(side="right")
        body.pack(fill="both", expand=True)

    def _show_source_mode(self):
        self.video_panel.pack_forget()
        self.images_panel.pack_forget()
        panel = self.video_panel if self.source_mode.get() == "video" else self.images_panel
        panel.pack(fill="x")

    def _configuration_wheel(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Combobox)):
            return
        while widget is not None and widget is not self.config_tab:
            widget = getattr(widget, "master", None)
        if widget is self.config_tab and event.delta:
            if self.config_canvas.yview() != (0.0, 1.0):
                units = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
                self.config_canvas.yview_scroll(units, "units")
                return "break"

    def _toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced_panel.pack(fill="x", before=self.extract_button)
        else:
            self.advanced_panel.pack_forget()
        self.advanced_button.configure(
            text=("▾" if self.advanced_open else "▸") + " Setări avansate de extragere"
        )

    def _toggle_context_details(self):
        self.context_details_open = not self.context_details_open
        if self.context_details_open:
            self.context_details_panel.pack(fill="both", expand=True, pady=(8, 0))
        else:
            self.context_details_panel.pack_forget()
        self.context_details_button.configure(
            text=("▾" if self.context_details_open else "▸") + " Vezi contextul și detaliile"
        )

    def _result_selected(self, event=None):
        ids = self.result_tree.selection()
        if ids and ids[0] in self.frames_by_id and ids[0] != self.active_frame_id:
            self._show_frame(ids[0])

    def _language(self):
        value = self.language_var.get().strip()
        return {"Română": "Romanian", "Engleză": "English"}.get(value, value)

    def _rdf_format(self):
        return {
            "RDF/XML": "xml", "Turtle": "turtle", "N-Triples": "nt",
        }.get(self.ontology_format_var.get())

    def _settings_changed(self, *args):
        if self.session is not None:
            self.dirty = True
        self._sync_controls()

    def _provider_changed(self, *args):
        provider = self.provider_var.get()

        if provider not in {"gemini", "openrouter", "openai"}:
            self._settings_changed()
            return

        if provider != self._active_provider:
            # Reținem ultimul model introdus pentru furnizorul anterior.
            self._models[self._active_provider] = (
                self.model_var.get().strip()
            )

            self._active_provider = provider

            self.model_var.set(
                self._models.get(provider, "")
            )

        self._settings_changed()

    def _invalidate_context(self, *args):
        self.ontology_context = None
        self.context_status_var.set("Context nepregătit. Alege fișierul și namespace-ul.")
        self._set_text(self.context_widget, "Pregătește contextul pentru previzualizare.")
        self._set_text(self.ontology_widget, "")
        self._settings_changed()

    def _capture_settings(self):
        context = self.ontology_context
        return InterpretationSettings(
            provider=self.provider_var.get(),
            batch_size=int(self.batch_size_var.get()),
            model=self.model_var.get().strip(),
            language=self._language(),
            domain_context=self.domain_var.get().strip(),
            use_ontology=self.use_ontology_var.get(),
            namespace=self.namespace_var.get().strip(),
            rdf_format=self._rdf_format(),
            context_turtle=context.turtle if context else "",
            context_report=deepcopy(context.report) if context else {},
        )

    def _with_settings(self, session):
        return WorkflowSession.model_validate({
            **session.model_dump(),
            "schema_version": "2.2",
            "ontology_path": self.ontology_path,
            "interpretation_settings": self._capture_settings(),
        })

    def _description_blocker(self):
        if self.busy:
            return "O operație este în desfășurare."

        if self.session is None:
            return "Încarcă un video sau imagini în pasul 1."

        if not any(
                state.selected for state in self.session.frames
        ):
            return "Selectează cel puțin o imagine în pasul 2."

        provider = self.provider_var.get()

        key_names = {
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
        }

        if provider not in key_names:
            return "Selectează un furnizor valid."

        if not self.api_keys.get(provider, "").strip():
            return (
                f"Lipsește cheia pentru {provider}. "
                f"Configurează {key_names[provider]} "
                "și repornește aplicația."
            )

        if not self.model_var.get().strip():
            return "Completează identificatorul modelului."

        try:
            batch_size = int(self.batch_size_var.get())
        except ValueError:
            return "Alege un număr valid de imagini per apel."

        if not 1 <= batch_size <= MAX_GROUP_SIZE:
            return f"Alege între 1 și {MAX_GROUP_SIZE} imagini per apel."

        if not self._language():
            return "Completează limba descrierilor."

        if (
                self.use_ontology_var.get()
                and self.ontology_context is None
        ):
            return (
                "Pregătește contextul ontologic "
                "sau dezactivează folosirea lui."
            )

        return ""

    def _sync_controls(self):
        for control in self.controls:
            control.configure(state="disabled" if self.busy else "normal")

        selection_state = "disabled" if self.busy else "readonly"

        self.provider_combo.configure(state=selection_state)
        self.batch_size_combo.configure(state=selection_state)
        self.format_combo.configure(state="disabled" if self.busy else "readonly")
        count = sum(state.selected for state in self.session.frames) if self.session else 0
        self.continue_button.configure(
            state="normal" if count and not self.busy else "disabled",
            text=f"Continuă cu {count} imagini" if count else "Selectează imagini pentru a continua",
        )
        if self.use_ontology_var.get():
            if not self.ontology_panel.winfo_manager():
                self.ontology_panel.pack(fill="x", before=self.config_summary, pady=8)
        else:
            self.ontology_panel.pack_forget()

        blocker = self._description_blocker()
        self.describe_button.configure(
            state="disabled" if blocker else "normal",
            text=f"Descrie cele {count} imagini",
        )
        existing = sum(
            state.selected and state.observation is not None
            for state in self.session.frames
        ) if self.session else 0
        ready_text = "Pregătit pentru analiză."
        if existing and not self.regenerate_var.get():
            ready_text += (
                f" {existing} descrieri existente vor fi păstrate. "
                "Pentru refacere, activează regenerarea în pasul 4."
            )
        elif existing:
            ready_text += f" Vor fi regenerate și {existing} descrieri existente."
        self.readiness_var.set(blocker or ready_text)
        context_label = (
            "Context ontologic activ" if self.ontology_context else "Context de pregătit"
        ) if self.use_ontology_var.get() else "Fără context ontologic"
        self.summary_var.set(
            f"{count} imagini selectate · {self.model_var.get().strip()} · "
            f"{self.language_var.get().strip()} · {context_label}"
        )
        save_state = "normal" if self.session and not self.busy else "disabled"
        self.save_button.configure(state=save_state)
        self.results_save_button.configure(state=save_state)
        self.generate_context_button.configure(
            state="normal" if not self.busy and self.ontology_path
            and self.namespace_var.get().strip() else "disabled"
        )
        self.export_context_button.configure(
            state="normal" if not self.busy and self.ontology_context else "disabled"
        )
        self.cancel_button.configure(
            state="normal" if self.busy in {"extraction", "description"}
            and not self.cancel_event.is_set() else "disabled"
        )
        self.gallery.set_enabled(not self.busy)

    def _generate_context(self):
        if self.busy or self.ontology_path is None:
            return
        path = self.ontology_path
        namespace = self.namespace_var.get().strip()
        rdf_format = self._rdf_format()
        cached_source = self.ontology_source
        self._invalidate_context()
        self.context_status_var.set("Se pregătește contextul…")
        self.status_var.set("Se extrage vocabularul ontologiei, local…")
        self._launch(
            "context",
            lambda cancel, emit: build_ontology_context_with_source(
                path,
                namespace,
                rdf_format=rdf_format,
                cached_source=cached_source,
            ),
        )

    def _export_context(self):
        if self.busy or self.ontology_context is None:
            return
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="Exportă contextul Turtle",
            initialfile="context.ttl", defaultextension=".ttl",
            filetypes=[("Turtle", "*.ttl")],
        )
        if not filename:
            return
        try:
            destination = Path(filename).resolve()
            protected = {self.ontology_path.resolve()} if self.ontology_path else set()
            if self.session:
                protected.update(
                    get_frame_path(self.session, frame.frame_id, must_exist=False)
                    for frame in self.session.keyframes
                )
                if self.session.extraction:
                    protected.add(self.session.extraction.input_video.resolve())
                    protected.add(self.session.extraction.manifest.resolve())
            if destination in protected:
                raise ValueError("Alege o destinație diferită de fișierele sursă.")
            destination.write_text(self.ontology_context.turtle, encoding="utf-8")
            self.status_var.set(f"Context exportat: {destination}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export nereușit", str(exc), parent=self.root)

    def _choose_video(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Alege video",
            filetypes=[
                ("Video", "*.mp4 *.avi *.mov *.mkv"),
                ("Toate", "*.*"),
            ],
        )
        if path:
            self.video_var.set(path)

    def _choose_output(self):
        path = filedialog.askdirectory(parent=self.root)
        if path:
            self.output_var.set(path)

    def _choose_images(self):
        if self.busy:
            return

        filenames = filedialog.askopenfilenames(
            parent=self.root,
            title="Alege imaginile",
            filetypes=[
                ("Imagini", "*.jpg *.jpeg *.png *.webp"),
            ],
        )

        if not filenames:
            return

        if self.dirty and not messagebox.askyesno(
            "Sesiune nouă",
            "Încărcarea imaginilor va înlocui sesiunea din interfață. "
            "Modificările nesalvate se vor pierde. Continui?",
            parent=self.root,
        ):
            return

        paths = tuple(filenames)

        self.status_var.set("Se verifică imaginile…")
        self._launch(
            "images",
            lambda cancel, emit: create_session_from_images(paths),
        )


    def _launch(self, kind, operation):
        """Execută operația în fundal; comunicarea cu GUI trece prin coadă."""
        if self.busy:
            return

        self.busy = kind
        self.cancel_event = threading.Event()
        cancel = self.cancel_event

        self._sync_controls()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def emit(event, value):
            self.events.put((event, value))

        def work():
            try:
                result = operation(cancel, emit)
                emit("result", (kind, result))
            except Exception as exc:
                emit("error", f"{type(exc).__name__}: {exc}")
            finally:
                emit("done", None)

        threading.Thread(target=work, daemon=False).start()

    def _extract(self):
        if self.busy:
            return
        try:
            if (
                not self.video_var.get().strip()
                or not self.output_var.get().strip()
            ):
                raise ValueError(
                    "Completează video-ul și directorul rezultatelor."
                )

            video = (
                Path(self.video_var.get().strip())
                .expanduser()
                .resolve()
            )
            output = (
                Path(self.output_var.get().strip())
                .expanduser()
                .resolve()
            )

            seconds = float(self.seconds_var.get().replace(",", "."))
            threshold = float(
                self.threshold_var.get().replace(",", ".")
            )
            workers = int(self.workers_var.get())

            limit_text = self.limit_var.get().strip()
            limit = int(limit_text) if limit_text else None

            if not video.is_file() or video.stat().st_size == 0:
                raise ValueError(
                    "Alege un fișier video existent și nevid."
                )

            if output.exists() and not output.is_dir():
                raise ValueError(
                    "Destinația trebuie să fie un director."
                )

            settings = ExtractionSettings(
                seconds_per_keyframe=seconds,
                threshold=threshold,
                max_workers=workers,
                max_total_keyframes=limit,
            )

            if not 0 < threshold <= 255:
                raise ValueError(
                    "Pragul trebuie să fie mai mare de 0 și cel mult 255."
                )

            if workers > (os.cpu_count() or 1):
                raise ValueError(
                    "Numărul de procese depășește capacitatea procesorului."
                )

        except (ValueError, OSError) as exc:
            messagebox.showerror(
                "Configurare invalidă",
                str(exc),
                parent=self.root,
            )
            return

        if self.dirty and not messagebox.askyesno(
            "Sesiune nouă",
            "Noua extragere va înlocui sesiunea din interfață. "
            "Modificările nesalvate se vor pierde. Continui?",
            parent=self.root,
        ):
            return

        def operation(cancel, emit):
            pipeline = create_pipeline(
                threshold=threshold,
                max_workers=workers,
            )

            try:
                return pipeline.run(
                    input_video=video,
                    base_output_dir=output,
                    seconds_per_keyframe=settings.seconds_per_keyframe,
                    max_total_keyframes=settings.max_total_keyframes,
                    cancel_event=cancel,
                    progress_callback=lambda text, current, total: emit(
                        "extraction_progress",
                        (text, current, total),
                    ),
                )
            except PipelineError as exc:
                return exc.result

        self.status_var.set("Se pregătește extragerea…")
        self._launch("extraction", operation)

    def _select(self, all_frames):
        if self.busy or self.session is None:
            return

        self.gallery.set_selected(
            self.frames_by_id if all_frames else ()
        )
        self._selection_changed()

    def _selection_changed(self):
        if self.session is None:
            return

        old = {
            state.frame_id
            for state in self.session.frames
            if state.selected
        }

        if self.busy:
            self.gallery.set_selected(old)
            return

        ids = self.gallery.selected_ids()

        if ids != old:
            self.session = set_selection(self.session, ids)
            self.dirty = True

        self.selection_var.set(
            f"{len(ids)} / {len(self.session.frames)} cadre selectate"
        )
        self._refresh_result_list()
        self._sync_controls()

    def _populate_frames(self):
        self.frames_by_id = {
            frame.frame_id: frame
            for frame in self.session.keyframes
        }

        states = {
            state.frame_id: state
            for state in self.session.frames
        }

        selected = {
            state.frame_id
            for state in self.session.frames
            if state.selected
        }

        self.active_frame_id = None
        self.preview_id = None
        self.preview_photo = None

        self.picture.configure(
            image="",
            text="Apasă pe o miniatură.",
        )
        self.caption.configure(text="")
        self._set_text(self.observation_widget, "")
        self._set_text(self.json_widget, "")

        items = [
            {
                "id": frame.frame_id,
                "path": get_frame_path(
                    self.session,
                    frame.frame_id,
                    must_exist=False,
                ),
                "title": (
                    f"Scena {frame.scene_index} · {frame.image_path.name}"
                    if frame.scene_index is not None
                    else frame.image_path.name
                ),
                "status": STATUS_LABELS[
                    states[frame.frame_id].description_status
                ],
            }
            for frame in self.session.keyframes
        ]

        self.selection_preview_photo = None
        self.selection_picture.configure(image="", text="Apasă pe o miniatură.")
        self.selection_caption.configure(text="")
        self.result_tree.delete(*self.result_tree.get_children())
        self.gallery.set_frames(items, selected)
        self.gallery.set_enabled(not self.busy)

        self.selection_var.set(
            f"{len(selected)} / "
            f"{len(self.session.frames)} cadre selectate"
        )

        if self.session.keyframes:
            self._show_selection_frame(
                self.session.keyframes[0].frame_id
            )

        self._refresh_result_list()

    def _refresh_result_list(self):
        """Afișează numai cadrele selectate, fără să modifice observațiile."""
        states = {
            state.frame_id: state
            for state in self.session.frames
        } if self.session else {}

        visible_ids = [
            frame.frame_id
            for frame in self.session.keyframes
            if states[frame.frame_id].selected
        ] if self.session else []

        visible = set(visible_ids)

        # Eliminăm doar rândurile afișate, nu datele din sesiune.
        for frame_id in self.result_tree.get_children():
            if frame_id not in visible:
                self.result_tree.delete(frame_id)

        for index, frame_id in enumerate(visible_ids):
            frame = self.frames_by_id[frame_id]

            title = (
                f"Scena {frame.scene_index} · {frame.image_path.name}"
                if frame.scene_index is not None
                else frame.image_path.name
            )

            values = (
                STATUS_LABELS[states[frame_id].description_status],
            )

            if self.result_tree.exists(frame_id):
                self.result_tree.item(
                    frame_id,
                    text=title,
                    values=values,
                )
                self.result_tree.move(frame_id, "", index)
            else:
                self.result_tree.insert(
                    "",
                    index,
                    iid=frame_id,
                    text=title,
                    values=values,
                )

        if visible_ids:
            target = (
                self.active_frame_id
                if self.active_frame_id in visible
                else visible_ids[0]
            )
            self._show_frame(target)
        else:
            self.active_frame_id = None
            self.preview_id = None
            self.preview_photo = None

            self.result_tree.focus("")
            self.picture.configure(
                image="",
                text="Selectează imagini în pasul 2 pentru a le vedea aici.",
            )
            self.caption.configure(text="")
            self._set_text(self.observation_widget, "")
            self._set_text(self.json_widget, "")

    def _load_frame_previews(self, frame_id, sizes):
        """Încarcă imaginea o dată și creează previzualizările cerute."""
        path = get_frame_path(self.session, frame_id)
        photos = []

        with Image.open(path) as source:
            with ImageOps.exif_transpose(source) as oriented:
                with oriented.convert("RGB") as image:
                    for size in sizes:
                        with image.copy() as preview:
                            preview.thumbnail(
                                size,
                                Image.Resampling.LANCZOS,
                            )
                            photos.append(
                                ImageTk.PhotoImage(
                                    preview,
                                    master=self.root,
                                )
                            )

        return tuple(photos)

    def _frame_caption(self, frame_id):
        frame = self.frames_by_id[frame_id]

        if self.session.extraction is None:
            return (
                f"{frame.image_path.name} | Imagine încărcată direct."
            )

        scene = next(
            scene
            for scene in self.session.extraction.scenes
            if scene.index == frame.scene_index
        )

        return (
            f"{frame.image_path.name} | Scena {scene.index}: "
            f"{scene.start_seconds:.2f}–{scene.end_seconds:.2f} s. "
            "Intervalul este al scenei, nu timestamp-ul cadrului."
        )

    def _show_selection_frame(self, frame_id):
        """Previzualizează orice cadru în pasul 2, independent de rezultate."""
        if frame_id not in self.frames_by_id:
            return

        self.gallery.mark_active(frame_id)

        # _show_frame actualizează și previzualizarea din pasul 2.
        # Invalidăm cache-ul pentru revenirea ulterioară la acel cadru.
        self.preview_id = None

        try:
            (self.selection_preview_photo,) = self._load_frame_previews(
                frame_id,
                sizes=((520, 390),),
            )
            self.selection_picture.configure(
                image=self.selection_preview_photo,
                text="",
            )

        except (OSError, ValueError) as exc:
            self.selection_preview_photo = None
            self.selection_picture.configure(
                image="",
                text=f"Imagine indisponibilă: {exc}",
            )

        self.selection_caption.configure(
            text=self._frame_caption(frame_id)
        )

    def _update_row(self, frame_id):
        state = next(
            state
            for state in self.session.frames
            if state.frame_id == frame_id
        )

        label = STATUS_LABELS[state.description_status]
        self.gallery.set_status(frame_id, label)
        if self.result_tree.exists(frame_id):
            self.result_tree.item(frame_id, values=(label,))

    def _show_frame(self, frame_id):
        if (
                frame_id not in self.frames_by_id
                or not self.result_tree.exists(frame_id)
        ):
            return
        if self.result_tree.selection() != (frame_id,):
            self.result_tree.selection_set(frame_id)
            self.result_tree.see(frame_id)
        self.active_frame_id = frame_id
        self.gallery.mark_active(frame_id)

        state = next(
            s for s in self.session.frames
            if s.frame_id == frame_id
        )

        if self.preview_id != frame_id:
            try:
                (
                    self.selection_preview_photo,
                    self.preview_photo,
                ) = self._load_frame_previews(
                    frame_id,
                    sizes=((520, 390), (560, 240)),
                )

                self.selection_picture.configure(
                    image=self.selection_preview_photo,
                    text="",
                )
                self.picture.configure(
                    image=self.preview_photo,
                    text="",
                )
                self.preview_id = frame_id

            except (OSError, ValueError) as exc:
                self.preview_id = None
                self.selection_preview_photo = None
                self.preview_photo = None

                message = f"Imagine indisponibilă: {exc}"
                self.selection_picture.configure(
                    image="",
                    text=message,
                )
                self.picture.configure(
                    image="",
                    text=message,
                )

        caption = self._frame_caption(frame_id)
        self.caption.configure(text=caption)
        self.selection_caption.configure(text=caption)

        text = (
            f"Stare: {STATUS_LABELS[state.description_status]}\n\n"
        )

        if state.error:
            text += f"Eroare: {state.error}\n\n"

            if state.observation:
                text += (
                    "Mai jos este păstrată observația anterioară.\n\n"
                )

        text += (
            observation_text(state.observation)
            if state.observation
            else "Nu există încă o descriere validă."
        )

        self._set_text(self.observation_widget, text)

        if state.observation is not None:
            jsonld_text = json.dumps(
                state.observation.to_jsonld(),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        else:
            jsonld_text = (
                "Nu există încă o observație de afișat în JSON-LD."
            )

        self._set_text(self.json_widget, jsonld_text)

    def _describe(self):
        if self.busy:
            return

        try:
            blocker = self._description_blocker()

            if blocker:
                raise ValueError(blocker)

            context = (
                self.ontology_context
                if self.use_ontology_var.get()
                else None
            )

            if context:
                source = Path(context.report["source_path"])

                try:
                    current_hash = hashlib.sha256(
                        source.read_bytes()
                    ).hexdigest()

                except OSError as exc:
                    self._invalidate_context()

                    raise ValueError(
                        "Ontologia nu mai poate fi citită. "
                        "Reîncarcă fișierul."
                    ) from exc

                if current_hash != context.report["source_sha256"]:
                    self._invalidate_context()

                    raise ValueError(
                        "Ontologia s-a schimbat. "
                        "Pregătește din nou contextul."
                    )

            provider = self.provider_var.get()
            model = self.model_var.get().strip()
            api_key = self.api_keys[provider].strip()
            batch_size = int(self.batch_size_var.get())

            config = InterpretationConfig(
                language=self._language(),
                domain_context=self.domain_var.get().strip(),
                ontology_context=(
                    context.turtle if context else ""
                ),
                ontology_namespace=(
                    context.report["namespace"]
                    if context else ""
                ),
                ontology_source_sha256=(
                    context.report["source_sha256"]
                    if context else ""
                ),
                ontology_extraction_version=(
                    context.report["extraction_version"]
                    if context else ""
                ),
            )

            strategy = create_strategy(
                provider,
                api_key=api_key,
                model=model,
            )

            service = BatchInterpretationService(
                strategy=strategy,
                config=config,
            )

            self.session = self._with_settings(self.session)

            # Configurația rulării este capturată înainte de worker.
            snapshot = self.session
            regenerate = self.regenerate_var.get()

        except (ValueError, OSError) as exc:
            messagebox.showerror(
                "Configurare invalidă",
                str(exc),
                parent=self.root,
            )
            return

        def operation(cancel, emit):
            for event in describe_selected_batches(
                    snapshot,
                    service,
                    batch_size=batch_size,
                    regenerate=regenerate,
                    cancel_event=cancel,
            ):
                emit("description_progress", event)

        self.tabs.select(self.results_tab)

        first_selected = next(
            state
            for state in snapshot.frames
            if state.selected
        )

        self._show_frame(first_selected.frame_id)

        self.status_var.set(
            f"Se pregătesc descrierile: {provider} / {model}…"
        )

        self._launch("description", operation)

    def _choose_ontology(self):
        if self.busy:
            return
        filename = filedialog.askopenfilename(
            parent=self.root, title="Alege ontologia",
            filetypes=[("Ontologie", "*.rdf *.owl *.ttl *.nt"), ("Toate", "*.*")],
        )
        if filename:
            path = Path(filename).resolve()
            rdf_format = self._rdf_format()
            self.ontology_path = path
            self.ontology_source = None
            self.ontology_file_var.set(str(path))
            self.namespace_combo.configure(values=())
            self.namespace_var.set("")
            self._invalidate_context()
            self.status_var.set("Se citește ontologia…")
            self._launch(
                "ontology",
                lambda cancel, emit: load_ontology_with_source(
                    path,
                    rdf_format=rdf_format,
                ),
            )

    def _poll_events(self):
        """Actualizările Tkinter se fac exclusiv în firul principal."""
        try:
            for _ in range(100):
                try:
                    kind, value = self.events.get_nowait()
                except Empty:
                    break

                try:
                    self._handle_event(kind, value)
                except Exception as exc:
                    self.status_var.set(
                        "Eroare la afișarea rezultatului."
                    )
                    messagebox.showerror(
                        "Eroare",
                        str(exc),
                        parent=self.root,
                    )
        finally:
            self.poll_id = self.root.after(100, self._poll_events)

    def _handle_event(self, kind, value):
        if kind == "extraction_progress":
            text, current, total = value

            if not self.cancel_event.is_set():
                self.status_var.set(text)

            if total:
                self.progress.stop()
                self.progress.configure(
                    mode="determinate",
                    value=100 * current / total,
                )

        elif kind == "description_progress":
            self.session = value.session
            self.dirty = True

            self.progress.stop()
            self.progress.configure(
                mode="determinate",
                value=100 * value.processed / value.total,
            )

            if value.frame_id:
                self._update_row(value.frame_id)

                if self.active_frame_id == value.frame_id:
                    self._show_frame(value.frame_id)

            if value.kind == "batch_cancelled":
                for state in self.session.frames:
                    self._update_row(state.frame_id)

                if self.active_frame_id in self.frames_by_id:
                    self._show_frame(self.active_frame_id)

            prefix = {
                "batch_finished": "Procesare încheiată",
                "batch_cancelled": "Procesare anulată",
            }.get(value.kind, "Descriere")

            self.status_var.set(
                f"{prefix}: {value.processed}/{value.total}. "
                f"Noi: {value.succeeded}; erori: {value.failed}; "
                f"existente păstrate: {value.skipped}."
            )

        elif kind == "result":
            job, result = value

            if job == "extraction":
                session = create_session(result)

                self.session = self._with_settings(session)

                self.dirty = True
                self.regenerate_var.set(False)
                self._populate_frames()
                self.tabs.select(self.frames_tab)

                self.status_var.set(
                    f"{result.message} "
                    f"Cadre disponibile: {len(self.session.keyframes)}."
                    + (
                        " " + "; ".join(
                            e.message for e in result.errors[:3]
                        )
                        if result.errors
                        else ""
                    )
                )

            elif job == "images":
                self.session = self._with_settings(result)

                self.dirty = True
                self.regenerate_var.set(False)
                self._populate_frames()
                self.tabs.select(self.frames_tab)
                self.progress.configure(value=0)

                self.status_var.set(
                    f"Imagini încărcate: {len(self.session.keyframes)}. "
                    "Bifează imaginile pe care vrei să le descrii."
                )



            elif job == "ontology":

                self.ontology_source, catalog = result

                self.ontology_path = Path(catalog.source)

                self.ontology_file_var.set(str(self.ontology_path))

                suggestions = suggest_namespaces(catalog)

                self.namespace_combo.configure(values=suggestions)

                self.namespace_var.set(

                    suggestions[0] if suggestions else ""

                )

                self._set_text(

                    self.ontology_widget,

                    json.dumps(

                        catalog.summary(),

                        ensure_ascii=False,

                        indent=2,

                    ),

                )

                self.context_status_var.set(

                    "Verifică namespace-ul propus, "

                    "apoi pregătește contextul."

                )

                self.status_var.set(

                    "Ontologie încărcată. Contextul trebuie "

                    "pregătit înainte de analiză."

                )

            elif job == "context":

                self.ontology_source, context = result

                self.ontology_context = context

                result = context

                report = result.report

                self.context_status_var.set(
                    f"Context pregătit: {report['anchor_count']} concepte proprii · "
                    f"{report['context_triples']} triplete · "
                    f"{report['utf8_bytes'] / 1024:.1f} KB."
                )
                self._set_text(self.context_widget, result.turtle)
                self._set_text(self.ontology_widget, json.dumps(report, ensure_ascii=False, indent=2))
                if self.session:
                    self.dirty = True
                self.status_var.set("Context pregătit. Poți porni descrierea imaginilor.")

        elif kind == "error":
            self.status_var.set("Operația a eșuat.")
            if self.busy in {"context", "ontology"}:
                self.context_status_var.set("Pregătirea a eșuat. Verifică fișierul, formatul și namespace-ul.")

            messagebox.showerror(
                "Procesare nereușită",
                value,
                parent=self.root,
            )

        elif kind == "done":
            self.busy = None
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self._sync_controls()

    def _cancel(self):
        if self.busy in {"extraction", "description"}:
            self.cancel_event.set()
            self.status_var.set(
                "Anulare solicitată. "
                "Se așteaptă încheierea operației curente."
            )
            self._sync_controls()

    def _save(self):
        if self.busy or self.session is None:
            return

        initial_dir = (
            self.session.extraction.output_dir
            if self.session.extraction is not None
            else self.session.imported_frames[0].image_path.parent
        )

        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvează sesiunea JSON-LD",
            initialdir=str(initial_dir),
            initialfile=f"workflow_{self.session.session_id}.jsonld",
            defaultextension=".jsonld",
            filetypes=[("JSON-LD", "*.jsonld")],
        )

        if not filename:
            return

        try:
            self.session = self._with_settings(self.session)
            destination = save_session_jsonld(
                self.session,
                filename,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Salvare nereușită",
                str(exc),
                parent=self.root,
            )
            return

        self.dirty = False
        self.status_var.set(
            f"Sesiune salvată: {destination}"
        )

    def _close(self):
        if self.busy:
            messagebox.showinfo(
                "Procesare în desfășurare",
                "Anulează procesarea și așteaptă finalizarea "
                "înainte de închidere.",
                parent=self.root,
            )
            return

        if self.dirty and not messagebox.askyesno(
            "Închidere",
            "Sesiunea are modificări nesalvate. "
            "Închizi fără salvare?",
            parent=self.root,
        ):
            return

        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def launch_workflow_gui(
    *,
    api_keys,
    model_defaults,
    initial_provider,
    output_dir,
):
    root = tk.Tk()

    WorkflowGUI(
        root,
        api_keys=api_keys,
        model_defaults=model_defaults,
        initial_provider=initial_provider,
        output_dir=output_dir,
    )

    root.mainloop()
