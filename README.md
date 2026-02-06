# Classroom Jeopardy Game

A Jeopardy-style review game built with Python/Pygame for classroom use.

## Features

- **Full Jeopardy game board** - Click categories and dollar values
- **CSV question sets** - Easy to create and swap question sets
- **3 barcode scanner support** - Students scan to "buzz in"
- **Keyboard buzzer fallback** - Press 1, 2, or 3 to buzz in
- **Thinking music & sound effects** - Timed question rounds with audio
- **Score tracking** - Automatic scoring with correct/wrong buttons
- **Daily Doubles** - Randomly placed with custom wager support
- **Fullscreen mode** - Press F11 to toggle

## Quick Start

```bash
# Install pygame
pip install pygame

# Generate sound effects (first time only)
python3 generate_sounds.py

# Run the game
python3 jeopardy.py
```

## CSV Question Format

Place CSV files in the `questions/` folder. Format:

```csv
Category,Value,Question,Answer
Plate Tectonics,100,The theory that Earth's crust is broken into large moving pieces is called this.,Plate Tectonics
Plate Tectonics,200,This supercontinent existed about 250 million years ago.,Pangea
```

- **Category**: Groups questions into columns (5 categories recommended)
- **Value**: Point value (100, 200, 300, 400, 500 recommended)
- **Question**: The question text
- **Answer**: The correct answer

Each category should have the same number of values (typically 5).

## Controls

| Action | Control |
|--------|---------|
| Select a question | Click the dollar amount on the board |
| Buzz in (Team 1) | Barcode scanner 1 or press `1` |
| Buzz in (Team 2) | Barcode scanner 2 or press `2` |
| Buzz in (Team 3) | Barcode scanner 3 or press `3` |
| Return to board | Press `ESC` |
| Toggle fullscreen | Press `F11` |

## Barcode Scanner Setup

During the Scanner Setup screen:
1. Scan each team's barcode when prompted
2. The game maps each barcode to a team
3. During gameplay, scanning acts as a buzzer

If you don't have scanners, skip setup and use keyboard keys 1/2/3.

## Game Flow

1. **Select a question set** from available CSV files
2. **Set up team names** (click to edit)
3. **Configure scanners** (or skip for keyboard mode)
4. **Play!** - Host clicks questions, students buzz in
5. Host judges answers and clicks Correct/Wrong
6. Game ends when all questions are answered

## Creating Your Own Questions

Create a new `.csv` file in the `questions/` folder with:
- 5 categories (columns on the board)
- 5 questions per category (100-500 point values)
- Total of 25 questions per game
