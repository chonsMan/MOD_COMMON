#######################################################################################################################
# Title:   plots.py
# Author:  Jesse Harris
# Version: v1 (shared; from MOD_PSLF 04_GUI_V3 plots.py v3, from pslf_plots_v2.py)
# Purpose: Build matplotlib Figures for each test (embedded in the GUI and saved to run folders)
# Notes:   Uses matplotlib.figure.Figure directly (no pyplot, no plt.show), so it works inside Tkinter and in the
#          headless worker. Model data is the results DataFrame: time, poc_v/p/q/f, <unit>_v/p/q/f.
#          Shared by the PSLF and PSS(R)E Test Runners (MOD_COMMON); keep it simulator-free.
#######################################################################################################################
import numpy as np
from matplotlib.figure import Figure

# seaborn 'deep' palette (as in V2) without the seaborn dependency
COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
          "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"]


def _a(series):
    """numpy array (always pass arrays to ax.plot, never pandas Series)."""
    return np.asarray(series, dtype=float)


def _style(report):
    """V2 sizes: report (sav_flag=1) is 16:9 with large fonts; screen is 12x6."""
    if report:
        return dict(figsize=(16, 9), legend=16, font=14, font4=11, line=3.0)
    return dict(figsize=(12, 6), legend=9, font=11, font4=9, line=2.0)     # font4: y labels on 4-panel plots


def _new_fig(report, title=None):
    """New figure. Plots carry no title (user preference); `title` is accepted but not drawn."""
    s = _style(report)
    fig = Figure(figsize=s["figsize"], tight_layout=True)
    return fig, s


def _finish(ax, s, ylabel, t_max, xlabel=True, legend=True, ylabel_size=None):
    ax.set_ylabel(ylabel, fontsize=ylabel_size or s["font"])
    if xlabel:
        ax.set_xlabel("Time [s]", fontsize=s["font"])
    if legend:
        ax.legend(prop={"size": s["legend"]})
    ax.ticklabel_format(axis="y", useOffset=False)
    ax.grid(linestyle="--", color="grey", linewidth=0.5)
    ax.set_xlim(0, t_max)


def _pad_ylim(ax, y, min_span):
    """Centre the data with at least min_span of range, so a flat trace doesn't fill the axis with noise."""
    if np.isnan(y).all():
        return
    lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
    span = max(hi - lo, min_span)
    mid = (hi + lo) / 2
    ax.set_ylim(mid - 0.6 * span, mid + 0.6 * span)


def plot_flat_run(df, play=None, v_base=None, report=False, title=None, ctx=None):
    fig, s = _new_fig(report, title)
    t_max = _a(df["time"]).max()
    rows = [("poc_v", "Voltage [p.u.]", COLORS[2], 0.02),
            ("poc_q", "Reactive Power [MVAr]", COLORS[3], 10.0),
            ("poc_p", "Active Power [MW]", COLORS[4], 10.0),
            ("poc_f", "Frequency [Hz]", COLORS[5], 0.1)]
    for n, (col, label, color, span) in enumerate(rows, start=1):
        ax = fig.add_subplot(4, 1, n)
        ax.plot(_a(df["time"]), _a(df[col]), linewidth=s["line"] / 2, color=color, label=label)
        _finish(ax, s, label, t_max, xlabel=(n == 4), ylabel_size=s["font4"])
        _pad_ylim(ax, _a(df[col]), span)
    return fig


# ---------------------------------------------- Play-in context -------------------------------------------------------#
# ctx (from meta.json "plot_ctx"): {"shift": s, ...}
#   shift      measured time is shifted by this so the measured step lines up with t_step
def _play_time(play, ctx):
    return _a(play["Time"]) + float((ctx or {}).get("shift", 0.0))


def _play_voltage_pu(play, v_base):
    v = _a(play["Voltage"])
    return v if np.nanmedian(np.abs(v)) < 2.0 else v / v_base   # p.u. files are plotted as-is


def plot_mod026_vref(df, play, v_base, report=False, title=None, ctx=None):
    fig, s = _new_fig(report, title)
    t_max = _a(df["time"]).max() - 1

    ax = fig.add_subplot(2, 1, 1)
    ax.plot(_a(df["time"]), _a(df["poc_v"]), linewidth=s["line"], color=COLORS[2], label="Voltage (model)")
    if play is not None:
        ax.plot(_play_time(play, ctx), _play_voltage_pu(play, v_base), linewidth=s["line"], color=COLORS[1],
                label="Voltage (measured)")
    _finish(ax, s, "POI Voltage [p.u.]", t_max)

    ax = fig.add_subplot(2, 1, 2)
    ax.plot(_a(df["time"]), _a(df["poc_q"]), linewidth=s["line"], color=COLORS[3], label="Reactive Power (model)")
    if play is not None:
        ax.plot(_play_time(play, ctx), _a(play["Reactive Power"]), linewidth=s["line"], color=COLORS[4],
                label="Reactive Power (measured)")
    _finish(ax, s, "POI Reactive Power [MVAr]", t_max)
    return fig


def _single(df, play, report, title, col, play_col, name, ylabel, ctx):
    fig, s = _new_fig(report, title)
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(_a(df["time"]), _a(df[col]), linewidth=s["line"], color=COLORS[2], label=f"{name} (model)")
    if play is not None:
        ax.plot(_play_time(play, ctx), _a(play[play_col]), linewidth=s["line"], color=COLORS[1],
                label=f"{name} (measured)")
    _finish(ax, s, ylabel, _a(df["time"]).max() - 1)
    return fig


def plot_mod026_vreg(df, play, v_base=None, report=False, title=None, ctx=None):
    return _single(df, play, report, title, "poc_q", "Reactive Power", "Reactive Power", "POC Reactive Power [MVAr]",
                   ctx)


def plot_mod027_fref(df, play, v_base=None, report=False, title=None, ctx=None):
    return _single(df, play, report, title, "poc_p", "Real Power", "Real Power", "POI Active Power [MW]", ctx)


def plot_mod027_freg(df, play, v_base=None, report=False, title=None, ctx=None):
    return _single(df, play, report, title, "poc_p", "Real Power", "Real Power", "POC Active Power [MW]", ctx)


UNIT_PLOTS = {"fault_3ph"}      # tests whose main plot is every unit + POC (PSLF only so far)

PLOTS = {
    "flat_run":    plot_flat_run,
    "mod026_vref": plot_mod026_vref,
    "mod026_vreg": plot_mod026_vreg,
    "mod027_fref": plot_mod027_fref,
    "mod027_freg": plot_mod027_freg,
}


def build_figure(plot_key, df, play=None, v_base=None, report=False, title=None, ctx=None, units=None):
    if plot_key in UNIT_PLOTS:
        return plot_units(df, units or [], report=report, title=title, ctx=ctx)
    return PLOTS[plot_key](df, play, v_base=v_base, report=report, title=title, ctx=ctx)


OVERLAY_CHANNELS = {"poc_v": "POC Voltage [p.u.]", "poc_q": "POC Reactive Power [MVAr]",
                    "poc_p": "POC Active Power [MW]", "poc_f": "POC Frequency [Hz]"}


def plot_overlay(runs, channels=("poc_v", "poc_q", "poc_p"), report=False, title="Overlay"):
    """runs = [(label, results_df), ...]. One subplot per channel, one line per run."""
    fig, s = _new_fig(report, title)
    t_max = max(_a(df["time"]).max() for _, df in runs)
    for n, col in enumerate(channels, start=1):
        ax = fig.add_subplot(len(channels), 1, n)
        for k, (label, df) in enumerate(runs):
            ax.plot(_a(df["time"]), _a(df[col]), linewidth=s["line"] / 2, color=COLORS[k % len(COLORS)], label=label)
        _finish(ax, s, OVERLAY_CHANNELS[col], t_max, xlabel=(n == len(channels)))
    return fig


UNIT_ROWS = (("v", "Voltage [p.u.]"), ("p", "Active Power [MW]"), ("q", "Reactive Power [MVAr]"),
             ("f", "Frequency [Hz]"))


def plot_units(df, units, report=False, title="Units", ctx=None):
    """V/P/Q/F: one line per online unit (slack dotted) plus the POC (black dashed). Missing channels are skipped.

    ctx {"fault": [t_on, t_off]} marks the fault with thin grey vertical lines.
    """
    fault = (ctx or {}).get("fault")
    fig, s = _new_fig(report, title)
    t = _a(df["time"])
    for n, (q, label) in enumerate(UNIT_ROWS, start=1):
        ax = fig.add_subplot(len(UNIT_ROWS), 1, n)
        for k, u in enumerate(units):
            col = f"{u['key']}_{q}"
            if col in df and not df[col].isna().all():
                name = f"{u['name'] or u['bus']} [{u['id']}]" + (" slack" if u.get("slack") else "")
                ax.plot(t, _a(df[col]), linewidth=s["line"] / 2, color=COLORS[k % len(COLORS)],
                        linestyle=":" if u.get("slack") else "-", label=name)
        col = f"poc_{q}"
        if col in df and not df[col].isna().all():
            ax.plot(t, _a(df[col]), linewidth=s["line"] / 2, color="black", linestyle="--", label="POC")
        for tf in fault or ():
            ax.axvline(tf, color="#888888", linewidth=0.8, linestyle="-.")
        _finish(ax, s, label, t.max(), xlabel=(n == len(UNIT_ROWS)), legend=False, ylabel_size=s["font4"])
        if n == 1:
            ax.legend(prop={"size": s["legend"]}, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    return fig


CHANNEL_MODES = ("Group by type", "One axis", "One axis per channel")


def plot_channels(series, mode=CHANNEL_MODES[0], report=False, title="Channels"):
    """series = [(label, time, values, group), ...]; each series carries its own time vector.

    Group by type:        one subplot per group (e.g. all 'pg' together, all voltages together)
    One axis:             everything on one subplot
    One axis per channel: one subplot per series
    """
    fig, s = _new_fig(report, title)
    t_max = max(_a(t).max() for _, t, _, _ in series)
    if mode == CHANNEL_MODES[1]:
        panels = [("", series)]
    elif mode == CHANNEL_MODES[2]:
        panels = [(item[0], [item]) for item in series]
    else:
        panels = []
        for item in series:
            for g, members in panels:
                if g == item[3]:
                    members.append(item)
                    break
            else:
                panels.append((item[3], [item]))

    for n, (ylabel, members) in enumerate(panels, start=1):
        ax = fig.add_subplot(len(panels), 1, n)
        for k, (label, t, values, _) in enumerate(members):
            ax.plot(_a(t), _a(values), linewidth=s["line"] / 2, color=COLORS[k % len(COLORS)], label=label)
        _finish(ax, s, ylabel if mode != CHANNEL_MODES[2] else "", t_max, xlabel=(n == len(panels)), legend=False)
        ax.legend(prop={"size": s["legend"]}, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    return fig
