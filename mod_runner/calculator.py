#######################################################################################################################
# Title:   calculator.py
# Author:  Jesse Harris
# Version: v1 (shared; from MOD_PSSE 04_GUI_V1 engine/calculator.py)
# Purpose: The Calculator window's math: droop bands, plant Q limits, Kc, ddn/dup, step-test conditions, tie-line X,
#          Vref and the state estimation operating points. Formulas from the IBR Test Tool's MOD tab
#          (MOD_PSSE\06_MARKDOWN\completed\Calculator.md).
# Notes:   Simulator-free, no tkinter. compute() takes the window's inputs and returns every variable and output; a value
#          that can't be worked out yet (missing input, division by zero) is None.
#          Every MVA base is the plant controller's (each app's PpcInfo.mva).
#          Step tests: Initial = mean of the first IC_WINDOW seconds (play_in.compute_initial_conditions), Final = mean
#          of the last IC_WINDOW seconds. Their p.u. values divide by V Base whatever the Droop Base (as IBR does).
#######################################################################################################################
import math

import numpy as np

from mod_runner.play_in import IC_MIN_SAMPLES, IC_WINDOW, compute_initial_conditions

AVR_TEST_TYPES = ("Vref", "Vreg", "Feed Forward")
STEPS = ("up", "down")


def _ok(*xs):
    return all(x is not None and math.isfinite(x) for x in xs)


def _div(a, b):
    return a / b if _ok(a, b) and b else None


def band(droop_pct, setpoint_base, base, deadband, setpoint):
    """Droop band around the setpoint (voltage in kV or frequency in Hz). The droop % and every p.u. value are on the
    setpoint when setpoint_base, otherwise on base."""
    ref = setpoint if setpoint_base else base
    droop = droop_pct / 100.0 * ref if _ok(droop_pct, ref) else None
    pts = {1: (setpoint, -1, droop), 2: (setpoint, -1, deadband), 4: (setpoint, 1, deadband), 5: (setpoint, 1, droop)}
    out = {"ref": ref, "droop": droop, "deadband": deadband, "setpoint": setpoint, "base": base, 3: setpoint}
    for n, (s, sign, d) in pts.items():
        out[n] = s + sign * d if _ok(s, d) else None
    out["pu"] = {k: _div(out[k], ref) for k in ("base", "deadband", "droop", 1, 2, 3, 4, 5)}
    return out


def final_values(df, window=IC_WINDOW, min_samples=IC_MIN_SAMPLES):
    """(V, Q) = mean of the last `window` seconds of a play-in (at least min_samples rows), in the file's units."""
    df = df.sort_values("Time")
    t = df["Time"].to_numpy(dtype=float)
    idx = np.nonzero(t > t[-1] - float(window))[0]
    if len(idx) < min_samples:
        idx = np.arange(max(0, len(t) - min_samples), len(t))
    return (float(df["Voltage"].to_numpy(dtype=float)[idx].mean()),
            float(df["Reactive Power"].to_numpy(dtype=float)[idx].mean()))


def step_conditions(df, v_base, mva):
    """Initial / final Vreg (kV) and Qbr (MVAr) of a volt-step play-in. Returns ({"initial": (V, Q), "final": ...},
    notes) or (None, error text)."""
    ic = compute_initial_conditions(df, plant_mva=mva)
    if not ic.ok:
        return None, "; ".join(ic.errors)
    v_f, q_f = final_values(df)
    to_kv = (lambda v: v * v_base if _ok(v_base) else None) if ic.v_unit == "p.u." else (lambda v: v)
    return {"initial": (to_kv(ic.V0), ic.Q0), "final": (to_kv(v_f), q_f)}, "; ".join(ic.notes + ic.warnings)


def compute(v, steps=None):
    """v: the window's inputs (floats or None, see calculator window). steps: {"up"/"down": step_conditions result}.
    Returns {"avr", "pfr", "qmax", "qmin", "kc", "ddn", "table", "tie", "vref", "se"}."""
    mva = v.get("mva")
    avr = band(v.get("v_droop_pct"), v.get("v_droop_base") == "Setpoint", v.get("v_base"), v.get("v_deadband"),
               v.get("v_setpoint"))
    pfr = band(v.get("f_droop_pct"), False, v.get("f_base"), v.get("f_deadband"), v.get("f_setpoint"))

    pmax, pf = v.get("pmax"), v.get("pf")
    if v.get("use_pf"):
        qmax = pmax / pf * math.sqrt(1 - pf ** 2) if _ok(pmax, pf) and 0 < pf <= 1 else None
        qmin = -qmax if qmax is not None else None
    else:
        qmax, qmin = v.get("qmax"), v.get("qmin")

    def gains(droop, db, fn):
        wodb = droop - db if _ok(droop, db) else None
        return {"droop_wdb": droop, "droop_wodb": wodb, "wdb": fn(droop), "wodb": fn(wodb)}

    # Kc = Droop * MVA / |Qlim|;  ddn = dup = (1 / Droop) * (Plim / MVA)
    kc = gains(avr["pu"]["droop"], avr["pu"]["deadband"],
               lambda d: d * mva / abs(qmax) if _ok(d, mva, qmax) and qmax else None) | {"qlim": qmax}
    ddn = gains(pfr["pu"]["droop"], pfr["pu"]["deadband"],
                lambda d: _div(1.0, d) * pmax / mva if _ok(d, pmax, mva) and d and mva else None) | {"plim": pmax}

    # Step tests: rows vref_kv / vreg_kv / qbr_mvar and their p.u., columns initial / final / delta
    table, tie, vref = {}, {}, {}
    vbase = v.get("v_base")
    for s in STEPS:
        cond = (steps or {}).get(s)
        rows = {}
        for col in ("initial", "final"):
            vreg, qbr = cond[col] if cond else (None, None)
            vr = v.get("v_setpoint") if v.get("avr_test") == "Vreg" else v.get(f"vref_{s}_{col}")
            rows[col] = {"vref_kv": vr, "vreg_kv": vreg, "qbr_mvar": qbr,
                         "vref_pu": _div(vr, vbase), "vreg_pu": _div(vreg, vbase), "qbr_pu": _div(qbr, mva)}
        rows["delta"] = {k: abs(rows["final"][k] - rows["initial"][k]) if _ok(rows["final"][k], rows["initial"][k])
                         else None for k in rows["initial"]}
        table[s] = rows

        # Tie-line: I = Q / V (p.u.), X = |dV / dI|
        i_i = _div(rows["initial"]["qbr_pu"], rows["initial"]["vreg_pu"])
        i_f = _div(rows["final"]["qbr_pu"], rows["final"]["vreg_pu"])
        dv = rows["final"]["vreg_pu"] - rows["initial"]["vreg_pu"] if _ok(rows["final"]["vreg_pu"],
                                                                          rows["initial"]["vreg_pu"]) else None
        x = abs(dv / (i_f - i_i)) if _ok(dv, i_i, i_f) and i_f != i_i else None
        tie[s] = {"i_ini": i_i, "i_fin": i_f, "x": x}

        # Vref = Vreg + Kc * Q (p.u.); only for a Vref test. Plus, not IBR's minus: the controller's droop path
        # compares Vref with Vt + Kc * Qbranch (REPCA1 / PLNTB1 / HPLNTDU block diagrams)
        def vr(col, k):
            r = rows[col]
            return r["vreg_pu"] + k * r["qbr_pu"] if v.get("avr_test") == "Vref" and _ok(r["vreg_pu"], r["qbr_pu"], k) \
                else None
        vref[s] = {"ini": vr("initial", kc["wdb"]), "ac": vr("final", kc["wdb"]), "bd": vr("final", kc["wodb"])}
    xs = [tie[s]["x"] for s in STEPS if tie[s]["x"] is not None]
    tie["avg"] = sum(xs) / len(xs) if xs else None

    se = {"Full Lag": (avr[1], qmax, pmax), "Full Lead": (avr[5], qmin, pmax),
          "Max Dispatch": (avr["setpoint"], 0.0, pmax)}
    return {"avr": avr, "pfr": pfr, "qmax": qmax, "qmin": qmin, "kc": kc, "ddn": ddn, "table": table, "tie": tie,
            "vref": vref, "se": se}


def sig4(x):
    """4 significant figures ('' for None), as the IBR Test Tool shows them."""
    if x is None or not math.isfinite(x):
        return ""
    if x == 0:
        return "0"
    d = min(max(3 - math.floor(math.log10(abs(x))), 0), 10)
    return f"{x:.{d}f}"
