#!/usr/bin/env python3
"""Generate sound effects for the Jeopardy game using pygame/wave synthesis."""
import struct
import wave
import math
import os

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
SAMPLE_RATE = 44100


def generate_tone(freq, duration, volume=0.5, sample_rate=SAMPLE_RATE):
    """Generate a sine wave tone."""
    n_samples = int(sample_rate * duration)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        # Apply fade in/out envelope
        envelope = 1.0
        fade = int(0.01 * sample_rate)
        if i < fade:
            envelope = i / fade
        elif i > n_samples - fade:
            envelope = (n_samples - i) / fade
        value = volume * envelope * math.sin(2 * math.pi * freq * t)
        samples.append(int(value * 32767))
    return samples


def write_wav(filename, samples, sample_rate=SAMPLE_RATE):
    """Write samples to a WAV file."""
    filepath = os.path.join(SOUNDS_DIR, filename)
    with wave.open(filepath, "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for s in samples:
            wav.writeframes(struct.pack("<h", max(-32767, min(32767, s))))
    print(f"  Created {filepath}")


def generate_thinking_music():
    """Generate Jeopardy-style thinking music (~30 seconds)."""
    # Classic Jeopardy think music melody pattern (simplified)
    # Using a sequence of notes that evokes the feel
    notes = [
        # (frequency_hz, duration_seconds)
        # Measure 1-2: Main theme
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.5), (392, 0.5),
        (330, 0.25), (294, 0.25), (330, 0.25), (392, 0.25),
        (349, 1.0),
        # Measure 3-4
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.25), (587, 0.25), (523, 0.25), (494, 0.25),
        (440, 0.25), (392, 0.25), (349, 0.25), (330, 0.25),
        (294, 1.0),
        # Measure 5-6: Repeat with variation
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.5), (392, 0.5),
        (330, 0.25), (294, 0.25), (330, 0.25), (392, 0.25),
        (349, 1.0),
        # Measure 7-8: Rising tension
        (440, 0.25), (494, 0.25), (523, 0.25), (587, 0.25),
        (523, 0.25), (494, 0.25), (440, 0.25), (392, 0.25),
        (349, 0.25), (330, 0.25), (294, 0.25), (262, 0.25),
        (294, 1.0),
        # Measure 9-10: Repeat main theme
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.5), (392, 0.5),
        (330, 0.25), (294, 0.25), (330, 0.25), (392, 0.25),
        (349, 1.0),
        # Measure 11-12
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.25), (587, 0.25), (523, 0.25), (494, 0.25),
        (440, 0.25), (392, 0.25), (349, 0.25), (330, 0.25),
        (294, 1.0),
        # Final measures - resolution
        (392, 0.25), (330, 0.25), (392, 0.25), (523, 0.25),
        (494, 0.5), (440, 0.5),
        (392, 1.5),
    ]

    all_samples = []
    for freq, dur in notes:
        all_samples.extend(generate_tone(freq, dur, volume=0.35))

    write_wav("thinking.wav", all_samples)


def generate_buzzer_sound():
    """Generate a buzzer/ring-in sound."""
    samples = []
    # Two-tone ascending beep
    samples.extend(generate_tone(880, 0.1, volume=0.6))
    samples.extend(generate_tone(1320, 0.15, volume=0.6))
    write_wav("buzzer.wav", samples)


def generate_correct_sound():
    """Generate a 'correct answer' ding."""
    samples = []
    # Pleasant ascending chord
    n_samples = int(SAMPLE_RATE * 0.4)
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        envelope = 1.0
        fade = int(0.01 * SAMPLE_RATE)
        decay_start = int(0.1 * SAMPLE_RATE)
        if i < fade:
            envelope = i / fade
        elif i > decay_start:
            envelope = max(0, 1.0 - (i - decay_start) / (n_samples - decay_start))
        value = 0.3 * envelope * (
            math.sin(2 * math.pi * 523 * t) +
            math.sin(2 * math.pi * 659 * t) +
            math.sin(2 * math.pi * 784 * t)
        )
        samples.append(int(value * 32767))
    write_wav("correct.wav", samples)


def generate_wrong_sound():
    """Generate an 'incorrect answer' buzz."""
    samples = []
    n_samples = int(SAMPLE_RATE * 0.5)
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        envelope = 1.0
        fade = int(0.01 * SAMPLE_RATE)
        if i < fade:
            envelope = i / fade
        elif i > n_samples - int(0.1 * SAMPLE_RATE):
            envelope = (n_samples - i) / int(0.1 * SAMPLE_RATE)
        # Dissonant low buzz
        value = 0.3 * envelope * (
            math.sin(2 * math.pi * 150 * t) +
            0.5 * math.sin(2 * math.pi * 155 * t) +
            0.3 * math.sin(2 * math.pi * 310 * t)
        )
        samples.append(int(value * 32767))
    write_wav("wrong.wav", samples)


def generate_daily_double_sound():
    """Generate a daily double reveal sound."""
    samples = []
    # Dramatic ascending fanfare
    freqs = [(392, 0.15), (494, 0.15), (587, 0.15), (784, 0.4)]
    for freq, dur in freqs:
        n = int(SAMPLE_RATE * dur)
        for i in range(n):
            t = i / SAMPLE_RATE
            envelope = 1.0
            fade = int(0.01 * SAMPLE_RATE)
            if i < fade:
                envelope = i / fade
            elif i > n - fade:
                envelope = (n - i) / fade
            value = 0.4 * envelope * (
                math.sin(2 * math.pi * freq * t) +
                0.5 * math.sin(2 * math.pi * freq * 1.5 * t)
            )
            samples.append(int(value * 32767))
    write_wav("daily_double.wav", samples)


def generate_times_up_sound():
    """Generate a time's up sound."""
    samples = []
    # Three descending beeps
    for freq in [880, 660, 440]:
        samples.extend(generate_tone(freq, 0.2, volume=0.5))
        samples.extend([0] * int(SAMPLE_RATE * 0.05))
    write_wav("times_up.wav", samples)


if __name__ == "__main__":
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    print("Generating game sounds...")
    generate_thinking_music()
    generate_buzzer_sound()
    generate_correct_sound()
    generate_wrong_sound()
    generate_daily_double_sound()
    generate_times_up_sound()
    print("Done! All sounds saved to", SOUNDS_DIR)
