#######################################################################################################################
# Title:   playback.py
# Author:  Jesse Harris
# Version: v1 (shared)
# Purpose: Grid playback profiles for the Vreg / Freg Step tests: read one from Excel or build a single step
# Notes:   Simulator-free (shared by the PSLF and PSS(R)E Test Runners). Each app writes the profile in its own format
#          (PSLF gencls "plyfil" .txt, PSS(R)E PLBVF1 .plb). Plan: MOD_PSLF\06_MARKDOWN\completed\Grid_Playback_Plan.md.
#          A profile is a list of (time [s], value) points; signal "v" = voltage, "f" = frequency.
#          Excel layout: first sheet, header row, columns Time and Voltage (or Frequency).
#            Voltage:   median < 2 -> p.u., otherwise kV
#            Frequency: median > 2 -> Hz,   otherwise p.u.
#######################################################################################################################
import numpy as np
import pandas as pd

COLUMN = {"v": "Voltage", "f": "Frequency"}
STEP_EDGE = 0.001    # [s] the value before the step is held until t_step - STEP_EDGE


def profile_unit(values, signal):
    """Unit of a profile's values, from their median (same rule as play_in.voltage_is_pu)."""
    m = float(np.nanmedian(np.abs(values)))
    if signal == "v":
        return "p.u." if m < 2.0 else "kV"
    return "Hz" if m > 2.0 else "p.u."


def read_excel(path, signal):
    """(rows, unit, notes) from the first sheet of an Excel profile. Raises ValueError on anything unusable.

    Times are shifted to start at 0 (both simulators need that); notes say when that happened.
    """
    col = COLUMN[signal]
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception as e:
        raise ValueError(f"cannot read {path}: {e}") from None
    names = {str(c).strip().lower(): c for c in df.columns}
    missing = [c for c in ("Time", col) if c.lower() not in names]
    if missing:
        raise ValueError("missing column(s): " + ", ".join(missing) + f" (found: {', '.join(map(str, df.columns))})")
    t = pd.to_numeric(df[names["time"]], errors="coerce").to_numpy(dtype=float)
    x = pd.to_numeric(df[names[col.lower()]], errors="coerce").to_numpy(dtype=float)
    keep = ~(np.isnan(t) | np.isnan(x))
    t, x = t[keep], x[keep]
    if len(t) < 2:
        raise ValueError(f"fewer than 2 numeric rows of Time and {col}")
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time must increase on every row")

    notes = []
    if t[0] != 0.0:
        notes.append(f"times shifted by {-t[0]:+g} s so the profile starts at 0")
        t = t - t[0]
    return [(float(a), float(b)) for a, b in zip(t, x)], profile_unit(x, signal), notes


def hold_to(rows, t_end):
    """Extend a profile with its last value out to t_end (playback past the last sample is undefined)."""
    if rows[-1][0] < t_end:
        return rows + [(float(t_end), rows[-1][1])]
    return rows


def step_rows(initial, final, t_step, t_end, edge=STEP_EDGE):
    """(time, value) points of a single step: flat at `initial`, then `final` from t_step to t_end."""
    return [(0.0, initial), (t_step - edge, initial), (t_step, final), (t_end, final)]
