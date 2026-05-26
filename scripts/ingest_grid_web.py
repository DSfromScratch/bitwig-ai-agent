"""
Ingest Bitwig Grid module data from official documentation into Neo4j.

Source: https://www.bitwig.com/userguide/latest/grid_modules/
Focuses on musically relevant Grid modules with parameter descriptions.

Usage:
    source .venv/bin/activate
    python scripts/ingest_grid_web.py [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from neo4j import GraphDatabase

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jllm")

# ── Grid module data from official Bitwig documentation ──────────────────────
# Format: {name, type, description, use_case, category, params: [{name, description, range, low_means, high_means, tip}]}

GRID_MODULES = [

    # ── Filters ──────────────────────────────────────────────────────────────
    {
        "name": "SVF",
        "type": "fx",
        "description": "State Variable Filter — highly resonant multimode filter with simultaneous LP/BP/HP outputs",
        "use_case": "Classic subtractive synthesis filter; great for acid bass, leads, sweeps",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "dark, muffled tone", "high_means": "bright, open tone", "tip": "Modulate with ADSR envelope for classic synth sweeps"},
            {"name": "Resonance", "description": "Filter resonance / Q", "range": "0–1", "low_means": "smooth, gentle filter", "high_means": "self-oscillation, piercing peak", "tip": "At max resonance SVF self-oscillates as a sine wave oscillator"},
            {"name": "Drive", "description": "Input saturation before filter", "range": "0–1", "low_means": "clean signal", "high_means": "warm saturation and harmonic distortion", "tip": "Use light drive for analog warmth"},
        ],
    },
    {
        "name": "Low-pass LD",
        "type": "fx",
        "description": "Resonant low-pass ladder filter inspired by classic Moog ladder topology",
        "use_case": "Warm bass filtering, classic analog synth sounds",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "very dark, sub-bass only", "high_means": "fully open, all harmonics pass", "tip": "Ladder filter sounds especially warm with slow envelope modulation"},
            {"name": "Resonance", "description": "Ladder resonance / Q", "range": "0–1", "low_means": "no resonant peak", "high_means": "strong resonant peak, self-oscillation at max", "tip": "Classic Moog style: resonance around 0.6–0.8 for character without self-oscillation"},
        ],
    },
    {
        "name": "Low-pass MG",
        "type": "fx",
        "description": "Moog-inspired low-pass filter with Drive control for saturation",
        "use_case": "Warm analog low-pass filtering with drive character",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "dark filtered tone", "high_means": "bright open tone", "tip": "Combine with Drive for classic analog warmth"},
            {"name": "Resonance", "description": "Filter resonance", "range": "0–1", "low_means": "smooth filter", "high_means": "resonant peak near self-oscillation", "tip": ""},
            {"name": "Drive", "description": "Input saturation level", "range": "0–1", "low_means": "clean", "high_means": "overdriven, harmonically rich", "tip": "Drive into the filter for warm saturation characteristic of Moog circuits"},
        ],
    },
    {
        "name": "Sallen-Key",
        "type": "fx",
        "description": "Resonant Sallen-Key filter with 16 models including LP/HP/BP at various slopes",
        "use_case": "Versatile filter for any subtractive synthesis task",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "dark tone", "high_means": "bright tone", "tip": ""},
            {"name": "Resonance", "description": "Filter resonance", "range": "0–1", "low_means": "flat response", "high_means": "strong resonant peak", "tip": ""},
            {"name": "Model", "description": "Filter topology: LP/HP/BP at 6/12/24 dB/oct slopes", "range": "16 options", "low_means": "low-pass models", "high_means": "high-pass / band-pass models", "tip": "Use 24 dB LP for classic analog bass, 12 dB BP for nasal midrange sounds"},
        ],
    },
    {
        "name": "XP",
        "type": "fx",
        "description": "15 filter configurations inspired by Oberheim synthesizers",
        "use_case": "Classic Oberheim/Xpander filter sounds, evolving pad textures",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "closed, dark tone", "high_means": "open, bright tone", "tip": ""},
            {"name": "Resonance", "description": "Filter resonance", "range": "0–1", "low_means": "smooth", "high_means": "sharp resonant character", "tip": "XP at high resonance produces distinctive Oberheim character"},
            {"name": "Model", "description": "One of 15 filter configurations (LP/BP/HP/Notch combinations)", "range": "15 options", "low_means": "low-pass modes", "high_means": "complex multi-mode configurations", "tip": "Try all-pass and notch models for phaser-like timbres"},
        ],
    },
    {
        "name": "Comb",
        "type": "fx",
        "description": "Comb filter creating resonant peaks/notches via short delay feedback",
        "use_case": "Metallic flanging effects, Karplus-Strong string synthesis, comb filtering",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Comb delay time / fundamental frequency", "range": "Hz", "low_means": "low pitch resonance, long delay", "high_means": "high pitch resonance, short delay", "tip": "Set to match note pitch via Key Tracking for Karplus-Strong strings"},
            {"name": "Feedback", "description": "Amount of delayed signal fed back into the filter", "range": "0–1", "low_means": "short decay, subtle effect", "high_means": "long sustain, near-infinite resonance", "tip": "High feedback with filtered noise input = convincing plucked string"},
            {"name": "Dampening Frequency", "description": "Low-pass filter in feedback path to damp high frequencies", "range": "Hz", "low_means": "dark, warm decay like nylon string", "high_means": "bright, metallic sustain like steel string", "tip": ""},
        ],
    },
    {
        "name": "Vowels",
        "type": "fx",
        "description": "Formant filter producing vowel sounds with five vowel position choosers",
        "use_case": "Vocal formant effects, talking synth, vowel movement on pads/leads",
        "category": "filter",
        "params": [
            {"name": "Vowel Blend", "description": "Crossfades between two vowel positions", "range": "0–1", "low_means": "first vowel position", "high_means": "second vowel position", "tip": "Modulate Vowel Blend with LFO or envelope for vowel movement effect"},
            {"name": "Vowel Position", "description": "One of 27 vowel sounds per position (A, E, I, O, U variants)", "range": "27 options", "low_means": "open vowels (A/O)", "high_means": "closed vowels (I/U)", "tip": "Use two contrasting vowels (A→I or O→U) for most expressive movement"},
            {"name": "Profile", "description": "Vocal profile: Women / Male / Kids variants", "range": "3 options", "low_means": "female formants (higher)", "high_means": "kids formants (highest)", "tip": "Mix profiles across voices for choir effect"},
            {"name": "Resonance", "description": "Filter resonance / Q for formant peaks", "range": "0–1", "low_means": "smooth, natural vowel tone", "high_means": "exaggerated, synthetic vowel effect", "tip": ""},
            {"name": "Drive", "description": "Input saturation", "range": "0–1", "low_means": "clean vowel filter", "high_means": "distorted vocal character", "tip": ""},
        ],
    },
    {
        "name": "Fizz",
        "type": "fx",
        "description": "Character filter spreading harmonic nodes with feedback gain and color control",
        "use_case": "Adding metallic fizz character, enhancing high-frequency harmonics",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "fizz in low frequencies", "high_means": "fizz in high frequencies", "tip": ""},
            {"name": "Feedback Gain", "description": "Feedback amount for resonant character", "range": "0–1", "low_means": "subtle harmonic spread", "high_means": "extreme metallic fizzing", "tip": ""},
            {"name": "Color", "description": "Bipolar tonal color of the feedback", "range": "-1 to +1", "low_means": "warm, dark fizz", "high_means": "bright, harsh fizz", "tip": ""},
            {"name": "Drive", "description": "Input saturation", "range": "0–1", "low_means": "clean", "high_means": "saturated", "tip": ""},
        ],
    },
    {
        "name": "Ripple",
        "type": "fx",
        "description": "Character filter with hyper-resonance; Nature settings Earth/Wind/Fire",
        "use_case": "Extreme resonant textures, sci-fi sounds, hyper-resonant sweeps",
        "category": "filter",
        "params": [
            {"name": "Cutoff", "description": "Filter cutoff frequency", "range": "Hz", "low_means": "low-frequency resonance", "high_means": "high-frequency resonance", "tip": ""},
            {"name": "Nature", "description": "Character preset: Earth / Wind / Fire", "range": "3 modes", "low_means": "Earth: grounded, deep resonance", "high_means": "Fire: bright, aggressive resonance", "tip": "Wind is the most versatile for melodic use"},
            {"name": "Feedback Gain", "description": "Bipolar feedback intensity", "range": "-1 to +1", "low_means": "negative feedback (cancellation)", "high_means": "positive feedback (resonance buildup)", "tip": ""},
            {"name": "Drive", "description": "Input saturation", "range": "0–1", "low_means": "clean", "high_means": "heavily distorted", "tip": ""},
        ],
    },

    # ── Oscillators ──────────────────────────────────────────────────────────
    {
        "name": "Wavetable",
        "type": "oscillator",
        "description": "Wavetable oscillator with 200+ factory wavetables, visual browser, three unison modes",
        "use_case": "Complex evolving timbres, supersaw-style leads, morphing pads",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Oscillator pitch/tuning", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Table Index", "description": "Position within the wavetable (morphs between waveforms)", "range": "0–1 (stereo)", "low_means": "first waveform in table", "high_means": "last waveform in table", "tip": "Modulate with LFO for continuous timbre morphing"},
            {"name": "Unison", "description": "Unison mode: Fat / Focused / Complex", "range": "3 modes", "low_means": "Fat: classic detuned unison", "high_means": "Complex: phase-complex unison", "tip": "Fat unison with Detune ~0.3 for classic supersaw"},
            {"name": "Detune", "description": "Unison voice detuning amount", "range": "0–1", "low_means": "tight, in-tune unison", "high_means": "wide, chorus-like detuning", "tip": ""},
            {"name": "Voices", "description": "Number of unison voices", "range": "1–8", "low_means": "single voice, clean", "high_means": "8 voices, massive unison", "tip": "More voices = more CPU and more width"},
        ],
    },
    {
        "name": "Bite",
        "type": "oscillator",
        "description": "Dual oscillator with exponential FM, hard sync, PWM, ring mod; seven waveshapes, dual feedback",
        "use_case": "Aggressive leads, FM-tinged basses, complex harmonic timbres",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Oscillator pitch", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Waveform", "description": "One of seven waveshapes (Sine, Triangle, Saw, Square variants)", "range": "7 options", "low_means": "sine/triangle (smooth, simple)", "high_means": "saw/square variants (bright, rich harmonics)", "tip": "Start with Saw for FM-style sounds"},
            {"name": "Feedback", "description": "Self-FM feedback amount for both oscillators", "range": "0–1", "low_means": "clean oscillator tone", "high_means": "extreme self-FM distortion and noise", "tip": "Small feedback amounts add harmonics without going chaotic"},
            {"name": "FM Amount", "description": "Exponential FM depth from osc2 into osc1", "range": "0–1", "low_means": "no frequency modulation", "high_means": "wide FM sidebands", "tip": ""},
            {"name": "Sync", "description": "Hard sync osc2 to osc1", "range": "off/on", "low_means": "free-running oscillators", "high_means": "osc2 synced to osc1 for timbral variation", "tip": "Sweep Pitch2 with sync on for classic hard sync sweep"},
        ],
    },
    {
        "name": "Scrawl",
        "type": "oscillator",
        "description": "Freely drawable segmented oscillator with anti-aliasing, stereo detune, and key tracking",
        "use_case": "Custom waveforms, drawn oscillator shapes, unusual timbres",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Oscillator pitch", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Pitch Offset", "description": "Fine pitch offset from base pitch", "range": "±semitones", "low_means": "below base pitch", "high_means": "above base pitch", "tip": ""},
            {"name": "Detune", "description": "Stereo detuning between left/right channels", "range": "0–1", "low_means": "mono, perfectly tuned", "high_means": "wide stereo with beating", "tip": ""},
            {"name": "Numerator / Denominator", "description": "Frequency ratio multiplier for polyrhythmic relationships", "range": "integers", "low_means": "lower harmonic relationship", "high_means": "higher harmonic relationship", "tip": "Use integer ratios for harmonic relationships, fractional for inharmonic timbres"},
        ],
    },
    {
        "name": "Swarm",
        "type": "oscillator",
        "description": "Unison oscillator with many detuned voices for massive sounds",
        "use_case": "Supersaw pads, thick leads, wall-of-sound textures",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Base pitch of all unison voices", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Detune", "description": "Detuning spread across unison voices", "range": "0–1", "low_means": "tight, almost mono", "high_means": "wide chorus-like detuning", "tip": "Detune 0.2–0.4 for classic supersaw without going out of tune"},
            {"name": "Voices", "description": "Number of unison voices", "range": "2–16", "low_means": "fewer voices, thinner sound", "high_means": "many voices, massive thick sound", "tip": "More voices increases CPU load significantly"},
        ],
    },
    {
        "name": "Phase-1",
        "type": "oscillator",
        "description": "Phase distortion oscillator inspired by Casio CZ synthesis",
        "use_case": "Classic CZ-style timbres, bell and reed sounds, bright digital tones",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Oscillator pitch", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Distortion", "description": "Amount of phase distortion applied to the waveform", "range": "0–1", "low_means": "clean sine-like wave", "high_means": "heavily distorted, rich harmonics", "tip": "Modulate Distortion with envelope for evolving timbre"},
            {"name": "Waveform", "description": "Base waveform type before phase distortion", "range": "options", "low_means": "simple waveforms", "high_means": "complex waveforms", "tip": ""},
        ],
    },
    {
        "name": "Union",
        "type": "oscillator",
        "description": "DC-drifting analog-inspired oscillator blending pulse, saw, and triangle with individual level controls",
        "use_case": "Warm analog-style oscillator for basses, pads, and leads",
        "category": "oscillator",
        "params": [
            {"name": "Pitch", "description": "Oscillator pitch", "range": "semitones", "low_means": "lower pitch", "high_means": "higher pitch", "tip": ""},
            {"name": "Pulse Level", "description": "Mix level of pulse/square waveform", "range": "0–1", "low_means": "no pulse wave", "high_means": "full pulse contribution", "tip": ""},
            {"name": "Saw Level", "description": "Mix level of sawtooth waveform", "range": "0–1", "low_means": "no saw wave", "high_means": "full saw contribution", "tip": "Saw-heavy mix for classic analog bass"},
            {"name": "Triangle Level", "description": "Mix level of triangle waveform", "range": "0–1", "low_means": "no triangle", "high_means": "full triangle contribution", "tip": "Triangle adds softness and sub-presence"},
            {"name": "Pulse Width", "description": "Duty cycle of the pulse waveform", "range": "0–1", "low_means": "narrow pulse (thin, nasal sound)", "high_means": "wide pulse (fuller, square-like)", "tip": "Modulate PW with LFO for pulse width modulation effect"},
        ],
    },

    # ── Envelopes ────────────────────────────────────────────────────────────
    {
        "name": "ADSR",
        "type": "device",
        "description": "Four-stage gated envelope generator with built-in amplifier; three models: Analog, Relative, Digital",
        "use_case": "Core envelope for controlling amplitude, filter cutoff, or any parameter over note duration",
        "category": "envelope",
        "params": [
            {"name": "Attack", "description": "Time to rise from zero to peak level", "range": "0–1 (time)", "low_means": "instant attack, percussive", "high_means": "slow fade-in, pad-like", "tip": "Short attack for pluck/perc, long attack (0.6+) for pads"},
            {"name": "Decay", "description": "Time to fall from peak to sustain level", "range": "0–1 (time)", "low_means": "fast decay, punchy", "high_means": "slow decay, sustained peak", "tip": ""},
            {"name": "Sustain", "description": "Level held while note is held", "range": "0–1", "low_means": "silent sustain (gate-like)", "high_means": "full sustain (organ-like)", "tip": "Set sustain = 0 for percussive one-shot sounds"},
            {"name": "Release", "description": "Time to fall from sustain to zero after note off", "range": "0–1 (time)", "low_means": "abrupt cutoff", "high_means": "long tail after release", "tip": ""},
            {"name": "Model", "description": "Envelope curve model: Analog / Relative / Digital", "range": "3 modes", "low_means": "Analog: curved, natural transitions", "high_means": "Digital: linear, precise transitions", "tip": "Analog model sounds most natural for musical use"},
        ],
    },
    {
        "name": "AD",
        "type": "device",
        "description": "Two-stage triggered envelope with Attack and Decay, optional looping mode",
        "use_case": "Percussion envelopes, LFO-like looping envelopes, one-shot modulation shapes",
        "category": "envelope",
        "params": [
            {"name": "Attack", "description": "Rise time from zero to peak", "range": "0–1 (time)", "low_means": "instant attack", "high_means": "slow rise", "tip": ""},
            {"name": "Decay", "description": "Fall time from peak back to zero", "range": "0–1 (time)", "low_means": "short decay, click-like", "high_means": "long decay, long tail", "tip": ""},
            {"name": "Loop", "description": "Looping mode — rereleases trigger on completion", "range": "off/on", "low_means": "one-shot envelope", "high_means": "continuously looping like an LFO", "tip": "Loop mode turns AD into an AD-style LFO"},
            {"name": "Model", "description": "Analog / Relative / Digital curve shape", "range": "3 modes", "low_means": "Analog curves", "high_means": "Digital linear", "tip": ""},
        ],
    },
    {
        "name": "AR",
        "type": "device",
        "description": "Three-stage gated envelope (Attack, hold at peak, Release) with amplifier",
        "use_case": "Gated sounds, organ-style envelopes, drum hits",
        "category": "envelope",
        "params": [
            {"name": "Attack", "description": "Rise time to peak", "range": "0–1 (time)", "low_means": "percussive attack", "high_means": "slow attack", "tip": ""},
            {"name": "Release", "description": "Fall time after gate closes", "range": "0–1 (time)", "low_means": "abrupt cutoff", "high_means": "long release tail", "tip": ""},
            {"name": "Model", "description": "Curve model: Analog / Relative / Digital", "range": "3 modes", "low_means": "Analog curves", "high_means": "Digital linear", "tip": ""},
        ],
    },
    {
        "name": "Segments",
        "type": "device",
        "description": "Freely drawable multi-segment envelope with four play modes including looping and ping-pong",
        "use_case": "Complex custom envelope shapes, LFO-like looping modulation, step sequences",
        "category": "envelope",
        "params": [
            {"name": "Rate", "description": "Overall speed of the envelope", "range": "0.2–50 Hz", "low_means": "very slow (LFO-like)", "high_means": "very fast (audio-rate modulation)", "tip": ""},
            {"name": "Play Mode", "description": "One-shot / Hold / Looping / Ping Pong", "range": "4 modes", "low_means": "One-shot: plays once per trigger", "high_means": "Ping Pong: loops back and forth", "tip": "Looping mode at low rate = sophisticated custom LFO"},
            {"name": "Smoothing", "description": "Applies lag processing to smooth drawn curves", "range": "0–1", "low_means": "sharp, exact curve", "high_means": "smooth, rounded transitions", "tip": ""},
            {"name": "Bipolar", "description": "Allows envelope to go into negative values", "range": "off/on", "low_means": "unipolar 0–1 range", "high_means": "bipolar -1 to +1 range", "tip": "Enable for modulation that cuts below zero"},
        ],
    },
    {
        "name": "Pluck",
        "type": "device",
        "description": "Plucked string-style envelope generator combining attack and exponential decay",
        "use_case": "Karplus-Strong synthesis, plucked string sounds, percussive attacks",
        "category": "envelope",
        "params": [
            {"name": "Attack", "description": "Rise time of the pluck transient", "range": "0–1 (time)", "low_means": "sharp, immediate pluck attack", "high_means": "slower, softer pluck", "tip": "Keep very short for realistic pluck transient"},
            {"name": "Decay", "description": "Exponential decay time after the pluck", "range": "0–1 (time)", "low_means": "fast decay, staccato", "high_means": "long sustain, resonant string", "tip": "Combine with Comb filter at matching pitch for full Karplus-Strong string"},
        ],
    },

    # ── LFOs ─────────────────────────────────────────────────────────────────
    {
        "name": "LFO",
        "type": "fx",
        "description": "Free or beat-synced geometric oscillator for modulation",
        "use_case": "Classic LFO modulation: vibrato, tremolo, filter sweeps, wobble bass",
        "category": "lfo",
        "params": [
            {"name": "Rate", "description": "LFO frequency", "range": "0.01–20 Hz or beat divisions", "low_means": "very slow sweep", "high_means": "fast tremolo/vibrato", "tip": "Sync to tempo for rhythmic modulation"},
            {"name": "Waveform", "description": "LFO shape: Sine, Triangle, Saw, Square, S/H", "range": "5 shapes", "low_means": "smooth shapes (Sine/Triangle)", "high_means": "harsh shapes (Square/S&H)", "tip": "Sine for smooth vibrato, Square for hard gating"},
            {"name": "Phase", "description": "Starting phase offset", "range": "0–1", "low_means": "starts at waveform beginning", "high_means": "offset start position", "tip": "Use different phases on voices for spread modulation"},
            {"name": "Depth", "description": "Modulation amount at destination", "range": "0–1", "low_means": "subtle modulation", "high_means": "wide modulation swing", "tip": ""},
        ],
    },
    {
        "name": "Curves",
        "type": "fx",
        "description": "Freely drawable segmented LFO with smoothing, bipolar option, and retrigger",
        "use_case": "Custom LFO shapes, complex rhythmic modulation, non-standard waveforms",
        "category": "lfo",
        "params": [
            {"name": "Rate", "description": "LFO speed", "range": "0.2–50 Hz", "low_means": "slow", "high_means": "fast", "tip": ""},
            {"name": "Smoothing", "description": "Softens drawn curve transitions", "range": "0–1", "low_means": "exact drawn shape", "high_means": "smooth rounded transitions", "tip": ""},
            {"name": "Bipolar", "description": "Enables negative modulation range", "range": "off/on", "low_means": "0–1 unipolar", "high_means": "-1 to +1 bipolar", "tip": ""},
            {"name": "Phase", "description": "Starting position in the LFO cycle", "range": "0–1", "low_means": "start at beginning", "high_means": "offset starting phase", "tip": ""},
        ],
    },
    {
        "name": "S/H LFO",
        "type": "fx",
        "description": "Free or beat-synced sample-and-hold random oscillator generating stepped random values",
        "use_case": "Random stepped modulation, generative sequences, random filter movements",
        "category": "lfo",
        "params": [
            {"name": "Rate", "description": "How often a new random value is sampled", "range": "Hz / beat divisions", "low_means": "slow random steps", "high_means": "fast random stepping", "tip": "Sync to tempo for rhythmic randomness"},
            {"name": "Smooth", "description": "Interpolation between random values", "range": "0–1", "low_means": "hard steps (true S/H)", "high_means": "smooth glides between values", "tip": "Smooth = 1 for random LFO-like gliding"},
        ],
    },

    # ── Shapers ──────────────────────────────────────────────────────────────
    {
        "name": "Wavefolder",
        "type": "fx",
        "description": "Wavefolder that reflects each cycle back on itself, adding harmonics",
        "use_case": "Adding complex harmonics, metallic distortion, west-coast synthesis style",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Input gain before folding", "range": "0–1", "low_means": "subtle folding, few added harmonics", "high_means": "extreme folding, complex harmonic distortion", "tip": "Feed simple sine through wavefolder with high Drive for complex metallic timbre"},
        ],
    },
    {
        "name": "Chebyshev",
        "type": "fx",
        "description": "Nonlinear waveshaper targeting specific harmonics via Chebyshev polynomials",
        "use_case": "Adding precise harmonic content, tube amp simulation, gentle saturation",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Input gain / distortion amount", "range": "0–1", "low_means": "subtle harmonic enhancement", "high_means": "heavy nonlinear distortion", "tip": ""},
            {"name": "Order", "description": "Chebyshev polynomial order (targets specific harmonic)", "range": "1–8", "low_means": "low-order harmonics (2nd/3rd — warm)", "high_means": "high-order harmonics (bright, harsh)", "tip": "2nd order = warm even harmonics (tube-like); 3rd = fuller, more aggressive"},
        ],
    },
    {
        "name": "Diode",
        "type": "fx",
        "description": "Parametric waveshaper modeling classic diode clipper circuit with Bias and Low-pass",
        "use_case": "Analog-style clipping, guitar amp emulation, asymmetric distortion",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Input gain into diode circuit", "range": "0–1", "low_means": "gentle clipping", "high_means": "hard clipping with strong harmonics", "tip": ""},
            {"name": "Bias", "description": "DC offset shifting asymmetric clipping point", "range": "-1 to +1", "low_means": "clipping shifted toward negative", "high_means": "clipping shifted toward positive", "tip": "Non-zero Bias creates asymmetric distortion with even harmonics (warmer, analog-like)"},
            {"name": "Low-pass Cutoff", "description": "Post-distortion low-pass filter", "range": "Hz", "low_means": "heavy filtering of distortion artifacts", "high_means": "all harmonics pass through", "tip": ""},
        ],
    },
    {
        "name": "Transfer",
        "type": "fx",
        "description": "Freely drawable waveshaper with Drive, bipolar modes, and unipolar clip/reflect",
        "use_case": "Custom distortion curves, any nonlinear processing",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Input gain before waveshaping (±24 dB)", "range": "±24 dB", "low_means": "signal quieter before shaping", "high_means": "signal louder, more of curve is used", "tip": ""},
            {"name": "Bipolar", "description": "Enables negative input/output range in drawn curve", "range": "off/on", "low_means": "unipolar shaping only", "high_means": "full bipolar waveshaping", "tip": "Enable for symmetric distortion curves"},
        ],
    },
    {
        "name": "Push",
        "type": "fx",
        "description": "Character soft clipper with detailed curve and anti-aliasing",
        "use_case": "Gentle saturation, adding warmth without harsh clipping",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Amount of soft clipping applied", "range": "0–1", "low_means": "barely audible saturation", "high_means": "clear soft clip character", "tip": "Push is very gentle — use for subtle analog warmth on master bus"},
        ],
    },
    {
        "name": "Heat",
        "type": "fx",
        "description": "Character S-shaped clipper starting soft then driving hard",
        "use_case": "Gradually intensifying distortion, transitioning from warmth to grit",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Distortion intensity on S-curve", "range": "0–1", "low_means": "soft warm saturation", "high_means": "hard driven distortion", "tip": "Automate Drive for a rising distortion effect in a build"},
        ],
    },
    {
        "name": "Soar",
        "type": "fx",
        "description": "Character soft wave folder that amplifies quiet parts of the signal",
        "use_case": "Adding brightness to soft signals, enhancing dynamics through folding",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Folding intensity", "range": "0–1", "low_means": "subtle harmonic lift", "high_means": "strong folding of quiet parts", "tip": ""},
        ],
    },
    {
        "name": "Howl",
        "type": "fx",
        "description": "Character wave folder that focuses loud parts of the signal",
        "use_case": "Aggressive distortion on peaks, crunchy transient processing",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Folding intensity on loud parts", "range": "0–1", "low_means": "subtle peak folding", "high_means": "extreme crunchy distortion", "tip": ""},
        ],
    },
    {
        "name": "Shred",
        "type": "fx",
        "description": "Character non-linear wave folder creating cancellation and artifacts",
        "use_case": "Extreme distortion, glitch effects, noise synthesis",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Intensity of non-linear folding", "range": "0–1", "low_means": "subtle artifact addition", "high_means": "extreme glitchy destruction", "tip": "High Drive on Shred produces unpredictable noise/glitch character"},
        ],
    },
    {
        "name": "Saturator (Shaper)",
        "type": "fx",
        "description": "Waveshaper with loud/quiet settings and bipolar skews",
        "use_case": "Saturation with control over which parts of the waveform are saturated",
        "category": "shaper",
        "params": [
            {"name": "Drive", "description": "Overall saturation amount", "range": "0–1", "low_means": "light, warm saturation", "high_means": "heavy clipping saturation", "tip": ""},
            {"name": "Loud Skew", "description": "Saturation emphasis on loud signal peaks", "range": "-1 to +1", "low_means": "soft treatment of peaks", "high_means": "hard clipping of loud peaks", "tip": ""},
            {"name": "Quiet Skew", "description": "Saturation emphasis on quiet signal parts", "range": "-1 to +1", "low_means": "soft treatment of quiet parts", "high_means": "amplification/saturation of quiet parts", "tip": ""},
        ],
    },

    # ── Delays / FX ──────────────────────────────────────────────────────────
    {
        "name": "Freq Shift+",
        "type": "fx",
        "description": "Analog-style frequency shifter with feedback, filtering, and phase modulation",
        "use_case": "Metallic shimmering effects, Doppler-like shifts, creating inharmonic timbres",
        "category": "fx",
        "params": [
            {"name": "Frequency Shift", "description": "Amount of frequency shift in Hz (not pitch shift)", "range": "±100% (relative to Range)", "low_means": "slight metallic shimmer", "high_means": "extreme inharmonic shifting", "tip": "Unlike pitch shift, frequency shift creates inharmonic relationships — great for metallic textures"},
            {"name": "Feedback", "description": "Amount of shifted signal fed back", "range": "0–1", "low_means": "single shift pass", "high_means": "accumulating metallic resonance", "tip": ""},
            {"name": "Feedback Low-cut / High-cut", "description": "Filters in feedback path", "range": "Hz", "low_means": "filtering more of feedback", "high_means": "feedback passes through unfiltered", "tip": ""},
        ],
    },
    {
        "name": "Pitch Shift",
        "type": "fx",
        "description": "Pitch transposer using granular processing with adjustable Grain Rate and Fade",
        "use_case": "Pitch shifting, harmonizing, creating pitch-shifted layers",
        "category": "fx",
        "params": [
            {"name": "Pitch Shift", "description": "Transposition amount in semitones", "range": "±48 semitones", "low_means": "shifted down by up to 4 octaves", "high_means": "shifted up by up to 4 octaves", "tip": ""},
            {"name": "Grain Rate", "description": "Size/frequency of granular processing grains", "range": "Hz", "low_means": "large grains, smoother but more smearing", "high_means": "small grains, better time resolution but more artifacts", "tip": ""},
            {"name": "Grain Fade", "description": "Cross-fade between grains", "range": "0–1", "low_means": "hard grain boundaries (clicks)", "high_means": "smooth grain transitions", "tip": ""},
        ],
    },
    {
        "name": "Mod Delay",
        "type": "fx",
        "description": "Modulated delay with internal feedback loop for chorus, flanger, and vibrato",
        "use_case": "Chorus, flanger, tape-style vibrato, modulated echo",
        "category": "fx",
        "params": [
            {"name": "Delay Time", "description": "Base delay time before modulation", "range": "ms", "low_means": "short delay (chorus/flanger range)", "high_means": "longer delay (echo range)", "tip": ""},
            {"name": "Feedback", "description": "Amount of delayed signal fed back", "range": "0–1", "low_means": "single repeat", "high_means": "many repeating echoes", "tip": ""},
            {"name": "Modulation Rate", "description": "LFO speed for delay time modulation", "range": "Hz", "low_means": "slow sweep (vibrato)", "high_means": "fast modulation (metallic flutter)", "tip": ""},
            {"name": "Modulation Depth", "description": "Depth of delay time modulation", "range": "0–1", "low_means": "subtle modulation", "high_means": "strong pitch wobble / flanger sweep", "tip": "Short delay + deep modulation = flanger; longer delay + moderate mod = chorus"},
            {"name": "Mix", "description": "Wet/dry blend", "range": "0–1", "low_means": "mostly dry signal", "high_means": "mostly modulated delay", "tip": ""},
        ],
    },
    {
        "name": "Long Delay",
        "type": "fx",
        "description": "Delay with time set in beats or milliseconds with feedback connections",
        "use_case": "Rhythmic delay, echo effects, dub-style delay",
        "category": "fx",
        "params": [
            {"name": "Delay Time", "description": "Time between original and delayed signal", "range": "ms or beat divisions", "low_means": "short pre-delay or slapback", "high_means": "long echo repeats", "tip": "Sync to tempo with beat divisions for rhythmic delay"},
            {"name": "Feedback", "description": "How much of the delayed signal feeds back into the delay", "range": "0–1", "low_means": "single repeat", "high_means": "many decaying repeats", "tip": "High feedback + tempo sync = classic dub delay"},
        ],
    },

    # ── Mix ──────────────────────────────────────────────────────────────────
    {
        "name": "Voice Stack Mix",
        "type": "fx",
        "description": "Modulatable processor with volume, panning, solo, and enable controls per voice in voice stack",
        "use_case": "Precise per-voice control in polyphonic patches, stereo spreading of voices",
        "category": "mixing",
        "params": [
            {"name": "Volume", "description": "Per-voice volume level", "range": "0–1", "low_means": "silence that voice", "high_means": "full volume for that voice", "tip": ""},
            {"name": "Pan", "description": "Per-voice stereo panning", "range": "-1 to +1", "low_means": "hard left", "high_means": "hard right", "tip": "Set different pan positions per voice for wide stereo spread"},
        ],
    },
    {
        "name": "Blend",
        "type": "mixing",
        "description": "Crossfades between two incoming signals",
        "use_case": "Mixing two signal paths, morph between two sounds",
        "category": "mixing",
        "params": [
            {"name": "Mix", "description": "Crossfade position between signal A and B", "range": "0–1", "low_means": "100% signal A", "high_means": "100% signal B", "tip": "Modulate Mix with LFO for continuous A-B morphing"},
        ],
    },
    {
        "name": "Stereo Width",
        "type": "mixing",
        "description": "Controls the stereo width of a signal from mono to wide",
        "use_case": "Widening or narrowing stereo signals, mono compatibility checking",
        "category": "mixing",
        "params": [
            {"name": "Width", "description": "Stereo width amount", "range": "0–1", "low_means": "mono (fully summed)", "high_means": "maximum stereo width", "tip": "Narrow width on bass elements for better mono compatibility"},
        ],
    },

    # ── Level / Utility ──────────────────────────────────────────────────────
    {
        "name": "Lag",
        "type": "fx",
        "description": "Lag processor that smooths abrupt signal changes (portamento/glide for any signal)",
        "use_case": "Portamento / glide effect, smoothing modulation, anti-click",
        "category": "utility",
        "params": [
            {"name": "Rise", "description": "Lag time for rising signals", "range": "0–1 (time)", "low_means": "instant response on rising edge", "high_means": "slow glide upward", "tip": ""},
            {"name": "Fall", "description": "Lag time for falling signals", "range": "0–1 (time)", "low_means": "instant response on falling edge", "high_means": "slow glide downward", "tip": "Apply Lag to Pitch In output for portamento on any oscillator"},
        ],
    },
    {
        "name": "Sample / Hold",
        "type": "fx",
        "description": "Samples an input signal on trigger and holds that value until next trigger",
        "use_case": "Random stepped modulation, sequential value holding, gate-triggered value capture",
        "category": "utility",
        "params": [
            {"name": "Input", "description": "Signal being sampled", "range": "any signal", "low_means": "low values will be held", "high_means": "high values will be held", "tip": "Feed Noise into S/H triggered by Gate In for random pitch sequences"},
        ],
    },
    {
        "name": "Amplify",
        "type": "fx",
        "description": "Signal amplifier from 0% to 800%",
        "use_case": "Boosting signals beyond normal levels, driving into other modules",
        "category": "utility",
        "params": [
            {"name": "Gain", "description": "Amplification factor", "range": "0–800%", "low_means": "signal reduced to zero", "high_means": "signal amplified 8x", "tip": "Use Amplify before Wavefolder to drive it harder"},
        ],
    },
    {
        "name": "Phasor",
        "type": "modulation",
        "description": "Phase signal generator — the master timing signal for wavetable lookup and sequencer modules",
        "use_case": "Driving wavetable lookup, step sequencers, any phase-based module",
        "category": "phase",
        "params": [
            {"name": "Rate", "description": "Frequency of the phasor (phase ramp speed)", "range": "Hz / beat sync", "low_means": "slow ramp, low frequency", "high_means": "fast ramp, high frequency (audio rate)", "tip": "At audio rate, Phasor drives oscillators; at LFO rate, drives sequencers"},
            {"name": "Sync", "description": "Beat-sync mode for tempo-locked operation", "range": "off/on", "low_means": "free-running", "high_means": "locked to project tempo", "tip": ""},
        ],
    },

    # ── Pitch ────────────────────────────────────────────────────────────────
    {
        "name": "Pitch Quantize",
        "type": "pitch",
        "description": "Quantizes incoming pitch signal to designated or held pitch classes (scales/chords)",
        "use_case": "Forcing notes into scale, generative melody quantization, scale-corrected pitch CV",
        "category": "pitch",
        "params": [
            {"name": "Scale", "description": "Target pitch class set to quantize to", "range": "scale options", "low_means": "simple scales (major/minor)", "high_means": "complex scales (diminished, whole tone)", "tip": "Feed random pitch through Pitch Quantize for generative melodies always in key"},
            {"name": "Root", "description": "Root note of the scale", "range": "C–B", "low_means": "C root", "high_means": "B root", "tip": ""},
        ],
    },
    {
        "name": "Transpose",
        "type": "pitch",
        "description": "Semitone pitch shifter for transposing signals by integer semitone amounts",
        "use_case": "Harmonizing, octave shifting, building chord voices",
        "category": "pitch",
        "params": [
            {"name": "Semitones", "description": "Number of semitones to transpose", "range": "±48 semitones", "low_means": "transpose down", "high_means": "transpose up", "tip": "Use multiple Transpose modules with Voice Stack to create chords"},
        ],
    },
]


def write_to_neo4j(driver, modules: list[dict], dry_run: bool) -> dict:
    counts = {"devices": 0, "parameters": 0}

    if dry_run:
        for m in modules:
            counts["devices"] += 1
            counts["parameters"] += len(m.get("params", []))
        return counts

    with driver.session() as s:
        for m in modules:
            s.run("""
                MERGE (d:Device {name: $name})
                SET d.description = coalesce(d.description, $description),
                    d.use_case    = coalesce(d.use_case, $use_case),
                    d.device_type = coalesce(d.device_type, $dtype),
                    d.category    = coalesce(d.category, $category),
                    d.source      = 'bitwig_userguide_web'
            """, name=m["name"],
                 description=m.get("description", ""),
                 use_case=m.get("use_case", ""),
                 dtype=m.get("type", ""),
                 category=m.get("category", ""))
            counts["devices"] += 1

            for p in m.get("params", []):
                s.run("""
                    MATCH (d:Device {name: $device})
                    MERGE (p:Parameter {name: $name, device: $device})
                    SET p.description = coalesce(p.description, $description),
                        p.range       = coalesce(p.range, $range),
                        p.low_means   = coalesce(p.low_means, $low_means),
                        p.high_means  = coalesce(p.high_means, $high_means),
                        p.tip         = coalesce(p.tip, $tip),
                        p.source      = 'bitwig_userguide_web'
                    MERGE (d)-[:HAS_PARAMETER]->(p)
                """, device=m["name"],
                     name=p["name"],
                     description=p.get("description", ""),
                     range=p.get("range", ""),
                     low_means=p.get("low_means", ""),
                     high_means=p.get("high_means", ""),
                     tip=p.get("tip", ""))
                counts["parameters"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(description="Ingest Grid module data from web docs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    driver = None if args.dry_run else GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )

    if args.dry_run:
        print("[dry-run] Would write:")

    counts = write_to_neo4j(driver, GRID_MODULES, args.dry_run)

    if driver:
        driver.close()

    print(f"[done] devices={counts['devices']}, parameters={counts['parameters']}")


if __name__ == "__main__":
    main()
