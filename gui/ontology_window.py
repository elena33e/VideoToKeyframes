"""Fereastra independentă pentru populare și revizie."""

import json
import os
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import filedialog, ttk

from dotenv import load_dotenv
from rdflib.util import guess_format

from gui.ontology_review import OntologyReview
from ontology_population.claude import ClaudeClient
from ontology_population.config import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_OPENAI_MODEL,
    MAX_BATCH_SIZE,
)
from ontology_population.openai import OpenAIClient
from ontology_population.review import build_review_frames
from ontology_population.session import iter_population_reports
from ontology.reader import read_ontology_source

PROVIDERS = {
    "openai": ("OPENAI", DEFAULT_OPENAI_MODEL, OpenAIClient),
    "claude": ("ANTHROPIC", DEFAULT_CLAUDE_MODEL, ClaudeClient),
}


class OntologyWindow(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, padding=12)
        self.session_path = tk.StringVar(master=self)
        self.ontology_path = tk.StringVar(master=self)
        self.provider = tk.StringVar(master=self, value="openai")
        self.model = tk.StringVar(master=self)
        self.batch_size = tk.StringVar(master=self, value=str(MAX_BATCH_SIZE))
        self.status = tk.StringVar(master=self, value="Alege un export de sesiune.")
        self.events = Queue()
        self.stop = Event()
        self.review: OntologyReview | None = None
        self.reports = []
        self.received = 0

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        form = ttk.Frame(self.tabs, padding=12)
        form.columnconfigure(1, weight=1)
        self.review_tab = ttk.Frame(self.tabs)
        self.tabs.add(form, text="Populare")
        self.tabs.add(self.review_tab, text="Revizie", state="disabled")

        self._file_field(form, 0, "Exportul sesiunii", self.session_path, "*.jsonld")
        self._file_field(
            form, 1, "Ontologie (implicit din sesiune)",
            self.ontology_path, "*.rdf *.owl *.ttl *.nt",
        )

        ttk.Label(form, text="Furnizor").grid(row=2, column=0, sticky="w", pady=5)
        provider_box = ttk.Combobox(
            form, textvariable=self.provider, values=tuple(PROVIDERS), state="readonly"
        )
        provider_box.grid(row=2, column=1, sticky="w", padx=8)
        provider_box.bind("<<ComboboxSelected>>", self._set_default_model)

        ttk.Label(form, text="Model").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.model).grid(row=3, column=1, sticky="ew", padx=8)

        ttk.Label(form, text="Cadre per apel").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Combobox(
            form, textvariable=self.batch_size, state="readonly",
            values=tuple(range(1, MAX_BATCH_SIZE + 1)), width=5,
        ).grid(row=4, column=1, sticky="w", padx=8)

        self.generate_button = ttk.Button(
            form, text="Generează pentru cadrele selectate", command=self._start
        )
        self.generate_button.grid(row=5, column=1, sticky="e", pady=12)
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(
            anchor="w", fill="x", pady=(8, 0)
        )
        self._set_default_model()

    def _file_field(self, form, row, label, value, pattern) -> None:
        def choose() -> None:
            path = filedialog.askopenfilename(parent=self, filetypes=[(label, pattern)])
            if path:
                value.set(path)

        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=value).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(form, text="Alege…", command=choose).grid(row=row, column=2)

    def _set_default_model(self, _event=None) -> None:
        prefix, default_model, _ = PROVIDERS[self.provider.get()]
        self.model.set(os.getenv(f"{prefix}_MODEL") or default_model)

    def _start(self) -> None:
        session_path = self.session_path.get().strip()
        model = self.model.get().strip()
        if not session_path or not model:
            self.status.set("Alege exportul sesiunii și completează modelul.")
            return

        args = (
            Path(session_path), self.ontology_path.get().strip(),
            self.provider.get(), model, int(self.batch_size.get()),
        )
        self.received = 0
        self.generate_button.configure(state="disabled")
        self.status.set("Se generează grafurile candidate…")
        Thread(target=self._generate, args=args, daemon=True).start()
        self.after(80, self._poll)

    def _generate(self, session_path, ontology_name, provider, model, batch_size) -> None:
        try:
            session = json.loads(session_path.read_text(encoding="utf-8-sig"))
            ontology_name = ontology_name or session.get("ontology_path")
            if not ontology_name:
                raise ValueError("Alege fișierul ontologiei.")

            ontology_path = Path(ontology_name)
            rdf_format = guess_format(ontology_path.name)
            if rdf_format is None:
                raise ValueError("Alege o ontologie RDF/XML, Turtle sau N-Triples.")

            ontology_source = read_ontology_source(ontology_path, rdf_format=rdf_format)

            prefix, _, client_type = PROVIDERS[provider]
            client = client_type(api_key=os.getenv(f"{prefix}_API_KEY", ""), model=model)
            reports = iter_population_reports(
                session, ontology_source=ontology_source,
                client=client, provider=provider, requested_model=model,
                batch_size=batch_size,
            )
            while not self.stop.is_set():
                report = next(reports, None)
                if report is None:
                    break
                frames = build_review_frames(
                    session, report, ontology_source=ontology_source
                )
                self.events.put(("batch", (report, frames)))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        else:
            self.events.put(("done", None))

    def _poll(self) -> None:
        try:
            kind, payload = self.events.get_nowait()
        except Empty:
            self.after(80, self._poll)
            return

        if kind == "batch":
            report, frames = payload
            review = self.review
            if self.received == 0 or review is None:
                if review is not None:
                    review.destroy()
                self.review = OntologyReview(self.review_tab, frames)
                self.review.pack(fill="both", expand=True)
                self.reports.clear()
                self.tabs.tab(self.review_tab, state="normal")
                self.tabs.select(self.review_tab)
            else:
                review.add_frames(frames)

            self.reports.append(report)
            self.received += len(frames)
            self.status.set(
                f"{self.received} grafuri disponibile după {len(self.reports)} grupuri."
            )
            self.after(80, self._poll)
            return

        self.generate_button.configure(state="normal")
        if kind == "error":
            self.status.set(f"Generare oprită după {self.received} grafuri. {payload}")
        else:
            self.status.set(f"Generare finalizată. {self.received} grafuri disponibile.")

    def close(self) -> None:
        self.stop.set()
        self.winfo_toplevel().destroy()


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    root = tk.Tk()
    root.title("Populare și revizie ontologică")
    root.geometry("1000x650")
    root.minsize(700, 420)
    window = OntologyWindow(root)
    window.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", window.close)
    root.mainloop()


if __name__ == "__main__":
    main()