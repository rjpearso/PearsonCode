#!/usr/bin/env python3
"""
Classroom Jeopardy Game
=======================
A Jeopardy-style review game with:
- Full game board GUI (pygame)
- CSV-based question sets (Category, Value, Question, Answer)
- 3 barcode scanner buzzer support (reads as keyboard input)
- Thinking music, sound effects
- Score tracking for up to 3 teams

Usage:
    python3 jeopardy.py

Controls:
    - Click a dollar value on the board to reveal a question
    - Barcode scanners (or keyboard 1/2/3) to buzz in
    - Host clicks "Show Answer" to reveal the answer
    - Host clicks "Correct" (+points) or "Wrong" (-points)
    - ESC to return to board from a question
    - F11 to toggle fullscreen
"""

import pygame
import csv
import os
import sys
import glob
import random
import textwrap
import time
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_DIR = os.path.join(BASE_DIR, "questions")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")

# Colors - Jeopardy theme
BLUE_DARK = (6, 12, 83)
BLUE_BOARD = (6, 19, 120)
BLUE_CELL = (6, 25, 155)
BLUE_HIGHLIGHT = (20, 50, 200)
GOLD = (218, 165, 32)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (34, 177, 76)
RED = (200, 50, 50)
GRAY = (100, 100, 100)
LIGHT_GRAY = (180, 180, 180)
YELLOW = (255, 223, 0)

# Team colors
TEAM_COLORS = [(230, 70, 70), (70, 180, 70), (70, 130, 230)]
TEAM_NAMES_DEFAULT = ["Team 1", "Team 2", "Team 3"]

# Timing
THINK_TIME_SECONDS = 30
BUZZ_WINDOW_SECONDS = 10

# Scanner configuration - map barcode values to team indices
# Barcode scanners send characters followed by Enter
# Configure these to match your scanner output
SCANNER_MAP = {}  # Will be populated during setup


# ---------------------------------------------------------------------------
# Sound Manager
# ---------------------------------------------------------------------------
class SoundManager:
    def __init__(self):
        self.sounds = {}
        self.music_playing = False
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            self._load_sounds()
        except Exception as e:
            print(f"Warning: Could not initialize audio: {e}")

    def _load_sounds(self):
        sound_files = {
            "buzzer": "buzzer.wav",
            "correct": "correct.wav",
            "wrong": "wrong.wav",
            "daily_double": "daily_double.wav",
            "times_up": "times_up.wav",
        }
        for name, filename in sound_files.items():
            path = os.path.join(SOUNDS_DIR, filename)
            if os.path.exists(path):
                try:
                    self.sounds[name] = pygame.mixer.Sound(path)
                except Exception:
                    pass

    def play(self, name):
        if name in self.sounds:
            self.sounds[name].play()

    def start_thinking_music(self):
        path = os.path.join(SOUNDS_DIR, "thinking.wav")
        if os.path.exists(path):
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play(-1)  # Loop
                self.music_playing = True
            except Exception:
                pass

    def stop_thinking_music(self):
        if self.music_playing:
            try:
                pygame.mixer.music.fadeout(300)
            except Exception:
                pass
            self.music_playing = False


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
    # Sort each category by value
    for cat in categories:
        categories[cat].sort(key=lambda x: x[0])
    return categories


def get_csv_files():
    """Find all CSV files in the questions directory."""
    pattern = os.path.join(QUESTIONS_DIR, "*.csv")
    files = sorted(glob.glob(pattern))
    return files


# ---------------------------------------------------------------------------
# Text rendering helpers
# ---------------------------------------------------------------------------
def render_text_wrapped(surface, text, font, color, rect, line_spacing=5):
    """Render wrapped text centered in a rect. Returns total height used."""
    words = text.split()
    lines = []
    current_line = ""
    max_width = rect.width - 40  # padding

    for word in words:
        test_line = current_line + " " + word if current_line else word
        if font.size(test_line)[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    total_height = len(lines) * (font.get_height() + line_spacing)
    start_y = rect.centery - total_height // 2

    for i, line in enumerate(lines):
        text_surf = font.render(line, True, color)
        text_rect = text_surf.get_rect(
            centerx=rect.centerx,
            top=start_y + i * (font.get_height() + line_spacing),
        )
        surface.blit(text_surf, text_rect)

    return total_height


def draw_text_centered(surface, text, font, color, rect):
    """Draw text centered in a rect."""
    text_surf = font.render(text, True, color)
    text_rect = text_surf.get_rect(center=rect.center)
    surface.blit(text_surf, text_rect)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------
class Button:
    def __init__(self, rect, text, color, text_color=WHITE, font=None, hover_color=None):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color
        self.text_color = text_color
        self.font = font
        self.hover_color = hover_color or tuple(min(c + 30, 255) for c in color)
        self.hovered = False

    def draw(self, surface):
        color = self.hover_color if self.hovered else self.color
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=8)
        if self.font:
            draw_text_centered(surface, self.text, self.font, self.text_color, self.rect)

    def update(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)

    def clicked(self, mouse_pos):
        return self.rect.collidepoint(mouse_pos)


# ---------------------------------------------------------------------------
# Game States
# ---------------------------------------------------------------------------
STATE_FILE_SELECT = "file_select"
STATE_TEAM_SETUP = "team_setup"
STATE_SCANNER_SETUP = "scanner_setup"
STATE_BOARD = "board"
STATE_QUESTION = "question"
STATE_ANSWER = "answer"
STATE_BUZZ_IN = "buzz_in"
STATE_DAILY_DOUBLE = "daily_double"
STATE_DD_WAGER = "dd_wager"
STATE_GAME_OVER = "game_over"


# ---------------------------------------------------------------------------
# Main Game Class
# ---------------------------------------------------------------------------
class JeopardyGame:
    def __init__(self):
        pygame.init()

        # Get display info for sizing
        info = pygame.display.Info()
        self.screen_w = min(1280, info.current_w - 100)
        self.screen_h = min(800, info.current_h - 100)
        self.fullscreen = False
        self.screen = pygame.display.set_mode(
            (self.screen_w, self.screen_h), pygame.RESIZABLE
        )
        pygame.display.set_caption("Classroom Jeopardy!")

        self.clock = pygame.time.Clock()
        self.sound = SoundManager()

        # Fonts - will be sized relative to screen
        self._init_fonts()

        # Game state
        self.state = STATE_FILE_SELECT
        self.categories = None
        self.answered = set()  # (cat_index, val_index) pairs
        self.scores = [0, 0, 0]
        self.team_names = list(TEAM_NAMES_DEFAULT)
        self.current_question = None  # (cat, val, question, answer, cat_idx, val_idx)
        self.buzzed_team = None
        self.buzz_time = 0
        self.think_start = 0
        self.daily_doubles = set()  # (cat_idx, val_idx) pairs
        self.dd_wager = ""
        self.dd_team = 0

        # Scanner input buffer
        self.scanner_buffer = ""
        self.scanner_codes = ["", "", ""]  # Codes for each team
        self.scanner_setup_team = 0  # Which team we're setting up

        # File selection
        self.csv_files = get_csv_files()
        self.selected_file = 0
        self.file_scroll = 0

        # Team name editing
        self.editing_team = -1
        self.edit_text = ""

        # UI elements
        self.buttons = []

    def _init_fonts(self):
        """Initialize fonts scaled to screen size."""
        base = max(self.screen_h // 50, 12)
        self.font_title = pygame.font.SysFont("Arial", base * 3, bold=True)
        self.font_category = pygame.font.SysFont("Arial", base + 6, bold=True)
        self.font_value = pygame.font.SysFont("Impact", base * 2 + 4, bold=True)
        self.font_question = pygame.font.SysFont("Arial", base * 2, bold=False)
        self.font_answer = pygame.font.SysFont("Arial", base * 2, bold=True)
        self.font_button = pygame.font.SysFont("Arial", base + 4, bold=True)
        self.font_score = pygame.font.SysFont("Arial", base + 6, bold=True)
        self.font_small = pygame.font.SysFont("Arial", base + 2)
        self.font_large = pygame.font.SysFont("Impact", base * 4, bold=True)
        self.font_medium = pygame.font.SysFont("Arial", base + 8, bold=True)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            info = pygame.display.Info()
            self.screen_w = info.current_w
            self.screen_h = info.current_h
        else:
            self.screen_w = 1280
            self.screen_h = 800
            self.screen = pygame.display.set_mode(
                (self.screen_w, self.screen_h), pygame.RESIZABLE
            )
        self._init_fonts()

    def setup_daily_doubles(self):
        """Randomly assign 1-2 daily doubles."""
        if not self.categories:
            return
        cat_names = list(self.categories.keys())
        all_cells = []
        for ci, cat in enumerate(cat_names):
            for vi in range(len(self.categories[cat])):
                # Skip the lowest value questions
                if self.categories[cat][vi][0] > min(v for v, _, _ in self.categories[cat]):
                    all_cells.append((ci, vi))
        n_dd = min(2, len(all_cells))
        if all_cells:
            self.daily_doubles = set(random.sample(all_cells, n_dd))

    def load_game(self, csv_path):
        """Load a question set and initialize the board."""
        self.categories = load_questions(csv_path)
        self.answered = set()
        self.current_question = None
        self.daily_doubles = set()
        self.setup_daily_doubles()
        self.state = STATE_TEAM_SETUP

    # -----------------------------------------------------------------------
    # Drawing Methods
    # -----------------------------------------------------------------------
    def draw_file_select(self):
        """Draw the CSV file selection screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        # Title
        title_rect = pygame.Rect(0, sh * 0.03, sw, sh * 0.1)
        draw_text_centered(self.screen, "CLASSROOM JEOPARDY!", self.font_title, GOLD, title_rect)

        subtitle_rect = pygame.Rect(0, sh * 0.12, sw, sh * 0.05)
        draw_text_centered(self.screen, "Select a Question Set", self.font_medium, WHITE, subtitle_rect)

        # Instructions
        inst_rect = pygame.Rect(sw * 0.1, sh * 0.18, sw * 0.8, sh * 0.05)
        draw_text_centered(
            self.screen,
            f"Place CSV files in: {QUESTIONS_DIR}",
            self.font_small,
            LIGHT_GRAY,
            inst_rect,
        )

        if not self.csv_files:
            msg_rect = pygame.Rect(sw * 0.2, sh * 0.4, sw * 0.6, sh * 0.1)
            draw_text_centered(self.screen, "No CSV files found!", self.font_question, RED, msg_rect)
            return

        # File list
        self.buttons = []
        visible_count = min(len(self.csv_files), 8)
        btn_h = sh * 0.07
        btn_gap = sh * 0.02
        start_y = sh * 0.26
        btn_w = sw * 0.6

        for i in range(visible_count):
            idx = i + self.file_scroll
            if idx >= len(self.csv_files):
                break
            fname = os.path.basename(self.csv_files[idx])
            display_name = fname.replace(".csv", "").replace("_", " ").title()

            y = start_y + i * (btn_h + btn_gap)
            rect = pygame.Rect((sw - btn_w) // 2, y, btn_w, btn_h)

            color = BLUE_HIGHLIGHT if idx == self.selected_file else BLUE_CELL
            btn = Button(rect, display_name, color, GOLD, self.font_button)
            btn.file_index = idx
            btn.draw(self.screen)
            self.buttons.append(btn)

        # Load button
        load_rect = pygame.Rect((sw - 200) // 2, sh * 0.85, 200, 50)
        load_btn = Button(load_rect, "LOAD GAME", GREEN, WHITE, self.font_button)
        load_btn.action = "load"
        load_btn.draw(self.screen)
        self.buttons.append(load_btn)

    def draw_team_setup(self):
        """Draw team name configuration screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        title_rect = pygame.Rect(0, sh * 0.05, sw, sh * 0.1)
        draw_text_centered(self.screen, "TEAM SETUP", self.font_title, GOLD, title_rect)

        inst_rect = pygame.Rect(0, sh * 0.15, sw, sh * 0.05)
        draw_text_centered(
            self.screen,
            "Click a team name to edit it, then press Enter",
            self.font_small,
            LIGHT_GRAY,
            inst_rect,
        )

        self.buttons = []
        for i in range(3):
            y = sh * 0.28 + i * sh * 0.17
            # Team color indicator
            color_rect = pygame.Rect(sw * 0.2, y, sw * 0.05, sh * 0.1)
            pygame.draw.rect(self.screen, TEAM_COLORS[i], color_rect, border_radius=5)

            # Team name box
            name_rect = pygame.Rect(sw * 0.28, y, sw * 0.44, sh * 0.1)
            if self.editing_team == i:
                pygame.draw.rect(self.screen, BLUE_HIGHLIGHT, name_rect, border_radius=5)
                pygame.draw.rect(self.screen, YELLOW, name_rect, 3, border_radius=5)
                display_text = self.edit_text + "|"
            else:
                pygame.draw.rect(self.screen, BLUE_CELL, name_rect, border_radius=5)
                pygame.draw.rect(self.screen, WHITE, name_rect, 2, border_radius=5)
                display_text = self.team_names[i]

            draw_text_centered(self.screen, display_text, self.font_button, WHITE, name_rect)

            btn = Button(name_rect, "", BLUE_CELL)
            btn.team_index = i
            self.buttons.append(btn)

        # Continue button
        cont_rect = pygame.Rect((sw - 300) // 2, sh * 0.82, 300, 55)
        cont_btn = Button(cont_rect, "CONTINUE TO SCANNER SETUP", GREEN, WHITE, self.font_button)
        cont_btn.action = "continue_scanner"
        cont_btn.draw(self.screen)
        self.buttons.append(cont_btn)

        # Skip scanner setup button
        skip_rect = pygame.Rect((sw - 250) // 2, sh * 0.91, 250, 40)
        skip_btn = Button(skip_rect, "SKIP (Use Keys 1/2/3)", GRAY, WHITE, self.font_small)
        skip_btn.action = "skip_scanner"
        skip_btn.draw(self.screen)
        self.buttons.append(skip_btn)

    def draw_scanner_setup(self):
        """Draw barcode scanner configuration screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        title_rect = pygame.Rect(0, sh * 0.05, sw, sh * 0.08)
        draw_text_centered(self.screen, "SCANNER SETUP", self.font_title, GOLD, title_rect)

        if self.scanner_setup_team < 3:
            team = self.scanner_setup_team
            inst_rect = pygame.Rect(0, sh * 0.18, sw, sh * 0.06)
            draw_text_centered(
                self.screen,
                f"Scan the barcode for {self.team_names[team]}",
                self.font_medium,
                TEAM_COLORS[team],
                inst_rect,
            )

            inst2_rect = pygame.Rect(0, sh * 0.26, sw, sh * 0.05)
            draw_text_centered(
                self.screen,
                "Scan now... (the scanner sends characters + Enter)",
                self.font_small,
                LIGHT_GRAY,
                inst2_rect,
            )

            # Show buffer
            buf_rect = pygame.Rect(sw * 0.25, sh * 0.38, sw * 0.5, sh * 0.08)
            pygame.draw.rect(self.screen, BLUE_CELL, buf_rect, border_radius=5)
            pygame.draw.rect(self.screen, WHITE, buf_rect, 2, border_radius=5)
            display_buf = self.scanner_buffer if self.scanner_buffer else "(waiting for scan...)"
            draw_text_centered(self.screen, display_buf, self.font_button, YELLOW, buf_rect)

            # Show already configured
            for i in range(team):
                y = sh * 0.55 + i * sh * 0.08
                info_rect = pygame.Rect(sw * 0.2, y, sw * 0.6, sh * 0.06)
                code_display = self.scanner_codes[i][:20] + "..." if len(self.scanner_codes[i]) > 20 else self.scanner_codes[i]
                draw_text_centered(
                    self.screen,
                    f"{self.team_names[i]}: {code_display}",
                    self.font_small,
                    TEAM_COLORS[i],
                    info_rect,
                )
        else:
            # All configured
            done_rect = pygame.Rect(0, sh * 0.2, sw, sh * 0.08)
            draw_text_centered(self.screen, "All Scanners Configured!", self.font_medium, GREEN, done_rect)

            for i in range(3):
                y = sh * 0.35 + i * sh * 0.1
                info_rect = pygame.Rect(sw * 0.2, y, sw * 0.6, sh * 0.06)
                code_display = self.scanner_codes[i][:20] + "..." if len(self.scanner_codes[i]) > 20 else self.scanner_codes[i]
                draw_text_centered(
                    self.screen,
                    f"{self.team_names[i]}: {code_display}",
                    self.font_small,
                    TEAM_COLORS[i],
                    info_rect,
                )

        self.buttons = []
        # Start game button
        start_rect = pygame.Rect((sw - 200) // 2, sh * 0.85, 200, 50)
        start_btn = Button(start_rect, "START GAME", GREEN, WHITE, self.font_button)
        start_btn.action = "start_game"
        start_btn.draw(self.screen)
        self.buttons.append(start_btn)

        # Skip button
        skip_rect = pygame.Rect(sw * 0.75, sh * 0.85, 150, 40)
        skip_btn = Button(skip_rect, "Skip Scanner", GRAY, WHITE, self.font_small)
        skip_btn.action = "skip_this_scanner"
        skip_btn.draw(self.screen)
        self.buttons.append(skip_btn)

    def draw_board(self):
        """Draw the main Jeopardy game board."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        if not self.categories:
            return

        cat_names = list(self.categories.keys())
        n_cats = len(cat_names)
        if n_cats == 0:
            return

        # Determine grid dimensions
        max_values = max(len(self.categories[c]) for c in cat_names)

        # Board area
        board_top = sh * 0.02
        board_bottom = sh * 0.75
        board_left = sw * 0.02
        board_right = sw * 0.98

        board_w = board_right - board_left
        board_h = board_bottom - board_top

        cell_w = board_w / n_cats
        header_h = board_h * 0.15
        cell_h = (board_h - header_h) / max_values if max_values > 0 else 0
        gap = 3

        self.board_cells = []

        # Draw category headers
        for ci, cat in enumerate(cat_names):
            x = board_left + ci * cell_w + gap
            w = cell_w - gap * 2
            rect = pygame.Rect(x, board_top + gap, w, header_h - gap * 2)
            pygame.draw.rect(self.screen, BLUE_BOARD, rect, border_radius=4)
            render_text_wrapped(self.screen, cat.upper(), self.font_category, WHITE, rect)

        # Draw value cells
        for ci, cat in enumerate(cat_names):
            values = self.categories[cat]
            for vi, (val, q, a) in enumerate(values):
                x = board_left + ci * cell_w + gap
                y = board_top + header_h + vi * cell_h + gap
                w = cell_w - gap * 2
                h = cell_h - gap * 2
                rect = pygame.Rect(x, y, w, h)

                if (ci, vi) in self.answered:
                    pygame.draw.rect(self.screen, BLUE_DARK, rect, border_radius=4)
                    pygame.draw.rect(self.screen, BLUE_BOARD, rect, 1, border_radius=4)
                else:
                    pygame.draw.rect(self.screen, BLUE_CELL, rect, border_radius=4)
                    # Draw dollar value
                    val_text = f"${val}"
                    draw_text_centered(self.screen, val_text, self.font_value, GOLD, rect)
                    self.board_cells.append((rect, ci, vi, cat, val, q, a))

        # Draw scores at bottom
        self.draw_scores()

        # Check if game is over
        total_cells = sum(len(self.categories[c]) for c in cat_names)
        if len(self.answered) >= total_cells:
            self.state = STATE_GAME_OVER

    def draw_scores(self):
        """Draw the score panel at the bottom of the screen."""
        sw, sh = self.screen_w, self.screen_h
        score_y = sh * 0.78
        score_h = sh * 0.2
        panel_w = sw * 0.3

        for i in range(3):
            x = sw * 0.02 + i * (panel_w + sw * 0.02)
            rect = pygame.Rect(x, score_y, panel_w, score_h)
            pygame.draw.rect(self.screen, TEAM_COLORS[i], rect, border_radius=8)
            pygame.draw.rect(self.screen, WHITE, rect, 2, border_radius=8)

            # Team name
            name_rect = pygame.Rect(x, score_y, panel_w, score_h * 0.45)
            draw_text_centered(self.screen, self.team_names[i], self.font_score, WHITE, name_rect)

            # Score
            score_rect = pygame.Rect(x, score_y + score_h * 0.4, panel_w, score_h * 0.55)
            score_text = f"${self.scores[i]:,}"
            draw_text_centered(self.screen, score_text, self.font_large, YELLOW, score_rect)

    def draw_question(self):
        """Draw the question display screen."""
        self.screen.fill(BLUE_BOARD)
        sw, sh = self.screen_w, self.screen_h

        if not self.current_question:
            return

        cat, val, question, answer, cat_idx, val_idx = self.current_question

        # Category and value header
        header_rect = pygame.Rect(0, sh * 0.02, sw, sh * 0.08)
        draw_text_centered(
            self.screen,
            f"{cat.upper()} - ${val}",
            self.font_medium,
            GOLD,
            header_rect,
        )

        # Question text - large centered
        q_rect = pygame.Rect(sw * 0.08, sh * 0.13, sw * 0.84, sh * 0.35)
        pygame.draw.rect(self.screen, BLUE_DARK, q_rect, border_radius=10)
        pygame.draw.rect(self.screen, GOLD, q_rect, 3, border_radius=10)
        render_text_wrapped(self.screen, question, self.font_question, WHITE, q_rect)

        # Timer bar
        if self.think_start > 0:
            elapsed = time.time() - self.think_start
            remaining = max(0, THINK_TIME_SECONDS - elapsed)
            pct = remaining / THINK_TIME_SECONDS

            bar_rect = pygame.Rect(sw * 0.1, sh * 0.5, sw * 0.8, sh * 0.03)
            pygame.draw.rect(self.screen, GRAY, bar_rect, border_radius=4)

            fill_color = GREEN if pct > 0.3 else YELLOW if pct > 0.1 else RED
            fill_rect = pygame.Rect(sw * 0.1, sh * 0.5, sw * 0.8 * pct, sh * 0.03)
            pygame.draw.rect(self.screen, fill_color, fill_rect, border_radius=4)

            timer_text = f"{remaining:.0f}s"
            timer_rect = pygame.Rect(sw * 0.45, sh * 0.535, sw * 0.1, sh * 0.03)
            draw_text_centered(self.screen, timer_text, self.font_small, WHITE, timer_rect)

            if remaining <= 0:
                self.sound.stop_thinking_music()
                self.sound.play("times_up")
                self.state = STATE_ANSWER
                return

        # Buzz in instruction
        if self.state == STATE_QUESTION:
            buzz_rect = pygame.Rect(0, sh * 0.58, sw, sh * 0.06)
            draw_text_centered(
                self.screen,
                "SCAN / PRESS 1, 2, or 3 TO BUZZ IN!",
                self.font_button,
                YELLOW,
                buzz_rect,
            )

        # Buzzed-in team display
        if self.state == STATE_BUZZ_IN and self.buzzed_team is not None:
            buzz_rect = pygame.Rect(sw * 0.25, sh * 0.56, sw * 0.5, sh * 0.1)
            pygame.draw.rect(
                self.screen, TEAM_COLORS[self.buzzed_team], buzz_rect, border_radius=10
            )
            pygame.draw.rect(self.screen, WHITE, buzz_rect, 3, border_radius=10)
            draw_text_centered(
                self.screen,
                f"{self.team_names[self.buzzed_team]} BUZZED IN!",
                self.font_medium,
                WHITE,
                buzz_rect,
            )

        self.buttons = []

        if self.state == STATE_BUZZ_IN:
            # Correct / Wrong buttons
            btn_y = sh * 0.7
            correct_rect = pygame.Rect(sw * 0.15, btn_y, sw * 0.3, sh * 0.08)
            correct_btn = Button(correct_rect, "CORRECT (+$" + str(val) + ")", GREEN, WHITE, self.font_button)
            correct_btn.action = "correct"
            correct_btn.draw(self.screen)
            self.buttons.append(correct_btn)

            wrong_rect = pygame.Rect(sw * 0.55, btn_y, sw * 0.3, sh * 0.08)
            wrong_btn = Button(wrong_rect, "WRONG (-$" + str(val) + ")", RED, WHITE, self.font_button)
            wrong_btn.action = "wrong"
            wrong_btn.draw(self.screen)
            self.buttons.append(wrong_btn)

        if self.state in (STATE_QUESTION, STATE_BUZZ_IN):
            # Show Answer button
            show_rect = pygame.Rect(sw * 0.3, sh * 0.82, sw * 0.4, sh * 0.06)
            show_btn = Button(show_rect, "SHOW ANSWER", GOLD, BLACK, self.font_button)
            show_btn.action = "show_answer"
            show_btn.draw(self.screen)
            self.buttons.append(show_btn)

        if self.state == STATE_ANSWER:
            # Show the answer
            a_rect = pygame.Rect(sw * 0.08, sh * 0.56, sw * 0.84, sh * 0.2)
            pygame.draw.rect(self.screen, (20, 60, 20), a_rect, border_radius=10)
            pygame.draw.rect(self.screen, GREEN, a_rect, 3, border_radius=10)

            label_rect = pygame.Rect(sw * 0.08, sh * 0.57, sw * 0.84, sh * 0.05)
            draw_text_centered(self.screen, "ANSWER:", self.font_small, LIGHT_GRAY, label_rect)

            answer_rect = pygame.Rect(sw * 0.08, sh * 0.61, sw * 0.84, sh * 0.14)
            render_text_wrapped(self.screen, answer, self.font_answer, GREEN, answer_rect)

            # Award points buttons (if someone buzzed in)
            if self.buzzed_team is not None:
                btn_y = sh * 0.79
                correct_rect = pygame.Rect(sw * 0.15, btn_y, sw * 0.3, sh * 0.07)
                correct_btn = Button(correct_rect, "CORRECT (+$" + str(val) + ")", GREEN, WHITE, self.font_button)
                correct_btn.action = "correct"
                correct_btn.draw(self.screen)
                self.buttons.append(correct_btn)

                wrong_rect = pygame.Rect(sw * 0.55, btn_y, sw * 0.3, sh * 0.07)
                wrong_btn = Button(wrong_rect, "WRONG (-$" + str(val) + ")", RED, WHITE, self.font_button)
                wrong_btn.action = "wrong"
                wrong_btn.draw(self.screen)
                self.buttons.append(wrong_btn)

            # Back to board
            back_rect = pygame.Rect(sw * 0.35, sh * 0.89, sw * 0.3, sh * 0.06)
            back_btn = Button(back_rect, "BACK TO BOARD", BLUE_CELL, WHITE, self.font_button)
            back_btn.action = "back"
            back_btn.draw(self.screen)
            self.buttons.append(back_btn)

        # Scores at bottom
        self.draw_mini_scores()

    def draw_daily_double(self):
        """Draw Daily Double reveal screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        # Animated-ish "DAILY DOUBLE!" text
        dd_rect = pygame.Rect(0, sh * 0.15, sw, sh * 0.3)
        draw_text_centered(self.screen, "DAILY", self.font_title, GOLD, pygame.Rect(0, sh * 0.2, sw, sh * 0.12))
        draw_text_centered(self.screen, "DOUBLE!", self.font_title, GOLD, pygame.Rect(0, sh * 0.35, sw, sh * 0.12))

        # Stars/decoration
        for offset in [-200, -100, 100, 200]:
            star_x = sw // 2 + offset
            pygame.draw.polygon(
                self.screen,
                YELLOW,
                [
                    (star_x, sh * 0.18),
                    (star_x + 8, sh * 0.22),
                    (star_x + 15, sh * 0.22),
                    (star_x + 10, sh * 0.26),
                    (star_x + 12, sh * 0.32),
                    (star_x, sh * 0.28),
                    (star_x - 12, sh * 0.32),
                    (star_x - 10, sh * 0.26),
                    (star_x - 15, sh * 0.22),
                    (star_x - 8, sh * 0.22),
                ],
            )

        # Select team who picks
        inst_rect = pygame.Rect(0, sh * 0.52, sw, sh * 0.06)
        draw_text_centered(self.screen, "Which team found it?", self.font_medium, WHITE, inst_rect)

        self.buttons = []
        for i in range(3):
            x = sw * 0.1 + i * sw * 0.3
            rect = pygame.Rect(x, sh * 0.62, sw * 0.25, sh * 0.1)
            btn = Button(rect, self.team_names[i], TEAM_COLORS[i], WHITE, self.font_button)
            btn.action = f"dd_team_{i}"
            btn.draw(self.screen)
            self.buttons.append(btn)

    def draw_dd_wager(self):
        """Draw Daily Double wager screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        cat, val, question, answer, cat_idx, val_idx = self.current_question

        header_rect = pygame.Rect(0, sh * 0.05, sw, sh * 0.08)
        draw_text_centered(self.screen, "DAILY DOUBLE!", self.font_title, GOLD, header_rect)

        team_rect = pygame.Rect(0, sh * 0.16, sw, sh * 0.06)
        draw_text_centered(
            self.screen,
            f"{self.team_names[self.dd_team]}'s Wager",
            self.font_medium,
            TEAM_COLORS[self.dd_team],
            team_rect,
        )

        score_rect = pygame.Rect(0, sh * 0.24, sw, sh * 0.05)
        current_score = max(self.scores[self.dd_team], 0)
        max_wager = max(current_score, max(v for v, _, _ in self.categories[cat]))
        draw_text_centered(
            self.screen,
            f"Current Score: ${self.scores[self.dd_team]:,}  |  Max Wager: ${max_wager:,}",
            self.font_small,
            LIGHT_GRAY,
            score_rect,
        )

        # Wager input
        wager_rect = pygame.Rect(sw * 0.3, sh * 0.35, sw * 0.4, sh * 0.1)
        pygame.draw.rect(self.screen, BLUE_CELL, wager_rect, border_radius=8)
        pygame.draw.rect(self.screen, GOLD, wager_rect, 3, border_radius=8)
        display_wager = "$" + self.dd_wager if self.dd_wager else "Type wager amount..."
        color = GOLD if self.dd_wager else GRAY
        draw_text_centered(self.screen, display_wager, self.font_medium, color, wager_rect)

        # Quick wager buttons
        self.buttons = []
        quick_wagers = [100, 200, 500, 1000]
        for i, w in enumerate(quick_wagers):
            x = sw * 0.15 + i * sw * 0.18
            rect = pygame.Rect(x, sh * 0.5, sw * 0.15, sh * 0.06)
            btn = Button(rect, f"${w}", BLUE_CELL, GOLD, self.font_button)
            btn.action = f"wager_{w}"
            btn.draw(self.screen)
            self.buttons.append(btn)

        # All-in button
        allin_rect = pygame.Rect(sw * 0.35, sh * 0.58, sw * 0.3, sh * 0.06)
        allin_btn = Button(allin_rect, f"ALL IN (${max_wager})", RED, WHITE, self.font_button)
        allin_btn.action = f"wager_{max_wager}"
        allin_btn.draw(self.screen)
        self.buttons.append(allin_btn)

        # Confirm button
        confirm_rect = pygame.Rect(sw * 0.35, sh * 0.7, sw * 0.3, sh * 0.07)
        confirm_btn = Button(confirm_rect, "CONFIRM WAGER", GREEN, WHITE, self.font_button)
        confirm_btn.action = "confirm_wager"
        confirm_btn.draw(self.screen)
        self.buttons.append(confirm_btn)

    def draw_game_over(self):
        """Draw the game over / winner screen."""
        self.screen.fill(BLUE_DARK)
        sw, sh = self.screen_w, self.screen_h

        title_rect = pygame.Rect(0, sh * 0.05, sw, sh * 0.12)
        draw_text_centered(self.screen, "GAME OVER!", self.font_title, GOLD, title_rect)

        # Determine winner
        max_score = max(self.scores)
        winners = [i for i, s in enumerate(self.scores) if s == max_score]

        if len(winners) == 1:
            winner = winners[0]
            win_rect = pygame.Rect(0, sh * 0.2, sw, sh * 0.1)
            draw_text_centered(
                self.screen,
                f"{self.team_names[winner]} WINS!",
                self.font_title,
                TEAM_COLORS[winner],
                win_rect,
            )
        else:
            win_rect = pygame.Rect(0, sh * 0.2, sw, sh * 0.1)
            tie_names = " & ".join(self.team_names[w] for w in winners)
            draw_text_centered(self.screen, f"TIE: {tie_names}!", self.font_medium, YELLOW, win_rect)

        # Final scores
        for i in range(3):
            y = sh * 0.38 + i * sh * 0.15
            rect = pygame.Rect(sw * 0.2, y, sw * 0.6, sh * 0.12)
            pygame.draw.rect(self.screen, TEAM_COLORS[i], rect, border_radius=10)
            pygame.draw.rect(self.screen, WHITE, rect, 2, border_radius=10)

            # Rank
            sorted_scores = sorted(self.scores, reverse=True)
            rank = sorted_scores.index(self.scores[i]) + 1
            rank_text = {1: "1st", 2: "2nd", 3: "3rd"}.get(rank, f"{rank}th")

            text = f"{rank_text}  {self.team_names[i]}:  ${self.scores[i]:,}"
            draw_text_centered(self.screen, text, self.font_medium, WHITE, rect)

        self.buttons = []
        # Play Again
        again_rect = pygame.Rect(sw * 0.2, sh * 0.85, sw * 0.25, sh * 0.07)
        again_btn = Button(again_rect, "PLAY AGAIN", GREEN, WHITE, self.font_button)
        again_btn.action = "play_again"
        again_btn.draw(self.screen)
        self.buttons.append(again_btn)

        # New Questions
        new_rect = pygame.Rect(sw * 0.55, sh * 0.85, sw * 0.25, sh * 0.07)
        new_btn = Button(new_rect, "NEW QUESTIONS", BLUE_CELL, WHITE, self.font_button)
        new_btn.action = "new_questions"
        new_btn.draw(self.screen)
        self.buttons.append(new_btn)

    def draw_mini_scores(self):
        """Draw compact score display on question screens."""
        sw, sh = self.screen_w, self.screen_h
        for i in range(3):
            x = sw * 0.02 + i * sw * 0.33
            rect = pygame.Rect(x, sh * 0.95, sw * 0.3, sh * 0.045)
            pygame.draw.rect(self.screen, TEAM_COLORS[i], rect, border_radius=5)
            text = f"{self.team_names[i]}: ${self.scores[i]:,}"
            draw_text_centered(self.screen, text, self.font_small, WHITE, rect)

    # -----------------------------------------------------------------------
    # Event Handling
    # -----------------------------------------------------------------------
    def handle_buzz(self, team_index):
        """Handle a team buzzing in."""
        if self.state == STATE_QUESTION and self.current_question:
            self.buzzed_team = team_index
            self.state = STATE_BUZZ_IN
            self.sound.stop_thinking_music()
            self.sound.play("buzzer")

    def check_scanner_input(self, text):
        """Check if scanner input matches a team's barcode."""
        text = text.strip()
        if not text:
            return
        for i, code in enumerate(self.scanner_codes):
            if code and text == code:
                self.handle_buzz(i)
                return

    def handle_event(self, event):
        """Process a single pygame event."""
        mouse_pos = pygame.mouse.get_pos()

        # Update button hover states
        for btn in self.buttons:
            btn.update(mouse_pos)

        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.VIDEORESIZE:
            if not self.fullscreen:
                self.screen_w, self.screen_h = event.w, event.h
                self.screen = pygame.display.set_mode(
                    (self.screen_w, self.screen_h), pygame.RESIZABLE
                )
                self._init_fonts()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F11:
                self.toggle_fullscreen()
                return True

            # Scanner setup input
            if self.state == STATE_SCANNER_SETUP and self.scanner_setup_team < 3:
                if event.key == pygame.K_RETURN:
                    if self.scanner_buffer:
                        self.scanner_codes[self.scanner_setup_team] = self.scanner_buffer
                        SCANNER_MAP[self.scanner_buffer] = self.scanner_setup_team
                        self.scanner_setup_team += 1
                        self.scanner_buffer = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.scanner_buffer = self.scanner_buffer[:-1]
                elif event.unicode and event.unicode.isprintable():
                    self.scanner_buffer += event.unicode
                return True

            # Team name editing
            if self.state == STATE_TEAM_SETUP and self.editing_team >= 0:
                if event.key == pygame.K_RETURN:
                    if self.edit_text:
                        self.team_names[self.editing_team] = self.edit_text
                    self.editing_team = -1
                    self.edit_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.edit_text = self.edit_text[:-1]
                elif event.key == pygame.K_ESCAPE:
                    self.editing_team = -1
                    self.edit_text = ""
                elif event.unicode and event.unicode.isprintable():
                    self.edit_text += event.unicode
                return True

            # DD wager input
            if self.state == STATE_DD_WAGER:
                if event.key == pygame.K_RETURN:
                    self._confirm_wager()
                elif event.key == pygame.K_BACKSPACE:
                    self.dd_wager = self.dd_wager[:-1]
                elif event.unicode and event.unicode.isdigit():
                    self.dd_wager += event.unicode
                return True

            # Buzz in with keyboard 1/2/3
            if self.state == STATE_QUESTION:
                if event.key == pygame.K_1:
                    self.handle_buzz(0)
                elif event.key == pygame.K_2:
                    self.handle_buzz(1)
                elif event.key == pygame.K_3:
                    self.handle_buzz(2)
                elif event.key == pygame.K_ESCAPE:
                    self.sound.stop_thinking_music()
                    self.state = STATE_BOARD
                    self.current_question = None
                # Check for scanner input (arrives as rapid keystrokes + enter)
                elif event.key == pygame.K_RETURN:
                    self.check_scanner_input(self.scanner_buffer)
                    self.scanner_buffer = ""
                elif event.unicode and event.unicode.isprintable() and event.key not in (pygame.K_1, pygame.K_2, pygame.K_3):
                    self.scanner_buffer += event.unicode

            # Escape from answer view
            if self.state in (STATE_ANSWER, STATE_BUZZ_IN):
                if event.key == pygame.K_ESCAPE:
                    self.sound.stop_thinking_music()
                    self.state = STATE_BOARD
                    self.current_question = None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(mouse_pos)

        return True

    def _handle_click(self, pos):
        """Handle mouse click based on current state."""
        if self.state == STATE_FILE_SELECT:
            for btn in self.buttons:
                if btn.clicked(pos):
                    if hasattr(btn, "file_index"):
                        self.selected_file = btn.file_index
                    elif hasattr(btn, "action") and btn.action == "load":
                        if self.csv_files:
                            self.load_game(self.csv_files[self.selected_file])

        elif self.state == STATE_TEAM_SETUP:
            for btn in self.buttons:
                if btn.clicked(pos):
                    if hasattr(btn, "team_index"):
                        self.editing_team = btn.team_index
                        self.edit_text = self.team_names[btn.team_index]
                    elif hasattr(btn, "action"):
                        if btn.action == "continue_scanner":
                            self.state = STATE_SCANNER_SETUP
                            self.scanner_setup_team = 0
                            self.scanner_buffer = ""
                        elif btn.action == "skip_scanner":
                            self.state = STATE_BOARD

        elif self.state == STATE_SCANNER_SETUP:
            for btn in self.buttons:
                if btn.clicked(pos):
                    if hasattr(btn, "action"):
                        if btn.action == "start_game":
                            self.state = STATE_BOARD
                        elif btn.action == "skip_this_scanner":
                            if self.scanner_setup_team < 3:
                                self.scanner_setup_team += 1
                                self.scanner_buffer = ""

        elif self.state == STATE_BOARD:
            if hasattr(self, "board_cells"):
                for rect, ci, vi, cat, val, q, a in self.board_cells:
                    if rect.collidepoint(pos) and (ci, vi) not in self.answered:
                        self.answered.add((ci, vi))
                        self.current_question = (cat, val, q, a, ci, vi)
                        self.buzzed_team = None
                        self.scanner_buffer = ""

                        # Check daily double
                        if (ci, vi) in self.daily_doubles:
                            self.state = STATE_DAILY_DOUBLE
                            self.sound.play("daily_double")
                        else:
                            self.state = STATE_QUESTION
                            self.think_start = time.time()
                            self.sound.start_thinking_music()
                        break

        elif self.state == STATE_DAILY_DOUBLE:
            for btn in self.buttons:
                if btn.clicked(pos) and hasattr(btn, "action"):
                    if btn.action.startswith("dd_team_"):
                        self.dd_team = int(btn.action[-1])
                        self.dd_wager = ""
                        self.state = STATE_DD_WAGER

        elif self.state == STATE_DD_WAGER:
            for btn in self.buttons:
                if btn.clicked(pos) and hasattr(btn, "action"):
                    if btn.action.startswith("wager_"):
                        self.dd_wager = btn.action.split("_")[1]
                    elif btn.action == "confirm_wager":
                        self._confirm_wager()

        elif self.state in (STATE_QUESTION, STATE_BUZZ_IN, STATE_ANSWER):
            for btn in self.buttons:
                if btn.clicked(pos) and hasattr(btn, "action"):
                    if btn.action == "correct":
                        self._handle_correct()
                    elif btn.action == "wrong":
                        self._handle_wrong()
                    elif btn.action == "show_answer":
                        self.sound.stop_thinking_music()
                        self.state = STATE_ANSWER
                    elif btn.action == "back":
                        self.sound.stop_thinking_music()
                        self.state = STATE_BOARD
                        self.current_question = None

        elif self.state == STATE_GAME_OVER:
            for btn in self.buttons:
                if btn.clicked(pos) and hasattr(btn, "action"):
                    if btn.action == "play_again":
                        self.scores = [0, 0, 0]
                        self.answered = set()
                        self.setup_daily_doubles()
                        self.state = STATE_BOARD
                    elif btn.action == "new_questions":
                        self.scores = [0, 0, 0]
                        self.state = STATE_FILE_SELECT
                        self.csv_files = get_csv_files()

    def _confirm_wager(self):
        """Confirm a daily double wager and show the question."""
        if not self.dd_wager:
            return
        try:
            wager = int(self.dd_wager)
        except ValueError:
            return

        cat = self.current_question[0]
        current_score = max(self.scores[self.dd_team], 0)
        max_wager = max(current_score, max(v for v, _, _ in self.categories[cat]))
        wager = max(0, min(wager, max_wager))

        # Store wager as the value for scoring
        self.current_question = (
            self.current_question[0],
            wager,
            self.current_question[2],
            self.current_question[3],
            self.current_question[4],
            self.current_question[5],
        )
        self.buzzed_team = self.dd_team
        self.state = STATE_QUESTION
        self.think_start = time.time()
        self.sound.start_thinking_music()

    def _handle_correct(self):
        """Handle a correct answer."""
        if self.buzzed_team is not None and self.current_question:
            val = self.current_question[1]
            self.scores[self.buzzed_team] += val
            self.sound.play("correct")
        self.sound.stop_thinking_music()
        self.state = STATE_BOARD
        self.current_question = None

    def _handle_wrong(self):
        """Handle a wrong answer."""
        if self.buzzed_team is not None and self.current_question:
            val = self.current_question[1]
            self.scores[self.buzzed_team] -= val
            self.sound.play("wrong")
        # Go back to question for other teams to buzz in
        self.buzzed_team = None
        if self.state == STATE_ANSWER:
            # Already showed answer, go to board
            self.sound.stop_thinking_music()
            self.state = STATE_BOARD
            self.current_question = None
        else:
            self.state = STATE_QUESTION
            self.think_start = time.time()
            self.sound.start_thinking_music()

    # -----------------------------------------------------------------------
    # Main Loop
    # -----------------------------------------------------------------------
    def run(self):
        """Main game loop."""
        running = True
        while running:
            for event in pygame.event.get():
                if not self.handle_event(event):
                    running = False
                    break

            # Draw current state
            if self.state == STATE_FILE_SELECT:
                self.draw_file_select()
            elif self.state == STATE_TEAM_SETUP:
                self.draw_team_setup()
            elif self.state == STATE_SCANNER_SETUP:
                self.draw_scanner_setup()
            elif self.state == STATE_BOARD:
                self.draw_board()
            elif self.state in (STATE_QUESTION, STATE_BUZZ_IN, STATE_ANSWER):
                self.draw_question()
            elif self.state == STATE_DAILY_DOUBLE:
                self.draw_daily_double()
            elif self.state == STATE_DD_WAGER:
                self.draw_dd_wager()
            elif self.state == STATE_GAME_OVER:
                self.draw_game_over()

            pygame.display.flip()
            self.clock.tick(30)

        pygame.quit()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    game = JeopardyGame()
    game.run()
