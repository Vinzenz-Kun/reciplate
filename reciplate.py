from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import ConfigError, Settings, load_settings
from copy_template import copy_template, file_hash, tidy_recipe_folder
from download import DownloadError, download_media, fetch_info
from fill import RecipeDraft, fill_copy
from language import DE, EN, detect_language, language_name
from latex_build import compile_folder
from names import (
    canonical_recipe_url,
    find_folder_by_url,
    folder_name,
    folder_number,
    move_recipe_folder,
    next_insta_number,
    rename_stem_files,
)
from parse import format_ingredients, format_steps, groups_from_text, parse_caption, steps_from_text
from translate import TranslateError, bilingual_drafts

BG = "#1c1815"
CARD = "#2a241f"
TEXT = "#f6f0e8"
MUTED = "#b7a89b"
ACCENT = "#d36b38"
LINE = "#3f352d"
APP_NAME = "Reciplate"
SESSION = Path(__file__).with_name("reciplate.last")

_FONT = "Segoe UI"
_BODY = 12
_TITLE = 15
_SMALL = 10


def ui_font(size: int | None = None, *styles: str) -> tuple:
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        from common.ui import ui_font as shared

        return shared(size, *styles)
    except ImportError:
        used = _BODY if size is None else size
        return (_FONT, used, *styles) if styles else (_FONT, used)


def _enable_dpi() -> None:
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        from common.launch import enable_dpi_awareness

        enable_dpi_awareness()
        return
    except ImportError:
        pass
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _apply_ui_fonts(root: tk.Tk) -> None:
    global _FONT
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        from common.ui import apply_theme, ui_family

        apply_theme(root)
        _FONT = ui_family()
        return
    except ImportError:
        pass
    import tkinter.font as tkfont

    available = {name.casefold() for name in tkfont.families(root)}
    for name in ("Segoe UI", "Yu Gothic UI", "Meiryo UI", "Meiryo", "BIZ UDPGothic"):
        if name.casefold() in available:
            _FONT = name
            break
    for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(named).configure(family=_FONT, size=_BODY)
        except tk.TclError:
            continue
    try:
        tkfont.nametofont("TkHeadingFont").configure(family=_FONT, size=_BODY, weight="bold")
    except tk.TclError:
        pass
    root.option_add("*Font", ui_font())


class ReciplateApp:
    def __init__(self, root: tk.Tk, settings: Settings) -> None:
        self.root = root
        self.settings = settings
        self._busy = False
        root.title(APP_NAME)
        root.geometry("1180x860")
        root.minsize(860, 640)
        root.configure(bg=BG)
        self._style()
        pad = {"padx": 10, "pady": 5}

        tk.Frame(root, bg=ACCENT, height=2).grid(row=0, column=0, columnspan=3, sticky="ew")
        head = tk.Frame(root, bg=BG)
        head.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 6))
        tk.Label(head, text=APP_NAME, bg=BG, fg=TEXT, font=ui_font(_TITLE, "bold")).pack(anchor="w")
        blurb = tk.Label(
            head,
            text=(
                "Instagram-URL oder PDF. Metadaten holen, Texte prüfen, dann Ordner aus der Vorlage bauen. Strg+Enter erzeugt.\n"
                "InstagramのURLかPDF。内容を確認してからテンプレートでフォルダを作成。Ctrl+Enterで実行。"
            ),
            bg=BG,
            fg=MUTED,
            font=ui_font(_SMALL),
            wraplength=1040,
            justify="left",
        )
        blurb.pack(anchor="w", pady=(3, 0))

        ttk.Label(root, text="Instagram URL or local PDF").grid(row=2, column=0, sticky="e", **pad)
        self.source = tk.StringVar()
        source_entry = ttk.Entry(root, textvariable=self.source, width=86)
        self._source_entry = source_entry
        source_entry.grid(row=2, column=1, sticky="ew", **pad)
        source_entry.bind("<Return>", lambda _event: self.fetch())
        root.bind("<Control-Return>", lambda _event: self.create())
        root.bind("<Control-l>", lambda _event: self._focus_source() or "break")
        root.bind("<Control-L>", lambda _event: self._focus_source() or "break")
        source_btns = ttk.Frame(root)
        source_btns.grid(row=2, column=2, **pad)
        ttk.Button(source_btns, text="Paste", command=self.paste_source).pack(side="left")
        self._pdf_btn = ttk.Button(source_btns, text="PDF…", command=self.pick_pdf)
        self._pdf_btn.pack(side="left", padx=(6, 0))

        ttk.Label(root, text="Section").grid(row=3, column=0, sticky="e", **pad)
        self.section = tk.StringVar(value=settings.default_section)
        row = ttk.Frame(root)
        row.grid(row=3, column=1, sticky="w", **pad)
        for index, name in enumerate(settings.sections):
            ttk.Radiobutton(row, text=name, variable=self.section, value=name).pack(
                side="left", padx=(0 if index == 0 else 12, 0)
            )

        ttk.Label(root, text="Recipe / video language").grid(row=4, column=0, sticky="e", **pad)
        self.language = tk.StringVar(value=DE)
        lang_row = ttk.Frame(root)
        lang_row.grid(row=4, column=1, sticky="w", **pad)
        ttk.Radiobutton(lang_row, text="Deutsch", variable=self.language, value=DE).pack(side="left")
        ttk.Radiobutton(lang_row, text="English", variable=self.language, value=EN).pack(side="left", padx=(12, 0))
        ttk.Label(root, text="Detected from the text; used for the video note / 本文から判定、動画メモに使う", style="Muted.TLabel").grid(
            row=4, column=2, sticky="w"
        )

        ttk.Label(root, text="Browser cookies (optional)").grid(row=5, column=0, sticky="e", **pad)
        self.cookies = tk.StringVar(value=settings.cookies_from_browser)
        ttk.Entry(root, textvariable=self.cookies, width=32).grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(
            root,
            text="chrome / edge / firefox if Instagram blocks the download",
            style="Muted.TLabel",
        ).grid(row=5, column=2, sticky="w")

        buttons = ttk.Frame(root)
        buttons.grid(row=6, column=1, sticky="ew", **pad)
        self._fetch_btn = ttk.Button(buttons, text="Fetch metadata", command=self.fetch)
        self._fetch_btn.pack(side="left", padx=(0, 8))
        self._create_btn = tk.Button(
            buttons,
            text="Create folder",
            command=self.create,
            bg=ACCENT,
            fg="#fff",
            activebackground="#e07a42",
            activeforeground="#fff",
            relief="flat",
            padx=14,
            pady=6,
            font=ui_font(_BODY, "bold"),
            cursor="hand2",
        )
        self._create_btn.pack(side="left")

        ttk.Label(root, text="Title").grid(row=7, column=0, sticky="e", **pad)
        self.title = tk.StringVar()
        ttk.Entry(root, textvariable=self.title).grid(row=7, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(root, text="Handle").grid(row=8, column=0, sticky="e", **pad)
        self.handle = tk.StringVar()
        ttk.Entry(root, textvariable=self.handle).grid(row=8, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(root, text="Ingredients (blank line = new group)").grid(row=9, column=0, sticky="ne", **pad)
        self.ingredients = tk.Text(
            root,
            height=12,
            wrap="word",
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=ui_font(),
            padx=10,
            pady=8,
            insertwidth=2,
        )
        self.ingredients.grid(row=9, column=1, columnspan=2, sticky="nsew", **pad)

        ttk.Label(root, text="Steps (Tipps/Tips starts tips)").grid(row=10, column=0, sticky="ne", **pad)
        self.steps = tk.Text(
            root,
            height=10,
            wrap="word",
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=ui_font(),
            padx=10,
            pady=8,
            insertwidth=2,
        )
        self.steps.grid(row=10, column=1, columnspan=2, sticky="nsew", **pad)

        start = (
            f"Personal paths: {settings.config_path}\n"
            f"Master {settings.template_tex.name} is only copied, never overwritten."
        )
        if not settings.template_tex.is_file():
            start += f"\nTemplate missing: {settings.template_tex}"
        self.status = tk.StringVar(value=start)
        ttk.Label(root, textvariable=self.status, wraplength=1040, style="Muted.TLabel").grid(
            row=11, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 10)
        )
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(9, weight=1)
        root.grid_rowconfigure(10, weight=1)
        try:
            parent = Path(__file__).resolve().parent.parent
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            from common.ui import bind_responsive_ui, fit_window

            bind_responsive_ui(root)
            root.after_idle(lambda: fit_window(root, min_width=1100, min_height=780, fill=0.72))
        except ImportError:
            pass
        self._restore_session()
        self._source_entry.focus_set()
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self) -> None:
        _apply_ui_fonts(self.root)
        parent = Path(__file__).resolve().parent.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        try:
            from common.ui import apply_ttk_style

            apply_ttk_style(self.root)
            return
        except ImportError:
            pass
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD, font=ui_font())
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=ui_font())
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=ui_font(_SMALL))
        style.configure("TButton", background=CARD, foreground=TEXT, padding=(12, 7), borderwidth=0, font=ui_font())
        style.map("TButton", background=[("active", ACCENT)])
        style.configure("TRadiobutton", background=BG, foreground=TEXT, font=ui_font())
        style.map("TRadiobutton", background=[("active", BG)])
        style.configure("TEntry", fieldbackground=CARD, foreground=TEXT, insertcolor=TEXT, font=ui_font())

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._fetch_btn.configure(state=state)
        self._create_btn.configure(state=state)
        self._pdf_btn.configure(state=state)
        try:
            self._source_entry.configure(state=state)
        except tk.TclError:
            pass
        try:
            self.root.configure(cursor="wait" if busy else "")
        except tk.TclError:
            pass
        if message:
            self.status.set(message)

    def _call_on_ui(self, callback) -> None:
        def run() -> None:
            try:
                if self.root.winfo_exists():
                    callback()
            except tk.TclError:
                pass

        self.root.after(0, run)

    def _status_later(self, message: str) -> None:
        self._call_on_ui(lambda msg=message: self.status.set(msg))

    def pick_pdf(self) -> None:
        if self._busy:
            return
        chosen = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if chosen:
            self.source.set(chosen)
            self.fetch()

    def fetch(self) -> None:
        if self._busy:
            return
        source = self.source.get().strip()
        if not source:
            messagebox.showerror("Source", "Paste an Instagram URL or choose a PDF.")
            return
        path = Path(source)
        if source.lower().endswith(".pdf") or (path.is_file() and path.suffix.lower() == ".pdf"):
            self._fetch_pdf(path)
            return
        if path.is_file():
            messagebox.showerror("Source", "Use an Instagram URL or a PDF.")
            return
        cookies = self.cookies.get().strip()
        self._set_busy(True, "Fetching Instagram metadata…")

        def work() -> None:
            try:
                info = fetch_info(source, cookies)
            except Exception as error:
                self._call_on_ui(lambda err=error: self._on_fetch_error(err))
                return
            self._call_on_ui(lambda: self._on_fetch_ok(info, source))

        threading.Thread(target=work, daemon=True).start()

    def _fetch_pdf(self, path: Path) -> None:
        self._set_busy(True, "Reading PDF…")

        def work() -> None:
            try:
                from pdf_text import extract_pdf_text

                text = extract_pdf_text(path)
            except Exception as error:
                self._call_on_ui(lambda err=error: self._on_fetch_error(err))
                return
            self._call_on_ui(lambda: self._on_pdf_ok(path, text))

        threading.Thread(target=work, daemon=True).start()

    def _on_fetch_error(self, error: Exception) -> None:
        self._set_busy(False)
        messagebox.showerror("Fetch", str(error))

    def _fill_from_draft(self, draft, *, extra: str = "", caption: str = "") -> None:
        self.title.set(draft.title)
        self.handle.set(draft.handle)
        detected = detect_language(
            draft.title,
            caption,
            format_ingredients(draft.groups),
            " ".join(draft.steps),
        )
        self.language.set(detected)
        self.ingredients.delete("1.0", "end")
        self.steps.delete("1.0", "end")
        self.ingredients.insert("1.0", format_ingredients(draft.groups))
        steps_text = format_steps(draft.steps, draft.tips, language=detected)
        if not (draft.steps or draft.tips) and caption.strip():
            steps_text = caption.strip()
        self.steps.insert("1.0", steps_text)
        spoken = language_name(detected, in_language=DE if detected == DE else EN)
        n_ing = sum(len(group.items) for group in draft.groups)
        self._set_busy(False)
        self.status.set(
            f"Language: {spoken}. Split into {n_ing} ingredients and {len(draft.steps)} steps. "
            f"Check and edit the lists, then Create.{extra}"
        )

    def _on_pdf_ok(self, path: Path, text: str) -> None:
        draft = parse_caption(path.stem, "", "", text)
        self._fill_from_draft(
            draft,
            caption=text,
            extra=f" From PDF: {path.name}",
        )

    def _on_fetch_ok(self, info: dict, url: str) -> None:
        title = str(info.get("title") or info.get("description") or "recipe").split("\n")[0][:80]
        uploader = str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or "")
        caption = str(info.get("description") or "")
        draft = parse_caption(title, f"@{uploader}" if uploader else "", url, caption)
        existing = find_folder_by_url(self.settings.sections.values(), url)
        extra = f" Already exists: {existing.name} — Create will ask to abort or update." if existing else ""
        self._fill_from_draft(draft, extra=extra, caption=caption)

    def _ask_abort_or_update(self, dest: Path) -> bool:
        result = {"update": False}
        win = tk.Toplevel(self.root)
        win.title("Rezept existiert bereits")
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(
            win,
            text=(
                "Dieses Instagram-Rezept gibt es schon:\n"
                "このInstagramレシピはすでにあります:\n\n"
                f"{dest}\n\n"
                "Abbrechen, oder den vorhandenen Ordner aktualisieren?\n"
                "中止するか、既存フォルダを更新しますか？"
            ),
            wraplength=640,
            justify="left",
        ).pack(padx=18, pady=(16, 8))
        row = ttk.Frame(win)
        row.pack(pady=(4, 16))

        def abort() -> None:
            result["update"] = False
            win.destroy()

        def update() -> None:
            result["update"] = True
            win.destroy()

        ttk.Button(row, text="Abbrechen", command=abort).pack(side="left", padx=8)
        ttk.Button(row, text="Aktualisieren", command=update).pack(side="left", padx=8)
        win.protocol("WM_DELETE_WINDOW", abort)
        win.bind("<Escape>", lambda _event: abort())
        win.grab_set()
        win.wait_window()
        return result["update"]

    def _close(self) -> None:
        self._persist()
        self.root.destroy()

    def _restore_session(self) -> None:
        parent = Path(__file__).resolve().parent.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        try:
            from common.session import load_session

            saved = load_session(SESSION)
        except ImportError:
            return
        if saved.get("source"):
            self.source.set(saved["source"])
        if saved.get("section") and saved["section"] in self.settings.sections:
            self.section.set(saved["section"])
        if saved.get("cookies"):
            self.cookies.set(saved["cookies"])

    def _persist(self) -> None:
        parent = Path(__file__).resolve().parent.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        try:
            from common.session import save_session

            save_session(
                SESSION,
                {
                    "source": self.source.get().strip(),
                    "section": self.section.get().strip(),
                    "cookies": self.cookies.get().strip(),
                },
            )
        except (ImportError, OSError):
            pass

    def _focus_source(self) -> None:
        self._source_entry.focus_set()
        self._source_entry.select_range(0, "end")

    def paste_source(self) -> None:
        try:
            body = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        if not body:
            return
        self.source.set(body)
        if "instagram.com" in body.lower() or body.lower().endswith(".pdf"):
            self.fetch()

    def _recipe_url(self) -> str:
        url = self.source.get().strip().strip('"')
        if not url or Path(url).is_file():
            return ""
        if not url.lower().startswith("http"):
            if "instagram.com" in url.lower() or "instagr.am" in url.lower():
                url = "https://" + url.lstrip("/")
            else:
                return ""
        return canonical_recipe_url(url)

    def create(self) -> None:
        if self._busy:
            return
        template = self.settings.template_tex
        if not template.is_file():
            messagebox.showerror("Template", f"Master template missing:\n{template}")
            return
        parent = self.settings.section_path(self.section.get())
        if not parent.is_dir():
            messagebox.showerror("Folder", f"Section folder missing:\n{parent}")
            return
        title = self.title.get().strip() or "recipe"
        url = self._recipe_url()
        existing = find_folder_by_url(self.settings.sections.values(), url) if url else None
        updating = False
        if existing:
            if not self._ask_abort_or_update(existing):
                self.status.set(f"Cancelled. Existing folder left unchanged:\n{existing}")
                return
            dest = existing
            updating = True
            number = folder_number(dest.name, self.settings.folder_code) or next_insta_number(
                self.settings.sections.values(), self.settings.folder_code
            )
            wanted = parent / folder_name(number, title, self.settings.folder_code)
            if dest.resolve() != wanted.resolve():
                try:
                    rename_stem_files(dest, dest.name, wanted.name)
                    dest = move_recipe_folder(dest, wanted)
                except OSError as error:
                    messagebox.showerror("Rename", str(error))
                    return
        else:
            number = next_insta_number(self.settings.sections.values(), self.settings.folder_code)
            dest = parent / folder_name(number, title, self.settings.folder_code)
        source = self.source.get().strip()
        cookies = self.cookies.get().strip()
        handle = self.handle.get().strip()
        ingredients_text = self.ingredients.get("1.0", "end")
        steps_text = self.steps.get("1.0", "end")
        source_lang = self.language.get() if self.language.get() in {DE, EN} else detect_language(title)
        folder_code = self.settings.folder_code
        self._set_busy(True, "Copying template and translating…")

        def work() -> None:
            try:
                copies, pdfs, warning, compile_warning = self._run_pipeline(
                    template=template,
                    dest=dest,
                    updating=updating,
                    number=number,
                    title=title,
                    url=url,
                    handle=handle,
                    source_lang=source_lang,
                    ingredients_text=ingredients_text,
                    steps_text=steps_text,
                    source=source,
                    cookies=cookies,
                    folder_code=folder_code,
                )
            except Exception as error:
                self._call_on_ui(lambda err=error: self._on_create_error(err, dest))
                return
            self._call_on_ui(
                lambda: self._on_create_ok(
                    dest, copies, pdfs, warning, compile_warning, source_lang, updating
                )
            )

        threading.Thread(target=work, daemon=True).start()

    def _run_pipeline(
        self,
        *,
        template: Path,
        dest: Path,
        updating: bool,
        number: int,
        title: str,
        url: str,
        handle: str,
        source_lang: str,
        ingredients_text: str,
        steps_text: str,
        source: str,
        cookies: str,
        folder_code: int,
    ) -> tuple[dict[str, Path], list[Path], str, str]:
        master_hash = file_hash(template)
        copies = copy_template(template, dest, overwrite=updating)
        full_title = f"[{folder_code}][{number:02d}] {title}"
        step_list, tip_list = steps_from_text(steps_text)
        draft = RecipeDraft(
            title=full_title,
            handle=handle,
            url=url,
            image_name=f"{dest.name}.jpg",
            groups=groups_from_text(ingredients_text),
            steps=step_list,
            tips=tip_list,
            notes="",
            language=source_lang,
            video_language=source_lang,
        )
        warning = ""
        try:
            pair = bilingual_drafts(draft)
        except TranslateError as error:
            warning = str(error)
            pair = {
                DE: replace(draft, language=DE, video_language=source_lang),
                EN: replace(draft, language=EN, video_language=source_lang),
            }
        for lang, tex_path in copies.items():
            fill_copy(tex_path, pair[lang], master=template)
        if file_hash(template) != master_hash:
            raise RuntimeError(f"Master template was modified. Stop and restore {template}.")
        recipe_url = url or self._normalize_http(source)
        if recipe_url:
            self._status_later("Downloading video…")
            download_media(recipe_url, dest, cookies)
        elif Path(source).is_file() and source.lower().endswith(".pdf"):
            shutil.copy2(source, dest / f"{dest.name}.pdf")
        self._status_later("Compiling PDFs with LuaLaTeX…")
        pdfs, compile_warning = compile_folder(dest, copies)
        tidy_recipe_folder(dest)
        return copies, pdfs, warning, compile_warning

    def _on_create_error(self, error: Exception, dest: Path) -> None:
        tidy_recipe_folder(dest)
        self._set_busy(False, f"Partial folder: {dest}")
        messagebox.showerror(
            "Stopped after copy",
            f"The folder exists with template copies.\nMaster template is unchanged.\n\n{error}",
        )

    def _on_create_ok(
        self,
        dest: Path,
        copies: dict[str, Path],
        pdfs: list[Path],
        warning: str,
        compile_warning: str,
        source_lang: str,
        updating: bool,
    ) -> None:
        files = "\n".join(str(path) for path in copies.values())
        pdf_lines = "\n".join(str(path) for path in pdfs) if pdfs else "(no PDF)"
        extra = ""
        if warning:
            extra += f"\n\nTranslation fallback: {warning}"
        if compile_warning:
            extra += f"\n\nPDF compile: {compile_warning}"
        verb = "Updated" if updating else "Created"
        self._set_busy(False, f"{verb} {dest}\nPDFs: {len(pdfs)}\nMaster template hash unchanged.{extra}")
        messagebox.showinfo(
            "Done",
            f"{verb}:\n{files}\n\n{pdf_lines}\n\nVideo language: {source_lang}"
            f"{extra}",
        )
        parent = Path(__file__).resolve().parent.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        try:
            from common.ui import open_in_explorer

            open_in_explorer(dest)
        except ImportError:
            try:
                os.startfile(dest)  # type: ignore[attr-defined]
            except OSError:
                pass

    @staticmethod
    def _normalize_http(source: str) -> str:
        text = source.strip().strip('"')
        if text.lower().startswith("http"):
            return text
        if "instagram.com" in text.lower() or "instagr.am" in text.lower():
            return "https://" + text.lstrip("/")
        return ""


def main() -> None:
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        from common.launch import hide_owned_console

        hide_owned_console()
    except ImportError:
        pass
    _enable_dpi()
    root = tk.Tk()
    try:
        settings = load_settings()
    except ConfigError as error:
        messagebox.showerror("Config", str(error))
        root.destroy()
        return
    ReciplateApp(root, settings)
    root.mainloop()


if __name__ == "__main__":
    main()
