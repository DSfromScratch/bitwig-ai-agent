package com.bitwigagent;

import com.bitwig.extension.controller.ControllerExtension;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.*;

/**
 * Standalone Launchpad MK2 Controller — drei Modi:
 *
 *   CONTROL    — Transport-Controls + Mixer (Seiten-Button Row 8, Note 89)
 *   DRUM       — 4×4 Drum-Pad-Grid, MIDI-Noten frei konfigurierbar (Row 7, Note 79)
 *   INSTRUMENT — 8×8 Scale-Layout, Root-Note + Skala konfigurierbar (Row 6, Note 69)
 *
 * Konfiguration: Konstanten am Anfang der Klasse.
 */
public class LaunchpadControllerExtension extends ControllerExtension {

    // ── Drum Pad Konfiguration ────────────────────────────────────────────────
    // 4×4 Grid (16 Pads), Zeile 1 unten → Zeile 4 oben
    // Standard: Bitwig Drum Machine Layout (GM-kompatibel, ab C1=36)
    private static final int[] DRUM_NOTES = {
        // Zeile 1 (unterste Pads, Launchpad-Row 1)
        36, 37, 38, 39,   // Kick, Rimshot, Snare, Clap
        // Zeile 2
        40, 41, 42, 43,   // E-Snare, Low Floor Tom, Closed HH, High Floor Tom
        // Zeile 3
        44, 45, 46, 47,   // Pedal HH, Low Tom, Open HH, Low-Mid Tom
        // Zeile 4 (oberste Pads)
        48, 49, 50, 51    // Hi-Mid Tom, Crash 1, High Tom, Ride
    };

    // Drum-Pad Farben (r, g, b je 0–63) — pro Drum-Kategorie
    private static final int[] DRUM_COLOR_KICK    = {63, 10,  0};  // rot-orange
    private static final int[] DRUM_COLOR_SNARE   = {63, 40,  0};  // orange
    private static final int[] DRUM_COLOR_HH      = {63, 63,  0};  // gelb
    private static final int[] DRUM_COLOR_TOM     = {0,  40, 63};  // blau
    private static final int[] DRUM_COLOR_CYMBAL  = {40,  0, 63};  // lila
    private static final int[] DRUM_COLOR_HIT     = {63, 63, 63};  // weiß (bei Treffer)

    // MIDI-Kanal für Drum-Noten (0 = Kanal 1)
    private static final int DRUM_MIDI_CHANNEL = 9; // Kanal 10 (GM Drum)

    // ── Instrument Konfiguration ──────────────────────────────────────────────
    // Root-Note (MIDI): 60 = C4, 48 = C3, 36 = C2
    private static final int INST_ROOT_NOTE = 48; // C3

    // Skala-Intervalle (Halbtonschritte ab Root)
    // Major:        {0, 2, 4, 5, 7, 9, 11}
    // Minor:        {0, 2, 3, 5, 7, 8, 10}
    // Pentatonic:   {0, 2, 4, 7, 9}
    // Blues:        {0, 3, 5, 6, 7, 10}
    // Chromatic:    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
    private static final int[] INST_SCALE = {0, 2, 4, 5, 7, 9, 11}; // Major

    // Intervall zwischen Zeilen (Halbtonschritte): 5 = Quarte, 7 = Quinte
    private static final int INST_ROW_INTERVAL = 5; // Quarte (Ableton-Push-Layout)

    // MIDI-Kanal für Instrument-Noten (0 = Kanal 1)
    private static final int INST_MIDI_CHANNEL = 0;

    // Instrument Farben
    private static final int[] INST_COLOR_ROOT    = {0,  63,  0};  // grün (Root-Note)
    private static final int[] INST_COLOR_SCALE   = {0,  20, 63};  // blau (Skalenton)
    private static final int[] INST_COLOR_OUTSIDE = {5,   5,  5};  // sehr dunkel (außerhalb)
    private static final int[] INST_COLOR_HIT     = {63, 63, 63};  // weiß (bei Treffer)

    // ── Control Mode Mapping ──────────────────────────────────────────────────
    // 8 Pads in Zeile 1 (Notes 11–18) → Aktionen
    private static final String[] CONTROL_ROW1 = {
        "play_stop", "stop", "record", "undo",
        "loop_toggle", "mute_toggle", "next_track", "prev_track"
    };
    // 8 Pads in Zeile 2 (Notes 21–28) → Aktionen (leer = inaktiv)
    private static final String[] CONTROL_ROW2 = {
        "solo_toggle", "vol_up", "vol_down", "tempo_up",
        "tempo_down", "", "", ""
    };

    // ── Launchpad MK2 Layout ──────────────────────────────────────────────────
    // Grid-Noten: Zeile r (1=unten, 8=oben), Spalte c (1=links, 8=rechts) → Note r*10+c
    // Seiten-Buttons (rechte Spalte): 19, 29, 39, 49, 59, 69, 79, 89
    private static final int BTN_MODE_CONTROL    = 89; // Zeile 8, rechts
    private static final int BTN_MODE_DRUM       = 79; // Zeile 7, rechts
    private static final int BTN_MODE_INSTRUMENT = 69; // Zeile 6, rechts

    // Velocity für Drum-Noten
    private static final int DRUM_VELOCITY = 100;

    // ── Interne Zustands-Felder ───────────────────────────────────────────────
    private enum Mode { CONTROL, DRUM, INSTRUMENT }
    private Mode currentMode = Mode.CONTROL;

    private MidiIn  midiIn;
    private MidiOut midiOut;

    private ControllerHost host;
    private Transport      transport;
    private CursorTrack    cursorTrack;
    private Application    application;

    // ── Konstruktor ───────────────────────────────────────────────────────────

    protected LaunchpadControllerExtension(
            ControllerExtensionDefinition def, ControllerHost host) {
        super(def, host);
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    @Override
    public void init() {
        host = (ControllerHost) getHost();

        transport   = host.createTransport();
        cursorTrack = host.createCursorTrack("lp-cursor", "LP Cursor", 0, 0, true);
        application = host.createApplication();

        midiIn  = host.getMidiInPort(0);
        midiOut = host.getMidiOutPort(0);

        midiIn.setMidiCallback(this::onMidi);

        enterMode(Mode.CONTROL);
        host.showPopupNotification("Launchpad Controller — Control Mode");
        host.println("[Launchpad] Controller gestartet");
    }

    @Override
    public void exit() {
        clearAllLeds();
        host.println("[Launchpad] Controller beendet");
    }

    @Override
    public void flush() {}

    // ── MIDI Input ────────────────────────────────────────────────────────────

    private void onMidi(int status, int data1, int data2) {
        int type    = status & 0xF0;
        boolean pressed = (type == 0x90 && data2 > 0);
        boolean released = (type == 0x80 || (type == 0x90 && data2 == 0));

        if (!pressed && !released) return;

        // Modus-Buttons (Seiten-Buttons rechte Spalte)
        if (pressed) {
            if (data1 == BTN_MODE_CONTROL)    { enterMode(Mode.CONTROL);    return; }
            if (data1 == BTN_MODE_DRUM)       { enterMode(Mode.DRUM);       return; }
            if (data1 == BTN_MODE_INSTRUMENT) { enterMode(Mode.INSTRUMENT); return; }
        }

        switch (currentMode) {
            case CONTROL:    handleControl(data1, pressed);    break;
            case DRUM:       handleDrum(data1, data2, pressed, released); break;
            case INSTRUMENT: handleInstrument(data1, data2, pressed, released); break;
        }
    }

    // ── Control Mode ─────────────────────────────────────────────────────────

    private void handleControl(int note, boolean pressed) {
        if (!pressed) return;
        int row = note / 10;
        int col = (note % 10) - 1; // 0-basiert
        if (col < 0 || col > 7) return;

        String action = null;
        if (row == 1 && col < CONTROL_ROW1.length) action = CONTROL_ROW1[col];
        if (row == 2 && col < CONTROL_ROW2.length) action = CONTROL_ROW2[col];

        if (action != null && !action.isEmpty()) {
            executeAction(action);
            flashLed(note, 63, 63, 63); // kurzes Weiß-Aufleuchten
        }
    }

    private void executeAction(String action) {
        switch (action) {
            case "play_stop":   transport.play();                                    break;
            case "stop":        transport.stop();                                    break;
            case "record":      transport.record();                                  break;
            case "undo":        application.undo();                                  break;
            case "loop_toggle": transport.isArrangerLoopEnabled().toggle();          break;
            case "mute_toggle": cursorTrack.mute().toggle();                         break;
            case "solo_toggle": cursorTrack.solo().toggle();                         break;
            case "next_track":  cursorTrack.selectNext();                            break;
            case "prev_track":  cursorTrack.selectPrevious();                        break;
            case "vol_up":      cursorTrack.volume().inc(1.0 / 128.0, 128);          break;
            case "vol_down":    cursorTrack.volume().inc(-1.0 / 128.0, 128);         break;
            case "tempo_up":    transport.tempo().inc(1.0, 512);                     break;
            case "tempo_down":  transport.tempo().inc(-1.0, 512);                    break;
        }
    }

    private void paintControlMode() {
        // Zeile 1
        for (int c = 0; c < CONTROL_ROW1.length; c++) {
            int note = 11 + c;
            int[] col = actionColor(CONTROL_ROW1[c]);
            setLed(note, col[0], col[1], col[2]);
        }
        // Zeile 2
        for (int c = 0; c < CONTROL_ROW2.length; c++) {
            int note = 21 + c;
            if (CONTROL_ROW2[c].isEmpty()) { setLed(note, 0, 0, 0); continue; }
            int[] col = actionColor(CONTROL_ROW2[c]);
            setLed(note, col[0], col[1], col[2]);
        }
    }

    private int[] actionColor(String action) {
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

    // ── Drum Mode ────────────────────────────────────────────────────────────

    // Launchpad-Noten für das 4×4 Drum-Grid (unten-links)
    // Zeile 1 = Notes 11–14, Zeile 2 = 21–24, Zeile 3 = 31–34, Zeile 4 = 41–44
    private static final int[][] DRUM_GRID_NOTES = {
        {11, 12, 13, 14},
        {21, 22, 23, 24},
        {31, 32, 33, 34},
        {41, 42, 43, 44}
    };

    private void handleDrum(int note, int velocity, boolean pressed, boolean released) {
        int drumIdx = drumGridIndex(note);
        if (drumIdx < 0 || drumIdx >= DRUM_NOTES.length) return;
        int drumNote = DRUM_NOTES[drumIdx];

        if (pressed) {
            int vel = Math.max(1, Math.min(127, velocity));
            midiOut.sendMidi(0x90 | DRUM_MIDI_CHANNEL, drumNote, vel);
            setLed(note, DRUM_COLOR_HIT[0], DRUM_COLOR_HIT[1], DRUM_COLOR_HIT[2]);
        } else {
            midiOut.sendMidi(0x80 | DRUM_MIDI_CHANNEL, drumNote, 0);
            int[] col = drumColor(drumIdx);
            setLed(note, col[0], col[1], col[2]);
        }
    }

    private int drumGridIndex(int note) {
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                if (DRUM_GRID_NOTES[row][col] == note) return row * 4 + col;
            }
        }
        return -1;
    }

    private int[] drumColor(int idx) {
        int note = DRUM_NOTES[idx];
        if (note == 36 || note == 40)             return DRUM_COLOR_KICK;
        if (note == 37 || note == 38 || note == 39) return DRUM_COLOR_SNARE;
        if (note == 42 || note == 44 || note == 46) return DRUM_COLOR_HH;
        if (note == 49 || note == 51 || note == 57) return DRUM_COLOR_CYMBAL;
        return DRUM_COLOR_TOM;
    }

    private void paintDrumMode() {
        clearAllLeds();
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                int idx = row * 4 + col;
                int[] color = drumColor(idx);
                setLed(DRUM_GRID_NOTES[row][col], color[0], color[1], color[2]);
            }
        }
    }

    // ── Instrument Mode ───────────────────────────────────────────────────────

    private void handleInstrument(int note, int velocity, boolean pressed, boolean released) {
        int midiNote = instNoteForPad(note);
        if (midiNote < 0 || midiNote > 127) return;

        if (pressed) {
            int vel = Math.max(1, Math.min(127, velocity));
            midiOut.sendMidi(0x90 | INST_MIDI_CHANNEL, midiNote, vel);
            setLed(note, INST_COLOR_HIT[0], INST_COLOR_HIT[1], INST_COLOR_HIT[2]);
        } else {
            midiOut.sendMidi(0x80 | INST_MIDI_CHANNEL, midiNote, 0);
            int[] col = instPadColor(midiNote);
            setLed(note, col[0], col[1], col[2]);
        }
    }

    // Berechnet die MIDI-Note für einen Launchpad-Pad im Instrument-Modus
    private int instNoteForPad(int padNote) {
        int row = padNote / 10;   // 1–8
        int col = padNote % 10;   // 1–8
        if (row < 1 || row > 8 || col < 1 || col > 8) return -1;
        // Zeile 1 = unterste Reihe, fängt bei INST_ROOT_NOTE an
        // Jede Zeile höher → INST_ROW_INTERVAL Halbtonschritte höher
        int base = INST_ROOT_NOTE + (row - 1) * INST_ROW_INTERVAL;
        // Jede Spalte → nächste Skala-Note
        int scaleStep = (col - 1) % INST_SCALE.length;
        int octaveStep = (col - 1) / INST_SCALE.length;
        return base + INST_SCALE[scaleStep] + octaveStep * 12;
    }

    private int[] instPadColor(int midiNote) {
        int interval = ((midiNote - INST_ROOT_NOTE) % 12 + 12) % 12;
        if (interval == 0) return INST_COLOR_ROOT;
        for (int s : INST_SCALE) if (s == interval) return INST_COLOR_SCALE;
        return INST_COLOR_OUTSIDE;
    }

    private void paintInstrumentMode() {
        clearAllLeds();
        for (int row = 1; row <= 8; row++) {
            for (int col = 1; col <= 8; col++) {
                int padNote  = row * 10 + col;
                int midiNote = instNoteForPad(padNote);
                if (midiNote < 0 || midiNote > 127) continue;
                int[] color = instPadColor(midiNote);
                setLed(padNote, color[0], color[1], color[2]);
            }
        }
    }

    // ── Modus wechseln ────────────────────────────────────────────────────────

    private void enterMode(Mode mode) {
        currentMode = mode;
        clearAllLeds();
        paintModeButtons();

        switch (mode) {
            case CONTROL:    paintControlMode();    break;
            case DRUM:       paintDrumMode();       break;
            case INSTRUMENT: paintInstrumentMode(); break;
        }
        host.println("[Launchpad] Modus: " + mode);
    }

    private void paintModeButtons() {
        // Aktiver Modus → hell, andere → dunkel
        setLed(BTN_MODE_CONTROL,
            currentMode == Mode.CONTROL    ? 63 : 8,
            currentMode == Mode.CONTROL    ? 63 : 8,
            currentMode == Mode.CONTROL    ? 63 : 8);
        setLed(BTN_MODE_DRUM,
            currentMode == Mode.DRUM       ? 63 : 8, 0, 0);
        setLed(BTN_MODE_INSTRUMENT,
            0,
            currentMode == Mode.INSTRUMENT ? 63 : 8, 0);
    }

    // ── LED Hilfsmethoden ─────────────────────────────────────────────────────

    private void setLed(int note, int r, int g, int b) {
        if (midiOut == null) return;
        r = Math.max(0, Math.min(63, r));
        g = Math.max(0, Math.min(63, g));
        b = Math.max(0, Math.min(63, b));
        // SysEx: Manufacturer=00 20 29, Model=02 18, Cmd=0B, note, r, g, b
        String hex = String.format("00 20 29 02 18 0B %02X %02X %02X %02X", note, r, g, b);
        midiOut.sendSysex(hex);
    }

    private void flashLed(int note, int r, int g, int b) {
        setLed(note, r, g, b);
        // Note: Bitwig's flush() würde hier reichen, aber wir setzten nach kurzer
        // Zeit zurück via Timer — stattdessen setzen wir sofort zurück beim Release
    }

    private void clearAllLeds() {
        // Reset via SysEx (Launchpad MK2 Reset: F0 00 20 29 02 18 0E 00 F7)
        if (midiOut == null) return;
        midiOut.sendSysex("00 20 29 02 18 0E 00");
    }
}
