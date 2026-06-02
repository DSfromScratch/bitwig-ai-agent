package com.bitwigagent;

/**
 * Launchpad MK2 Layout-Konstanten und reine Berechnungen.
 * Kein Bitwig-API-State — nur Daten und Mathematik.
 */
final class LaunchpadPadLayout {

    private LaunchpadPadLayout() {}

    // ── Drum-Grid Launchpad-Noten (4×4 unten-links) ───────────────────────────

    static final int[][] DRUM_GRID_NOTES = {
        {11, 12, 13, 14},
        {21, 22, 23, 24},
        {31, 32, 33, 34},
        {41, 42, 43, 44},
    };

    static int drumGridIndex(int note) {
        for (int row = 0; row < 4; row++)
            for (int col = 0; col < 4; col++)
                if (DRUM_GRID_NOTES[row][col] == note) return row * 4 + col;
        return -1;
    }

    // ── Chromatische Tonklassen-Farben (C=grün … B=gelb) ─────────────────────

    static final int[][] CHROMATIC_COLORS = {
        {0,  50,  0},  // C
        {0,  30,  5},  // C#
        {0,  40, 30},  // D
        {0,  20, 20},  // D#
        {0,  20, 50},  // E
        {20,  0, 50},  // F
        {10,  0, 30},  // F#
        {35,  0, 50},  // G
        {50,  0, 35},  // G#
        {50, 20,  0},  // A
        {35, 15,  0},  // A#
        {50, 50,  0},  // B
    };

    // ── Control-Mode Aktions-Farben ────────────────────────────────────────────

    static int[] actionColor(String action) {
        switch (action) {
            case "play_stop":   return new int[]{0,  63,  0};
            case "stop":        return new int[]{63, 20,  0};
            case "record":      return new int[]{63,  0,  0};
            case "undo":        return new int[]{63, 63,  0};
            case "loop_toggle": return new int[]{63,  0, 63};
            case "mute_toggle": return new int[]{63, 30,  0};
            case "solo_toggle": return new int[]{40, 63,  0};
            case "next_track":  return new int[]{0,  63, 63};
            case "prev_track":  return new int[]{0,  30, 63};
            case "vol_up":      return new int[]{30, 63, 30};
            case "vol_down":    return new int[]{20, 40, 20};
            case "tempo_up":    return new int[]{63, 63, 30};
            case "tempo_down":  return new int[]{40, 40, 20};
            default:            return new int[]{15, 15, 15};
        }
    }

    // ── Instrument-Mode Note-Berechnung ───────────────────────────────────────

    static int instNoteForPad(int padNote, int rootNote, int rowInterval, int[] scale) {
        int row = padNote / 10;
        int col = padNote % 10;
        if (row < 1 || row > 8 || col < 1 || col > 8) return -1;
        int base      = rootNote + (row - 1) * rowInterval;
        int scaleStep = (col - 1) % scale.length;
        int octave    = (col - 1) / scale.length;
        return base + scale[scaleStep] + octave * 12;
    }
}
