#!/usr/bin/env python3
"""
SDR Contest Frequency Helper
Finds active ham radio frequencies from DX cluster websites and SDR scanning,
then tracks contacts made during a contest.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import requests
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import numpy as np

try:
    from rtlsdr import RtlSdr
    SDR_AVAILABLE = True
except ImportError:
    SDR_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class ContactStatus(Enum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONTACTED = "contacted"
    NOT_CONTACTED = "not_contacted"


# Band frequency ranges in MHz
BAND_RANGES = {
    "160m": (1.800, 2.000),
    "80m":  (3.500, 4.000),
    "60m":  (5.330, 5.410),
    "40m":  (7.000, 7.300),
    "30m":  (10.100, 10.150),
    "20m":  (14.000, 14.350),
    "17m":  (18.068, 18.168),
    "15m":  (21.000, 21.450),
    "12m":  (24.890, 24.990),
    "10m":  (28.000, 29.700),
    "6m":   (50.000, 54.000),
    "2m":   (144.000, 148.000),
}


@dataclass
class FrequencyEntry:
    frequency: float        # MHz
    callsign: str = ""
    mode: str = ""
    spotter: str = ""
    comment: str = ""
    source: str = "website"  # "website" or "scan"
    status: ContactStatus = ContactStatus.UNKNOWN

    @property
    def freq_str(self) -> str:
        return f"{self.frequency:9.3f}"

    def band(self) -> str:
        for name, (lo, hi) in BAND_RANGES.items():
            if lo <= self.frequency <= hi:
                return name
        return "?"


class DXSpotter:
    """Fetches DX spots from online cluster sources."""

    def fetch_dxsummit(self) -> List[FrequencyEntry]:
        entries = []
        try:
            resp = requests.get(
                "https://www.dxsummit.fi/api/v1/spots?limit=200",
                timeout=10,
                headers={"User-Agent": "SDR-Contest-Helper/1.0 (+ham radio)"},
            )
            if resp.status_code == 200:
                for spot in resp.json():
                    try:
                        freq_khz = float(spot.get("frequency", 0))
                        if freq_khz <= 0:
                            continue
                        entries.append(FrequencyEntry(
                            frequency=round(freq_khz / 1000.0, 3),
                            callsign=spot.get("dx_call", "").strip(),
                            mode=spot.get("mode", "").strip().upper(),
                            spotter=spot.get("de_call", "").strip(),
                            comment=spot.get("comment", "").strip(),
                            source="DX Summit",
                        ))
                    except (ValueError, TypeError):
                        continue
        except Exception as exc:
            print(f"DX Summit error: {exc}")
        return entries

    def fetch_dxwatch(self) -> List[FrequencyEntry]:
        """DXWatch JSON feed."""
        entries = []
        try:
            resp = requests.get(
                "https://dxwatch.com/dxsd1/s.php?s=0&r=50",
                timeout=10,
                headers={"User-Agent": "SDR-Contest-Helper/1.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                spots = data.get("s", {})
                for key in spots:
                    spot = spots[key]
                    try:
                        freq_mhz = float(spot.get("f", 0)) / 1000.0
                        if freq_mhz <= 0:
                            continue
                        entries.append(FrequencyEntry(
                            frequency=round(freq_mhz, 3),
                            callsign=spot.get("dx", "").strip(),
                            mode=spot.get("m", "").strip().upper(),
                            spotter=spot.get("de", "").strip(),
                            comment=spot.get("i", "").strip(),
                            source="DXWatch",
                        ))
                    except (ValueError, TypeError):
                        continue
        except Exception as exc:
            print(f"DXWatch error: {exc}")
        return entries

    def fetch_all(self) -> List[FrequencyEntry]:
        all_entries = self.fetch_dxsummit() + self.fetch_dxwatch()
        # Deduplicate within 1 kHz
        seen: set = set()
        unique: List[FrequencyEntry] = []
        for e in sorted(all_entries, key=lambda x: x.frequency):
            bucket = round(e.frequency * 1000)
            if bucket not in seen:
                seen.add(bucket)
                unique.append(e)
        return unique


class SDRController:
    """Wraps RTL-SDR (or simulates one for demo)."""

    SAMPLE_RATE = 2.4e6
    FFT_SIZE = 2048

    def __init__(self):
        self.sdr = None
        self.current_freq: float = 14.200  # MHz
        self._lock = threading.Lock()

    # -- connection ----------------------------------------------------------

    def connect(self) -> bool:
        if not SDR_AVAILABLE:
            return False
        try:
            self.sdr = RtlSdr()
            self.sdr.sample_rate = self.SAMPLE_RATE
            self.sdr.center_freq = self.current_freq * 1e6
            self.sdr.gain = "auto"
            return True
        except Exception as exc:
            print(f"SDR connect: {exc}")
            return False

    def disconnect(self):
        if self.sdr:
            try:
                self.sdr.close()
            except Exception:
                pass
            self.sdr = None

    # -- tuning --------------------------------------------------------------

    def tune(self, freq_mhz: float):
        freq_mhz = round(freq_mhz, 6)
        with self._lock:
            self.current_freq = freq_mhz
            if self.sdr:
                try:
                    self.sdr.center_freq = freq_mhz * 1e6
                except Exception as exc:
                    print(f"Tune error: {exc}")

    # -- spectrum ------------------------------------------------------------

    def get_spectrum(self, num_samples: int = 65536):
        """Return (freqs_mhz, power_dbfs) arrays."""
        with self._lock:
            if self.sdr:
                try:
                    samples = self.sdr.read_samples(num_samples)
                    return self._compute_spectrum(samples)
                except Exception as exc:
                    print(f"Spectrum read error: {exc}")
            return self._simulated_spectrum()

    def _compute_spectrum(self, samples):
        n = self.FFT_SIZE
        fft = np.fft.fftshift(np.fft.fft(samples[:n], n=n))
        power = 20 * np.log10(np.abs(fft) / n + 1e-12)
        freqs_hz = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / self.SAMPLE_RATE))
        freqs_mhz = (freqs_hz + self.current_freq * 1e6) / 1e6
        return freqs_mhz, power

    def _simulated_spectrum(self):
        n = self.FFT_SIZE
        freqs = np.linspace(
            self.current_freq - self.SAMPLE_RATE / 2e6,
            self.current_freq + self.SAMPLE_RATE / 2e6,
            n,
        )
        noise = np.random.normal(-85, 2, n)
        # Sprinkle fake signals
        rng = np.random.default_rng(seed=int(self.current_freq * 1000) % (2**31))
        num_sigs = rng.integers(2, 8)
        for _ in range(num_sigs):
            offset = rng.uniform(-1.0, 1.0)
            idx = np.argmin(np.abs(freqs - (self.current_freq + offset)))
            width = rng.integers(2, 8)
            amplitude = rng.uniform(15, 35)
            lo = max(0, idx - width)
            hi = min(n - 1, idx + width)
            noise[lo:hi] += amplitude
        return freqs, noise

    # -- scanning ------------------------------------------------------------

    def scan_band(
        self,
        start_mhz: float,
        end_mhz: float,
        threshold_db: float,
        progress_cb=None,
    ) -> List[float]:
        """Sweep the band and return list of peak frequencies in MHz."""
        found: List[float] = []
        bw_mhz = self.SAMPLE_RATE / 1e6  # ~2.4 MHz
        step = bw_mhz * 0.85            # 15 % overlap
        center = start_mhz + bw_mhz / 2

        while center < end_mhz + bw_mhz / 2:
            self.tune(center)
            time.sleep(0.25)
            freqs, power = self.get_spectrum(32768)

            peaks = self._find_peaks(freqs, power, threshold_db, start_mhz, end_mhz)
            for p in peaks:
                if not any(abs(p - f) < 0.002 for f in found):
                    found.append(round(p, 3))

            if progress_cb:
                pct = min(100, int((center - start_mhz) / max(end_mhz - start_mhz, 0.001) * 100))
                progress_cb(center, pct, list(found))

            center += step

        return sorted(found)

    @staticmethod
    def _find_peaks(freqs, power, threshold, band_lo, band_hi) -> List[float]:
        peaks = []
        in_peak = False
        peak_start = 0
        above = power > threshold

        for i, flag in enumerate(above):
            if flag and not in_peak:
                in_peak = True
                peak_start = i
            elif not flag and in_peak:
                in_peak = False
                seg = power[peak_start:i]
                top_idx = peak_start + int(np.argmax(seg))
                freq = float(freqs[top_idx])
                if band_lo <= freq <= band_hi:
                    peaks.append(freq)

        return peaks


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

BG_DARK    = "#1e1e1e"
BG_MID     = "#252526"
BG_PANEL   = "#2d2d30"
BG_TOOLBAR = "#3c3c3c"
FG_MAIN    = "#d4d4d4"
FG_ACCENT  = "#4ec9b0"
FG_WARN    = "#ce9178"
FG_DIM     = "#888888"

BTN_STYLE = dict(relief=tk.FLAT, bd=0, padx=8, pady=5, cursor="hand2")

STATUS_COLORS = {
    ContactStatus.UNKNOWN:       ("#2d2d30", "#d4d4d4"),
    ContactStatus.ACTIVE:        ("#3a3a00", "#ffff88"),
    ContactStatus.INACTIVE:      ("#3a1a1a", "#cc8888"),
    ContactStatus.CONTACTED:     ("#1a3a1a", "#88ff88"),
    ContactStatus.NOT_CONTACTED: ("#3a1a1a", "#ff8888"),
}


class ContestApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("SDR Contest Frequency Helper")
        self.root.geometry("1480x860")
        self.root.minsize(1100, 700)
        self.root.configure(bg=BG_DARK)

        self.spotter = DXSpotter()
        self.sdr = SDRController()

        self.website_freqs: List[FrequencyEntry] = []
        self.filtered_freqs: List[FrequencyEntry] = []
        self.active_freqs: List[FrequencyEntry] = []
        self.scanned_freqs: List[FrequencyEntry] = []

        self._event_q: queue.Queue = queue.Queue()
        self._spectrum_running = False

        self._build_ui()
        self._connect_sdr()
        self._process_events()
        if MATPLOTLIB_AVAILABLE:
            self._start_spectrum_loop()

    # -----------------------------------------------------------------------
    # SDR connection
    # -----------------------------------------------------------------------

    def _connect_sdr(self):
        ok = self.sdr.connect()
        self.sdr_status_var.set("SDR Connected ✓" if ok else "Demo Mode (no SDR)")

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        self._build_toolbar()
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        left = tk.Frame(main, bg=BG_DARK, width=310)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        left.pack_propagate(False)
        self._build_website_panel(left)

        center = tk.Frame(main, bg=BG_DARK)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self._build_sdr_panel(center)

        right = tk.Frame(main, bg=BG_DARK, width=330)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        right.pack_propagate(False)
        self._build_contact_panel(right)

    # -- toolbar -------------------------------------------------------------

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG_TOOLBAR, height=48)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        tk.Label(bar, text="SDR Contest Helper", font=("Helvetica", 15, "bold"),
                 bg=BG_TOOLBAR, fg=FG_ACCENT).pack(side=tk.LEFT, padx=12)

        self.sdr_status_var = tk.StringVar(value="Connecting…")
        tk.Label(bar, textvariable=self.sdr_status_var, font=("Helvetica", 9),
                 bg=BG_TOOLBAR, fg=FG_DIM).pack(side=tk.LEFT, padx=16)

        tk.Button(bar, text="⟳  Refresh Websites", command=self._refresh_websites,
                  bg="#205c20", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.LEFT, padx=4, pady=6)

        tk.Button(bar, text="⌖  Scan SDR Band", command=self._start_scan,
                  bg="#1a3a5c", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.LEFT, padx=4, pady=6)

        self.status_bar_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self.status_bar_var, font=("Helvetica", 9),
                 bg=BG_TOOLBAR, fg=FG_WARN).pack(side=tk.LEFT, padx=16)

    # -- left panel: website spots -------------------------------------------

    def _build_website_panel(self, parent):
        self._section_header(parent, "Website DX Spots", right_var_attr="spot_count_var",
                             right_default="0 spots")

        # Filters
        ff = tk.Frame(parent, bg=BG_MID, padx=6, pady=4)
        ff.pack(fill=tk.X, pady=(2, 0))
        tk.Label(ff, text="Band:", bg=BG_MID, fg=FG_DIM,
                 font=("Helvetica", 9)).pack(side=tk.LEFT)

        self.band_filter = ttk.Combobox(ff, width=6, state="readonly",
            values=["All"] + list(BAND_RANGES.keys()))
        self.band_filter.set("20m")
        self.band_filter.pack(side=tk.LEFT, padx=(4, 10))
        self.band_filter.bind("<<ComboboxSelected>>", lambda _: self._populate_website_list())

        tk.Label(ff, text="Mode:", bg=BG_MID, fg=FG_DIM,
                 font=("Helvetica", 9)).pack(side=tk.LEFT)
        self.mode_filter = ttk.Combobox(ff, width=6, state="readonly",
            values=["All", "SSB", "CW", "FT8", "FT4", "RTTY", "PSK31"])
        self.mode_filter.set("All")
        self.mode_filter.pack(side=tk.LEFT, padx=(4, 0))
        self.mode_filter.bind("<<ComboboxSelected>>", lambda _: self._populate_website_list())

        # Listbox
        lf = tk.Frame(parent, bg=BG_DARK)
        lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        sb = tk.Scrollbar(lf, bg=BG_MID)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.website_lb = tk.Listbox(lf, yscrollcommand=sb.set,
            bg=BG_DARK, fg=FG_MAIN, selectbackground="#094771",
            font=("Courier", 9), activestyle="none",
            selectforeground="white", exportselection=False)
        self.website_lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.website_lb.yview)
        self.website_lb.bind("<<ListboxSelect>>", self._on_website_select)
        self.website_lb.bind("<Double-Button-1>", lambda _: self._tune_to_website())

        # Detail label
        self.website_detail_var = tk.StringVar(value="")
        tk.Label(parent, textvariable=self.website_detail_var,
                 bg=BG_MID, fg=FG_DIM, font=("Helvetica", 8),
                 wraplength=280, justify=tk.LEFT).pack(fill=tk.X, padx=4, pady=2)

        # Buttons
        bf = tk.Frame(parent, bg=BG_DARK)
        bf.pack(fill=tk.X, pady=(4, 0))
        tk.Button(bf, text="Tune to Selected", command=self._tune_to_website,
                  bg="#1a3a5c", fg="white", font=("Helvetica", 10),
                  **BTN_STYLE).pack(fill=tk.X, padx=2, pady=2)

        row = tk.Frame(bf, bg=BG_DARK)
        row.pack(fill=tk.X)
        tk.Button(row, text="Active ✓", command=lambda: self._website_mark(ContactStatus.ACTIVE),
                  bg="#5a5a00", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 1), pady=2)
        tk.Button(row, text="Not Active ✗", command=lambda: self._website_mark(ContactStatus.INACTIVE),
                  bg="#5a2000", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(1, 2), pady=2)

    # -- center panel: SDR ---------------------------------------------------

    def _build_sdr_panel(self, parent):
        # Freq display + fine tune
        tf = tk.Frame(parent, bg=BG_MID, padx=10, pady=8)
        tf.pack(fill=tk.X, pady=(0, 4))

        tk.Label(tf, text="Tuned:", bg=BG_MID, fg=FG_DIM,
                 font=("Helvetica", 10)).pack(side=tk.LEFT)

        self.current_freq_var = tk.StringVar(value="14.200 MHz")
        tk.Label(tf, textvariable=self.current_freq_var, bg=BG_MID, fg=FG_ACCENT,
                 font=("Courier", 20, "bold")).pack(side=tk.LEFT, padx=10)

        # Fine-tune buttons
        ft = tk.Frame(tf, bg=BG_MID)
        ft.pack(side=tk.LEFT, padx=10)
        tk.Label(ft, text="Fine tune (kHz):", bg=BG_MID, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(anchor=tk.W)
        btn_row = tk.Frame(ft, bg=BG_MID)
        btn_row.pack()
        for step, lbl in [(-10, "◀◀"), (-1, "◀"), (1, "▶"), (10, "▶▶")]:
            tk.Button(btn_row, text=lbl, command=lambda s=step: self._fine_tune(s),
                      bg=BG_PANEL, fg=FG_MAIN, font=("Courier", 9),
                      relief=tk.FLAT, padx=6, pady=2, cursor="hand2").pack(side=tk.LEFT, padx=1)

        # Manual entry
        me = tk.Frame(tf, bg=BG_MID)
        me.pack(side=tk.RIGHT)
        tk.Label(me, text="Jump to (MHz):", bg=BG_MID, fg=FG_DIM,
                 font=("Helvetica", 9)).pack(side=tk.LEFT)
        self.manual_freq_var = tk.StringVar()
        e = tk.Entry(me, textvariable=self.manual_freq_var, width=10,
                     bg=BG_PANEL, fg=FG_MAIN, insertbackground=FG_MAIN,
                     font=("Courier", 11), relief=tk.FLAT)
        e.pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", self._manual_tune)
        tk.Button(me, text="Go", command=self._manual_tune,
                  bg="#334400", fg="white", font=("Helvetica", 9),
                  **BTN_STYLE).pack(side=tk.LEFT)

        # Spectrum
        if MATPLOTLIB_AVAILABLE:
            self._build_spectrum(parent)
        else:
            tk.Label(parent, text="Install matplotlib for spectrum display\npip install matplotlib",
                     bg=BG_DARK, fg=FG_DIM, font=("Helvetica", 11),
                     justify=tk.CENTER).pack(expand=True)

        # Scan controls
        sc = tk.Frame(parent, bg=BG_MID, padx=8, pady=6)
        sc.pack(fill=tk.X, pady=(4, 0))

        fields = [
            ("Start (MHz):", "scan_start_var", "14.000"),
            ("End (MHz):",   "scan_end_var",   "14.350"),
            ("Threshold (dB):", "scan_thresh_var", "-60"),
        ]
        for label, attr, default in fields:
            tk.Label(sc, text=label, bg=BG_MID, fg=FG_DIM,
                     font=("Helvetica", 9)).pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            tk.Entry(sc, textvariable=var, width=8,
                     bg=BG_PANEL, fg=FG_MAIN, insertbackground=FG_MAIN,
                     font=("Courier", 10), relief=tk.FLAT).pack(side=tk.LEFT, padx=(2, 10))

        self.scan_btn = tk.Button(sc, text="▶ Start Scan", command=self._start_scan,
                                  bg="#1a3a5c", fg="white", font=("Helvetica", 10, "bold"),
                                  **BTN_STYLE)
        self.scan_btn.pack(side=tk.LEFT)
        self.scan_progress_var = tk.StringVar(value="")
        tk.Label(sc, textvariable=self.scan_progress_var, bg=BG_MID, fg=FG_WARN,
                 font=("Helvetica", 9)).pack(side=tk.LEFT, padx=10)

    def _build_spectrum(self, parent):
        frame = tk.Frame(parent, bg="#000000")
        frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.fig = Figure(figsize=(8, 3.2), dpi=96, facecolor="#050505")
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#050505")
        for spine in self.ax.spines.values():
            spine.set_color("#333333")
        self.ax.tick_params(colors=FG_DIM, labelsize=8)
        self.ax.set_xlabel("Frequency (MHz)", color=FG_DIM, fontsize=9)
        self.ax.set_ylabel("Power (dBFS)", color=FG_DIM, fontsize=9)
        self.ax.grid(True, color="#222222", linewidth=0.5)
        self.fig.tight_layout(pad=1.5)

        self.spectrum_line, = self.ax.plot([], [], color=FG_ACCENT, linewidth=0.7)
        self.tune_line = self.ax.axvline(x=self.sdr.current_freq, color="#ff6644",
                                          linewidth=1.0, linestyle="--", alpha=0.7)

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self._on_spectrum_click)

    # -- right panel: contact tracking ---------------------------------------

    def _build_contact_panel(self, parent):
        self._section_header(parent, "Contact Tracking", right_var_attr="contact_count_var",
                             right_default="0 / 0")

        # Active freq list (need-to-contact)
        tk.Label(parent, text="Frequencies to work:", bg=BG_DARK, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(anchor=tk.W, padx=4, pady=(4, 0))

        lf = tk.Frame(parent, bg=BG_DARK)
        lf.pack(fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(lf, bg=BG_MID)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.contact_lb = tk.Listbox(lf, yscrollcommand=sb.set,
            bg=BG_DARK, fg=FG_MAIN, selectbackground="#094771",
            font=("Courier", 9), activestyle="none",
            selectforeground="white", exportselection=False)
        self.contact_lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.contact_lb.yview)
        self.contact_lb.bind("<<ListboxSelect>>", self._on_contact_select)
        self.contact_lb.bind("<Double-Button-1>", lambda _: self._tune_to_contact())

        # Buttons
        bf = tk.Frame(parent, bg=BG_DARK)
        bf.pack(fill=tk.X, pady=(4, 0))
        tk.Button(bf, text="Tune to Selected", command=self._tune_to_contact,
                  bg="#1a3a5c", fg="white", font=("Helvetica", 10),
                  **BTN_STYLE).pack(fill=tk.X, padx=2, pady=2)

        row = tk.Frame(bf, bg=BG_DARK)
        row.pack(fill=tk.X)
        tk.Button(row, text="Made Contact", command=lambda: self._contact_mark(ContactStatus.CONTACTED),
                  bg="#1a5c1a", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 1), pady=2)
        tk.Button(row, text="No Contact", command=lambda: self._contact_mark(ContactStatus.NOT_CONTACTED),
                  bg="#5c1a1a", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(1, 2), pady=2)

        tk.Button(bf, text="Remove Selected", command=self._remove_contact,
                  bg="#3a2a00", fg=FG_WARN, font=("Helvetica", 9),
                  **BTN_STYLE).pack(fill=tk.X, padx=2, pady=2)

        # Divider
        tk.Frame(parent, bg="#444444", height=1).pack(fill=tk.X, pady=6)

        # Scanned frequencies
        tk.Label(parent, text="SDR-scanned signals (click to add):",
                 bg=BG_DARK, fg=FG_DIM, font=("Helvetica", 8)).pack(anchor=tk.W, padx=4)

        sf = tk.Frame(parent, bg=BG_DARK)
        sf.pack(fill=tk.BOTH, expand=True)
        ssb = tk.Scrollbar(sf, bg=BG_MID)
        ssb.pack(side=tk.RIGHT, fill=tk.Y)
        self.scan_lb = tk.Listbox(sf, yscrollcommand=ssb.set,
            bg="#0d1a0d", fg="#88ccff", selectbackground="#094771",
            font=("Courier", 9), activestyle="none",
            selectforeground="white", exportselection=False,
            height=7)
        self.scan_lb.pack(fill=tk.BOTH, expand=True)
        ssb.config(command=self.scan_lb.yview)
        self.scan_lb.bind("<Double-Button-1>", lambda _: self._tune_to_scanned())

        sbf = tk.Frame(parent, bg=BG_DARK)
        sbf.pack(fill=tk.X, pady=(4, 0))
        tk.Button(sbf, text="Tune to Scanned", command=self._tune_to_scanned,
                  bg="#223344", fg="white", font=("Helvetica", 10),
                  **BTN_STYLE).pack(fill=tk.X, padx=2, pady=2)
        tk.Button(sbf, text="Add to Contact List", command=self._add_scanned_to_contacts,
                  bg="#1a3a1a", fg="white", font=("Helvetica", 10, "bold"),
                  **BTN_STYLE).pack(fill=tk.X, padx=2, pady=2)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _section_header(self, parent, title, right_var_attr=None, right_default=""):
        h = tk.Frame(parent, bg=BG_TOOLBAR, padx=6, pady=6)
        h.pack(fill=tk.X)
        tk.Label(h, text=title, font=("Helvetica", 11, "bold"),
                 bg=BG_TOOLBAR, fg=FG_ACCENT).pack(side=tk.LEFT)
        if right_var_attr:
            var = tk.StringVar(value=right_default)
            setattr(self, right_var_attr, var)
            tk.Label(h, textvariable=var, font=("Helvetica", 9),
                     bg=BG_TOOLBAR, fg=FG_DIM).pack(side=tk.RIGHT)

    def _set_status(self, msg: str):
        self.status_bar_var.set(msg)

    # -----------------------------------------------------------------------
    # Data population
    # -----------------------------------------------------------------------

    def _populate_website_list(self):
        self.website_lb.delete(0, tk.END)
        band_sel = self.band_filter.get()
        mode_sel = self.mode_filter.get()

        self.filtered_freqs = []
        for e in self.website_freqs:
            if band_sel != "All":
                lo, hi = BAND_RANGES.get(band_sel, (0, 1e9))
                if not (lo <= e.frequency <= hi):
                    continue
            if mode_sel != "All" and e.mode and e.mode != mode_sel.upper():
                continue
            self.filtered_freqs.append(e)

        for e in self.filtered_freqs:
            label = f"{e.freq_str}  {e.callsign:<10}  {e.mode:<6}"
            self.website_lb.insert(tk.END, label)
            bg, fg = STATUS_COLORS.get(e.status, (BG_DARK, FG_MAIN))
            self.website_lb.itemconfig(tk.END, bg=bg, fg=fg)

        self.spot_count_var.set(f"{len(self.filtered_freqs)} spots")

    def _populate_contact_list(self):
        self.contact_lb.delete(0, tk.END)
        for e in self.active_freqs:
            tag = ""
            if e.status == ContactStatus.CONTACTED:
                tag = "✓"
            elif e.status == ContactStatus.NOT_CONTACTED:
                tag = "✗"
            label = f"{e.freq_str}  {e.callsign:<10}  {tag}"
            self.contact_lb.insert(tk.END, label)
            bg, fg = STATUS_COLORS.get(e.status, (BG_DARK, FG_MAIN))
            self.contact_lb.itemconfig(tk.END, bg=bg, fg=fg)

        contacted = sum(1 for e in self.active_freqs if e.status == ContactStatus.CONTACTED)
        self.contact_count_var.set(f"{contacted} / {len(self.active_freqs)} contacted")

    def _populate_scan_list(self):
        self.scan_lb.delete(0, tk.END)
        for e in self.scanned_freqs:
            self.scan_lb.insert(tk.END, f"{e.freq_str}  (scanned)")

    # -----------------------------------------------------------------------
    # SDR operations
    # -----------------------------------------------------------------------

    def _tune_to(self, freq_mhz: float):
        self.sdr.tune(freq_mhz)
        self.current_freq_var.set(f"{freq_mhz:.3f} MHz")
        if MATPLOTLIB_AVAILABLE and hasattr(self, "tune_line"):
            self.tune_line.set_xdata([freq_mhz, freq_mhz])

    def _fine_tune(self, step_khz: int):
        self._tune_to(self.sdr.current_freq + step_khz / 1000.0)

    def _manual_tune(self, _event=None):
        try:
            freq = float(self.manual_freq_var.get())
            self._tune_to(freq)
        except ValueError:
            messagebox.showerror("Invalid Frequency",
                                 "Enter a frequency in MHz, e.g. 14.225")

    def _on_spectrum_click(self, event):
        if event.xdata is not None:
            self._tune_to(round(event.xdata, 3))
            self.manual_freq_var.set(f"{event.xdata:.3f}")

    def _tune_to_website(self):
        sel = self.website_lb.curselection()
        if sel:
            e = self.filtered_freqs[sel[0]]
            self._tune_to(e.frequency)

    def _tune_to_contact(self):
        sel = self.contact_lb.curselection()
        if sel:
            e = self.active_freqs[sel[0]]
            self._tune_to(e.frequency)

    def _tune_to_scanned(self):
        sel = self.scan_lb.curselection()
        if sel:
            e = self.scanned_freqs[sel[0]]
            self._tune_to(e.frequency)

    # -----------------------------------------------------------------------
    # Status marking
    # -----------------------------------------------------------------------

    def _website_mark(self, status: ContactStatus):
        sel = self.website_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        e = self.filtered_freqs[idx]
        e.status = status
        bg, fg = STATUS_COLORS.get(status, (BG_DARK, FG_MAIN))
        self.website_lb.itemconfig(idx, bg=bg, fg=fg)

        if status == ContactStatus.ACTIVE:
            if not any(abs(e.frequency - x.frequency) < 0.001 for x in self.active_freqs):
                self.active_freqs.append(e)
                self._populate_contact_list()

        # Advance to next entry and auto-tune
        next_idx = idx + 1
        if next_idx < self.website_lb.size():
            self.website_lb.selection_clear(0, tk.END)
            self.website_lb.selection_set(next_idx)
            self.website_lb.see(next_idx)
            nxt = self.filtered_freqs[next_idx]
            self._tune_to(nxt.frequency)
            self._show_website_detail(nxt)

    def _contact_mark(self, status: ContactStatus):
        sel = self.contact_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self.active_freqs[idx].status = status
        self._populate_contact_list()

        # Advance
        next_idx = min(idx + 1, len(self.active_freqs) - 1)
        if next_idx != idx:
            self.contact_lb.selection_clear(0, tk.END)
            self.contact_lb.selection_set(next_idx)
            self.contact_lb.see(next_idx)
            self._tune_to(self.active_freqs[next_idx].frequency)

    def _remove_contact(self):
        sel = self.contact_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self.active_freqs.pop(idx)
        self._populate_contact_list()

    def _add_scanned_to_contacts(self):
        sel = self.scan_lb.curselection()
        if not sel:
            messagebox.showinfo("Select first", "Select one or more scanned frequencies to add.")
            return
        for idx in sel:
            e = self.scanned_freqs[idx]
            if not any(abs(e.frequency - x.frequency) < 0.001 for x in self.active_freqs):
                new_e = FrequencyEntry(frequency=e.frequency, source="scan",
                                       status=ContactStatus.UNKNOWN)
                self.active_freqs.append(new_e)
        self._populate_contact_list()

    # -----------------------------------------------------------------------
    # Selection events
    # -----------------------------------------------------------------------

    def _on_website_select(self, _event=None):
        sel = self.website_lb.curselection()
        if sel and self.filtered_freqs:
            self._show_website_detail(self.filtered_freqs[sel[0]])

    def _show_website_detail(self, e: FrequencyEntry):
        parts = []
        if e.spotter:
            parts.append(f"Spotter: {e.spotter}")
        if e.comment:
            parts.append(f"Remark: {e.comment}")
        if e.source:
            parts.append(f"Source: {e.source}")
        self.website_detail_var.set("  |  ".join(parts) if parts else "")

    def _on_contact_select(self, _event=None):
        pass

    # -----------------------------------------------------------------------
    # Web refresh
    # -----------------------------------------------------------------------

    def _refresh_websites(self):
        self._set_status("Fetching DX spots…")

        def _fetch():
            spots = self.spotter.fetch_all()
            self._event_q.put(("website_spots", spots))

        threading.Thread(target=_fetch, daemon=True).start()

    # -----------------------------------------------------------------------
    # SDR scan
    # -----------------------------------------------------------------------

    def _start_scan(self):
        try:
            start = float(self.scan_start_var.get())
            end   = float(self.scan_end_var.get())
            thresh = float(self.scan_thresh_var.get())
        except ValueError:
            messagebox.showerror("Scan Error", "Check scan parameters (numeric MHz / dB values).")
            return

        self.scanned_freqs.clear()
        self._populate_scan_list()
        self.scan_btn.config(state=tk.DISABLED)
        self._set_status("Scanning…")

        def _scan():
            def progress(center, pct, found):
                self._event_q.put(("scan_progress", (center, pct, list(found))))

            peaks = self.sdr.scan_band(start, end, thresh, progress)
            self._event_q.put(("scan_done", peaks))

        threading.Thread(target=_scan, daemon=True).start()

    # -----------------------------------------------------------------------
    # Spectrum update loop
    # -----------------------------------------------------------------------

    def _start_spectrum_loop(self):
        self._spectrum_running = True
        self._update_spectrum()

    def _update_spectrum(self):
        if not self._spectrum_running:
            return
        try:
            freqs, power = self.sdr.get_spectrum()
            self.spectrum_line.set_data(freqs, power)
            self.ax.set_xlim(freqs[0], freqs[-1])
            pmin = float(np.percentile(power, 5)) - 5
            pmax = float(np.max(power)) + 5
            self.ax.set_ylim(pmin, pmax)
            self.canvas.draw_idle()
        except Exception:
            pass
        self.root.after(400, self._update_spectrum)

    # -----------------------------------------------------------------------
    # Event queue processor (runs in main thread via after())
    # -----------------------------------------------------------------------

    def _process_events(self):
        try:
            while True:
                tag, data = self._event_q.get_nowait()

                if tag == "website_spots":
                    self.website_freqs = data
                    self._populate_website_list()
                    self._set_status(f"Loaded {len(data)} DX spots")

                elif tag == "scan_progress":
                    center, pct, found = data
                    self.scan_progress_var.set(f"{center:.2f} MHz  {pct}%")
                    self.scanned_freqs = [FrequencyEntry(frequency=f, source="scan")
                                          for f in found]
                    self._populate_scan_list()

                elif tag == "scan_done":
                    peaks = data
                    self.scanned_freqs = [FrequencyEntry(frequency=f, source="scan")
                                          for f in peaks]
                    self._populate_scan_list()
                    self.scan_btn.config(state=tk.NORMAL)
                    self.scan_progress_var.set("")
                    self._set_status(f"Scan complete – {len(peaks)} signal(s) found")

        except queue.Empty:
            pass

        self.root.after(80, self._process_events)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = ContestApp(root)

    def _on_close():
        app._spectrum_running = False
        app.sdr.disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
