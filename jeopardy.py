#!/usr/bin/env python3
"""
Classroom Jeopardy Game (Tkinter version - no installs needed)
===============================================================
A Jeopardy-style review game with:
- Full game board GUI (tkinter - built into Python)
- CSV-based question sets (Category, Value, Question, Answer)
- 3 barcode scanner buzzer support (reads as keyboard input)
- Thinking music via winsound (Windows) with silent fallback
- Score tracking for up to 3 teams

Usage:
    python jeopardy.py

Controls:
    - Click a dollar value on the board to reveal a question
    - Barcode scanners (or keyboard 1/2/3) to buzz in
    - Host clicks "Show Answer" to reveal the answer
    - Host clicks "Correct" (+points) or "Wrong" (-points)
    - ESC to return to board from a question
    - F11 to toggle fullscreen
"""

import tkinter as tk
from tkinter import font as tkfont
import csv
import os
import sys
import glob
import random
import time
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Sound - uses winsound on Windows, silent fallback otherwise
# ---------------------------------------------------------------------------
try:
    import winsound

    def play_wav(path, loop=False):
        if os.path.exists(path):
            flags = winsound.SND_FILENAME | winsound.SND_ASYNC
            if loop:
                flags |= winsound.SND_LOOP
            try:
                winsound.PlaySound(path, flags)
            except Exception:
                pass

    def stop_sound():
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    HAS_SOUND = True
except ImportError:
    def play_wav(path, loop=False):
        pass

    def stop_sound():
        pass

    HAS_SOUND = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_DIR = os.path.join(BASE_DIR, "questions")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")

# Colors - Jeopardy theme
BLUE_DARK = "#060C53"
BLUE_BOARD = "#061378"
BLUE_CELL = "#06199B"
BLUE_HIGHLIGHT = "#1432C8"
GOLD = "#DAA520"
GOLD_BRIGHT = "#FFD700"
WHITE = "#FFFFFF"
BLACK = "#000000"
GREEN = "#22B14C"
GREEN_DARK = "#1A8038"
RED = "#C83232"
RED_DARK = "#A02828"
GRAY = "#646464"
LIGHT_GRAY = "#B4B4B4"
YELLOW = "#FFDF00"

TEAM_COLORS = ["#E64646", "#46B446", "#4682E6"]
TEAM_COLORS_DARK = ["#C03030", "#309630", "#3066C0"]

THINK_TIME_SECONDS = 30


# ---------------------------------------------------------------------------
# Question Loader
# ---------------------------------------------------------------------------
def load_questions(csv_path):
    """Load questions from CSV. Returns {category: [(value, question, answer), ...]}"""
    categories = OrderedDict()
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = row["Category"].strip()
            val = int(row["Value"].strip())
            q = row["Question"].strip()
            a = row["Answer"].strip()
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((val, q, a))
    for cat in categories:
        categories[cat].sort(key=lambda x: x[0])
    return categories


def get_csv_files():
    """Find all CSV files in the questions directory."""
    if not os.path.exists(QUESTIONS_DIR):
        os.makedirs(QUESTIONS_DIR, exist_ok=True)
    return sorted(glob.glob(os.path.join(QUESTIONS_DIR, "*.csv")))


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class JeopardyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Classroom Jeopardy!")
        self.root.configure(bg=BLUE_DARK)
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)

        # State
        self.categories = None
        self.answered = set()
        self.scores = [0, 0, 0]
        self.team_names = ["Team 1", "Team 2", "Team 3"]
        self.current_question = None
        self.buzzed_team = None
        self.think_start = 0
        self.timer_id = None
        self.daily_doubles = set()
        self.dd_team = 0
        self.dd_wager = 0
        self.fullscreen = False

        # Scanner
        self.scanner_buffer = ""
        self.scanner_codes = ["", "", ""]
        self.scanner_last_key_time = 0

        # Fonts (will be created after root exists)
        self._create_fonts()

        # Container for swapping screens
        self.container = tk.Frame(self.root, bg=BLUE_DARK)
        self.container.pack(fill=tk.BOTH, expand=True)

        # Key bindings
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<Key>", self._on_key)

        # Start with file selection
        self.show_file_select()

    def _create_fonts(self):
        self.font_title = tkfont.Font(family="Arial", size=36, weight="bold")
        self.font_subtitle = tkfont.Font(family="Arial", size=20, weight="bold")
        self.font_category = tkfont.Font(family="Arial", size=13, weight="bold")
        self.font_value = tkfont.Font(family="Impact", size=26, weight="bold")
        self.font_question = tkfont.Font(family="Arial", size=22)
        self.font_answer = tkfont.Font(family="Arial", size=22, weight="bold")
        self.font_button = tkfont.Font(family="Arial", size=14, weight="bold")
        self.font_score_name = tkfont.Font(family="Arial", size=14, weight="bold")
        self.font_score_val = tkfont.Font(family="Impact", size=28, weight="bold")
        self.font_small = tkfont.Font(family="Arial", size=12)
        self.font_big = tkfont.Font(family="Impact", size=48, weight="bold")
        self.font_medium = tkfont.Font(family="Arial", size=18, weight="bold")

    def _toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _on_escape(self, event=None):
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes("-fullscreen", False)
            return
        if self.current_question is not None:
            self._back_to_board()

    def _on_key(self, event):
        now = time.time()

        # Buzz in with 1/2/3
        if self.current_question and self.buzzed_team is None:
            if event.char == "1":
                self._buzz_in(0)
                return
            elif event.char == "2":
                self._buzz_in(1)
                return
            elif event.char == "3":
                self._buzz_in(2)
                return

        # Scanner input detection: rapid keystrokes ending with Return
        if self.current_question and self.buzzed_team is None:
            if event.keysym == "Return":
                if self.scanner_buffer:
                    self._check_scanner(self.scanner_buffer.strip())
                    self.scanner_buffer = ""
                return
            if event.char and event.char.isprintable() and event.char not in "123":
                if now - self.scanner_last_key_time > 1.0:
                    self.scanner_buffer = ""
                self.scanner_buffer += event.char
                self.scanner_last_key_time = now

    def _check_scanner(self, code):
        for i, sc in enumerate(self.scanner_codes):
            if sc and code == sc:
                self._buzz_in(i)
                return

    def _clear_container(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        for widget in self.container.winfo_children():
            widget.destroy()

    # -----------------------------------------------------------------------
    # File Selection Screen
    # -----------------------------------------------------------------------
    def show_file_select(self):
        self._clear_container()
        stop_sound()
        self.current_question = None

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(
            frame, text="CLASSROOM JEOPARDY!",
            font=self.font_title, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(30, 5))

        tk.Label(
            frame, text="Select a Question Set",
            font=self.font_subtitle, fg=WHITE, bg=BLUE_DARK
        ).pack(pady=(0, 5))

        tk.Label(
            frame, text=f"Place CSV files in: {QUESTIONS_DIR}",
            font=self.font_small, fg=LIGHT_GRAY, bg=BLUE_DARK
        ).pack(pady=(0, 20))

        csv_files = get_csv_files()

        if not csv_files:
            tk.Label(
                frame, text="No CSV files found!",
                font=self.font_question, fg=RED, bg=BLUE_DARK
            ).pack(pady=40)
            return

        # Scrollable file list
        list_frame = tk.Frame(frame, bg=BLUE_DARK)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=200, pady=10)

        self.selected_file = tk.StringVar(value=csv_files[0])

        for f in csv_files:
            display_name = os.path.basename(f).replace(".csv", "").replace("_", " ").title()
            rb = tk.Radiobutton(
                list_frame,
                text=display_name,
                variable=self.selected_file,
                value=f,
                font=self.font_button,
                fg=GOLD,
                bg=BLUE_CELL,
                selectcolor=BLUE_HIGHLIGHT,
                activebackground=BLUE_HIGHLIGHT,
                activeforeground=GOLD_BRIGHT,
                indicatoron=0,
                padx=20,
                pady=12,
                borderwidth=2,
                relief=tk.RAISED,
                cursor="hand2",
            )
            rb.pack(fill=tk.X, pady=4)

        # Load button
        tk.Button(
            frame, text="LOAD GAME",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK, activeforeground=WHITE,
            padx=30, pady=10, cursor="hand2",
            command=self._load_selected_file,
        ).pack(pady=20)

    def _load_selected_file(self):
        path = self.selected_file.get()
        if path and os.path.exists(path):
            self.categories = load_questions(path)
            self.answered = set()
            self.daily_doubles = set()
            self._setup_daily_doubles()
            self.show_team_setup()

    def _setup_daily_doubles(self):
        if not self.categories:
            return
        cat_names = list(self.categories.keys())
        all_cells = []
        for ci, cat in enumerate(cat_names):
            for vi in range(len(self.categories[cat])):
                if self.categories[cat][vi][0] > min(v for v, _, _ in self.categories[cat]):
                    all_cells.append((ci, vi))
        n_dd = min(2, len(all_cells))
        if all_cells:
            self.daily_doubles = set(random.sample(all_cells, n_dd))

    # -----------------------------------------------------------------------
    # Team Setup Screen
    # -----------------------------------------------------------------------
    def show_team_setup(self):
        self._clear_container()

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text="TEAM SETUP",
            font=self.font_title, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(30, 5))

        tk.Label(
            frame, text="Enter team names, then continue",
            font=self.font_small, fg=LIGHT_GRAY, bg=BLUE_DARK
        ).pack(pady=(0, 25))

        self.team_entries = []
        for i in range(3):
            row = tk.Frame(frame, bg=BLUE_DARK)
            row.pack(pady=10)

            # Color indicator
            color_box = tk.Label(
                row, text="  ", bg=TEAM_COLORS[i],
                width=3, relief=tk.RAISED
            )
            color_box.pack(side=tk.LEFT, padx=(0, 15))

            entry = tk.Entry(
                row, font=self.font_medium,
                fg=WHITE, bg=BLUE_CELL,
                insertbackground=WHITE,
                width=25, justify=tk.CENTER,
                relief=tk.RAISED, borderwidth=2,
            )
            entry.insert(0, self.team_names[i])
            entry.pack(side=tk.LEFT)
            self.team_entries.append(entry)

        btn_frame = tk.Frame(frame, bg=BLUE_DARK)
        btn_frame.pack(pady=30)

        tk.Button(
            btn_frame, text="SCANNER SETUP",
            font=self.font_button, fg=WHITE, bg=BLUE_HIGHLIGHT,
            activebackground=BLUE_CELL, activeforeground=WHITE,
            padx=20, pady=10, cursor="hand2",
            command=self._go_to_scanner_setup,
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame, text="START GAME (Keys 1/2/3)",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK, activeforeground=WHITE,
            padx=20, pady=10, cursor="hand2",
            command=self._start_game_skip_scanner,
        ).pack(side=tk.LEFT, padx=10)

    def _save_team_names(self):
        for i, entry in enumerate(self.team_entries):
            name = entry.get().strip()
            if name:
                self.team_names[i] = name

    def _go_to_scanner_setup(self):
        self._save_team_names()
        self.scanner_setup_team = 0
        self.show_scanner_setup()

    def _start_game_skip_scanner(self):
        self._save_team_names()
        self.show_board()

    # -----------------------------------------------------------------------
    # Scanner Setup Screen
    # -----------------------------------------------------------------------
    def show_scanner_setup(self):
        self._clear_container()

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text="SCANNER SETUP",
            font=self.font_title, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(30, 10))

        self.scanner_setup_team = getattr(self, "scanner_setup_team", 0)

        if self.scanner_setup_team < 3:
            team = self.scanner_setup_team
            tk.Label(
                frame,
                text=f"Scan the barcode for {self.team_names[team]}",
                font=self.font_subtitle, fg=TEAM_COLORS[team], bg=BLUE_DARK
            ).pack(pady=15)

            tk.Label(
                frame,
                text="Click the box below, then scan. The barcode text will appear.",
                font=self.font_small, fg=LIGHT_GRAY, bg=BLUE_DARK
            ).pack(pady=(0, 15))

            self.scanner_entry = tk.Entry(
                frame, font=self.font_medium,
                fg=YELLOW, bg=BLUE_CELL,
                insertbackground=YELLOW,
                width=30, justify=tk.CENTER,
                relief=tk.RAISED, borderwidth=3,
            )
            self.scanner_entry.pack(pady=10)
            self.scanner_entry.focus_set()
            self.scanner_entry.bind("<Return>", self._scanner_entered)

            # Show already configured
            for i in range(team):
                code_display = self.scanner_codes[i][:20]
                tk.Label(
                    frame,
                    text=f"{self.team_names[i]}: {code_display}",
                    font=self.font_small, fg=TEAM_COLORS[i], bg=BLUE_DARK
                ).pack(pady=2)
        else:
            tk.Label(
                frame, text="All Scanners Configured!",
                font=self.font_subtitle, fg=GREEN, bg=BLUE_DARK
            ).pack(pady=20)

            for i in range(3):
                code_display = self.scanner_codes[i][:25] if self.scanner_codes[i] else "(skipped)"
                tk.Label(
                    frame,
                    text=f"{self.team_names[i]}: {code_display}",
                    font=self.font_small, fg=TEAM_COLORS[i], bg=BLUE_DARK
                ).pack(pady=3)

        btn_frame = tk.Frame(frame, bg=BLUE_DARK)
        btn_frame.pack(pady=30)

        if self.scanner_setup_team < 3:
            tk.Button(
                btn_frame, text="SKIP THIS SCANNER",
                font=self.font_small, fg=WHITE, bg=GRAY,
                padx=15, pady=8, cursor="hand2",
                command=self._skip_scanner,
            ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame, text="START GAME",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK, activeforeground=WHITE,
            padx=20, pady=10, cursor="hand2",
            command=self.show_board,
        ).pack(side=tk.LEFT, padx=10)

    def _scanner_entered(self, event=None):
        code = self.scanner_entry.get().strip()
        if code and self.scanner_setup_team < 3:
            self.scanner_codes[self.scanner_setup_team] = code
            self.scanner_setup_team += 1
            self.show_scanner_setup()

    def _skip_scanner(self):
        if self.scanner_setup_team < 3:
            self.scanner_setup_team += 1
            self.show_scanner_setup()

    # -----------------------------------------------------------------------
    # Game Board Screen
    # -----------------------------------------------------------------------
    def show_board(self):
        self._clear_container()
        stop_sound()
        self.current_question = None
        self.buzzed_team = None

        if not self.categories:
            return

        cat_names = list(self.categories.keys())
        n_cats = len(cat_names)
        max_vals = max(len(self.categories[c]) for c in cat_names)

        # Check game over
        total = sum(len(self.categories[c]) for c in cat_names)
        if len(self.answered) >= total:
            self.show_game_over()
            return

        # Board frame
        board_frame = tk.Frame(self.container, bg=BLUE_DARK, padx=5, pady=5)
        board_frame.pack(fill=tk.BOTH, expand=True)

        # Configure grid weights for responsive sizing
        for ci in range(n_cats):
            board_frame.columnconfigure(ci, weight=1)
        board_frame.rowconfigure(0, weight=1)  # category headers
        for vi in range(max_vals):
            board_frame.rowconfigure(vi + 1, weight=2)

        # Category headers
        for ci, cat in enumerate(cat_names):
            lbl = tk.Label(
                board_frame, text=cat.upper(),
                font=self.font_category, fg=WHITE, bg=BLUE_BOARD,
                wraplength=180, pady=8, padx=5,
                relief=tk.RAISED, borderwidth=1,
            )
            lbl.grid(row=0, column=ci, sticky="nsew", padx=2, pady=2)

        # Value cells
        for ci, cat in enumerate(cat_names):
            for vi, (val, q, a) in enumerate(self.categories[cat]):
                if (ci, vi) in self.answered:
                    lbl = tk.Label(
                        board_frame, text="",
                        bg=BLUE_DARK, relief=tk.FLAT,
                    )
                    lbl.grid(row=vi + 1, column=ci, sticky="nsew", padx=2, pady=2)
                else:
                    btn = tk.Button(
                        board_frame,
                        text=f"${val}",
                        font=self.font_value, fg=GOLD_BRIGHT, bg=BLUE_CELL,
                        activebackground=BLUE_HIGHLIGHT,
                        activeforeground=GOLD_BRIGHT,
                        relief=tk.RAISED, borderwidth=2,
                        cursor="hand2",
                        command=lambda c=cat, v=val, qu=q, an=a, cidx=ci, vidx=vi:
                            self._select_question(c, v, qu, an, cidx, vidx),
                    )
                    btn.grid(row=vi + 1, column=ci, sticky="nsew", padx=2, pady=2)

        # Score panel
        score_frame = tk.Frame(self.container, bg=BLUE_DARK, pady=5)
        score_frame.pack(fill=tk.X)
        for i in range(3):
            score_frame.columnconfigure(i, weight=1)

        for i in range(3):
            panel = tk.Frame(score_frame, bg=TEAM_COLORS[i], padx=10, pady=5,
                             relief=tk.RAISED, borderwidth=2)
            panel.grid(row=0, column=i, sticky="nsew", padx=8, pady=3)

            tk.Label(
                panel, text=self.team_names[i],
                font=self.font_score_name, fg=WHITE, bg=TEAM_COLORS[i]
            ).pack()

            tk.Label(
                panel, text=f"${self.scores[i]:,}",
                font=self.font_score_val, fg=YELLOW, bg=TEAM_COLORS[i]
            ).pack()

    def _select_question(self, cat, val, question, answer, ci, vi):
        self.answered.add((ci, vi))
        self.current_question = (cat, val, question, answer, ci, vi)
        self.buzzed_team = None
        self.scanner_buffer = ""

        if (ci, vi) in self.daily_doubles:
            self.show_daily_double()
        else:
            self.show_question()

    # -----------------------------------------------------------------------
    # Question Screen
    # -----------------------------------------------------------------------
    def show_question(self):
        self._clear_container()
        self.root.focus_set()

        cat, val, question, answer, ci, vi = self.current_question
        self.think_start = time.time()

        # Play thinking music
        thinking_path = os.path.join(SOUNDS_DIR, "thinking.wav")
        play_wav(thinking_path, loop=True)

        frame = tk.Frame(self.container, bg=BLUE_BOARD)
        frame.pack(fill=tk.BOTH, expand=True)

        # Header
        tk.Label(
            frame, text=f"{cat.upper()} - ${val}",
            font=self.font_subtitle, fg=GOLD, bg=BLUE_BOARD
        ).pack(pady=(15, 10))

        # Question box
        q_frame = tk.Frame(frame, bg=BLUE_DARK, padx=30, pady=20,
                           relief=tk.RIDGE, borderwidth=3)
        q_frame.pack(fill=tk.X, padx=40, pady=10)

        tk.Label(
            q_frame, text=question,
            font=self.font_question, fg=WHITE, bg=BLUE_DARK,
            wraplength=700, justify=tk.CENTER, pady=15,
        ).pack()

        # Timer bar
        timer_frame = tk.Frame(frame, bg=BLUE_BOARD)
        timer_frame.pack(fill=tk.X, padx=80, pady=(10, 5))

        self.timer_canvas = tk.Canvas(
            timer_frame, height=24, bg=GRAY,
            highlightthickness=0, relief=tk.SUNKEN, borderwidth=1
        )
        self.timer_canvas.pack(fill=tk.X)

        self.timer_label = tk.Label(
            frame, text=f"{THINK_TIME_SECONDS}s",
            font=self.font_small, fg=WHITE, bg=BLUE_BOARD
        )
        self.timer_label.pack()

        # Buzz instruction
        self.buzz_label = tk.Label(
            frame, text="SCAN or PRESS 1, 2, 3 TO BUZZ IN!",
            font=self.font_button, fg=YELLOW, bg=BLUE_BOARD
        )
        self.buzz_label.pack(pady=8)

        # Buzzed-in display (hidden initially)
        self.buzzed_frame = tk.Frame(frame, bg=BLUE_BOARD)
        self.buzzed_frame.pack(pady=5)

        # Button area
        self.q_btn_frame = tk.Frame(frame, bg=BLUE_BOARD)
        self.q_btn_frame.pack(pady=10)

        tk.Button(
            self.q_btn_frame, text="SHOW ANSWER",
            font=self.font_button, fg=BLACK, bg=GOLD,
            activebackground=GOLD_BRIGHT,
            padx=20, pady=8, cursor="hand2",
            command=self._show_answer,
        ).pack(side=tk.LEFT, padx=10)

        # Answer area (hidden initially)
        self.answer_frame = tk.Frame(frame, bg=BLUE_BOARD)
        self.answer_frame.pack(fill=tk.X, padx=40, pady=5)

        # Mini scores
        self._draw_mini_scores(frame)

        # Start timer
        self._update_timer()

    def _update_timer(self):
        if self.current_question is None or self.think_start == 0:
            return

        elapsed = time.time() - self.think_start
        remaining = max(0, THINK_TIME_SECONDS - elapsed)
        pct = remaining / THINK_TIME_SECONDS

        # Update bar
        try:
            self.timer_canvas.delete("all")
            w = self.timer_canvas.winfo_width()
            h = self.timer_canvas.winfo_height()
            if w < 2:
                w = 600

            color = GREEN if pct > 0.3 else YELLOW if pct > 0.1 else RED
            self.timer_canvas.create_rectangle(0, 0, w * pct, h, fill=color, outline="")
            self.timer_label.config(text=f"{remaining:.0f}s")
        except tk.TclError:
            return

        if remaining <= 0:
            stop_sound()
            times_up_path = os.path.join(SOUNDS_DIR, "times_up.wav")
            play_wav(times_up_path)
            self.think_start = 0
            self._show_answer()
            return

        self.timer_id = self.root.after(100, self._update_timer)

    def _buzz_in(self, team):
        if self.current_question is None or self.buzzed_team is not None:
            return

        self.buzzed_team = team
        stop_sound()
        buzzer_path = os.path.join(SOUNDS_DIR, "buzzer.wav")
        play_wav(buzzer_path)

        # Show who buzzed in
        try:
            self.buzz_label.config(text="")
            for w in self.buzzed_frame.winfo_children():
                w.destroy()

            buzz_panel = tk.Label(
                self.buzzed_frame,
                text=f"  {self.team_names[team]} BUZZED IN!  ",
                font=self.font_subtitle,
                fg=WHITE, bg=TEAM_COLORS[team],
                padx=20, pady=8,
                relief=tk.RAISED, borderwidth=3,
            )
            buzz_panel.pack()

            # Add correct/wrong buttons
            val = self.current_question[1]
            score_frame = tk.Frame(self.buzzed_frame, bg=BLUE_BOARD)
            score_frame.pack(pady=8)

            tk.Button(
                score_frame, text=f"CORRECT (+${val})",
                font=self.font_button, fg=WHITE, bg=GREEN,
                activebackground=GREEN_DARK,
                padx=15, pady=8, cursor="hand2",
                command=self._correct,
            ).pack(side=tk.LEFT, padx=10)

            tk.Button(
                score_frame, text=f"WRONG (-${val})",
                font=self.font_button, fg=WHITE, bg=RED,
                activebackground=RED_DARK,
                padx=15, pady=8, cursor="hand2",
                command=self._wrong,
            ).pack(side=tk.LEFT, padx=10)

        except tk.TclError:
            pass

    def _show_answer(self):
        if self.current_question is None:
            return

        stop_sound()
        self.think_start = 0
        cat, val, question, answer, ci, vi = self.current_question

        try:
            for w in self.answer_frame.winfo_children():
                w.destroy()

            ans_box = tk.Frame(
                self.answer_frame, bg="#143C14",
                padx=20, pady=15, relief=tk.RIDGE, borderwidth=3,
            )
            ans_box.pack(fill=tk.X)

            tk.Label(
                ans_box, text="ANSWER:",
                font=self.font_small, fg=LIGHT_GRAY, bg="#143C14"
            ).pack()

            tk.Label(
                ans_box, text=answer,
                font=self.font_answer, fg=GREEN, bg="#143C14",
                wraplength=650, justify=tk.CENTER,
            ).pack(pady=5)

            # Add correct/wrong if someone buzzed and hasn't been scored yet
            if self.buzzed_team is not None:
                score_frame = tk.Frame(ans_box, bg="#143C14")
                score_frame.pack(pady=8)

                tk.Button(
                    score_frame, text=f"CORRECT (+${val})",
                    font=self.font_button, fg=WHITE, bg=GREEN,
                    activebackground=GREEN_DARK,
                    padx=15, pady=6, cursor="hand2",
                    command=self._correct,
                ).pack(side=tk.LEFT, padx=10)

                tk.Button(
                    score_frame, text=f"WRONG (-${val})",
                    font=self.font_button, fg=WHITE, bg=RED,
                    activebackground=RED_DARK,
                    padx=15, pady=6, cursor="hand2",
                    command=self._wrong,
                ).pack(side=tk.LEFT, padx=10)

            # Back to board
            tk.Button(
                ans_box, text="BACK TO BOARD",
                font=self.font_small, fg=WHITE, bg=BLUE_CELL,
                padx=15, pady=6, cursor="hand2",
                command=self._back_to_board,
            ).pack(pady=(8, 0))

        except tk.TclError:
            pass

    def _correct(self):
        if self.buzzed_team is not None and self.current_question:
            val = self.current_question[1]
            self.scores[self.buzzed_team] += val
            correct_path = os.path.join(SOUNDS_DIR, "correct.wav")
            play_wav(correct_path)
        self._back_to_board()

    def _wrong(self):
        if self.buzzed_team is not None and self.current_question:
            val = self.current_question[1]
            self.scores[self.buzzed_team] -= val
            wrong_path = os.path.join(SOUNDS_DIR, "wrong.wav")
            play_wav(wrong_path)
            # Let others buzz in
            self.buzzed_team = None
            try:
                self.buzz_label.config(text="SCAN or PRESS 1, 2, 3 TO BUZZ IN!")
                for w in self.buzzed_frame.winfo_children():
                    w.destroy()
                # Restart timer
                self.think_start = time.time()
                thinking_path = os.path.join(SOUNDS_DIR, "thinking.wav")
                play_wav(thinking_path, loop=True)
                self._update_timer()
            except tk.TclError:
                self._back_to_board()

    def _back_to_board(self):
        stop_sound()
        self.current_question = None
        self.buzzed_team = None
        self.think_start = 0
        self.show_board()

    def _draw_mini_scores(self, parent):
        score_frame = tk.Frame(parent, bg=BLUE_BOARD)
        score_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=3)
        for i in range(3):
            score_frame.columnconfigure(i, weight=1)
        for i in range(3):
            lbl = tk.Label(
                score_frame,
                text=f"{self.team_names[i]}: ${self.scores[i]:,}",
                font=self.font_small, fg=WHITE, bg=TEAM_COLORS[i],
                padx=10, pady=3, relief=tk.RAISED,
            )
            lbl.grid(row=0, column=i, sticky="ew", padx=4)

    # -----------------------------------------------------------------------
    # Daily Double
    # -----------------------------------------------------------------------
    def show_daily_double(self):
        self._clear_container()

        dd_path = os.path.join(SOUNDS_DIR, "daily_double.wav")
        play_wav(dd_path)

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text="DAILY",
            font=self.font_big, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(60, 0))
        tk.Label(
            frame, text="DOUBLE!",
            font=self.font_big, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(0, 30))

        tk.Label(
            frame, text="Which team found it?",
            font=self.font_subtitle, fg=WHITE, bg=BLUE_DARK
        ).pack(pady=20)

        btn_frame = tk.Frame(frame, bg=BLUE_DARK)
        btn_frame.pack(pady=10)

        for i in range(3):
            tk.Button(
                btn_frame,
                text=self.team_names[i],
                font=self.font_button, fg=WHITE, bg=TEAM_COLORS[i],
                activebackground=TEAM_COLORS_DARK[i],
                padx=25, pady=10, cursor="hand2",
                command=lambda t=i: self._dd_select_team(t),
            ).pack(side=tk.LEFT, padx=15)

    def _dd_select_team(self, team):
        self.dd_team = team
        self.show_dd_wager()

    def show_dd_wager(self):
        self._clear_container()

        cat, val, question, answer, ci, vi = self.current_question

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text="DAILY DOUBLE!",
            font=self.font_title, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(20, 10))

        tk.Label(
            frame,
            text=f"{self.team_names[self.dd_team]}'s Wager",
            font=self.font_subtitle, fg=TEAM_COLORS[self.dd_team], bg=BLUE_DARK
        ).pack(pady=5)

        current_score = max(self.scores[self.dd_team], 0)
        max_wager = max(current_score, max(v for v, _, _ in self.categories[cat]))
        tk.Label(
            frame,
            text=f"Current Score: ${self.scores[self.dd_team]:,}  |  Max Wager: ${max_wager:,}",
            font=self.font_small, fg=LIGHT_GRAY, bg=BLUE_DARK
        ).pack(pady=5)

        # Wager entry
        self.wager_entry = tk.Entry(
            frame, font=self.font_subtitle,
            fg=GOLD, bg=BLUE_CELL,
            insertbackground=GOLD,
            width=12, justify=tk.CENTER,
            relief=tk.RAISED, borderwidth=3,
        )
        self.wager_entry.pack(pady=15)
        self.wager_entry.focus_set()
        self.wager_entry.bind("<Return>", lambda e: self._confirm_wager(max_wager))

        # Quick wager buttons
        quick_frame = tk.Frame(frame, bg=BLUE_DARK)
        quick_frame.pack(pady=8)

        for w in [100, 200, 500, 1000]:
            tk.Button(
                quick_frame, text=f"${w}",
                font=self.font_small, fg=GOLD, bg=BLUE_CELL,
                padx=12, pady=5, cursor="hand2",
                command=lambda amt=w: self._set_wager(amt),
            ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame, text=f"ALL IN (${max_wager})",
            font=self.font_button, fg=WHITE, bg=RED,
            activebackground=RED_DARK,
            padx=15, pady=6, cursor="hand2",
            command=lambda: self._set_wager(max_wager),
        ).pack(pady=8)

        tk.Button(
            frame, text="CONFIRM WAGER",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK,
            padx=20, pady=10, cursor="hand2",
            command=lambda: self._confirm_wager(max_wager),
        ).pack(pady=15)

    def _set_wager(self, amount):
        self.wager_entry.delete(0, tk.END)
        self.wager_entry.insert(0, str(amount))

    def _confirm_wager(self, max_wager):
        try:
            wager = int(self.wager_entry.get().strip())
        except (ValueError, AttributeError):
            return
        wager = max(0, min(wager, max_wager))

        cat, val, question, answer, ci, vi = self.current_question
        self.current_question = (cat, wager, question, answer, ci, vi)
        self.buzzed_team = self.dd_team
        self.show_question_dd()

    def show_question_dd(self):
        """Show question for daily double (team already selected)."""
        self._clear_container()
        self.root.focus_set()

        cat, val, question, answer, ci, vi = self.current_question
        self.think_start = time.time()

        thinking_path = os.path.join(SOUNDS_DIR, "thinking.wav")
        play_wav(thinking_path, loop=True)

        frame = tk.Frame(self.container, bg=BLUE_BOARD)
        frame.pack(fill=tk.BOTH, expand=True)

        # Header
        tk.Label(
            frame, text=f"DAILY DOUBLE - {cat.upper()} (${val} wager)",
            font=self.font_subtitle, fg=GOLD, bg=BLUE_BOARD
        ).pack(pady=(15, 10))

        # Buzzed team
        tk.Label(
            frame,
            text=f"  {self.team_names[self.dd_team]}  ",
            font=self.font_subtitle, fg=WHITE, bg=TEAM_COLORS[self.dd_team],
            padx=15, pady=5, relief=tk.RAISED, borderwidth=2,
        ).pack(pady=5)

        # Question
        q_frame = tk.Frame(frame, bg=BLUE_DARK, padx=30, pady=20,
                           relief=tk.RIDGE, borderwidth=3)
        q_frame.pack(fill=tk.X, padx=40, pady=10)

        tk.Label(
            q_frame, text=question,
            font=self.font_question, fg=WHITE, bg=BLUE_DARK,
            wraplength=700, justify=tk.CENTER, pady=15,
        ).pack()

        # Timer
        timer_frame = tk.Frame(frame, bg=BLUE_BOARD)
        timer_frame.pack(fill=tk.X, padx=80, pady=(10, 5))
        self.timer_canvas = tk.Canvas(
            timer_frame, height=24, bg=GRAY, highlightthickness=0
        )
        self.timer_canvas.pack(fill=tk.X)
        self.timer_label = tk.Label(frame, text="", font=self.font_small, fg=WHITE, bg=BLUE_BOARD)
        self.timer_label.pack()

        # Hidden buzz label for compatibility
        self.buzz_label = tk.Label(frame, text="", bg=BLUE_BOARD)
        self.buzzed_frame = tk.Frame(frame, bg=BLUE_BOARD)

        # Buttons
        btn_frame = tk.Frame(frame, bg=BLUE_BOARD)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame, text=f"CORRECT (+${val})",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK,
            padx=15, pady=8, cursor="hand2",
            command=self._correct,
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame, text=f"WRONG (-${val})",
            font=self.font_button, fg=WHITE, bg=RED,
            activebackground=RED_DARK,
            padx=15, pady=8, cursor="hand2",
            command=lambda: self._dd_wrong(),
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame, text="SHOW ANSWER",
            font=self.font_button, fg=BLACK, bg=GOLD,
            padx=15, pady=8, cursor="hand2",
            command=self._show_answer,
        ).pack(side=tk.LEFT, padx=10)

        # Answer area
        self.answer_frame = tk.Frame(frame, bg=BLUE_BOARD)
        self.answer_frame.pack(fill=tk.X, padx=40, pady=5)

        self._draw_mini_scores(frame)
        self._update_timer()

    def _dd_wrong(self):
        """Daily double wrong - deduct points and go back to board."""
        if self.buzzed_team is not None and self.current_question:
            val = self.current_question[1]
            self.scores[self.buzzed_team] -= val
            wrong_path = os.path.join(SOUNDS_DIR, "wrong.wav")
            play_wav(wrong_path)
        self._back_to_board()

    # -----------------------------------------------------------------------
    # Game Over Screen
    # -----------------------------------------------------------------------
    def show_game_over(self):
        self._clear_container()
        stop_sound()

        frame = tk.Frame(self.container, bg=BLUE_DARK)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text="GAME OVER!",
            font=self.font_big, fg=GOLD, bg=BLUE_DARK
        ).pack(pady=(40, 10))

        # Winner
        max_score = max(self.scores)
        winners = [i for i, s in enumerate(self.scores) if s == max_score]

        if len(winners) == 1:
            w = winners[0]
            tk.Label(
                frame,
                text=f"{self.team_names[w]} WINS!",
                font=self.font_title, fg=TEAM_COLORS[w], bg=BLUE_DARK
            ).pack(pady=10)
        else:
            names = " & ".join(self.team_names[w] for w in winners)
            tk.Label(
                frame, text=f"TIE: {names}!",
                font=self.font_subtitle, fg=YELLOW, bg=BLUE_DARK
            ).pack(pady=10)

        # Final scores
        sorted_teams = sorted(range(3), key=lambda i: self.scores[i], reverse=True)
        ranks = ["1st", "2nd", "3rd"]
        for rank_idx, i in enumerate(sorted_teams):
            panel = tk.Label(
                frame,
                text=f"  {ranks[rank_idx]}   {self.team_names[i]}:   ${self.scores[i]:,}  ",
                font=self.font_subtitle, fg=WHITE, bg=TEAM_COLORS[i],
                padx=20, pady=10, relief=tk.RAISED, borderwidth=2,
            )
            panel.pack(pady=6, padx=150, fill=tk.X)

        btn_frame = tk.Frame(frame, bg=BLUE_DARK)
        btn_frame.pack(pady=30)

        tk.Button(
            btn_frame, text="PLAY AGAIN (Same Questions)",
            font=self.font_button, fg=WHITE, bg=GREEN,
            activebackground=GREEN_DARK,
            padx=20, pady=10, cursor="hand2",
            command=self._play_again,
        ).pack(side=tk.LEFT, padx=15)

        tk.Button(
            btn_frame, text="NEW QUESTIONS",
            font=self.font_button, fg=WHITE, bg=BLUE_CELL,
            padx=20, pady=10, cursor="hand2",
            command=self._new_questions,
        ).pack(side=tk.LEFT, padx=15)

    def _play_again(self):
        self.scores = [0, 0, 0]
        self.answered = set()
        self._setup_daily_doubles()
        self.show_board()

    def _new_questions(self):
        self.scores = [0, 0, 0]
        self.answered = set()
        self.show_file_select()

    # -----------------------------------------------------------------------
    # Run
    # -----------------------------------------------------------------------
    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = JeopardyApp()
    app.run()
