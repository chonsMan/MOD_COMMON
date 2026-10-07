#######################################################################################################################
# Title:   plot_panel.py
# Author:  Jesse Harris
# Version: v1 (shared; from MOD_PSLF 04_GUI_V3 plot_panel.py v3)
# Purpose: Embedded matplotlib canvas (FigureCanvasTkAgg) with mouse cursor / zoom (gui/plot_interact.py)
#######################################################################################################################
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from gui import theme
from gui.plot_interact import PlotInteractor


class PlotPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.box = theme.boxed(self)
        self.box.pack(fill="both", expand=True)
        self.canvas = None
        self.interactor = None
        self.placeholder = tk.Label(self.box, text="📈\n\nRun a test, or pick a run and press Show / Units / Channels.",
                                    bg=theme.PANEL, fg=theme.MUTED, font=("Segoe UI", 12), justify="center")
        self.placeholder.pack(fill="both", expand=True)

    def show(self, fig):
        self.clear()
        self.placeholder.pack_forget()
        self.canvas = FigureCanvasTkAgg(fig, master=self.box)
        self.interactor = PlotInteractor(self.canvas, fig)
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.canvas.draw()

    def clear(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
            self.interactor = None
        self.placeholder.pack(fill="both", expand=True)
