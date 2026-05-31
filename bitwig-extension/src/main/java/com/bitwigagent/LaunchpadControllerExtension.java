package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.*;
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
    // Top-Row CC-Buttons (senden CC auf Kanal 1)
    private static final int CC_BTN_UP      = 104;
    private static final int CC_BTN_DOWN    = 105;
    private static final int CC_BTN_LEFT    = 106;
    private static final int CC_BTN_RIGHT   = 107;
    private static final int CC_BTN_SESSION = 108; // Modus: Control
    private static final int CC_BTN_USER1   = 109; // Modus: Drum
    private static final int CC_BTN_USER2   = 110; // Modus: Instrument
    private static final int CC_BTN_MIXER   = 111; // Bitwig Mixer-Panel

    // Rechte Spalte (Note-On, von oben nach unten)
    private static final int BTN_VOLUME     = 89;
    private static final int BTN_PAN        = 79;
    private static final int BTN_SEND_A     = 69;
    private static final int BTN_SEND_B     = 59;
    private static final int BTN_STOP_CLIP  = 49;
    private static final int BTN_MUTE       = 39;
    private static final int BTN_SOLO       = 29;
    private static final int BTN_RECORD_ARM = 19;

    // Velocity für Drum-Noten
    private static final int DRUM_VELOCITY = 100;

    // Port für den eingebauten OSC-Server (LED-Suggestions + Mode-Query vom Agent)
    private static final int LED_OSC_PORT   = 8003;
    // Reply-Port: Agent empfängt Mode-Antworten hier
    private static final int MODE_REPLY_PORT = 9005;

    // ── Interne Zustands-Felder ───────────────────────────────────────────────
    private enum Mode { CONTROL, DRUM, INSTRUMENT }
    private Mode currentMode = Mode.CONTROL;
    private OscConnection modeReplyConn;

    private MidiIn    midiIn;
    private MidiOut   midiOut;
    private NoteInput drumNoteInput;
    private NoteInput instNoteInput;

    private ControllerHost host;
    private Transport      transport;
    private CursorTrack    cursorTrack;
    private Application    application;

    // Pads die zuletzt per suggest_notes beleuchtet wurden (zum Löschen)
    private final java.util.List<Integer> suggestionPads = new java.util.ArrayList<>();

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

        // NoteInput für Drum-Modus: alle MIDI-Noten auf Kanal 1 (Launchpad-Standard)
        drumNoteInput = midiIn.createNoteInput("LP Drums", "9?????", "8?????");
        drumNoteInput.setShouldConsumeEvents(true);
        drumNoteInput.setKeyTranslationTable(buildDrumTranslationTable());

        // NoteInput für Instrument-Modus: eigener virtueller Kanal
        instNoteInput = midiIn.createNoteInput("LP Instrument", "9?????", "8?????");
        instNoteInput.setShouldConsumeEvents(true);
        instNoteInput.setKeyTranslationTable(buildInstTranslationTable());

        // Beide NoteInputs starten blockiert — MIDI-Callback übernimmt LED + Routing
        drumNoteInput.setShouldConsumeEvents(false);
        instNoteInput.setShouldConsumeEvents(false);

        midiIn.setMidiCallback(this::onMidi);

        setupLedOsc();

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
        int type      = status & 0xF0;
        boolean pressed   = (type == 0x90 && data2 > 0);
        boolean released  = (type == 0x80 || (type == 0x90 && data2 == 0));
        boolean ccPressed = (type == 0xB0 && data2 > 0);

        if (!pressed && !released && !ccPressed) return;

        // Top-Row CC-Buttons
        if (ccPressed) {
            switch (data1) {
                case CC_BTN_SESSION: enterMode(Mode.CONTROL);                                    break;
                case CC_BTN_USER1:   enterMode(Mode.DRUM);                                       break;
                case CC_BTN_USER2:   enterMode(Mode.INSTRUMENT);                                 break;
                case CC_BTN_MIXER:   application.setPanelLayout(Application.PANEL_LAYOUT_MIX);  break;
                case CC_BTN_UP:      executeAction("vol_up");                                    break;
                case CC_BTN_DOWN:    executeAction("vol_down");                                  break;
                case CC_BTN_LEFT:    executeAction("prev_track");                                break;
                case CC_BTN_RIGHT:   executeAction("next_track");                                break;
            }
            return;
        }

        // Rechte Spalte — globale Bitwig-Aktionen
        if (pressed) {
            switch (data1) {
                case BTN_VOLUME:     cursorTrack.mute().set(false);  return; // Unmute
                case BTN_MUTE:       cursorTrack.mute().set(true);   return; // Mute
                case BTN_STOP_CLIP:  transport.stop();               return;
                case BTN_RECORD_ARM: transport.record();             return;
            }
        }

        switch (currentMode) {
            case CONTROL:    handleControl(data1, pressed);                   break;
            case DRUM:       handleDrum(data1, data2, pressed, released);     break;
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
            drumNoteInput.sendRawMidiEvent(0x99, drumNote, vel); // Kanal 10 (9)
            setLed(note, DRUM_COLOR_HIT[0], DRUM_COLOR_HIT[1], DRUM_COLOR_HIT[2]);
            if (modeReplyConn != null)
                modeReplyConn.sendMessage("/launchpad/note/played", drumNote, vel);
        } else {
            drumNoteInput.sendRawMidiEvent(0x89, drumNote, 0);
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
            instNoteInput.sendRawMidiEvent(0x90, midiNote, vel);
            setLed(note, INST_COLOR_HIT[0], INST_COLOR_HIT[1], INST_COLOR_HIT[2]);
            if (modeReplyConn != null)
                modeReplyConn.sendMessage("/launchpad/note/played", midiNote, vel);
        } else {
            instNoteInput.sendRawMidiEvent(0x80, midiNote, 0);
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

    // ── Translation Tables für NoteInput ─────────────────────────────────────

    private Integer[] buildDrumTranslationTable() {
        Integer[] table = new Integer[128];
        java.util.Arrays.fill(table, -1); // alle blockieren
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                int padNote  = DRUM_GRID_NOTES[row][col];
                int drumNote = DRUM_NOTES[row * 4 + col];
                if (padNote < 128) table[padNote] = drumNote;
            }
        }
        return table;
    }

    private Integer[] buildInstTranslationTable() {
        Integer[] table = new Integer[128];
        java.util.Arrays.fill(table, -1);
        for (int row = 1; row <= 8; row++) {
            for (int col = 1; col <= 8; col++) {
                int padNote  = row * 10 + col;
                int midiNote = instNoteForPad(padNote);
                if (padNote < 128 && midiNote >= 0 && midiNote <= 127)
                    table[padNote] = midiNote;
            }
        }
        return table;
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
        if (modeReplyConn != null)
            modeReplyConn.sendMessage("/launchpad/mode/changed", mode.name());
        host.println("[Launchpad] Modus: " + mode);
    }

    private void paintModeButtons() {
        // Session/User1/User2: aktiver Modus hell, andere dunkel
        setLed(CC_BTN_SESSION,
            currentMode == Mode.CONTROL    ? 63 : 8,
            currentMode == Mode.CONTROL    ? 63 : 8,
            currentMode == Mode.CONTROL    ? 63 : 8);
        setLed(CC_BTN_USER1,
            currentMode == Mode.DRUM       ? 63 : 8, 0, 0);
        setLed(CC_BTN_USER2,
            0, currentMode == Mode.INSTRUMENT ? 63 : 8, 0);
        // Mixer-Button immer leicht weiß
        setLed(CC_BTN_MIXER, 20, 20, 20);
        // Pfeil-Buttons
        setLed(CC_BTN_UP,    20, 40, 20);
        setLed(CC_BTN_DOWN,  10, 20, 10);
        setLed(CC_BTN_LEFT,   0, 20, 40);
        setLed(CC_BTN_RIGHT,  0, 30, 50);
        // Rechte Spalte: feste Aktionen
        setLed(BTN_VOLUME,     0,  50,  0);  // grün = unmute
        setLed(BTN_MUTE,      50,  15,  0);  // orange = mute
        setLed(BTN_STOP_CLIP, 50,  20,  0);  // orange-rot = stop
        setLed(BTN_RECORD_ARM, 63,  0,  0);  // rot = record
    }

    // ── LED Hilfsmethoden ─────────────────────────────────────────────────────

    // ── OSC LED-Server (Port 8003) ────────────────────────────────────────────

    private void setupLedOsc() {
        try {
            OscModule       osc   = host.getOscModule();
            OscAddressSpace space = osc.createAddressSpace();

            // Outbound: Reply-Verbindung zu Python (Port 9005)
            modeReplyConn = osc.connectToUdpServer("127.0.0.1", MODE_REPLY_PORT, space);

            // /launchpad/mode/get  — aktuellen Modus zurückschicken
            space.registerMethod("/launchpad/mode/get", "*", "Get current mode",
                (src, msg) -> {
                    if (modeReplyConn != null)
                        modeReplyConn.sendMessage("/launchpad/mode/response", currentMode.name());
                });

            // /launchpad/led <pad> <r> <g> <b>  — einzelne Pad-Farbe setzen
            space.registerMethod("/launchpad/led", "*", "Set suggestion LED",
                (src, msg) -> {
                    int pad = (int) oscFloat(msg, 0, 11f);
                    int r   = (int) oscFloat(msg, 1, 0f);
                    int g   = (int) oscFloat(msg, 2, 0f);
                    int b   = (int) oscFloat(msg, 3, 0f);
                    setLed(pad, r, g, b);
                    if (r == 0 && g == 0 && b == 0) {
                        suggestionPads.remove(Integer.valueOf(pad));
                    } else if (!suggestionPads.contains(pad)) {
                        suggestionPads.add(pad);
                    }
                });

            // /launchpad/suggest/clear  — alle Suggestion-LEDs löschen
            space.registerMethod("/launchpad/suggest/clear", "*", "Clear suggestion LEDs",
                (src, msg) -> {
                    for (int pad : suggestionPads) setLed(pad, 0, 0, 0);
                    suggestionPads.clear();
                    host.println("[Launchpad] Suggestion-LEDs gelöscht");
                });

            // /launchpad/note/on <note> <vel>  — Note in Bitwig spielen
            space.registerMethod("/launchpad/note/on", "*", "Play note via NoteInput",
                (src, msg) -> {
                    int note = (int) oscFloat(msg, 0, 60f);
                    int vel  = Math.max(1, Math.min(127, (int) oscFloat(msg, 1, 100f)));
                    if (currentMode == Mode.DRUM) {
                        drumNoteInput.sendRawMidiEvent(0x99, note, vel);
                    } else {
                        instNoteInput.sendRawMidiEvent(0x90, note, vel);
                    }
                });

            // /launchpad/note/off <note>  — Note beenden
            space.registerMethod("/launchpad/note/off", "*", "Stop note via NoteInput",
                (src, msg) -> {
                    int note = (int) oscFloat(msg, 0, 60f);
                    if (currentMode == Mode.DRUM) {
                        drumNoteInput.sendRawMidiEvent(0x89, note, 0);
                    } else {
                        instNoteInput.sendRawMidiEvent(0x80, note, 0);
                    }
                });

            osc.createUdpServer(LED_OSC_PORT, space);
            host.println("[Launchpad] LED-OSC auf UDP:" + LED_OSC_PORT);
        } catch (Throwable e) {
            host.println("[Launchpad] LED-OSC Fehler: " + e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private float oscFloat(OscMessage msg, int idx, float def) {
        try { Float v = msg.getFloat(idx); return v != null ? v : def; }
        catch (Exception e) { return def; }
    }

    private void setLed(int note, int r, int g, int b) {
        if (midiOut == null) return;
        r = Math.max(0, Math.min(63, r));
        g = Math.max(0, Math.min(63, g));
        b = Math.max(0, Math.min(63, b));
        // SysEx: F0 00 20 29 02 18 0B note r g b F7
        String hex = String.format("F0 00 20 29 02 18 0B %02X %02X %02X %02X F7", note, r, g, b);
        midiOut.sendSysex(hex);
    }

    private void flashLed(int note, int r, int g, int b) {
        setLed(note, r, g, b);
        // Note: Bitwig's flush() würde hier reichen, aber wir setzten nach kurzer
        // Zeit zurück via Timer — stattdessen setzen wir sofort zurück beim Release
    }

    private void clearAllLeds() {
        if (midiOut == null) return;
        // Reset SysEx (Launchpad MK2 Reset: F0 00 20 29 02 18 0E 00 F7)
        midiOut.sendSysex("F0 00 20 29 02 18 0E 00 F7");
    }
}
