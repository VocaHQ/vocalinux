#!/usr/bin/env python3
"""Generate Vocalinux notification WAVs.

Writes 16-bit PCM mono files at 44.1 kHz into resources/sounds/:

- start_recording.wav / stop_recording.wav / error.wav: the original Linux
  pair. Kept on disk; not used as the implicit default anymore.
- {id}_start.wav / {id}_stop.wav for each family tone except Off.

Usage:
    python scripts/generate_sounds.py
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import wave

SAMPLE_RATE = 44100

# Named pitches used by the family catalog.
G2 = 98.00
C3 = 130.81
D3 = 146.83
F3 = 174.61
G3 = 196.00
C4 = 261.63
E4 = 329.63
F4 = 349.23
G4 = 392.00
A4 = 440.00
C5 = 523.25
A5 = 880.00
C6 = 1046.50
E7 = 2637.02
C7 = 2093.00


def _smoothstep(progress: float) -> float:
    return progress * progress * (3.0 - 2.0 * progress)


def _sine_envelope(progress: float) -> float:
    return (math.sin(math.pi * progress) ** 2) * math.exp(-0.5 * progress)


def generate_glide_tone(
    filename: str,
    freq_start: float,
    freq_end: float,
    duration: float = 0.6,
    amplitude: float = 0.16,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Generate a smooth pitch glide tone (original Linux pair recipe)."""
    num_samples = int(sample_rate * duration)
    samples = []

    for i in range(num_samples):
        t = i / sample_rate
        progress = i / num_samples
        envelope = _sine_envelope(progress)
        glide = _smoothstep(progress)
        freq_current = freq_start + (freq_end - freq_start) * glide
        phase = 2 * math.pi * freq_current * t
        samples.append(amplitude * envelope * math.sin(phase))

    _write_wav(filename, samples, sample_rate)


def _write_wav(filename: str, samples: list[float], sample_rate: int = SAMPLE_RATE) -> None:
    wav_samples = [int(max(-1.0, min(1.0, sample)) * 32767) for sample in samples]
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    with wave.open(filename, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack("<" + "h" * len(wav_samples), *wav_samples))
    print(f"Generated: {filename}")


def _tone_burst(
    freq: float,
    duration: float,
    amplitude: float = 0.12,
    decay: float = 8.0,
) -> list[float]:
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        progress = i / max(n - 1, 1)
        attack = min(1.0, i / max(int(0.004 * SAMPLE_RATE), 1))
        env = attack * math.exp(-decay * t) * (1.0 - 0.15 * progress)
        samples.append(amplitude * env * math.sin(2 * math.pi * freq * t))
    return samples


def _silence(duration: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration)


def generate_ticks(
    filename: str,
    freqs: tuple[float, ...],
    tick_duration: float = 0.07,
    gap: float = 0.045,
    amplitude: float = 0.11,
    decay: float = 14.0,
) -> None:
    samples: list[float] = []
    for index, freq in enumerate(freqs):
        if index:
            samples.extend(_silence(gap))
        samples.extend(_tone_burst(freq, tick_duration, amplitude, decay))
    _write_wav(filename, samples)


def generate_fifth_swell(
    filename: str,
    low: float,
    high: float,
    duration: float = 0.42,
    amplitude: float = 0.13,
    opening: bool = True,
) -> None:
    """Open-fifth swell. Start opens C4→G4; stop closes G4→C4."""
    n = int(SAMPLE_RATE * duration)
    samples = []
    phase_low = 0.0
    phase_high = 0.0
    dt = 1.0 / SAMPLE_RATE
    for i in range(n):
        progress = i / max(n - 1, 1)
        env = math.sin(math.pi * progress) ** 2
        blend = _smoothstep(progress)
        if opening:
            low_amt = 1.0
            high_amt = blend
        else:
            low_amt = 1.0
            high_amt = 1.0 - blend
        sample = (
            amplitude
            * env
            * (low_amt * math.sin(phase_low) + 0.85 * high_amt * math.sin(phase_high))
        )
        samples.append(sample)
        phase_low += 2 * math.pi * low * dt
        phase_high += 2 * math.pi * high * dt
    _write_wav(filename, samples)


def generate_ping(
    filename: str, freq: float, duration: float = 0.32, amplitude: float = 0.12
) -> None:
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-14.0 * t)
        samples.append(amplitude * env * math.sin(2 * math.pi * freq * t))
    _write_wav(filename, samples)


def generate_scale(
    filename: str,
    freqs: tuple[float, ...],
    note_duration: float = 0.085,
    gap: float = 0.02,
    amplitude: float = 0.12,
) -> None:
    generate_ticks(filename, freqs, note_duration, gap, amplitude, decay=9.0)


def _maybe_write_original(path: str, writer) -> None:
    if os.path.exists(path):
        print(f"Keeping existing: {path}")
        return
    writer()


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    sounds_dir = os.path.join(repo_root, "resources", "sounds")
    os.makedirs(sounds_dir, exist_ok=True)
    print(f"Generating sounds in: {sounds_dir}\n")

    start_path = os.path.join(sounds_dir, "start_recording.wav")
    stop_path = os.path.join(sounds_dir, "stop_recording.wav")
    error_path = os.path.join(sounds_dir, "error.wav")

    _maybe_write_original(
        start_path,
        lambda: generate_glide_tone(start_path, F4, A4, duration=0.6, amplitude=0.16),
    )
    _maybe_write_original(
        stop_path,
        lambda: generate_glide_tone(stop_path, A4, F4, duration=0.6, amplitude=0.16),
    )
    _maybe_write_original(
        error_path,
        lambda: generate_glide_tone(error_path, E4, C4, duration=0.7, amplitude=0.14),
    )

    # lift: Linux-family F4→A4 sine glide (own files; does not replace the originals)
    generate_glide_tone(os.path.join(sounds_dir, "lift_start.wav"), F4, A4, 0.48, 0.16)
    generate_glide_tone(os.path.join(sounds_dir, "lift_stop.wav"), A4, F4, 0.48, 0.16)

    # flick: same interval, shorter
    generate_glide_tone(os.path.join(sounds_dir, "flick_start.wav"), F4, A4, 0.18, 0.15)
    generate_glide_tone(os.path.join(sounds_dir, "flick_stop.wav"), A4, F4, 0.18, 0.15)

    # ember: low warm G3→C4
    generate_glide_tone(os.path.join(sounds_dir, "ember_start.wav"), G3, C4, 0.55, 0.15)
    generate_glide_tone(os.path.join(sounds_dir, "ember_stop.wav"), C4, G3, 0.55, 0.15)

    # step: two soft C/E ticks
    generate_ticks(os.path.join(sounds_dir, "step_start.wav"), (C4, E4), 0.07, 0.05, 0.11)
    generate_ticks(os.path.join(sounds_dir, "step_stop.wav"), (E4, C4), 0.07, 0.05, 0.11)

    # voca: open fifth swell (id is voca, not fifth)
    generate_fifth_swell(os.path.join(sounds_dir, "voca_start.wav"), C4, G4, 0.44, 0.14, True)
    generate_fifth_swell(os.path.join(sounds_dir, "voca_stop.wav"), C4, G4, 0.40, 0.13, False)

    # soft: very short muted ticks
    generate_ticks(os.path.join(sounds_dir, "soft_start.wav"), (C5,), 0.05, 0.0, 0.07, decay=22.0)
    generate_ticks(os.path.join(sounds_dir, "soft_stop.wav"), (A4,), 0.055, 0.0, 0.07, decay=22.0)

    # chirp: light high chirp
    generate_glide_tone(os.path.join(sounds_dir, "chirp_start.wav"), A5, C6, 0.09, 0.10)
    generate_glide_tone(os.path.join(sounds_dir, "chirp_stop.wav"), C6, A5, 0.10, 0.10)

    # scale: pentatonic A4→C5
    generate_scale(os.path.join(sounds_dir, "scale_start.wav"), (A4, C5), 0.09, 0.025, 0.12)
    generate_scale(os.path.join(sounds_dir, "scale_stop.wav"), (C5, A4), 0.09, 0.025, 0.12)

    # drop: low start, deeper stop
    generate_glide_tone(os.path.join(sounds_dir, "drop_start.wav"), D3, F3, 0.40, 0.16)
    generate_glide_tone(os.path.join(sounds_dir, "drop_stop.wav"), C3, G2, 0.48, 0.16)

    # glass: thin glass ping
    generate_ping(os.path.join(sounds_dir, "glass_start.wav"), E7, 0.30, 0.10)
    generate_ping(os.path.join(sounds_dir, "glass_stop.wav"), C7, 0.34, 0.09)

    # Package data lives in src/vocalinux/resources and is what ResourceManager
    # prefers when running from a checkout. Keep both trees in sync.
    packaged_dir = os.path.join(repo_root, "src", "vocalinux", "resources", "sounds")
    os.makedirs(packaged_dir, exist_ok=True)
    for name in os.listdir(sounds_dir):
        if not name.endswith(".wav"):
            continue
        if name in {"start_recording.wav", "stop_recording.wav", "error.wav"}:
            continue
        shutil.copy2(os.path.join(sounds_dir, name), os.path.join(packaged_dir, name))
        print(f"Copied: {os.path.join(packaged_dir, name)}")

    print("\nCatalog pairs written. Original start/stop/error files were left in place.")


if __name__ == "__main__":
    main()
