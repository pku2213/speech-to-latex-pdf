#!/usr/bin/env python3
"""
Small Windows-friendly desktop GUI for audio2pdf.

The GUI intentionally stays thin: it gathers paths/options, then runs the same
pipeline used by main.py in a background thread so the window remains responsive.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from pipeline import ConfigError, PipelineError, PipelineResult, run_pipeline


MEDIA_TYPES = [
    ("Audio and video", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov *.mkv *.avi *.wmv"),
    ("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"),
    ("Video", "*.mp4 *.mov *.mkv *.avi *.wmv"),
    ("All files", "*.*"),
]


class Audio2PdfApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("audio2pdf")
        self.geometry("860x620")
        self.minsize(760, 520)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_result: PipelineResult | None = None

        self.input_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.config_var = tk.StringVar(value=str(PROJECT_DIR / "config.yaml"))
        self.output_var = tk.StringVar(value=str(PROJECT_DIR / "output"))
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.after(150, self._poll_events)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(5, weight=1)

        ttk.Label(root, text="Input audio/video").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(root, text="Browse", command=self._choose_input).grid(row=0, column=2, sticky="ew")

        ttk.Label(root, text="Title").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.title_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(root, text="Blank uses file name").grid(row=1, column=2, sticky="w")

        ttk.Label(root, text="Config file").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.config_var).grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Button(root, text="Browse", command=self._choose_config).grid(row=2, column=2, sticky="ew")

        ttk.Label(root, text="Output folder").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.output_var).grid(row=3, column=1, sticky="ew", padx=8)
        ttk.Button(root, text="Browse", command=self._choose_output).grid(row=3, column=2, sticky="ew")

        button_bar = ttk.Frame(root)
        button_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        button_bar.columnconfigure(5, weight=1)
        self.run_button = ttk.Button(button_bar, text="Generate PDF", command=self._start_run)
        self.run_button.grid(row=0, column=0, padx=(0, 8))
        self.open_pdf_button = ttk.Button(button_bar, text="Open PDF", command=self._open_pdf, state=tk.DISABLED)
        self.open_pdf_button.grid(row=0, column=1, padx=(0, 8))
        self.open_folder_button = ttk.Button(button_bar, text="Open Folder", command=self._open_folder, state=tk.DISABLED)
        self.open_folder_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Label(button_bar, textvariable=self.status_var).grid(row=0, column=5, sticky="e")

        log_frame = ttk.Frame(root)
        log_frame.grid(row=5, column=0, columnspan=3, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", height=18)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _choose_input(self) -> None:
        path = filedialog.askopenfilename(title="Choose audio or video", filetypes=MEDIA_TYPES)
        if path:
            self.input_var.set(path)
            if not self.title_var.get().strip():
                self.title_var.set(Path(path).stem)

    def _choose_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose config YAML",
            initialdir=str(PROJECT_DIR),
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            self.config_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder", initialdir=str(PROJECT_DIR))
        if path:
            self.output_var.set(path)

    def _start_run(self) -> None:
        input_path = self.input_var.get().strip()
        config_path = self.config_var.get().strip()
        output_dir = self.output_var.get().strip()

        if not input_path:
            messagebox.showerror("Missing input", "Please choose an audio or video file.")
            return
        if not config_path:
            messagebox.showerror("Missing config", "Please choose config.yaml.")
            return

        self.last_result = None
        self.open_pdf_button.configure(state=tk.DISABLED)
        self.open_folder_button.configure(state=tk.DISABLED)
        self.run_button.configure(state=tk.DISABLED)
        self.status_var.set("Running")
        self.log_text.delete("1.0", tk.END)

        title = self.title_var.get().strip() or None

        def progress(message: str) -> None:
            self.events.put(("log", message))

        def worker() -> None:
            try:
                result = run_pipeline(
                    input_file=input_path,
                    title=title,
                    config_path=config_path,
                    progress_callback=progress,
                    output_dir=output_dir or None,
                )
                self.events.put(("done", result))
            except (ConfigError, PipelineError, RuntimeError, OSError) as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:  # Keep unexpected failures visible in the GUI.
                self.events.put(("error", f"Unexpected error: {exc}"))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._append_log(str(payload))
            elif kind == "done":
                self.last_result = payload  # type: ignore[assignment]
                self.status_var.set("Done")
                self.run_button.configure(state=tk.NORMAL)
                self.open_pdf_button.configure(state=tk.NORMAL)
                self.open_folder_button.configure(state=tk.NORMAL)
                self._append_log(f"PDF generated: {self.last_result.pdf_path}")
                messagebox.showinfo("audio2pdf", f"PDF generated:\n{self.last_result.pdf_path}")
            elif kind == "error":
                self.status_var.set("Error")
                self.run_button.configure(state=tk.NORMAL)
                self._append_log(f"ERROR: {payload}")
                messagebox.showerror("audio2pdf failed", str(payload))

        self.after(150, self._poll_events)

    def _append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _open_pdf(self) -> None:
        if self.last_result and self.last_result.pdf_path.exists():
            os.startfile(self.last_result.pdf_path)  # type: ignore[attr-defined]

    def _open_folder(self) -> None:
        if self.last_result and self.last_result.pdf_path.exists():
            os.startfile(self.last_result.pdf_path.parent)  # type: ignore[attr-defined]


def main() -> None:
    app = Audio2PdfApp()
    app.mainloop()


if __name__ == "__main__":
    main()
