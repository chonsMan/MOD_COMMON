#######################################################################################################################
# Title:   play_in.py
# Author:  Jesse Harris
# Version: v1 (shared; from MOD_PSLF 04_GUI_V3 play_in.py v3)
# Purpose: Load and validate play-in (measured) CSVs and compute initial conditions from them
# Notes:   Simulator-free (shared by the PSLF and PSS(R)E Test Runners), so the GUI can validate a file and
#          preview initial conditions as soon as it is picked.
#          Expected columns: Time [s], Voltage [kV or p.u.], Reactive Power [MVAr], Real Power [MW], Frequency [Hz]
#          Initial conditions (V0/P0/Q0) = average of the first ic_window seconds (default 3 s):
#            a. window t0 <= t < t0 + ic_window     (t0 = first time in the file, may be negative)
#            b. fewer than min_samples inside?     use the first min_samples rows instead (coarse data), and say so
#            c. V/P/Q moves past a fixed threshold inside the window?  end the window just before it
#            d. nothing left?                      error (never average across a step)
#            e. Voltage median < 2                 -> p.u., otherwise kV
#######################################################################################################################
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

ALL_COLUMNS = ("Time", "Voltage", "Reactive Power", "Real Power", "Frequency")

IC_WINDOW      = 3.0     # [s] default averaging window
IC_MIN_SAMPLES = 2       # fewest samples to average (coarse data extends the window to reach this)
V_STEP_FRAC    = 0.0025  # a V move > 0.25 % of V0 counts as the disturbance starting
PQ_STEP_FRAC   = 0.01    # a P/Q move > 1 % of the plant MVA counts as the disturbance starting
PQ_STEP_MIN    = 0.5     # [MW / MVAr] never use a P/Q threshold smaller than this
DEFAULT_MVA    = 100.0   # plant MVA used for the thresholds when it isn't known yet (GUI preview)


@dataclass
class PlayInCheck:
    path: str
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: Optional[pd.DataFrame] = None

    def summary(self):
        if not self.ok:
            return "✗ " + "; ".join(self.errors)
        if self.warnings:
            return "⚠ " + "; ".join(self.warnings)
        return "✓ columns OK"


def load(path) -> pd.DataFrame:
    return pd.read_csv(path)


def validate(path, required=("Time",)) -> PlayInCheck:
    """Check a play-in CSV has the columns a test needs, plus a few sanity checks."""
    chk = PlayInCheck(path=path)
    if not os.path.isfile(path):
        chk.ok = False
        chk.errors.append("file not found")
        return chk
    try:
        df = load(path)
    except Exception as e:
        chk.ok = False
        chk.errors.append(f"cannot read CSV: {e}")
        return chk
    chk.data = df

    missing = [c for c in required if c not in df.columns]
    if missing:
        chk.ok = False
        chk.errors.append("missing column(s): " + ", ".join(missing))
        return chk

    if len(df) < 2:
        chk.ok = False
        chk.errors.append("fewer than 2 rows")
        return chk

    if "Time" in df.columns and not df["Time"].is_monotonic_increasing:
        chk.warnings.append("Time is not increasing")
    if "Frequency" in required and "Frequency" in df.columns and (df["Frequency"] == -1).all():
        chk.ok = False
        chk.errors.append("this test needs Frequency, but it is all -1")
    if "Voltage" in df.columns and (pd.to_numeric(df["Voltage"], errors="coerce").fillna(0) == 0).all():
        chk.ok = False
        chk.errors.append("Voltage is all zero")
    if "Voltage" in df.columns and "Voltage" in required and voltage_is_pu(df):
        chk.warnings.append("Voltage is in p.u.")
    return chk


_RANGE_RE = re.compile(r"\(\s*([-\d.]+)\s*(?:kV|Hz)?[\s_]*to[\s_]*([-\d.]+)\s*(kV|Hz)?\s*\)", re.IGNORECASE)


def parse_step_from_name(path) -> Optional[Tuple[float, float, str]]:
    """'MOD026_FrefDN_(60 to 59.664 Hz).csv' -> (60.0, 59.664, 'Hz'); '(166_to_167.5)' -> (166.0, 167.5, '').
    Unit is '' if not in the name."""
    m = _RANGE_RE.search(os.path.basename(path))
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2)), (m.group(3) or "")
    except ValueError:
        return None


# ------------------------------------------------ Initial conditions --------------------------------------------------#
def voltage_is_pu(df) -> bool:
    """Voltage median < 2 means the column is in p.u.; otherwise kV."""
    v = pd.to_numeric(df["Voltage"], errors="coerce").dropna()
    return bool(len(v)) and float(v.abs().median()) < 2.0


def voltage_pu(df, v_base_kv):
    """Play-in Voltage as p.u. whatever unit the file uses (numpy array)."""
    v = df["Voltage"].to_numpy(dtype=float)
    return v if voltage_is_pu(df) else v / v_base_kv


@dataclass
class InitialConditions:
    V0: float = float("nan")               # in the file's unit (see v_unit)
    v_unit: str = "kV"                     # "kV" or "p.u."
    P0: float = float("nan")               # MW
    Q0: float = float("nan")               # MVAr
    t_start: float = 0.0                   # averaging window actually used [s, file time]
    t_end: float = 0.0
    n: int = 0                             # samples averaged
    dt: float = float("nan")               # median sample spacing [s]
    method: str = "mean"
    step_time: Optional[float] = None      # first time V/P/Q moves past its threshold (whole file)
    step_channel: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    def v0_kv(self, v_base_kv):
        return self.V0 * v_base_kv if self.v_unit == "p.u." else self.V0

    def v0_pu(self, v_base_kv):
        return self.V0 if self.v_unit == "p.u." else (self.V0 / v_base_kv if v_base_kv else float("nan"))

    def headline(self):
        return (f"V0 {self.V0:.4f} {self.v_unit}  |  P0 {self.P0:.3f} MW  |  Q0 {self.Q0:.3f} MVAr  |  "
                f"t {self.t_start:.3g}–{self.t_end:.3g} s ({self.n} samples, {self.method})")

    def summary(self):
        if not self.ok:
            return "✗ " + "; ".join(self.errors)
        extra = self.notes + ["⚠ " + w for w in self.warnings]
        return self.headline() + ("\n" + "; ".join(extra) if extra else "")

    def to_dict(self):
        return dict(self.__dict__)


def _thresholds(v_level, plant_mva):
    mva = plant_mva if plant_mva and plant_mva > 0 else DEFAULT_MVA
    pq = max(PQ_STEP_MIN, PQ_STEP_FRAC * mva)
    v = V_STEP_FRAC * abs(v_level) if v_level else float("inf")
    return {"Voltage": v, "Real Power": pq, "Reactive Power": pq}


def detect_step(df, plant_mva=None, start_samples=1):
    """First (time, column) where V, P or Q moves past its threshold from the starting level, else (None, None).

    The starting level is the first sample (a multi-sample level would already include a step that lands on the
    2nd sample of 2 s data). Thresholds are fixed in plant terms, far above measurement noise, because 1-2 s data
    gives too few samples to estimate noise statistically.
    """
    t = df["Time"].to_numpy(dtype=float)
    n0 = max(1, min(int(start_samples), len(df)))
    cols = ("Voltage", "Real Power", "Reactive Power")
    levels = {c: float(np.median(df[c].to_numpy(dtype=float)[:n0])) for c in cols}
    thr = _thresholds(levels["Voltage"], plant_mva)
    best = (None, None)
    for c in cols:
        x = df[c].to_numpy(dtype=float)
        hit = np.nonzero(np.abs(x - levels[c]) > thr[c])[0]
        if len(hit) and (best[0] is None or t[hit[0]] < best[0]):
            best = (float(t[hit[0]]), c)
    return best


# Step time of a step test (fills t_step in the form). Measured steps are rarely clean: a voltage can jump in one sample,
# a plant's P ramps (or settles exponentially) after an Fref step, 1 s data drawn as straight lines shows the step as a
# knee, the signal may drift before it, and high-rate data is noisy. So, per signal:
#   1. the main move = where the smoothed signal first gets STEP_CROSS of its largest excursion from the start level;
#   2. walk back from there while the backward slope is still more than STEP_KNEE of the main move's slope. The slope
#      window grows with the noise so noise can't stop the walk early;
#   3. when the window had to grow, refine with a local least-squares break fit (line, then a jump and a slope change);
#   4. a move whose slope is not clearly steeper than the signal before it (STEP_DRIFT) is drift, not a step.
# The step time returned is the LAST SAMPLE STILL AT THE OLD LEVEL (where the plotted measured line starts to move). On
# coarse data the step happened somewhere between that sample and the next, and recorders stamp the new value at the
# end of the interval: a 1 s play-in showing 225 kV at 5 s and 228 kV at 6 s was a step at 5 s. On fine data the
# difference is one sample.
STEP_SMOOTH = 0.1      # [s] rolling-median width
STEP_BASE = 1.0        # [s] start level = median of the first STEP_BASE seconds (at least 2 samples)
STEP_CROSS = 0.2       # the main move: first time the signal is this fraction of its largest excursion away
STEP_SLOPE_W = 0.125   # [s] shortest backward slope window (at least 1 sample)
STEP_KNEE = 0.2        # the step starts where the slope drops below this fraction of the main move's slope
STEP_DRIFT = 3.0       # the main move must be this many times steeper than the trend before it
STEP_MIN = {"Voltage": 0.002, "Frequency": 0.0005}   # smallest step that counts, as a fraction of the level ...
STEP_MIN_MW = 1.0      # ... and for Real / Reactive Power, in MW / MVAr


def _slopes(t, xs, h):
    back = np.clip(np.arange(len(t)) - h, 0, None)
    return (xs - xs[back]) / np.maximum(t - t[back], 1e-9)


def _break_fit(t, x):
    """Sample time tk that best fits x ~ a + b t + c [t >= tk] + d max(0, t - tk) (least squares)."""
    best_sse, best_tk = np.inf, None
    for k in range(1, len(t) - 1):
        a = np.column_stack([np.ones_like(t), t - t[0], (t >= t[k]).astype(float), np.maximum(0.0, t - t[k])])
        coef, *_ = np.linalg.lstsq(a, x, rcond=None)
        sse = float(np.sum((a @ coef - x) ** 2))
        if sse < best_sse:
            best_sse, best_tk = sse, float(t[k])
    return best_tk


def find_step_time(df, signals):
    """(time, signal) where the measured step starts (the last sample before it moves), from the first of `signals`
    (play-in column names) that has a clear step, or (None, None). Frequency columns of -1 (no data) are skipped."""
    for col in signals:
        if col not in df.columns or "Time" not in df.columns:
            continue
        t = pd.to_numeric(df["Time"], errors="coerce").to_numpy(dtype=float)
        x = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        ok = ~(np.isnan(t) | np.isnan(x)) & ((x > 0) if col == "Frequency" else True)
        order = np.argsort(t[ok], kind="stable")
        t, x = t[ok][order], x[ok][order]
        if len(t) < 4:
            continue
        dt = float(np.median(np.diff(t)))
        if not dt > 0:
            continue
        n_smooth = max(1, int(round(STEP_SMOOTH / dt)))
        xs = pd.Series(x).rolling(n_smooth, center=True, min_periods=1).median().to_numpy()
        base = t < t[0] + STEP_BASE
        if base.sum() < 2:
            base = np.arange(len(t)) < 2
        level = float(np.median(x[base]))
        noise = 1.4826 * float(np.median(np.abs(x[base] - level)))
        dev = np.abs(xs - level)
        peak = float(dev.max())
        smallest = max(STEP_MIN[col] * abs(level) if col in STEP_MIN else STEP_MIN_MW, 15.0 * noise)
        if peak < smallest:
            continue                                       # nothing on this signal that stands out as a step

        i_move = int(np.argmax(dev >= STEP_CROSS * peak))
        h = max(1, int(round(STEP_SLOPE_W / dt)))
        ref = _slopes(t, xs, h)[i_move]
        # Window long enough that noise moves the slope by well under STEP_KNEE of the main slope
        h_noise = int(np.ceil(4.0 * noise / (STEP_KNEE * abs(ref) * dt))) if ref else h
        h = min(max(h, h_noise), max(1, len(t) // 4))
        slope = _slopes(t, xs, h)
        ref = slope[i_move]
        i = i_move
        while i > 0 and slope[i - 1] * np.sign(ref) > STEP_KNEE * abs(ref):
            i -= 1

        if t[i] < t[0] + STEP_BASE:
            continue                                       # moving from the start: no steady level before a step
        pre = t < t[i]                                     # the trend before the step must be much flatter
        if abs(ref) < STEP_DRIFT * abs(np.polyfit(t[pre], x[pre], 1)[0]):
            continue                                       # only drift
        if h * dt > 2 * STEP_SLOPE_W:                      # long (noisy) window: the walk stops late; refine
            near = np.nonzero((t >= t[i] - 2 * h * dt) & (t <= t[i] + h * dt))[0]
            if len(near) >= 6:
                tk = _break_fit(t[near], x[near])
                if tk is not None:
                    i = int(np.searchsorted(t, tk))
        return float(t[max(i - 1, 0)]), col               # i is the first moving sample
    return None, None


def compute_initial_conditions(df, window=IC_WINDOW, min_samples=IC_MIN_SAMPLES, method="mean",
                               plant_mva=None) -> InitialConditions:
    """V0/P0/Q0 from the start of a play-in, following rules a-e at the top of this file."""
    ic = InitialConditions(method="median" if str(method).lower() == "median" else "mean")
    missing = [c for c in ("Time", "Voltage", "Real Power", "Reactive Power") if c not in df.columns]
    if missing:
        ic.errors.append("missing column(s): " + ", ".join(missing))
        return ic
    df = df.sort_values("Time").reset_index(drop=True)
    t = df["Time"].to_numpy(dtype=float)
    if len(t) == 0:
        ic.errors.append("no rows")
        return ic
    ic.dt = float(np.median(np.diff(t))) if len(t) > 1 else float("nan")
    ic.v_unit = "p.u." if voltage_is_pu(df) else "kV"
    min_samples = max(1, int(min_samples))
    ic.step_time, ic.step_channel = detect_step(df, plant_mva)

    # a. time window
    idx = np.nonzero(t < t[0] + float(window))[0]
    # b. coarse data
    if len(idx) < min_samples:
        idx = np.arange(min(min_samples, len(t)))
        ic.notes.append(f"{ic.dt:g} s data: window extended to the first {len(idx)} samples")
    # c. disturbance inside the window
    if ic.step_time is not None and ic.step_time <= t[idx[-1]]:
        idx = idx[t[idx] < ic.step_time]
        ic.notes.append(f"window cut at {ic.step_time:.3g} s ({ic.step_channel} moved)")
    # d. nothing left
    if len(idx) == 0:
        ic.errors.append(f"{ic.step_channel} moves at the first sample; set the IC window by hand")
        return ic
    if len(idx) < min_samples:
        ic.warnings.append(f"only {len(idx)} sample(s) before {ic.step_channel} moves")

    agg = np.median if ic.method == "median" else np.mean
    ic.V0 = float(agg(df["Voltage"].to_numpy(dtype=float)[idx]))
    ic.P0 = float(agg(df["Real Power"].to_numpy(dtype=float)[idx]))
    ic.Q0 = float(agg(df["Reactive Power"].to_numpy(dtype=float)[idx]))
    ic.t_start, ic.t_end, ic.n = float(t[idx[0]]), float(t[idx[-1]]), int(len(idx))

    # Checks that don't need the case (the worker adds the p.u.-range and plant-MVA checks)
    if not np.isfinite(ic.V0) or ic.V0 <= 0:
        ic.errors.append(f"V0 = {ic.V0:g}: Voltage is zero/empty at the start")
    for c in ("Voltage", "Real Power", "Reactive Power"):
        if np.all(df[c].to_numpy(dtype=float) == -1):
            ic.errors.append(f"{c} is a -1 placeholder")
    return ic
