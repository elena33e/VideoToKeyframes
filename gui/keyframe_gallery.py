"""Galerie de miniaturi cu selecție independentă de previzualizare."""

import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk


class KeyframeGallery(ttk.Frame):
    PAGE_SIZE = 12

    def __init__(self, parent, *, on_selection, on_preview):
        super().__init__(parent)

        self.on_selection = on_selection
        self.on_preview = on_preview

        self.items = []
        self.selected = set()
        self.cards = {}

        self.page = 0
        self.active = None
        self.enabled = True

        self.generation = 0
        self.results = Queue()
        self.cancel = threading.Event()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            width=400,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw",
        )

        self.body.bind("<Configure>", self._scrollregion)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.body.bind("<MouseWheel>", self._wheel)

        navigation = ttk.Frame(self)
        navigation.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=6,
        )

        self.previous = ttk.Button(
            navigation,
            text="◀",
            command=lambda: self._change_page(-1),
        )
        self.previous.pack(side="left")

        self.page_label = ttk.Label(
            navigation,
            text="Fără cadre",
        )
        self.page_label.pack(side="left", padx=10)

        self.next = ttk.Button(
            navigation,
            text="▶",
            command=lambda: self._change_page(1),
        )
        self.next.pack(side="right")

        self.poll_id = self.after(60, self._poll)

    def selected_ids(self):
        return set(self.selected)

    def set_frames(self, items, selected_ids=()):
        self.items = [dict(item) for item in items]

        available = {item["id"] for item in self.items}
        self.selected = set(selected_ids) & available

        self.page = 0
        self.active = None
        self._render_page()

    def set_selected(self, ids):
        available = {item["id"] for item in self.items}
        self.selected = set(ids) & available

        for frame_id, card in self.cards.items():
            card["var"].set(frame_id in self.selected)

    def set_enabled(self, enabled):
        self.enabled = enabled

        for card in self.cards.values():
            card["check"].configure(
                state="normal" if enabled else "disabled"
            )

    def set_status(self, frame_id, text):
        for item in self.items:
            if item["id"] == frame_id:
                item["status"] = text
                break

        if frame_id in self.cards:
            self.cards[frame_id]["status"].configure(text=text)

    def mark_active(self, frame_id):
        self.active = frame_id

        for key, card in self.cards.items():
            card["frame"].configure(
                relief="sunken" if key == frame_id else "ridge"
            )

    def _toggle(self, frame_id):
        if not self.enabled:
            self.cards[frame_id]["var"].set(
                frame_id in self.selected
            )
            return

        if self.cards[frame_id]["var"].get():
            self.selected.add(frame_id)
        else:
            self.selected.discard(frame_id)

        self.on_selection()

    def _change_page(self, direction):
        pages = max(
            1,
            (len(self.items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
        )
        self.page = max(
            0,
            min(self.page + direction, pages - 1),
        )
        self._render_page()

    def _render_page(self):
        # Rezultatele unei pagini vechi nu trebuie afișate pe pagina nouă.
        self.cancel.set()
        self.cancel = threading.Event()
        self.generation += 1

        generation = self.generation
        cancel = self.cancel

        for child in self.body.winfo_children():
            child.destroy()

        self.cards.clear()

        start = self.page * self.PAGE_SIZE
        page_items = self.items[start:start + self.PAGE_SIZE]

        for item in page_items:
            frame_id = item["id"]

            frame = ttk.Frame(
                self.body,
                padding=6,
                relief="ridge",
                borderwidth=2,
            )

            picture = ttk.Label(
                frame,
                text="Se încarcă…",
                anchor="center",
                cursor="hand2",
            )
            picture.pack(fill="x")
            picture.bind(
                "<Button-1>",
                lambda event, key=frame_id: self.on_preview(key),
            )

            title = ttk.Label(
                frame,
                text=item["title"],
                wraplength=170,
                cursor="hand2",
            )
            title.pack(fill="x", pady=4)
            title.bind(
                "<Button-1>",
                lambda event, key=frame_id: self.on_preview(key),
            )

            variable = tk.BooleanVar(
                master=self,
                value=frame_id in self.selected,
            )
            check = ttk.Checkbutton(
                frame,
                text="Include la descriere",
                variable=variable,
                command=lambda key=frame_id: self._toggle(key),
            )
            check.pack(anchor="w")

            status = ttk.Label(
                frame,
                text=item["status"],
                wraplength=170,
            )
            status.pack(anchor="w")

            for widget in (frame, picture, title, check, status):
                widget.bind("<MouseWheel>", self._wheel)

            self.cards[frame_id] = {
                "frame": frame,
                "picture": picture,
                "var": variable,
                "check": check,
                "status": status,
                "photo": None,
            }

        self._layout()
        self.mark_active(self.active)
        self.set_enabled(self.enabled)
        self.canvas.yview_moveto(0)

        pages = max(
            1,
            (len(self.items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
        )

        self.page_label.configure(
            text=(
                f"Pagina {self.page + 1} / {pages}"
                if self.items
                else "Fără cadre"
            )
        )
        self.previous.configure(
            state="normal" if self.page else "disabled"
        )
        self.next.configure(
            state="normal" if self.page + 1 < pages else "disabled"
        )

        paths = [
            (item["id"], Path(item["path"]))
            for item in page_items
        ]

        def load():
            # Citirea și redimensionarea imaginilor se fac în fundal.
            for frame_id, path in paths:
                if cancel.is_set():
                    return

                thumbnail = None

                try:
                    with Image.open(path) as source:
                        thumbnail = ImageOps.exif_transpose(
                            source
                        ).convert("RGB")

                    thumbnail.thumbnail(
                        (170, 110),
                        Image.Resampling.LANCZOS,
                    )
                    error = None

                except Exception:
                    error = "Imagine indisponibilă"

                if cancel.is_set():
                    if thumbnail is not None:
                        thumbnail.close()
                    return

                self.results.put(
                    (generation, frame_id, thumbnail, error)
                )

        if paths:
            threading.Thread(target=load, daemon=True).start()

    def _poll(self):
        # Obiectele Tkinter sunt create numai în firul principal.
        for _ in range(self.PAGE_SIZE * 2):
            try:
                generation, frame_id, thumbnail, error = (
                    self.results.get_nowait()
                )
            except Empty:
                break

            try:
                if (
                    generation != self.generation
                    or frame_id not in self.cards
                ):
                    continue

                card = self.cards[frame_id]

                if error:
                    card["picture"].configure(
                        text=error,
                        image="",
                    )
                else:
                    photo = ImageTk.PhotoImage(
                        thumbnail,
                        master=self,
                    )
                    card["photo"] = photo
                    card["picture"].configure(
                        image=photo,
                        text="",
                    )

            finally:
                if thumbnail is not None:
                    thumbnail.close()

        self.poll_id = self.after(60, self._poll)

    def _layout(self):
        columns = max(1, self.canvas.winfo_width() // 200)

        for index, card in enumerate(self.cards.values()):
            card["frame"].grid(
                row=index // columns,
                column=index % columns,
                padx=4,
                pady=4,
                sticky="nsew",
            )

    def _resize(self, event):
        self.canvas.itemconfigure(
            self.window,
            width=event.width,
        )
        self._layout()

    def _scrollregion(self, _event=None):
        self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        )

    def _wheel(self, event):
        if event.delta:
            units = (
                -int(event.delta / 120)
                or (-1 if event.delta > 0 else 1)
            )
            self.canvas.yview_scroll(units, "units")

        return "break"

    def destroy(self):
        self.cancel.set()
        self.after_cancel(self.poll_id)
        super().destroy()