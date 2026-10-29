import logging
import math
import os
import threading
import tkinter as tk
from contextlib import ExitStack
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

from extraction.keyframe_extractor import KatnaKeyframeExtractorService
from extraction.pipeline import PipelineError, VideoProcessingPipeline
from extraction.scene_detector import PySceneDetectorService


logger = logging.getLogger(__name__)


class VideoPipelineGUI:
    def __init__(self, root: tk.Tk, monitor_factory=None):
        self.root = root
        self.monitor_factory = monitor_factory
        root.title("Video to Keyframes")
        root.geometry("800x560")
        root.minsize(740, 520)
        self.project_root = Path(__file__).resolve().parent.parent
        self.events = Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.closing = False
        self.last_result = None
        self.controls = []
        self.video_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(self.project_root / "output"))
        self.limit_var = tk.StringVar(value="10")
        self.limit_enabled_var = tk.BooleanVar(value=False)
        self.seconds_var = tk.StringVar(value="15")
        self.threshold_var = tk.StringVar(value="27.0")
        self.workers_var = tk.StringVar(value=str(min(2, os.cpu_count() or 1)))
        self.status_var = tk.StringVar(value="Alege videoclipul și destinația rezultatelor.")
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(100, self._poll_events)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        for row, label, variable, command in (
            (0, "Videoclip:", self.video_var, self._browse_video),
            (2, "Folder pentru rezultate:", self.output_var, self._browse_output),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=(5, 4))
            line = ttk.Frame(frame)
            line.grid(row=row + 1, column=0, sticky="ew", pady=(0, 10))
            entry = ttk.Entry(line, textvariable=variable)
            entry.pack(side="left", fill="x", expand=True)
            button = ttk.Button(line, text="Răsfoiește…", command=command)
            button.pack(side="right", padx=(8, 0))
            self.controls.extend([entry, button])

        options = ttk.LabelFrame(
            frame, text="Opțiuni", padding=10
        )
        options.grid(row=4, column=0, sticky="ew", pady=8)

        ttk.Label(
            options,
            text="Secunde de scenă / keyframe:",
        ).grid(
            row=0, column=0, sticky="w", padx=5, pady=3
        )

        seconds_entry = ttk.Entry(
            options,
            textvariable=self.seconds_var,
            width=12,
        )
        seconds_entry.grid(
            row=0, column=1, sticky="w", padx=12, pady=3
        )
        self.controls.append(seconds_entry)

        for row, label, variable, lower, upper in (
                (1, "Prag detectare scene:", self.threshold_var, 0.1, 255),
                (
                        2, "Procese Katna:", self.workers_var,
                        1, os.cpu_count() or 1,
                ),
        ):
            ttk.Label(options, text=label).grid(
                row=row, column=0, sticky="w", padx=5, pady=3
            )
            spinbox = ttk.Spinbox(
                options,
                from_=lower,
                to=upper,
                textvariable=variable,
                width=12,
            )
            spinbox.grid(
                row=row, column=1, sticky="w", padx=12, pady=3
            )
            self.controls.append(spinbox)

        limit_check = ttk.Checkbutton(
            options,
            text="Limitează numărul total de cadre",
            variable=self.limit_enabled_var,
            command=self._sync_limit_input,
        )
        limit_check.grid(
            row=3, column=0, sticky="w", padx=5, pady=3
        )
        self.controls.append(limit_check)

        self.limit_spinbox = ttk.Spinbox(
            options,
            from_=1,
            to=10000,
            textvariable=self.limit_var,
            width=12,
        )
        self.limit_spinbox.grid(
            row=3, column=1, sticky="w", padx=12, pady=3
        )

        ttk.Label(
            options,
            text=(
                "Fără limită: toate scenele. "
                "O limită mică poate omite scene."
            ),
            wraplength=620,
        ).grid(
            row=4, column=0, columnspan=2,
            sticky="w", padx=5, pady=3,
        )

        self._sync_limit_input()

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="ew", pady=10)
        self.run_button = ttk.Button(buttons, text="Start procesare", command=self._start)
        self.run_button.pack(side="left")
        self.cancel_button = ttk.Button(
            buttons, text="Anulează", command=self._cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(
            buttons, text="Deschide rezultatele", command=self._open_results, state="disabled"
        )
        self.open_button.pack(side="left")
        self.preview_button = ttk.Button(
            buttons, text="Vezi cadrele", command=self._preview, state="disabled"
        )
        self.preview_button.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.grid(row=6, column=0, sticky="ew", pady=5)
        ttk.Label(frame, textvariable=self.status_var, wraplength=640).grid(
            row=7, column=0, sticky="w", pady=5
        )

    def _sync_limit_input(self):
        enabled = (
            self.limit_enabled_var.get()
            and not self.running
        )
        self.limit_spinbox.configure(
            state="normal" if enabled else "disabled"
        )

    def _browse_video(self):
        initial = self.project_root / "test_videos"
        selected = filedialog.askopenfilename(
            parent=self.root, title="Selectează videoclipul",
            initialdir=str(initial if initial.is_dir() else self.project_root),
            filetypes=[("Videoclipuri", "*.mp4 *.avi *.mov *.mkv"), ("Toate fișierele", "*.*")],
        )
        if selected:
            self.video_var.set(selected)

    def _browse_output(self):
        selected = filedialog.askdirectory(parent=self.root, title="Destinația rezultatelor")
        if selected:
            self.output_var.set(selected)

    def _start(self):
        if self.running:
            return

        try:
            video_text = self.video_var.get().strip()
            output_text = self.output_var.get().strip()

            if not video_text or not output_text:
                raise ValueError(
                    "Completează videoclipul și folderul de rezultate."
                )

            video = Path(video_text).expanduser().resolve()
            output = Path(output_text).expanduser().resolve()

            if not video.is_file() or video.stat().st_size == 0:
                raise ValueError(
                    "Selectează un fișier video existent și nevid."
                )

            if output.exists() and not output.is_dir():
                raise ValueError(
                    "Destinația rezultatelor trebuie să fie un folder."
                )

            seconds_per_keyframe = float(
                self.seconds_var.get().replace(",", ".")
            )
            if (
                    not math.isfinite(seconds_per_keyframe)
                    or seconds_per_keyframe <= 0
            ):
                raise ValueError(
                    "Intervalul pentru keyframes "
                    "trebuie să fie pozitiv și finit."
                )

            limit = None
            if self.limit_enabled_var.get():
                limit = int(self.limit_var.get())
                if limit < 1:
                    raise ValueError(
                        "Limita totală trebuie să fie un întreg pozitiv."
                    )

            workers = int(self.workers_var.get())
            threshold = float(
                self.threshold_var.get().replace(",", ".")
            )

            if not 1 <= workers <= (os.cpu_count() or 1):
                raise ValueError(
                    "Numărul de procese depășește capacitatea procesorului."
                )

            if (
                    not math.isfinite(threshold)
                    or not 0 < threshold <= 255
            ):
                raise ValueError(
                    "Pragul trebuie să fie mai mare de 0 și cel mult 255."
                )

        except (ValueError, OSError) as exc:
            messagebox.showerror(
                "Setări invalide", str(exc), parent=self.root
            )
            return

        self.cancel_event = threading.Event()
        self.last_result = None
        self._set_running(True)
        self.progress.configure(value=0)
        self.status_var.set("Pregătirea procesării…")

        threading.Thread(
            target=self._run_worker,
            args=(
                video,
                output,
                limit,
                threshold,
                workers,
                seconds_per_keyframe,
            ),
            daemon=False,
        ).start()

    def _run_worker(
            self, video, output, limit, threshold, workers,
            seconds_per_keyframe,
    ):
        monitor = None
        result = None

        try:
            pipeline = VideoProcessingPipeline(
                PySceneDetectorService(threshold=threshold),
                KatnaKeyframeExtractorService(max_workers=workers),
            )

            with ExitStack() as stack:
                if self.monitor_factory is not None:
                    try:
                        monitor = stack.enter_context(
                            self.monitor_factory()
                        )
                    except Exception:
                        logger.warning(
                            "Monitorizarea performanței nu a putut fi pornită. "
                            "Procesarea continuă fără diagnostic.",
                            exc_info=True,
                        )

                try:
                    result = pipeline.run(
                        input_video=video,
                        base_output_dir=output,
                        max_total_keyframes=limit,
                        seconds_per_keyframe=seconds_per_keyframe,
                        cancel_event=self.cancel_event,
                        progress_callback=lambda text, current, total:
                        self.events.put(
                            ("progress", (text, current, total))
                        ),
                    )
                except PipelineError as exc:
                    result = exc.result

        except Exception as exc:
            if result is None:
                self.events.put(("error", str(exc)))
                return

            logger.warning(
                "Finalizarea monitorizării performanței a eșuat.",
                exc_info=True,
            )

        if monitor is not None:
            try:
                monitor.report["settings"] = result.get("settings", {})
                monitor.report["input_video"] = str(video)
                monitor.save(result["output_dir"])
            except Exception:
                logger.warning(
                    "Raportul de performanță nu a putut fi salvat.",
                    exc_info=True,
                )

        self.events.put(("finished", result))

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    text, current, total = payload
                    self.progress.stop()
                    if total:
                        self.progress.configure(mode="determinate", value=100 * current / total)
                    else:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    if not self.cancel_event.is_set():
                        self.status_var.set(text)
                elif kind == "finished":
                    self._finish(payload)
                    if self.closing:
                        return
                elif kind == "error":
                    self._set_running(False)
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.status_var.set("Procesarea a eșuat.")
                    if self.closing:
                        self.root.destroy()
                        return
                    messagebox.showerror("Eroare", payload, parent=self.root)
        except Empty:
            pass
        self.root.after(100, self._poll_events)

    def _set_running(self, running):
        self.running = running

        for control in self.controls:
            control.configure(
                state="disabled" if running else "normal"
            )

        self._sync_limit_input()

        self.run_button.configure(
            state="disabled" if running else "normal"
        )
        self.cancel_button.configure(
            state="normal" if running else "disabled"
        )
        self.open_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")

    def _cancel(self):
        if self.running:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set(
                "Anulare solicitată. Se așteaptă încheierea operației curente."
            )

    def _finish(self, result):
        self.last_result = result
        self._set_running(False)
        self.progress.stop()

        selected = result["selected_scenes"]
        processed = result["processed_scenes"]

        self.progress.configure(
            mode="determinate",
            value=(
                100 * processed / selected
                if selected else 0
            ),
        )

        self.status_var.set(
            f"{result['message']} "
            f"Cadre salvate: {result['total_keyframes']}. "
            f"Scene cu cadre: "
            f"{result['covered_scenes']} / {result['total_scenes']}."
        )

        self.open_button.configure(state="normal")

        has_images = any(
            scene["images"] for scene in result["scenes"]
        )
        self.preview_button.configure(
            state="normal" if has_images else "disabled"
        )

        if self.closing:
            self.root.destroy()
            return

        details = (
            f"{result['message']}\n"
            f"Scene procesate: {processed} / {selected}\n"
            f"Scene cu cadre: "
            f"{result['covered_scenes']} / {result['total_scenes']}\n"
            f"Scene omise prin limită: {result['omitted_scenes']}\n"
            f"Cadre salvate: {result['total_keyframes']}\n"
            f"Cadre solicitate prin plan: {result['target_keyframes']}\n"
            f"Rezultate: {result['output_dir']}\n"
            f"Raport: {result['manifest']}"
        )

        if result["errors"]:
            details += "\n\n" + "\n".join(
                error["message"]
                for error in result["errors"][:3]
            )

        display = {
            "success": messagebox.showinfo,
            "partial": messagebox.showwarning,
            "cancelled": messagebox.showinfo,
            "failed": messagebox.showerror,
        }[result["status"]]

        display(
            "Rezultatul procesării",
            details,
            parent=self.root,
        )

    def _open_results(self):
        if self.last_result:
            try:
                os.startfile(self.last_result["output_dir"])
            except OSError as exc:
                messagebox.showerror("Eroare", str(exc), parent=self.root)

    def _preview(self):
        if not self.last_result:
            return

        base = Path(self.last_result["output_dir"])
        items = [
            (scene, base / name)
            for scene in self.last_result["scenes"] for name in scene["images"]
        ]
        if not items:
            return
        window = tk.Toplevel(self.root)
        window.title("Cadre extrase")
        window.geometry("1000x650")
        panel = ttk.Frame(window, padding=10)
        panel.pack(fill="both", expand=True)
        choices = tk.Listbox(panel, width=33, exportselection=False)
        choices.pack(side="left", fill="y", padx=(0, 10))
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=choices.yview)
        scrollbar.pack(side="left", fill="y")
        choices.configure(yscrollcommand=scrollbar.set)
        viewer = ttk.Frame(panel)
        viewer.pack(side="left", fill="both", expand=True)
        caption = ttk.Label(viewer, wraplength=600)
        caption.pack(pady=8)
        picture = ttk.Label(viewer)
        picture.pack(fill="both", expand=True)
        for scene, path in items:
            choices.insert("end", f"Scena {scene['index']}: {path.name}")

        def show_selected(_event=None):
            selected = choices.curselection()
            if not selected:
                return
            scene, path = items[selected[0]]
            try:
                with Image.open(path) as source:
                    image = source.copy()
                image.thumbnail((700, 520))
                picture.image = ImageTk.PhotoImage(image, master=window)
                picture.configure(image=picture.image)
                caption.configure(text=(
                    f"Scena {scene['index']}: {scene['start_seconds']:.2f}–"
                    f"{scene['end_seconds']:.2f} secunde în videoclipul original.\n"
                    "Intervalul indică scena; momentul exact al cadrului nu este disponibil."
                ))
            except (OSError, ValueError) as exc:
                messagebox.showerror("Imagine indisponibilă", str(exc), parent=window)

        choices.bind("<<ListboxSelect>>", show_selected)
        choices.selection_set(0)
        show_selected()

    def _close(self):
        if self.running:
            self.closing = True
            self._cancel()
        else:
            self.root.destroy()


def launch_gui(monitor_factory=None):
    root = tk.Tk()
    VideoPipelineGUI(root, monitor_factory=monitor_factory)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
