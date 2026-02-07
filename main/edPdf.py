import base64
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import fitz  # PyMuPDF
from datetime import datetime
import shutil

THUMB_WIDTH = 200       # thumbnail width in pixels
GRID_COLS = 4           # thumbnails per row
PAD = 10                # padding around thumbnail tiles


class PDFPrunerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Photo Pruner (delete pages)")
        self.geometry("980x720")

        self.pdf_path: Path | None = None
        self.doc: fitz.Document | None = None

        self.page_vars: list[tk.BooleanVar] = []
        self.thumb_images: list[tk.PhotoImage] = []  # keep refs (prevents GC)

        self._build_ui()

    def _build_ui(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Button(top, text="Exit", command=self.destroy).pack(side="left")
        tk.Button(top, text="Open PDF…", command=self.open_pdf).pack(side="left", padx=(10, 0))
        tk.Button(top, text="Replace Original", command=self.replace_original).pack(side="left", padx=(10, 0))

        self.status = tk.Label(top, text="Open a PDF to begin.", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=(12, 0))

        outer = tk.Frame(self)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.canvas = tk.Canvas(outer, highlightthickness=0)
        self.v_scroll = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)

        self.v_scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)


    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Keep inner frame same width as canvas
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        # Windows: event.delta is +/-120 multiples
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def open_pdf(self):
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            return

        # Close previous doc
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None

        self.pdf_path = Path(path)
        try:
            self.doc = fitz.open(self.pdf_path)
        except Exception as e:
            messagebox.showerror("Open failed", f"Could not open PDF:\n{e}")
            return

        self._populate_thumbnails()

    def _populate_thumbnails(self):
        # Clear previous thumbnails
        for w in self.inner.winfo_children():
            w.destroy()
        self.page_vars.clear()
        self.thumb_images.clear()

        if self.doc is None or self.pdf_path is None:
            return

        page_count = self.doc.page_count
        self.status.config(text=f"{self.pdf_path.name} — {page_count} pages. Check pages to DELETE, then Save/Replace…")

        # Render thumbnails
        for i in range(page_count):
            page = self.doc.load_page(i)
            rect = page.rect
            zoom = THUMB_WIDTH / rect.width
            matrix = fitz.Matrix(zoom, zoom)

            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")

            # Tk PhotoImage can accept base64-encoded PNG data
            b64 = base64.b64encode(png_bytes).decode("ascii")
            img = tk.PhotoImage(data=b64)
            self.thumb_images.append(img)

            var = tk.BooleanVar(value=False)  # unchecked = keep
            self.page_vars.append(var)

            tile = tk.Frame(self.inner, relief="groove", borderwidth=2)
            tile.config(highlightthickness=0)

            r = i // GRID_COLS
            c = i % GRID_COLS
            tile.grid(row=r, column=c, padx=PAD, pady=PAD, sticky="n")

            lbl = tk.Label(tile, image=img)
            lbl.pack(padx=6, pady=(6, 2))

            cb = tk.Checkbutton(
                tile,
                text=f"Delete page {i+1}",
                variable=var,
                command=lambda v=var, t=tile: self._update_tile_border(t, v.get())
            )
            cb.pack(padx=6, pady=(0, 6))
            # initialize border state
            self._update_tile_border(tile, var.get())

    def _update_tile_border(self, tile: tk.Frame, checked: bool):
        if checked:
            tile.config(highlightbackground="red", highlightcolor="red", highlightthickness=3, bd=0)
        else:
            tile.config(highlightthickness=0, bd=2, relief="groove")

    def select_all(self):
        for v in self.page_vars:
            v.set(True)

    def select_none(self):
        for v in self.page_vars:
            v.set(False)

    def _get_delete_pages_1based(self) -> list[int]:
        return [i + 1 for i, v in enumerate(self.page_vars) if v.get()]

    def _delete_pages_and_save(self, src_path: Path, out_path: Path, delete_pages_1based: list[int]):
        doc = fitz.open(src_path)

        delete_idx = sorted(
            {p - 1 for p in delete_pages_1based if 1 <= p <= doc.page_count},
            reverse=True
        )
        for idx in delete_idx:
            doc.delete_page(idx)

        doc.save(out_path)
        doc.close()

    def save_as(self):
        if self.pdf_path is None:
            messagebox.showinfo("No PDF", "Open a PDF first.")
            return

        delete_pages_1based = self._get_delete_pages_1based()
        if not delete_pages_1based:
            if not messagebox.askyesno("No deletions", "No pages are checked for deletion.\nSave a copy anyway?"):
                return

        out_path_str = filedialog.asksaveasfilename(
            title="Save edited PDF as…",
            defaultextension=".pdf",
            initialfile=f"{self.pdf_path.stem} - edited.pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not out_path_str:
            return

        out_path = Path(out_path_str)

        try:
            self._delete_pages_and_save(self.pdf_path, out_path, delete_pages_1based)
            messagebox.showinfo("Saved", f"Saved edited PDF:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save edited PDF:\n{e}")

    def replace_original(self):
        if self.pdf_path is None:
            messagebox.showinfo("No PDF", "Open a PDF first.")
            return

        delete_pages_1based = self._get_delete_pages_1based()
        if not delete_pages_1based:
            if not messagebox.askyesno("No deletions", "No pages are checked for deletion.\nReplace anyway?"):
                return

        original_path = self.pdf_path
        parent_dir = original_path.parent

        backup_dir = parent_dir / "pdfBackup"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{original_path.stem}_{timestamp}.pdf"

        try:
            # Close currently open PDF so Windows releases the file lock
            if self.doc is not None:
                try:
                    self.doc.close()
                except Exception:
                    pass
                self.doc = None

            # Move original to backup folder
            shutil.move(str(original_path), str(backup_path))

            # Create edited version from backup and write back to original name
            self._delete_pages_and_save(backup_path, original_path, delete_pages_1based)

            messagebox.showinfo(
                "Replaced Successfully",
                f"Original moved to:\n{backup_path}\n\nEdited PDF saved as original name."
            )

            # Reload edited PDF into UI
            self.doc = fitz.open(original_path)
            self._populate_thumbnails()

        except Exception as e:
            messagebox.showerror("Replace failed", f"Error:\n{e}")


if __name__ == "__main__":
    app = PDFPrunerApp()
    app.mainloop()