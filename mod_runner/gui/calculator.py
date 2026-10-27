#######################################################################################################################
# Title:   calculator.py
# Author:  Jesse Harris
# Version: v2 (shared; from MOD_PSSE 04_GUI_V1 gui/calculator.py)
# Purpose: The Calculator window (toolbar button): plant-controller parameters. A header with the plant controller and
#          the plant values both calculators use, then three tabs:
#            AVR Calculator  voltage droop band, Kc, volt step tests (Vreg / Qbr, tie-line X, Vref), SE operating points
#            PFR Calculator  frequency droop band, ddn / dup
#            Equations       every formula, typeset with matplotlib mathtext (rendered the first time the tab opens)
#          Math in mod_runner/calculator.py; plan and decisions in MOD_PSSE\06_MARKDOWN\completed\Calculator.md.
# Notes:   Read-only: nothing here changes the form, the SAV or the dynamics file, and nothing touches the simulator.
#          The MVA base is always the plant controller's, read from the last Inspect Case (meta.json "ppc": its
#          "instances", or the PPC's own "mva"); so is F Base. V Base starts at the PPC's base kV and can be edited.
#          Uses the app's settings (INSPECT_DIR, PLAY_IN_DIR) and gui.theme, like runs_panel. The "Plant controller
#          MVA base" equations differ per simulator: the app passes them (mva_equations).
#          Inputs are remembered in user_settings.json under "calculator".
#######################################################################################################################
import io
import json
import os
import tkinter as tk
from tkinter import filedialog, ttk

import settings
from gui import theme
from mod_runner import calculator as calc
from mod_runner import play_in

DEFAULTS = {"f_base": "60", "pf": "0.95", "use_pf": True, "v_droop_base": "System Base", "f_droop_pct": "5",
            "f_deadband": "0.036", "avr_test": "Vref"}
CHOICES = {"v_droop_base": ("System Base", "Setpoint"), "avr_test": calc.AVR_TEST_TYPES}
CHECKS = ("use_pf",)
LOCKED = ("mva", "f_base")          # from the plant controller (Inspect Case)
FILES = ("csv_up", "csv_down")
VREF_KEYS = ("vref_up_initial", "vref_up_final", "vref_down_initial", "vref_down_final")
STEP_NAMES = {"up": "Step Up", "down": "Step Down"}

SOFT = "#C5CDD9"                    # light border of the value boxes
KEY_BG = getattr(theme, "CALC_KEY_BG", "#E8F1FB")   # background of the main results (Kc, ddn / dup)
HEAD = getattr(theme, "NAVY", None) or theme.DARK  # card titles and equations (navy PSS(R)E, deep teal PSLF)
MONO = ("Consolas", 10)

# Equations tab: (card title, [lines]); a line in $...$ is typeset, anything else is a plain note
EQUATIONS_LEFT = (
    ("Plant controller MVA base", [
        r"$\mathrm{REPCA1,\ REPCC:}\ \ MVA_{base} = MBASE_{unit}$",
        r"$\mathrm{PLNTBU1:}\ \ MVA_{base} = CON(J{+}27)$",
        r"$\qquad\mathrm{if\ 0:}\ \ MVA_{base} = SBASE$",
        r"$\mathrm{HPLNTDU:}\ \ MVA_{base} = CON(J{+}57)$",
        r"$\qquad\mathrm{if\ 0:}\ \ MVA_{base} = \sum MBASE_{units}$"]),
    ("Voltage droop band", [
        r"$V_{ref} = V_{base}\ \ \mathrm{(Droop\ Base = System\ Base)}$",
        r"$V_{ref} = V_3\ \ \mathrm{(Droop\ Base = Setpoint)}$",
        r"$Droop_{kV} = (Droop_{\%}\,/\,100) \cdot V_{ref}$",
        r"$V_1 = V_3 - Droop_{kV} \qquad V_2 = V_3 - Deadband_{kV}$",
        r"$V_4 = V_3 + Deadband_{kV} \qquad V_5 = V_3 + Droop_{kV}$",
        r"$V_{p.u.} = V_{kV}\,/\,V_{ref}$"]),
    ("Frequency droop band", [
        r"$Droop_{Hz} = (Droop_{\%}\,/\,100) \cdot F_{base}$",
        r"$F_1 = F_3 - Droop_{Hz} \qquad F_2 = F_3 - Deadband_{Hz}$",
        r"$F_4 = F_3 + Deadband_{Hz} \qquad F_5 = F_3 + Droop_{Hz}$",
        r"$F_{p.u.} = F_{Hz}\,/\,F_{base}$"]),
    ("Plant Q limits", [
        r"$Q_{max} = (P_{max}\,/\,PF) \cdot \sqrt{1 - PF^{2}} \qquad Q_{min} = -\,Q_{max}$"]),
    ("Droop gain Kc", [
        r"$Droop_{w/\,db} = Droop_{p.u.}$",
        r"$Droop_{w/o\,db} = Droop_{p.u.} - Deadband_{p.u.}$",
        r"$K_c = Droop \cdot MVA_{base}\,/\,|\,Q_{lim}\,| \qquad Q_{lim} = Q_{max}$"]),
    ("Droop gain ddn / dup", [
        r"$d_{dn} = d_{up} = (1\,/\,Droop) \cdot (P_{lim}\,/\,MVA_{base}) \qquad P_{lim} = P_{max}$"]),
)
EQUATIONS_RIGHT = (
    ("Volt step test conditions", [
        r"$\mathrm{Initial} = \mathrm{mean}(x)_{\ \mathrm{first\ 3\ s}} \qquad \mathrm{Final} = \mathrm{mean}(x)_{\ \mathrm{last\ 3\ s}}$",
        r"$V_{ref,kV} = V_3\ \ \mathrm{(Vreg\ test)}$",
        r"$V_{ref,kV}\ \mathrm{typed\ in\ (Vref,\ Feed\ Forward\ tests)}$",
        r"$V_{p.u.} = V_{kV}\,/\,V_{base} \qquad Q_{p.u.} = Q_{MVAr}\,/\,MVA_{base}$",
        r"$\Delta = \left|\,\mathrm{Final} - \mathrm{Initial}\,\right|$"]),
    ("Tie-line impedance", [
        r"$I = Q_{br,p.u.}\,/\,V_{reg,p.u.}$",
        r"$X = |\,(V_{reg,fin} - V_{reg,ini})\,/\,(I_{fin} - I_{ini})\,|$",
        r"$X_{avg} = (X_{step\ up} + X_{step\ down})\,/\,2$"]),
    ("Reference voltage (Vref test)", [
        r"$V_{ref} = V_{reg} + K_c \cdot Q_{br}\ \ \mathrm{(p.u.)}$",
        r"$V_{ref}\,\mathrm{(ini)} = V_{reg,ini} + K_{c,w/\,db} \cdot Q_{br,ini}$",
        r"$V_{ref}\,\mathrm{(REPC\ a/c)} = V_{reg,fin} + K_{c,w/\,db} \cdot Q_{br,fin}$",
        r"$V_{ref}\,\mathrm{(REPC\ b/d)} = V_{reg,fin} + K_{c,w/o\,db} \cdot Q_{br,fin}$"]),
    ("State estimation operating points", [
        r"$\mathrm{Full\ Lag:}\ \ (V_1,\ Q_{max},\ P_{max})$",
        r"$\mathrm{Full\ Lead:}\ \ (V_5,\ Q_{min},\ P_{max})$",
        r"$\mathrm{Max\ Dispatch:}\ \ (V_3,\ 0,\ P_{max})$"]),
)


def latest_inspect():
    """meta.json of the newest Inspect Case folder (with "_sav": the case it inspected), or None."""
    try:
        dirs = sorted(d for d in os.listdir(settings.INSPECT_DIR) if os.path.isdir(os.path.join(settings.INSPECT_DIR, d)))
        folder = os.path.join(settings.INSPECT_DIR, dirs[-1])
        with open(os.path.join(folder, "meta.json")) as fh:
            meta = json.load(fh)
    except (OSError, IndexError, ValueError):
        return None
    sav = (meta.get("inspect_files") or {}).get("sav", "").replace("_solved.sav", "")   # PSS(R)E
    if not sav:
        try:
            with open(os.path.join(folder, "config.json")) as fh:
                sav = json.load(fh)["values"].get("sav") or ""
        except (OSError, ValueError, KeyError):
            pass
    meta["_sav"] = os.path.splitext(os.path.basename(sav))[0]
    return meta


def controllers(ppc):
    """The plant controllers with an MVA base: PSS(R)E lists every instance, PSLF has one PPC."""
    if ppc.get("instances"):
        return [i for i in ppc["instances"] if i.get("mva")]
    if not ppc.get("mva"):
        return []
    return [{"name": ppc.get("name"), "bus": ppc.get("ppc_bus") or ppc.get("mon_bus"), "id": ppc.get("ppc_id"),
             "mva": ppc["mva"], "mva_source": ppc.get("mva_source", "")}]


class CalculatorWindow(tk.Toplevel):
    def __init__(self, master, saved, on_save, mva_equations=None):
        super().__init__(master)
        self.title("Calculator")
        self.configure(bg=theme.BG)
        self.geometry("1180x760")
        self.minsize(1120, 720)
        self.on_save = on_save
        self.saved = dict(DEFAULTS, **{k: v for k, v in (saved or {}).items() if k not in LOCKED})
        self.vars, self.widgets, self.out = {}, {}, {}
        self.instances = []
        self.steps_cache = {}
        self._pending = None
        self._eq_images = None
        self.equations_left = (("Plant controller MVA base", list(mva_equations)),) + EQUATIONS_LEFT[1:] \
            if mva_equations else EQUATIONS_LEFT

        st = ttk.Style(self)
        st.configure("Calc.Value.TLabel", background=theme.PANEL, font=MONO, anchor="e", padding=(6, 1),
                     relief="solid", borderwidth=1, bordercolor=SOFT, lightcolor=SOFT, darkcolor=SOFT)
        st.configure("Calc.Key.TLabel", background=KEY_BG, foreground=theme.ACCENT, font=("Consolas", 11, "bold"),
                     anchor="e", padding=(6, 1), relief="solid", borderwidth=1, bordercolor=theme.ACCENT,
                     lightcolor=theme.ACCENT, darkcolor=theme.ACCENT)
        st.configure("Calc.Head.TLabel", foreground=theme.MUTED, font=("Segoe UI Semibold", 9))
        st.configure("Calc.Card.TLabelframe", padding=(10, 6, 10, 8))
        st.configure("Calc.Card.TLabelframe.Label", foreground=HEAD, font=theme.FONT_BOLD)
        st.configure("Calc.Warn.TLabel", foreground=theme.AMBER)

        self._build_header()
        self.book = ttk.Notebook(self)
        self.book.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        for title, build in (("AVR Calculator", self._build_avr), ("PFR Calculator", self._build_pfr),
                             ("Equations", self._build_equations)):
            page = ttk.Frame(self.book, padding=(8, 6))
            self.book.add(page, text=title)
            build(page)
        self.book.bind("<<NotebookTabChanged>>", lambda e: self._render_equations())

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.load_inspect()
        self._recompute()

    # ------------------------------------------------------------------ widget helpers
    def _var(self, key):
        if key not in self.vars:
            value = self.saved.get(key, "")
            self.vars[key] = tk.BooleanVar(value=bool(value)) if key in CHECKS else tk.StringVar(value=value)
            self.vars[key].trace_add("write", lambda *_: self._schedule())
        return self.vars[key]

    def _input(self, parent, r, c, key, label, unit="", width=10):
        """Label | widget | unit at (r, c)."""
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 16, 6), pady=2)
        if key in CHECKS:
            w = ttk.Checkbutton(parent, variable=self._var(key), text=unit)
            unit = ""
        elif key in CHOICES:
            w = ttk.Combobox(parent, textvariable=self._var(key), values=CHOICES[key], state="readonly",
                             width=width + 2)
        else:
            w = ttk.Entry(parent, textvariable=self._var(key), width=width, justify="right",
                          state="readonly" if key in LOCKED else "normal")
        w.grid(row=r, column=c + 1, sticky="w", pady=2)
        if unit:
            ttk.Label(parent, text=unit, style="Hint.TLabel").grid(row=r, column=c + 2, sticky="w", padx=(4, 0))
        self.widgets[key] = w
        return w

    def _value(self, parent, r, c, key, main=False, width=11):
        ttk.Label(parent, textvariable=self.out.setdefault(key, tk.StringVar()), width=width, anchor="e",
                  style="Calc.Key.TLabel" if main else "Calc.Value.TLabel").grid(
            row=r, column=c, sticky="ew", padx=2, pady=1)

    def _table(self, parent, row, headers, rows, label_width=16, width=11):
        """Read-only grid from `row`: headers over columns 1..n; rows = [(label, [out key | None], unit, main)].
        Returns the next free row."""
        for c, h in enumerate(headers, start=1):
            ttk.Label(parent, text=h, style="Calc.Head.TLabel", anchor="center", justify="center").grid(
                row=row, column=c, sticky="ew")
        for r, (label, keys, unit, main) in enumerate(rows, start=row + 1):
            ttk.Label(parent, text=label, width=label_width).grid(row=r, column=0, sticky="w", pady=1)
            for c, key in enumerate(keys, start=1):
                if key:
                    self._value(parent, r, c, key, main, width)
            if unit:
                ttk.Label(parent, text=unit, style="Hint.TLabel").grid(row=r, column=len(keys) + 1, sticky="w",
                                                                       padx=(4, 0))
        return row + 1 + len(rows)

    def _band_table(self, parent, key, sym, names, unit):
        """Droop band: columns Droop, Deadband, 1..5; rows unit and p.u."""
        headers = ["Droop", "Deadband"] + [f"{sym}{n}\n{names[n - 1]}" for n in range(1, 6)]
        self._table(parent, 0, headers, [
            (unit, [f"{key}.droop", f"{key}.deadband"] + [f"{key}.{n}" for n in range(1, 6)], "", False),
            ("p.u.", [f"{key}.pu.droop", f"{key}.pu.deadband"] + [f"{key}.pu.{n}" for n in range(1, 6)], "", False)],
            label_width=4, width=8)

    @staticmethod
    def _card(parent, title, r, c, **grid):
        card = ttk.LabelFrame(parent, text=title, style="Calc.Card.TLabelframe")
        card.grid(row=r, column=c, sticky="nsew", padx=5, pady=3, **grid)
        return card

    @staticmethod
    def _row(page, r):
        """A full-width row of cards on a tab page."""
        f = ttk.Frame(page)
        f.grid(row=r, column=0, sticky="ew")
        return f

    def _band_card(self, parent, title, key, sym, names, unit, inputs):
        """Droop band card: inputs (two per row) | the band table."""
        band = self._card(parent, title, 0, 0)
        left = ttk.Frame(band)
        left.grid(row=0, column=0, sticky="nw")
        for i, (k, label, u) in enumerate(inputs):
            self._input(left, i // 2, (i % 2) * 3, k, label, u, width=8)
        ttk.Separator(band, orient="vertical").grid(row=0, column=1, sticky="ns", padx=14)
        res = ttk.Frame(band)
        res.grid(row=0, column=2, sticky="nw")
        self._band_table(res, key, sym, names, unit)

    # ------------------------------------------------------------------ header (controller + plant)
    def _build_header(self):
        plant = ttk.LabelFrame(self, text="Plant", style="Calc.Card.TLabelframe")
        plant.pack(fill="x", padx=18, pady=(8, 0))
        top = ttk.Frame(plant)
        top.pack(fill="x")
        ttk.Label(top, text="Controller").pack(side="left")
        self.ctrl_var = tk.StringVar()
        self.ctrl_box = ttk.Combobox(top, textvariable=self.ctrl_var, state="readonly", width=58)
        self.ctrl_box.pack(side="left", padx=8)
        self.ctrl_box.bind("<<ComboboxSelected>>", lambda e: self._pick_controller())
        ttk.Button(top, text="↻  Load from Inspect Case", style="Small.TButton",
                   command=self.load_inspect).pack(side="left")
        self.ctrl_note = ttk.Label(plant, text="", style="Hint.TLabel")
        self.ctrl_note.pack(anchor="w", pady=(2, 4))
        vals = ttk.Frame(plant)
        vals.pack(anchor="w")
        self._input(vals, 0, 0, "mva", "MVA Base", "MVA", width=8)
        self._input(vals, 0, 3, "pmax", "P Max", "MW", width=8)
        self._input(vals, 0, 6, "pf", "P.F.", width=6)
        self._input(vals, 0, 8, "use_pf", "", "Q Max from P.F.")
        self._input(vals, 0, 10, "qmax", "Q Max", "MVAr", width=8)
        self._input(vals, 0, 13, "qmin", "Q Min", "MVAr", width=8)

    # ------------------------------------------------------------------ AVR tab
    def _build_avr(self, page):
        page.columnconfigure(0, weight=1)
        self._band_card(self._row(page, 0), "Voltage droop band", "avr", "V",
                        ("LV Bound", "LV DB", "Setpoint", "HV DB", "HV Bound"), "kV",
                        (("v_base", "V Base", "kV"), ("v_setpoint", "V3 (Setpoint)", "kV"),
                         ("v_droop_pct", "Droop", "%"), ("v_droop_base", "Droop Base", ""),
                         ("v_deadband", "Deadband", "kV")))

        mid = self._row(page, 1)
        kc = self._card(mid, "Droop gain Kc", 0, 0)
        self._table(kc, 0, ["w/ db", "w/o db"], [("Qlim", ["kc.qlim", "kc.qlim"], "MVAr", False),
                                                 ("Droop", ["kc.droop_wdb", "kc.droop_wodb"], "p.u.", False),
                                                 ("Kc", ["kc.wdb", "kc.wodb"], "", True)], label_width=6, width=9)
        se = self._card(mid, "State estimation operating points", 0, 1)
        self._table(se, 0, ["V (kV)", "Q (MVAr)", "P (MW)"],
                    [(n, [f"se.{n}.{i}" for i in range(3)], "", False) for n in ("Full Lag", "Full Lead",
                                                                                 "Max Dispatch")],
                    label_width=12, width=8)
        out = self._card(mid, "Tie-line X and Vref", 0, 2)
        self._table(out, 0, ["Step Up", "Step Down", "Average"], [
            ("Tie-line X", ["tie.up.x", "tie.down.x", "tie.avg"], "p.u.", True),
            ("Vref (ini)", ["vref.up.ini", "vref.down.ini"], "p.u.", False),
            ("Vref (REPC a/c)", ["vref.up.ac", "vref.down.ac"], "p.u.", True),
            ("Vref (REPC b/d)", ["vref.up.bd", "vref.down.bd"], "p.u.", True)], label_width=14, width=9)

        steps = self._card(self._row(page, 2), "Volt step tests", 0, 0)
        top = ttk.Frame(steps)
        top.grid(row=0, column=0, sticky="nw")
        self._input(top, 0, 0, "avr_test", "AVR Test Type")
        self.file_labels = {}
        for i, key in enumerate(FILES):
            r = 1 + 2 * i
            ttk.Label(top, text=f"{STEP_NAMES[key[4:]]} play-in").grid(row=r, column=0, sticky="w", pady=(8, 0))
            self._var(key)
            btns = ttk.Frame(top)
            btns.grid(row=r, column=1, columnspan=3, sticky="w", pady=(8, 0))
            ttk.Button(btns, text="Browse…", style="Small.TButton",
                       command=lambda k=key: self._pick_csv(k)).pack(side="left")
            ttk.Button(btns, text="✕", style="Small.TButton", width=2,
                       command=lambda k=key: self.vars[k].set("")).pack(side="left", padx=4)
            self.file_labels[key] = ttk.Label(top, text="", width=40, style="Hint.TLabel")
            self.file_labels[key].grid(row=r + 1, column=0, columnspan=4, sticky="w")
        self.step_note = ttk.Label(top, text="", style="Calc.Warn.TLabel", wraplength=300, justify="left")
        self.step_note.grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Separator(steps, orient="vertical").grid(row=0, column=1, sticky="ns", padx=14)

        t = ttk.Frame(steps)
        t.grid(row=0, column=2, sticky="nw")
        for c, s in ((1, "up"), (4, "down")):
            ttk.Label(t, text=STEP_NAMES[s], style="Section.TLabel", anchor="center").grid(
                row=0, column=c, columnspan=3, sticky="ew")
        cols = [(s, col) for s in calc.STEPS for col in ("initial", "final", "delta")]
        for c, (s, col) in enumerate(cols, start=1):
            ttk.Label(t, text={"initial": "Initial", "final": "Final", "delta": "Δ"}[col],
                      style="Calc.Head.TLabel", anchor="center").grid(row=1, column=c, sticky="ew")
        rows = (("vref_kv", "Vref (kV)"), ("vref_pu", "Vref (p.u.)"), ("vreg_kv", "Vreg (kV)"),
                ("vreg_pu", "Vreg (p.u.)"), ("qbr_mvar", "Qbr (MVAr)"), ("qbr_pu", "Qbr (p.u.)"))
        for r, (k, label) in enumerate(rows, start=2):
            ttk.Label(t, text=label, width=11).grid(row=r, column=0, sticky="w", pady=1)
            for c, (s, col) in enumerate(cols, start=1):
                if k == "vref_kv" and col != "delta":
                    key = f"vref_{s}_{col}"
                    self.widgets[key] = ttk.Entry(t, textvariable=self._var(key), width=8, justify="right")
                    self.widgets[key].grid(row=r, column=c, sticky="ew", padx=2, pady=1)
                else:
                    self._value(t, r, c, f"table.{s}.{col}.{k}", width=8)
        r = len(rows) + 2
        ttk.Label(t, text="I (p.u.)", width=11).grid(row=r, column=0, sticky="w", pady=1)
        for s, c0 in (("up", 1), ("down", 4)):
            self._value(t, r, c0, f"tie.{s}.i_ini", width=8)
            self._value(t, r, c0 + 1, f"tie.{s}.i_fin", width=8)

    # ------------------------------------------------------------------ PFR tab
    def _build_pfr(self, page):
        page.columnconfigure(0, weight=1)
        self._band_card(self._row(page, 0), "Frequency droop band", "pfr", "F",
                        ("LF Bound", "LF DB", "Setpoint", "HF DB", "HF Bound"), "Hz",
                        (("f_base", "F Base", "Hz"), ("f_setpoint", "F3 (Setpoint)", "Hz"),
                         ("f_droop_pct", "Droop", "%"), ("f_deadband", "Deadband", "Hz")))
        ddn = self._card(self._row(page, 1), "Droop gain ddn / dup", 0, 0)
        self._table(ddn, 0, ["w/ db", "w/o db"], [("Plim", ["ddn.plim", "ddn.plim"], "MW", False),
                                                  ("Droop", ["ddn.droop_wdb", "ddn.droop_wodb"], "p.u.", False),
                                                  ("ddn = dup", ["ddn.wdb", "ddn.wodb"], "", True)],
                    label_width=9, width=9)

    # ------------------------------------------------------------------ Equations tab
    def _build_equations(self, page):
        outer = ttk.Frame(page)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.eq_body = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=self.eq_body, anchor="nw")
        self.eq_body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.eq_canvas = canvas

    def _render_equations(self):
        """Typeset the Equations tab the first time it is shown (matplotlib mathtext -> PNG -> PhotoImage)."""
        if self._eq_images is not None or self.book.index("current") != 2:
            return
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
        self._eq_images = []
        prop = FontProperties(size=11)
        wheel = lambda e: self.eq_canvas.yview_scroll(int(-e.delta / 120), "units")   # noqa: E731
        for c, sections in enumerate((self.equations_left, EQUATIONS_RIGHT)):
            col = ttk.Frame(self.eq_body)
            col.grid(row=0, column=c, sticky="new", padx=6)
            self.eq_body.columnconfigure(c, weight=1)
            for title, lines in sections:
                card = ttk.LabelFrame(col, text=title, style="Calc.Card.TLabelframe")
                card.pack(fill="x", pady=6)
                body = tk.Frame(card, bg=theme.PANEL, highlightthickness=1, highlightbackground=SOFT)
                body.pack(fill="x")
                for line in lines:
                    buf = io.BytesIO()
                    mathtext.math_to_image(line, buf, prop=prop, dpi=100, format="png", color=HEAD)
                    img = tk.PhotoImage(data=buf.getvalue())
                    self._eq_images.append(img)
                    lbl = tk.Label(body, image=img, bg=theme.PANEL, anchor="w")
                    lbl.pack(fill="x", padx=10, pady=4)
                    lbl.bind("<MouseWheel>", wheel)
                for w in (card, body):
                    w.bind("<MouseWheel>", wheel)

    # ------------------------------------------------------------------ plant controller
    def load_inspect(self):
        meta = latest_inspect()
        ppc = (meta or {}).get("ppc") or {}
        self.instances = controllers(ppc)
        if not self.instances:
            self.ctrl_box.configure(values=[])
            self.ctrl_var.set("")
            self.vars["mva"].set("")
            self.ctrl_note.configure(text="The last Inspect Case has no controller MVA base. Run Inspect Case again."
                                     if ppc.get("instances") or ppc.get("name") else
                                     "Run Inspect Case on the plant's SAV and dynamics file: the MVA base is the "
                                     "plant controller's, read from it.")
            return
        case = meta["_sav"]
        names = [f"{i['name']} at bus {i['bus']}" + (f" [{i['id']}]" if i.get("id") else "") +
                 f"  ·  {i['mva']:g} MVA ({i['mva_source']})" for i in self.instances]
        self.ctrl_box.configure(values=names)
        self.ctrl_var.set(names[0])
        if ppc.get("v_base"):
            self.vars["v_base"].set(f"{ppc['v_base']:g}")
        if meta.get("f_base"):
            self.vars["f_base"].set(f"{meta['f_base']:g}")
        for key, base in (("v_setpoint", "v_base"), ("f_setpoint", "f_base")):
            if not self.vars[key].get().strip():
                self.vars[key].set(self.vars[base].get())
        self.ctrl_note.configure(text=f"From the last Inspect Case ({case})." + (
            "  The controllers have different bases: pick the one to calculate for." if len(
                {i["mva"] for i in self.instances}) > 1 else ""))
        self._pick_controller()

    def _pick_controller(self):
        i = self.ctrl_box.current()
        if 0 <= i < len(self.instances):
            self.vars["mva"].set(f"{self.instances[i]['mva']:g}")

    # ------------------------------------------------------------------ inputs
    def _pick_csv(self, key):
        path = filedialog.askopenfilename(parent=self, initialdir=settings.PLAY_IN_DIR,
                                          filetypes=[("Play-in CSV", "*.csv")])
        if path:
            self.vars[key].set(os.path.normpath(path))

    def _values(self):
        v = {}
        for key, var in self.vars.items():
            raw = var.get()
            if key in CHECKS or key in CHOICES or key in FILES:
                v[key] = raw
                continue
            try:
                v[key] = float(raw)
            except (TypeError, ValueError):
                v[key] = None
        return v

    def _steps(self, v):
        steps, notes = {}, []
        for s in calc.STEPS:
            path = v[f"csv_{s}"]
            self.file_labels[f"csv_{s}"].configure(text=os.path.basename(path) if path else "no play-in picked")
            if not path:
                continue
            key = (path, os.path.getmtime(path) if os.path.isfile(path) else None, v["v_base"], v["mva"])
            if key not in self.steps_cache:
                chk = play_in.validate(path, ("Time", "Voltage", "Reactive Power", "Real Power"))
                self.steps_cache[key] = (calc.step_conditions(chk.data, v["v_base"], v["mva"]) if chk.ok
                                         else (None, "; ".join(chk.errors)))
            cond, note = self.steps_cache[key]
            steps[s] = cond
            if note:
                notes.append(f"{STEP_NAMES[s]}: {note}")
        self.step_note.configure(text="\n".join(notes))
        return steps

    # ------------------------------------------------------------------ calculate
    def _schedule(self):
        if self._pending is None:
            self._pending = self.after_idle(self._recompute)

    def _recompute(self):
        self._pending = None
        v = self._values()
        use_pf = bool(v["use_pf"])
        for key in ("qmax", "qmin"):
            self.widgets[key].configure(state="readonly" if use_pf else "normal")
        for key in VREF_KEYS:
            self.widgets[key].configure(state="disabled" if v["avr_test"] == "Vreg" else "normal")
        r = calc.compute(v, self._steps(v))
        flat = {}

        def walk(prefix, x):
            if isinstance(x, dict):
                for k, val in x.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), val)
            elif isinstance(x, tuple):
                for k, val in enumerate(x):
                    walk(f"{prefix}.{k}", val)
            else:
                flat[prefix] = x
        walk("", r)
        for key, var in self.out.items():
            var.set(calc.sig4(flat.get(key)))
        if use_pf:   # computed Q limits shown in the input boxes too
            for key in ("qmax", "qmin"):
                text = calc.sig4(r[key])
                if self.vars[key].get() != text:
                    self.vars[key].set(text)

    # ------------------------------------------------------------------ close
    def saved_inputs(self):
        return {k: (bool(var.get()) if k in CHECKS else var.get()) for k, var in self.vars.items() if k not in LOCKED}

    def close(self):
        self.on_save(self.saved_inputs())
        self.destroy()
