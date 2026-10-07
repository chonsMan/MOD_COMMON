#######################################################################################################################
# Title:   runs_panel.py
# Author:  Jesse Harris
# Version: v1 (shared; from MOD_PSLF 04_GUI_V3 runs_panel.py v3)
# Purpose: List past runs in the runs folder: show plots, rename, keep, delete / clear (to the Recycle Bin)
# Notes:   Rename renames the run folder itself (the table shows folder names); runs are listed newest first by
#          their start time, so renamed runs stay in order.
#          Keep (★) sets meta.json "keep"; Clear all skips kept runs, _inspect, _se_cache and the run in progress.
#          Save ★ copies the kept runs into a new folder (picked under 01_CLIENTS), plus an _inputs folder holding
#          every SAV / DYD or DYR / play-in CSV / DYD playback file they used, so the saved set can be re-run
#          (PSS(R)E: generated .plb files and playback DYRs are already inside each run folder).
#######################################################################################################################
import ctypes
import json
import os
import re
import shutil
from datetime import datetime
from ctypes import wintypes
from tkinter import filedialog, messagebox, simpledialog, ttk

import pandas as pd

import settings
from gui import theme

# Column names used before per-unit collection was added (runs made with the first V3 build)
LEGACY_COLUMNS = {"v_pu": "poc_v", "p": "poc_p", "q": "poc_q", "f": "poc_f"}


def load_run(run_dir):
    """Return (config, meta, results_df or None) for a run folder."""
    def _json(name):
        path = os.path.join(run_dir, name)
        if os.path.isfile(path):
            with open(path) as fh:
                return json.load(fh)
        return {}

    results = os.path.join(run_dir, "results.csv")
    df = pd.read_csv(results) if os.path.isfile(results) else None
    if df is not None:
        df = df.rename(columns=LEGACY_COLUMNS)
    return _json("config.json"), _json("meta.json"), df


def _read_meta(run_dir):
    try:
        with open(os.path.join(run_dir, "meta.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _update_meta(run_dir, **changes):
    meta = _read_meta(run_dir)
    meta.update(changes)
    with open(os.path.join(run_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, default=str)


def _folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def clean_folder_name(name):
    """Return (folder_name, problem). Windows-illegal characters become '_'; problem is None if the name is usable."""
    name = _BAD_CHARS.sub("_", name.strip()).rstrip(" .")
    if not name:
        return name, "The name is empty."
    if name.startswith("_"):
        return name, "Names starting with '_' are hidden (reserved for _inspect / _se_cache)."
    if name.split(".")[0].upper() in _RESERVED:
        return name, f"'{name}' is a reserved Windows name."
    if len(os.path.join(settings.RUNS_DIR, name)) > 200:
        return name, "The name is too long for a Windows path."
    return name, None


def _started(run_dir, meta):
    """Sort key: the run's start time from meta.json, else the folder's creation time."""
    try:
        return datetime.fromisoformat(meta["started"]).timestamp()
    except (KeyError, TypeError, ValueError):
        try:
            return os.path.getctime(run_dir)
        except OSError:
            return 0.0


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def send_to_recycle_bin(paths):
    """Move folders to the Windows Recycle Bin (undoable). Raises OSError if Windows refuses."""
    if not paths:
        return
    op = _SHFILEOPSTRUCTW()
    op.wFunc = 3                                  # FO_DELETE
    op.pFrom = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
    op.fFlags = 0x40 | 0x10 | 0x04 | 0x400        # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Recycle Bin move failed (code {rc}). Is a file in the run folder open?")


def save_runs(run_dirs, target):
    r"""Copy run folders to target\<run> and the inputs they used to target\_inputs (each file once).

    Returns (number of input files copied, warnings). Raises if target already exists.
    """
    os.makedirs(target)
    for d in run_dirs:
        shutil.copytree(d, os.path.join(target, os.path.basename(d)))

    wanted, warnings = {}, []
    for d in run_dirs:
        with open(os.path.join(d, "config.json")) as fh:
            v = json.load(fh).get("values", {})
        for key, folder in (("sav", settings.MODELS_DIR), ("dyd", settings.MODELS_DIR), ("dyr", settings.MODELS_DIR),
                            ("play_in", settings.PLAY_IN_DIR)):
            if v.get(key):
                wanted.setdefault(os.path.join(folder, v[key]) if not os.path.isabs(v[key]) else v[key], d)
    for path in [p for p in wanted if p.lower().endswith(".dyd") and os.path.isfile(p)]:
        with open(path, errors="replace") as fh:
            for name in re.findall(r'"plyfil"\s+"?([^\s"/]+)', fh.read(), re.I):   # playback files, relative to
                wanted.setdefault(os.path.join(settings.PSLF_WORKING_DIR, name), path)   # the PSLF working dir (PSLF only)

    inputs = os.path.join(target, "_inputs")
    os.makedirs(inputs)
    copied = {}
    for path in wanted:
        name = os.path.basename(path)
        if not os.path.isfile(path):
            warnings.append(f"input not found, not saved: {path}")
        elif name.lower() in copied and os.path.normcase(copied[name.lower()]) != os.path.normcase(path):
            warnings.append(f"two different inputs named {name}; kept {copied[name.lower()]}, skipped {path}")
        elif name.lower() not in copied:
            shutil.copy2(path, os.path.join(inputs, name))
            copied[name.lower()] = path
    return len(copied), warnings


class RunsPanel(ttk.Frame):
    def __init__(self, master, on_show, on_units, on_channels, on_overlay, on_message, busy_dir=lambda: None,
                 on_renamed=lambda old, new: None):
        super().__init__(master, padding=4)
        self.on_renamed = on_renamed      # (old_dir, new_dir) so other panels can follow a renamed run
        self.on_show = on_show
        self.on_units = on_units
        self.on_channels = on_channels
        self.on_overlay = on_overlay
        self.on_message = on_message
        self.busy_dir = busy_dir          # returns the run folder currently being written, if any

        view = ttk.Frame(self)
        view.pack(fill="x", pady=(0, 3))
        ttk.Label(view, text="View", style="Section.TLabel").pack(side="left", padx=(0, 6))
        for text, cmd in (("Show", self._show), ("Units", self._units), ("Channels", self._channels),
                          ("Overlay", self._overlay)):
            ttk.Button(view, text=text, style="Small.TButton", command=cmd).pack(side="left", padx=1)
        ttk.Button(view, text="⟳ Refresh", style="Small.TButton", command=self.refresh).pack(side="right")

        manage = ttk.Frame(self)
        manage.pack(fill="x", pady=(0, 4))
        ttk.Label(manage, text="Manage", style="Section.TLabel").pack(side="left", padx=(0, 6))
        for text, cmd in (("✎ Rename", self._rename), ("★ Keep", self._toggle_keep), ("🗑 Delete", self._delete),
                          ("Clear all", self._clear_all), ("💾 Save ★", self._save_kept),
                          ("📂 Open folder", self._open)):
            ttk.Button(manage, text=text, style="Small.TButton", command=cmd).pack(side="left", padx=1)

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("keep", "test", "status", "when"), height=8, selectmode="extended")
        for col, text, width, anchor in (("#0", "Run", 230, "w"), ("keep", "★", 28, "center"),
                                         ("test", "Test", 140, "w"), ("status", "Status", 60, "center"),
                                         ("when", "Started", 125, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("#0", "test")))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        theme.stripe(self.tree)
        self.tree.bind("<Double-1>", lambda e: self._show())
        self.tree.bind("<F2>", lambda e: self._rename())
        self.tree.bind("<Delete>", lambda e: self._delete())
        self.refresh()

    # ------------------------------------------------------------------ table
    def _runs(self):
        """[(folder name, meta)] newest first by start time (not by name, so renamed runs keep their place)."""
        if not os.path.isdir(settings.RUNS_DIR):
            return []
        runs = []
        for n in os.listdir(settings.RUNS_DIR):
            d = os.path.join(settings.RUNS_DIR, n)
            if not n.startswith("_") and os.path.isdir(d):
                meta = _read_meta(d)
                runs.append((_started(d, meta), n, meta))
        return [(n, meta) for _, n, meta in sorted(runs, key=lambda r: (r[0], r[1]), reverse=True)]

    def _run_dirs(self):
        return [n for n, _ in self._runs()]

    def refresh(self):
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for k, (name, meta) in enumerate(self._runs()):
            status = meta.get("status", "?")
            when = (meta.get("started") or "").replace("T", " ")
            tags = ("odd" if k % 2 else "even", status if status in ("ok", "error", "running") else "")
            self.tree.insert("", "end", iid=name, text=meta.get("name") or name,
                             values=("★" if meta.get("keep") else "", meta.get("label", ""), status, when),
                             tags=tags)
        keep = [i for i in selected if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)

    def _selected_dirs(self):
        return [os.path.join(settings.RUNS_DIR, iid) for iid in self.tree.selection()]

    # ------------------------------------------------------------------ view
    def _show(self):
        dirs = self._selected_dirs()
        if dirs:
            self.on_show(dirs[0])

    def _units(self):
        dirs = self._selected_dirs()
        if dirs:
            self.on_units(dirs[0])

    def _channels(self):
        dirs = self._selected_dirs()
        if dirs:
            self.on_channels(dirs[0])

    def _overlay(self):
        dirs = self._selected_dirs()
        if len(dirs) < 2:
            self.on_message("Select two or more runs (Ctrl+click) to overlay.")
            return
        self.on_overlay(dirs)

    def _open(self):
        dirs = self._selected_dirs()
        os.startfile(dirs[0] if dirs else settings.RUNS_DIR)

    # ------------------------------------------------------------------ manage
    def _rename(self):
        dirs = self._selected_dirs()
        if len(dirs) != 1:
            self.on_message("Select one run to rename.")
            return
        old = dirs[0]
        busy = self.busy_dir()
        if busy and os.path.normcase(os.path.abspath(busy)) == os.path.normcase(os.path.abspath(old)):
            self.on_message("Can't rename the run in progress; rename it when it finishes.")
            return
        current = os.path.basename(old)
        meta = _read_meta(old)
        name = simpledialog.askstring("Rename run", "New name (renames the run folder too):",
                                      initialvalue=meta.get("name") or current, parent=self)
        if name is None:
            return
        name, problem = clean_folder_name(name)
        if problem:
            messagebox.showerror("Rename run", problem, parent=self)
            return
        if name == current:
            if meta.get("name"):                       # tidy up a display name left by an older build
                _update_meta(old, name=None)
                self.refresh()
            return
        new = os.path.join(settings.RUNS_DIR, name)
        if os.path.exists(new) and os.path.normcase(new) != os.path.normcase(old):
            messagebox.showerror("Rename run", f"A run named '{name}' already exists.", parent=self)
            return
        try:
            os.rename(old, new)
        except OSError as e:
            messagebox.showerror("Rename run", f"Windows couldn't rename the folder ({e.strerror}). "
                                               "Close any file from this run (Excel, Explorer preview) and retry.",
                                 parent=self)
            return
        # Paths recorded inside the run follow the folder; the display name is now the folder name itself
        meta = _read_meta(new)
        meta.pop("name", None)
        init = meta.get("initialization")
        if isinstance(init, dict) and isinstance(init.get("sav"), str):
            init["sav"] = os.path.join(new, os.path.basename(init["sav"]))
        with open(os.path.join(new, "meta.json"), "w") as fh:
            json.dump(meta, fh, indent=2, default=str)
        self.on_message(f"Renamed run '{current}' -> '{name}'.")
        self.on_renamed(old, new)
        self.refresh()
        self.tree.selection_set(name)
        self.tree.see(name)

    def _toggle_keep(self):
        dirs = self._selected_dirs()
        if not dirs:
            return
        keep = not all(_read_meta(d).get("keep") for d in dirs)     # any unkept -> keep all selected
        for d in dirs:
            _update_meta(d, keep=keep)
        self.refresh()
        self.on_message(f"{'Kept' if keep else 'Un-kept'} {len(dirs)} run(s).")

    def _deletable(self, dirs, skip_kept):
        busy = self.busy_dir()
        out, skipped = [], []
        for d in dirs:
            if busy and os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(busy)):
                skipped.append(f"{os.path.basename(d)} (running)")
            elif skip_kept and _read_meta(d).get("keep"):
                skipped.append(f"{os.path.basename(d)} (kept)")
            else:
                out.append(d)
        return out, skipped

    def _remove(self, dirs, what):
        if not dirs:
            self.on_message(f"Nothing to {what}.")
            return
        size = sum(_folder_size(d) for d in dirs) / 1e6
        if not messagebox.askyesno(f"{what.capitalize()} runs",
                                   f"Move {len(dirs)} run(s) ({size:.1f} MB) to the Recycle Bin?", parent=self):
            return
        try:
            send_to_recycle_bin(dirs)
            self.on_message(f"Moved {len(dirs)} run(s) to the Recycle Bin.")
        except OSError as e:
            self.on_message(f"ERROR: {e}")
        self.refresh()

    def _delete(self):
        dirs, skipped = self._deletable(self._selected_dirs(), skip_kept=False)
        for s in skipped:
            self.on_message(f"Skipped {s}.")
        self._remove(dirs, "delete")

    def _clear_all(self):
        all_dirs = [os.path.join(settings.RUNS_DIR, n) for n in self._run_dirs()]
        dirs, skipped = self._deletable(all_dirs, skip_kept=True)
        if skipped:
            self.on_message(f"Clear all keeps {len(skipped)} run(s): " + ", ".join(skipped))
        self._remove(dirs, "clear")

    def _save_kept(self):
        kept = [os.path.join(settings.RUNS_DIR, n) for n, m in self._runs() if m.get("keep")]
        kept, skipped = self._deletable(kept, skip_kept=False)          # leaves out a run still in progress
        for s in skipped:
            self.on_message(f"Not saved: {s}.")
        if not kept:
            self.on_message("No ★ runs to save. Select runs and press ★ Keep first.")
            return
        parent = filedialog.askdirectory(initialdir=settings.CLIENTS_DIR, parent=self,
                                         title=f"Save {len(kept)} ★ run(s): choose where to create the new folder")
        if not parent:
            return
        name = simpledialog.askstring("Save ★ runs", f"New folder in {parent}:",
                                      initialvalue=datetime.now().strftime("%Y%m%d") + "_MOD_runs", parent=self)
        if name is None:
            return
        name, problem = clean_folder_name(name)
        target = os.path.join(parent, name)
        if problem or os.path.exists(target):
            messagebox.showerror("Save ★ runs", problem or f"'{target}' already exists.", parent=self)
            return
        try:
            n_inputs, warnings = save_runs(kept, target)
        except OSError as e:
            messagebox.showerror("Save ★ runs", f"Saving stopped: {e}", parent=self)
            return
        for w in warnings:
            self.on_message(f"WARNING: {w}")
        self.on_message(f"Saved {len(kept)} ★ run(s) and {n_inputs} input file(s) to {target}")
        os.startfile(target)
