from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .clientes_saldo import AsyncSaldoCoordinator, SaldoPresentation
from .composition import WindowsRuntime, build_windows_runtime


class HelenaWindowsApp:
    POLL_INTERVAL_MS = 50

    def __init__(self, root: tk.Tk, coordinator: AsyncSaldoCoordinator) -> None:
        self.root = root
        self.coordinator = coordinator
        self.root.title("Sistema La Helena")
        self.root.minsize(620, 420)

        container = ttk.Frame(root, padding=24)
        container.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        ttk.Label(container, text="Clientes", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )
        ttk.Label(container, text="Cliente, nombre o identificador").grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        self.client_entry = ttk.Entry(container)
        self.client_entry.grid(row=2, column=0, sticky="ew", pady=(6, 12), padx=(0, 10))
        self.client_entry.bind("<Return>", lambda _event: self._consult())

        self.query_button = ttk.Button(container, text="Consultar saldo", command=self._consult)
        self.query_button.grid(row=2, column=1, sticky="e", pady=(6, 12))

        self.status_label = ttk.Label(container, text="")
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.result_text = tk.Text(container, wrap="word", height=12, state="disabled")
        self.result_text.grid(row=4, column=0, columnspan=2, sticky="nsew")

        self.clear_button = ttk.Button(container, text="Limpiar", command=self._clear)
        self.clear_button.grid(row=5, column=1, sticky="e", pady=(12, 0))

        self.client_entry.focus_set()
        self.root.after(self.POLL_INTERVAL_MS, self._poll)

    def _consult(self) -> None:
        self.coordinator.start(
            self.client_entry.get(),
            on_busy=self._set_busy,
            on_complete=self._show_presentation,
        )

    def _set_busy(self, busy: bool) -> None:
        self.query_button.configure(state="disabled" if busy else "normal")
        self.status_label.configure(text="Consultando…" if busy else "")

    def _show_presentation(self, presentation: SaldoPresentation) -> None:
        prefix = "" if presentation.success else "No se pudo completar la consulta.\n\n"
        self._set_result(prefix + presentation.message)

    def _set_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _clear(self) -> None:
        self.client_entry.delete(0, "end")
        self._set_result("")
        if not self.coordinator.running:
            self.status_label.configure(text="")
        self.client_entry.focus_set()

    def _poll(self) -> None:
        self.coordinator.poll()
        self.root.after(self.POLL_INTERVAL_MS, self._poll)


def main() -> None:
    runtime: WindowsRuntime = build_windows_runtime()
    root = tk.Tk()
    HelenaWindowsApp(root, runtime.coordinator)

    def close() -> None:
        runtime.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()

