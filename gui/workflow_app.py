"""Interfață comună pentru extragere, selecție și descriere."""

import json
import math
import os
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageOps, ImageTk

from extraction.keyframe_extractor import KatnaKeyframeExtractorService
from extraction.pipeline import PipelineError, VideoProcessingPipeline
from extraction.scene_detector import PySceneDetectorService
from interpretation.describe import DescriptionConfig, OpenRouterImageDescriber
from interpretation.ontology import load_ontology
from workflow.description import describe_selected
from workflow.models import WorkflowSession
from workflow.service import create_session, set_selection
from gui.keyframe_gallery import KeyframeGallery


DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"

# Modifică aici domeniul pentru testare.
# Pentru descriere fără context de domeniu, folosește "".
TEST_DOMAIN = "Traditional egg decorating (încondeierea ouălor)"

STATUS_LABELS = {
    "pending": "Nedescris",
    "running": "În procesare",
    "completed": "Descris",
    "failed": "Eroare",
}


def observation_text(result):
    obs = result.observation
    names = {entity.id: entity.name for entity in obs.entities}

    lines = [obs.description, "", "OBIECTE"]

    for entity in obs.entities:
        lines.append(
            f"• {entity.name}: {', '.join(entity.features)}\n"
            f"  Poziție: {entity.location}; "
            f"vizibilitate: {entity.visibility}"
        )

    lines += ["", "RELAȚII"]

    for relation in obs.relations:
        lines.append(
            f"• {names[relation.subject_id]} — "
            f"{relation.predicate} — "
            f"{names[relation.object_id]}"
        )

    lines += ["", "ACTIVITATE"]
    lines += [
        f"• {action.description}"
        + (" (incert)" if action.uncertain else "")
        for action in obs.actions
    ]

    lines += ["", "TEXT VIZIBIL", *obs.visible_text]
    lines += ["", "INCERTITUDINI", *obs.uncertainties]

    lines += [
        "",
        f"Model: {result.resolved_model}",
        f"Durată: {result.elapsed_seconds:.2f} s",
        f"Tokeni: {result.usage.get('total_tokens', 'indisponibil')}",
    ]

    return "\n".join(lines)


class WorkflowGUI:
    def __init__(self, root, *, api_key, model, output_dir):
        self.root = root
        self.api_key = api_key

        self.session = None
        self.ontology_path = None

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
        self.model_var = tk.StringVar(value=model or DEFAULT_MODEL)
        self.regenerate_var = tk.BooleanVar(value=False)

        self.status_var = tk.StringVar(
            value="Încarcă un video pentru a începe."
        )
        self.selection_var = tk.StringVar(value="0 cadre selectate")

        root.title("Video → keyframes → descrieri")
        root.geometry("1250x850")
        root.minsize(1050, 720)

        self._build_ui()
        self._sync_controls()

        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(100, self._poll_events)

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
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)

        video_tab = ttk.Frame(self.tabs, padding=12)
        self.frames_tab = ttk.Frame(self.tabs, padding=12)
        ontology_tab = ttk.Frame(self.tabs, padding=12)

        for tab, title in (
            (video_tab, "1. Video și extragere"),
            (self.frames_tab, "2. Cadre și descrieri"),
            (ontology_tab, "3. Ontologie"),
        ):
            self.tabs.add(tab, text=title)

        # Video și configurarea extragerii.
        video_tab.columnconfigure(1, weight=1)

        fields = [
            ("Video", self.video_var),
            ("Director rezultate", self.output_var),
            ("Secunde de scenă / keyframe", self.seconds_var),
            ("Limită cadre (gol = fără limită)", self.limit_var),
            ("Prag detectare scene", self.threshold_var),
            ("Procese Katna", self.workers_var),
        ]

        for row, (label, variable) in enumerate(fields):
            ttk.Label(video_tab, text=label).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 12),
                pady=7,
            )
            self._entry(video_tab, variable).grid(
                row=row,
                column=1,
                sticky="ew",
                pady=7,
            )

        self._button(
            video_tab, "Alege video…", self._choose_video
        ).grid(row=0, column=2, padx=8)

        self._button(
            video_tab, "Alege director…", self._choose_output
        ).grid(row=1, column=2, padx=8)

        self._button(
            video_tab, "Extrage keyframes", self._extract
        ).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=15,
        )

        ttk.Label(
            video_tab,
            text=(
                "După extragere, selectează cadrele "
                "pe care vrei să le descrii."
            ),
        ).grid(row=7, column=0, columnspan=3, sticky="w")

        # Galerie și previzualizare.
        tab = self.frames_tab
        tab.columnconfigure(0, weight=1, minsize=420)
        tab.columnconfigure(1, weight=1, minsize=450)
        tab.rowconfigure(0, weight=1)

        gallery_panel = ttk.Frame(tab)
        gallery_panel.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 12),
        )
        gallery_panel.rowconfigure(0, weight=1)
        gallery_panel.columnconfigure(0, weight=1)

        self.gallery = KeyframeGallery(
            gallery_panel,
            on_selection=self._selection_changed,
            on_preview=self._show_frame,
        )
        self.gallery.grid(row=0, column=0, sticky="nsew")

        selection = ttk.Frame(gallery_panel)
        selection.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=8,
        )

        self._button(
            selection, "Toate", lambda: self._select(True)
        ).pack(side="left")

        self._button(
            selection, "Niciunul", lambda: self._select(False)
        ).pack(side="left", padx=8)

        ttk.Label(
            gallery_panel,
            textvariable=self.selection_var,
        ).grid(row=2, column=0, sticky="w")

        ttk.Label(
            gallery_panel,
            text=(
                "Bifă = include la descriere. "
                "Clic pe imagine = previzualizare."
            ),
            wraplength=400,
        ).grid(row=3, column=0, sticky="w", pady=5)

        viewer = ttk.Frame(tab)
        viewer.grid(row=0, column=1, sticky="nsew")


        self.picture = ttk.Label(
            viewer,
            text="Selectează un cadru.",
            anchor="center",
        )
        self.picture.pack(fill="x")

        self.caption = ttk.Label(viewer, wraplength=650)
        self.caption.pack(fill="x", pady=5)

        result_tabs = ttk.Notebook(viewer)
        result_tabs.pack(fill="both", expand=True)

        observation_tab = ttk.Frame(result_tabs)
        json_tab = ttk.Frame(result_tabs)

        result_tabs.add(observation_tab, text="Observație")
        result_tabs.add(json_tab, text="JSON")

        self.observation_widget = self._text(observation_tab)
        self.json_widget = self._text(json_tab)

        settings = ttk.Frame(tab)
        settings.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Label(settings, text="Model:").pack(side="left")

        self._entry(
            settings, self.model_var, 45
        ).pack(side="left", padx=8)

        self.describe_button = self._button(
            settings,
            "Descrie selecția",
            self._describe,
        )
        self.describe_button.pack(side="left")

        regenerate = ttk.Checkbutton(
            settings,
            text="Regenerează descrierile existente",
            variable=self.regenerate_var,
        )
        regenerate.pack(side="left", padx=8)
        self.controls.append(regenerate)

        ttk.Label(
            tab,
            text=(
                f"Domeniu configurat în cod: "
                f"{TEST_DOMAIN or 'fără domeniu'}"
                + (
                    " | Lipsește OPENROUTER_API_KEY din mediu."
                    if not self.api_key.strip()
                    else ""
                )
            ),
            wraplength=1100,
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=6,
        )

        # Ontologia este încărcată independent de VLM.
        self._button(
            ontology_tab,
            "Încarcă ontologia…",
            self._choose_ontology,
        ).pack(anchor="w")

        ttk.Label(
            ontology_tab,
            text=(
                "Încărcarea ontologiei este independentă de descriere. "
                "Maparea nu este încă implementată."
            ),
            wraplength=1000,
        ).pack(anchor="w", pady=10)

        self.ontology_widget = self._text(ontology_tab)

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(10, 0))

        self.save_button = self._button(
            footer,
            "Salvează sesiunea JSON…",
            self._save,
        )
        self.save_button.pack(side="left")

        self.cancel_button = ttk.Button(
            footer,
            text="Anulează procesarea",
            command=self._cancel,
        )
        self.cancel_button.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(
            side="right",
            fill="x",
            expand=True,
            padx=(20, 0),
        )

        ttk.Label(
            main,
            textvariable=self.status_var,
            wraplength=1150,
        ).pack(fill="x", pady=(7, 0))

    def _sync_controls(self):
        for control in self.controls:
            control.configure(
                state="disabled" if self.busy else "normal"
            )

        selected = bool(
            self.session
            and any(s.selected for s in self.session.frames)
        )

        self.describe_button.configure(
            state=(
                "normal"
                if not self.busy and selected and self.api_key.strip()
                else "disabled"
            )
        )

        self.save_button.configure(
            state=(
                "normal"
                if not self.busy and self.session
                else "disabled"
            )
        )

        self.cancel_button.configure(
            state=(
                "normal"
                if self.busy in {"extraction", "description"}
                and not self.cancel_event.is_set()
                else "disabled"
            )
        )

        self.gallery.set_enabled(not self.busy)

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

            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(
                    "Intervalul trebuie să fie pozitiv și finit."
                )

            if not math.isfinite(threshold) or not 0 < threshold <= 255:
                raise ValueError(
                    "Pragul trebuie să fie între 0 și 255, exclusiv 0."
                )

            if not 1 <= workers <= (os.cpu_count() or 1):
                raise ValueError("Număr de procese nevalid.")

            if limit is not None and limit < 1:
                raise ValueError("Limita trebuie să fie pozitivă.")

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
            pipeline = VideoProcessingPipeline(
                PySceneDetectorService(threshold=threshold),
                KatnaKeyframeExtractorService(max_workers=workers),
            )

            try:
                return pipeline.run(
                    input_video=video,
                    base_output_dir=output,
                    seconds_per_keyframe=seconds,
                    max_total_keyframes=limit,
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
                "path": (
                        self.session.extraction.output_dir
                        / frame.image_path
                ),
                "title": (
                    f"Scena {frame.scene_index} · "
                    f"{frame.image_path.name}"
                ),
                "status": STATUS_LABELS[
                    states[frame.frame_id].description_status
                ],
            }
            for frame in self.session.keyframes
        ]

        self.gallery.set_frames(items, selected)
        self.gallery.set_enabled(not self.busy)

        self.selection_var.set(
            f"{len(selected)} / "
            f"{len(self.session.frames)} cadre selectate"
        )

        if self.session.keyframes:
            self._show_frame(
                self.session.keyframes[0].frame_id
            )

    def _update_row(self, frame_id):
        state = next(
            state
            for state in self.session.frames
            if state.frame_id == frame_id
        )

        self.gallery.set_status(
            frame_id,
            STATUS_LABELS[state.description_status],
        )

    def _show_frame(self, frame_id):
        self.active_frame_id = frame_id
        self.gallery.mark_active(frame_id)

        frame = self.frames_by_id[frame_id]
        state = next(
            s for s in self.session.frames
            if s.frame_id == frame_id
        )

        if self.preview_id != frame_id:
            try:
                path = (
                    self.session.extraction.output_dir
                    / frame.image_path
                )

                with Image.open(path) as source:
                    preview = ImageOps.exif_transpose(source).convert(
                        "RGB"
                    )

                preview.thumbnail(
                    (600, 260),
                    Image.Resampling.LANCZOS,
                )

                self.preview_photo = ImageTk.PhotoImage(
                    preview,
                    master=self.root,
                )
                self.picture.configure(
                    image=self.preview_photo,
                    text="",
                )
                self.preview_id = frame_id

            except (OSError, ValueError) as exc:
                self.preview_id = None
                self.picture.configure(
                    image="",
                    text=f"Imagine indisponibilă: {exc}",
                )

        scene = next(
            s for s in self.session.extraction.scenes
            if s.index == frame.scene_index
        )

        self.caption.configure(
            text=(
                f"{frame.image_path.name} | Scena {scene.index}: "
                f"{scene.start_seconds:.2f}–{scene.end_seconds:.2f} s. "
                "Intervalul este al scenei, nu timestamp-ul cadrului."
            )
        )

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
        self._set_text(
            self.json_widget,
            state.model_dump_json(indent=2),
        )

    def _describe(self):
        if self.busy or self.session is None:
            return

        try:
            model = self.model_var.get().strip()

            if not model.endswith(":free"):
                raise ValueError(
                    "Interfața de test acceptă doar modele :free."
                )

            config = DescriptionConfig(
                api_key=self.api_key,
                model=model,
                language="English",
                domain_context=TEST_DOMAIN,
            )

            snapshot = self.session
            regenerate = self.regenerate_var.get()

            if not any(s.selected for s in snapshot.frames):
                raise ValueError("Selectează cel puțin un cadru.")

        except ValueError as exc:
            messagebox.showerror(
                "Configurare invalidă",
                str(exc),
                parent=self.root,
            )
            return

        def operation(cancel, emit):
            describer = OpenRouterImageDescriber(config)

            for event in describe_selected(
                snapshot,
                describer,
                regenerate=regenerate,
                cancel_event=cancel,
            ):
                emit("description_progress", event)

        self.status_var.set("Se pregătesc descrierile…")
        self._launch("description", operation)

    def _choose_ontology(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Alege ontologia",
            filetypes=[
                ("Ontologie", "*.rdf *.owl *.ttl *.n3 *.nt *.jsonld"),
                ("Toate", "*.*"),
            ],
        )

        if filename:
            path = Path(filename).resolve()
            self.status_var.set("Se citește ontologia…")

            self._launch(
                "ontology",
                lambda cancel, emit: load_ontology(path),
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
            self.root.after(100, self._poll_events)

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

                self.session = WorkflowSession.model_validate({
                    **session.model_dump(),
                    "ontology_path": self.ontology_path,
                })

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

            elif job == "ontology":
                self.ontology_path = Path(result.source)

                if self.session:
                    self.session = WorkflowSession.model_validate({
                        **self.session.model_dump(),
                        "ontology_path": self.ontology_path,
                    })
                    self.dirty = True

                lines = [
                    str(self.ontology_path),
                    "",
                    json.dumps(
                        result.summary(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "",
                    "Previzualizare: primele 200 de concepte",
                ]

                lines += [
                    f"{concept.preferred_label()} — {concept.iri}"
                    for concept in result.concepts[:200]
                ]

                self._set_text(
                    self.ontology_widget,
                    "\n".join(lines),
                )

                self.status_var.set(
                    "Ontologie încărcată. "
                    "Nu se execută inferență sau mapare; "
                    "importurile externe nu sunt încărcate automat."
                )

        elif kind == "error":
            self.status_var.set("Operația a eșuat.")

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

        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvează sesiunea",
            initialdir=str(self.session.extraction.output_dir),
            initialfile=f"workflow_{self.session.session_id}.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )

        if not filename:
            return

        temporary = None

        try:
            destination = Path(filename).resolve()

            if destination.suffix.lower() != ".json":
                raise ValueError("Folosește extensia .json.")

            protected = {
                self.session.extraction.input_video.resolve(),
                self.session.extraction.manifest.resolve(),
            }

            if self.ontology_path:
                protected.add(self.ontology_path.resolve())

            if destination in protected:
                raise ValueError(
                    "Sesiunea nu poate înlocui fișierele sursă."
                )

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=".workflow_",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(
                    self.session.model_dump_json(indent=2) + "\n"
                )

            temporary.replace(destination)
            self.dirty = False
            self.status_var.set(
                f"Sesiune salvată: {destination}"
            )

        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Salvare nereușită",
                str(exc),
                parent=self.root,
            )

        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

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

        self.root.destroy()


def launch_workflow_gui(*, api_key, model=DEFAULT_MODEL, output_dir):
    root = tk.Tk()

    WorkflowGUI(
        root,
        api_key=api_key,
        model=model,
        output_dir=output_dir,
    )

    root.mainloop()