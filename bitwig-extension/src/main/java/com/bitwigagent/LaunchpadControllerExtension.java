package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.*;
import com.bitwig.extension.controller.ControllerExtension;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.*;

/**
 * Standalone Launchpad MK2 Controller — drei Modi:
 *
 *   SESSION    — 8×8 Clip-Launcher-Grid (Bitwig Session/Clip-Ansicht), Pfeil-Buttons scrollen
 *   DRUM       — 4×4 Drum-Pad-Grid, MIDI-Noten frei konfigurierbar
 *   INSTRUMENT — 8×8 Scale-Layout, Root-Note + Skala konfigurierbar
 *
 * Session-Button (CC 108) → SESSION, User1 (CC 109) → DRUM, User2 (CC 110) → INSTRUMENT
 */
public class LaunchpadControllerExtension extends ControllerExtension {

    // ── Drum Pad Konfiguration ────────────────────────────────────────────────
    // 4×4 Grid (16 Pads), Zeile 1 unten → Zeile 4 oben
    // ── Drum-Profile ─────────────────────────────────────────────────────────
    // GM / UJAM (VD-HEAVY, MT-PowerDrumKit): Standard General MIDI ab C1=36
    private static final int[] PROFILE_GM = {
        36, 37, 38, 39,   // Kick, Rimshot, Snare, Clap
        40, 41, 42, 43,   // E-Snare, Low Floor Tom, Closed HH, High Floor Tom
        44, 45, 46, 47,   // Pedal HH, Low Tom, Open HH, Low-Mid Tom
        48, 49, 50, 51    // Hi-Mid Tom, Crash 1, High Tom, Ride
    };
    // Bitwig Drum Machine: gleiche Noten wie GM (Standard-Belegung)
    private static final int[] PROFILE_DRUM_MACHINE = {
        36, 37, 38, 39,
        40, 41, 42, 43,
        44, 45, 46, 47,
        48, 49, 50, 51
    };
    // v9-Serie / Einzel-Instrumente: chromatisch ab C3=48
    private static final int[] PROFILE_V9 = {
        48, 49, 50, 51,   // C3, C#3, D3, D#3
        52, 53, 54, 55,   // E3, F3, F#3, G3
        56, 57, 58, 59,   // Ab3, A3, Bb3, B3
        60, 61, 62, 63    // C4, C#4, D4, D#4
    };

    // Aktives Profil (default: GM)
    private int[] DRUM_NOTES = PROFILE_GM;

    // Drum-Pad Farben (r, g, b je 0–63) — pro Drum-Kategorie
    private static final int[] DRUM_COLOR_KICK    = {63, 10,  0};  // rot-orange
    private static final int[] DRUM_COLOR_SNARE   = {63, 40,  0};  // orange
    private static final int[] DRUM_COLOR_HH      = {63, 63,  0};  // gelb
    private static final int[] DRUM_COLOR_TOM     = {0,  40, 63};  // blau
    private static final int[] DRUM_COLOR_CYMBAL  = {40,  0, 63};  // lila
    private static final int[] DRUM_COLOR_HIT     = {63, 63, 63};  // weiß (bei Treffer)

    // ── Instrument Konfiguration (dynamisch per OSC /launchpad/layout) ──────────
    // Root-Note (MIDI): 60 = C4, 48 = C3, 40 = E2 (Bass), 36 = C2
    private int instRootNote    = 48; // C3
    // Skala-Intervalle: Major={0,2,4,5,7,9,11}, Minor={0,2,3,5,7,8,10},
    //   Pentatonic={0,2,4,7,9}, Blues={0,3,5,6,7,10}, Chromatic=alle 12
    private int[] instScale       = {0, 2, 4, 5, 7, 9, 11}; // Major
    // Intervall zwischen Zeilen: 5 = Quarte (Push-Layout), 7 = Quinte
    private int instRowInterval = 5;

    // Instrument Farben
    private static final int[] INST_COLOR_ROOT    = {0,  63,  0};  // grün (Root-Note)
    private static final int[] INST_COLOR_SCALE   = {0,  20, 63};  // blau (Skalenton)
    private static final int[] INST_COLOR_OUTSIDE = {5,   5,  5};  // sehr dunkel (außerhalb)
    private static final int[] INST_COLOR_HIT     = {63, 63, 63};  // weiß (bei Treffer)

    // ── Session Mode Farben ───────────────────────────────────────────────────
    private static final int[] SESSION_COLOR_EMPTY     = { 0,  0,  0};  // aus
    private static final int[] SESSION_COLOR_STOPPED   = { 0, 25,  0};  // gedimmt grün
    private static final int[] SESSION_COLOR_PLAYING   = { 0, 63,  0};  // hell grün
    private static final int[] SESSION_COLOR_QUEUED    = {30, 63,  0};  // gelb-grün
    private static final int[] SESSION_COLOR_RECORDING = {63,  0,  0};  // rot
    private static final int[] SESSION_COLOR_REC_QUEUE = {63, 30,  0};  // orange

    private static final int SESSION_TRACKS = 8;
    private static final int SESSION_SCENES = 8;

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

    // Rechte Spalte (Note-On, von oben nach unten) — Original Launchpad MK2 Labels
    private static final int BTN_RECORD_ARM   = 89;
    private static final int BTN_TRACK_SELECT = 79;
    private static final int BTN_MUTE         = 69;
    private static final int BTN_SOLO         = 59;
    // 49=Volume, 39=Pan, 29=Sends — aktuell ungenutzt
    private static final int BTN_STOP_CLIP    = 19;

    // Port für den eingebauten OSC-Server (LED-Suggestions + Mode-Query vom Agent)
    private static final int LED_OSC_PORT   = 8003;
    // Reply-Port: Agent empfängt Mode-Antworten hier
    private static final int MODE_REPLY_PORT = 9005;

    // ── Interne Zustands-Felder ───────────────────────────────────────────────
    private enum Mode { SESSION, DRUM, INSTRUMENT }
    private Mode currentMode = Mode.SESSION;
    private OscConnection      modeReplyConn;
    private SettableStringValue agentHost;

    private MidiIn    midiIn;
    private MidiOut   midiOut;
    private NoteInput drumNoteInput;
    private NoteInput instNoteInput;

    private ControllerHost host;
    private Transport      transport;
    private CursorTrack    cursorTrack;
    private Application    application;
    private TrackBank      trackBank;
    private final ClipLauncherSlotBank[] slotBanks = new ClipLauncherSlotBank[SESSION_TRACKS];

    // Per-property boolean caches — updated only by indexed bank observers (no .get() calls)
    private final boolean[][] clipHasContent   = new boolean[SESSION_TRACKS][SESSION_SCENES];
    private final boolean[][] clipIsPlaying    = new boolean[SESSION_TRACKS][SESSION_SCENES];
    private final boolean[][] clipIsRecording  = new boolean[SESSION_TRACKS][SESSION_SCENES];
    private final boolean[][] clipIsPlayQueued = new boolean[SESSION_TRACKS][SESSION_SCENES];
    private final boolean[][] clipIsRecQueued  = new boolean[SESSION_TRACKS][SESSION_SCENES];

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

        agentHost = host.getPreferences()
                        .getStringSetting("Agent Host (IP)", "Network", 64, "127.0.0.1");
        agentHost.markInterested();

        // NoteInput nur für musikalische Pad-Noten; Funktions-/Scene-Buttons bleiben im Callback.
        drumNoteInput = midiIn.createNoteInput("LP Drums", buildDrumInputMasks());
        drumNoteInput.setShouldConsumeEvents(true);
        drumNoteInput.setKeyTranslationTable(buildDrumTranslationTable());

        // NoteInput für Instrument-Modus: 8×8 Grid ohne rechte Funktionsspalte.
        instNoteInput = midiIn.createNoteInput("LP Instrument", buildInstrumentInputMasks());
        instNoteInput.setShouldConsumeEvents(true);
        instNoteInput.setKeyTranslationTable(buildInstTranslationTable());

        // Beide NoteInputs starten blockiert — MIDI-Callback übernimmt LED + Routing
        drumNoteInput.setShouldConsumeEvents(false);
        instNoteInput.setShouldConsumeEvents(false);

        midiIn.setMidiCallback(this::onMidi);

        // TrackBank für Session View: 8 Tracks × 8 Scenes
        trackBank = host.createMainTrackBank(SESSION_TRACKS, 0, SESSION_SCENES);
        for (int t = 0; t < SESSION_TRACKS; t++) {
            final int ti = t;
            Track tr = (Track) trackBank.getItemAt(ti);
            tr.exists().markInterested();
            slotBanks[ti] = tr.clipLauncherSlotBank();
            slotBanks[ti].addHasContentObserver((idx, v) -> {
                if (idx < SESSION_SCENES) { clipHasContent[ti][idx] = v;   if (currentMode == Mode.SESSION) paintSlotLed(ti, idx); }
            });
            slotBanks[ti].addIsPlayingObserver((idx, v) -> {
                if (idx < SESSION_SCENES) { clipIsPlaying[ti][idx] = v;    if (currentMode == Mode.SESSION) paintSlotLed(ti, idx); }
            });
            slotBanks[ti].addIsRecordingObserver((idx, v) -> {
                if (idx < SESSION_SCENES) { clipIsRecording[ti][idx] = v;  if (currentMode == Mode.SESSION) paintSlotLed(ti, idx); }
            });
            slotBanks[ti].addIsPlaybackQueuedObserver((idx, v) -> {
                if (idx < SESSION_SCENES) { clipIsPlayQueued[ti][idx] = v; if (currentMode == Mode.SESSION) paintSlotLed(ti, idx); }
            });
            slotBanks[ti].addIsRecordingQueuedObserver((idx, v) -> {
                if (idx < SESSION_SCENES) { clipIsRecQueued[ti][idx] = v;  if (currentMode == Mode.SESSION) paintSlotLed(ti, idx); }
            });
        }

        setupLedOsc();

        // 300ms warten bis Launchpad MIDI-Verbindung bereit ist, dann LEDs setzen
        host.scheduleTask(() -> {
            enterMode(Mode.SESSION);
            host.showPopupNotification("Launchpad Agent — Session Mode");
        }, 300);
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

        if ((pressed || ccPressed) && handleFunctionButton(data1)) return;

        // Top-Row CC-Buttons
        if (ccPressed) {
            switch (data1) {
                case CC_BTN_SESSION: enterMode(Mode.SESSION);                                    break;
                case CC_BTN_USER1:   enterMode(Mode.DRUM);                                       break;
                case CC_BTN_USER2:   enterMode(Mode.INSTRUMENT);                                 break;
                case CC_BTN_MIXER:   application.setPanelLayout(Application.PANEL_LAYOUT_MIX);  break;
                case CC_BTN_UP:
                    if (currentMode == Mode.SESSION) trackBank.scrollTracksUp();
                    else executeAction("vol_up");    break;
                case CC_BTN_DOWN:
                    if (currentMode == Mode.SESSION) trackBank.scrollTracksDown();
                    else executeAction("vol_down");  break;
                case CC_BTN_LEFT:
                    if (currentMode == Mode.SESSION) trackBank.scrollScenesUp();
                    else executeAction("prev_track"); break;
                case CC_BTN_RIGHT:
                    if (currentMode == Mode.SESSION) trackBank.scrollScenesDown();
                    else executeAction("next_track"); break;
            }
            return;
        }

        switch (currentMode) {
            case SESSION:    handleSession(data1, pressed);                     break;
            case DRUM:       handleDrum(data1, data2, pressed, released);       break;
            case INSTRUMENT: handleInstrument(data1, data2, pressed, released); break;
        }
    }

    private boolean handleFunctionButton(int noteOrCc) {
        switch (noteOrCc) {
            case BTN_RECORD_ARM:
                cursorTrack.arm().toggle();
                flashFunctionButton(BTN_RECORD_ARM, 63, 63, 63);
                return true;
            case BTN_TRACK_SELECT:
                cursorTrack.selectNext();
                flashFunctionButton(BTN_TRACK_SELECT, 63, 63, 63);
                return true;
            case BTN_MUTE:
                cursorTrack.mute().toggle();
                flashFunctionButton(BTN_MUTE, 63, 63, 63);
                return true;
            case BTN_SOLO:
                cursorTrack.solo().toggle();
                flashFunctionButton(BTN_SOLO, 63, 63, 63);
                return true;
            case BTN_STOP_CLIP:
                transport.stop();
                flashFunctionButton(BTN_STOP_CLIP, 63, 63, 63);
                return true;
            default:
                return false;
        }
    }

    private void flashFunctionButton(int button, int r, int g, int b) {
        setLed(button, r, g, b);
        host.scheduleTask(this::paintModeButtons, 120);
    }

    // ── Session Mode ─────────────────────────────────────────────────────────

    /** Berechnet den Launchpad-Pad-Note aus Track- und Scene-Index. */
    private int sessionPadNote(int trackIdx, int sceneIdx) {
        int row = SESSION_SCENES - sceneIdx;  // Zeile 8 = Scene 0 (oben)
        int col = trackIdx + 1;
        return row * 10 + col;
    }

    /** Leitet den Clip-Anzeigestatus aus den boolean Caches ab (keine API-Calls). */
    private int deriveClipState(int t, int s) {
        if (clipIsRecQueued[t][s])  return 5;
        if (clipIsRecording[t][s])  return 4;
        if (clipIsPlayQueued[t][s]) return 3;
        if (clipIsPlaying[t][s])    return 2;
        if (clipHasContent[t][s])   return 1;
        return 0;
    }

    private void paintSlotLed(int trackIdx, int sceneIdx) {
        int pad = sessionPadNote(trackIdx, sceneIdx);
        int state = deriveClipState(trackIdx, sceneIdx);
        int[] color;
        switch (state) {
            case 1:  color = SESSION_COLOR_STOPPED;   break;
            case 2:  color = SESSION_COLOR_PLAYING;   break;
            case 3:  color = SESSION_COLOR_QUEUED;    break;
            case 4:  color = SESSION_COLOR_RECORDING; break;
            case 5:  color = SESSION_COLOR_REC_QUEUE; break;
            default: color = SESSION_COLOR_EMPTY;     break;
        }
        setLed(pad, color[0], color[1], color[2]);
    }

    private void handleSession(int note, boolean pressed) {
        if (!pressed) return;
        int row = note / 10;
        int col = note % 10;
        if (row < 1 || row > 8 || col < 1 || col > 8) return;
        int sceneIdx = SESSION_SCENES - row;
        int trackIdx = col - 1;
        if (trackIdx >= SESSION_TRACKS || sceneIdx >= SESSION_SCENES) return;
        slotBanks[trackIdx].launch(sceneIdx);
        // LED kurz weiß aufleuchten, dann zurück auf Clip-Status
        setLed(note, 63, 63, 63);
        host.scheduleTask(() -> paintSlotLed(trackIdx, sceneIdx), 150);
    }

    private boolean isSessionGridPad(int note) {
        int row = note / 10;
        int col = note % 10;
        return row >= 1 && row <= 8 && col >= 1 && col <= 8;
    }

    private void repaintSessionPad(int note) {
        int row = note / 10;
        int col = note % 10;
        int sceneIdx = SESSION_SCENES - row;
        int trackIdx = col - 1;
        if (trackIdx >= 0 && trackIdx < SESSION_TRACKS && sceneIdx >= 0 && sceneIdx < SESSION_SCENES) {
            paintSlotLed(trackIdx, sceneIdx);
        }
    }

    private void paintSessionMode() {
        for (int t = 0; t < SESSION_TRACKS; t++) {
            for (int s = 0; s < SESSION_SCENES; s++) {
                paintSlotLed(t, s);
            }
        }
    }

    private void executeAction(String action) {
        switch (action) {
            case "vol_up":   cursorTrack.volume().inc(1.0 / 128.0, 128);   break;
            case "vol_down": cursorTrack.volume().inc(-1.0 / 128.0, 128);  break;
            case "next_track": cursorTrack.selectNext();                    break;
            case "prev_track": cursorTrack.selectPrevious();                break;
        }
    }


    // ── Drum Mode ────────────────────────────────────────────────────────────

    private void handleDrum(int note, int velocity, boolean pressed, boolean released) {
        int drumIdx = LaunchpadPadLayout.drumGridIndex(note);
        if (drumIdx < 0 || drumIdx >= DRUM_NOTES.length) return;
        int drumNote = DRUM_NOTES[drumIdx];

        // LED-Feedback — MIDI-Routing übernimmt drumNoteInput (setShouldConsumeEvents=true in DRUM-Modus)
        if (pressed) {
            setLed(note, DRUM_COLOR_HIT[0], DRUM_COLOR_HIT[1], DRUM_COLOR_HIT[2]);
            safeSendReply("/launchpad/note/played", drumNote, velocity);
        } else {
            int[] col = drumColor(drumIdx);
            setLed(note, col[0], col[1], col[2]);
        }
    }



    private int[] drumColor(int idx) {
        int note = DRUM_NOTES[idx];
        // Profil-abhängige Farben
        if (DRUM_NOTES == PROFILE_V9) {
            // Chromatisch: Farbe nach Tonklasse
            return LaunchpadPadLayout.CHROMATIC_COLORS[note % 12];
        }
        // GM / Drum Machine: funktionale Farben
        if (note == 36 || note == 40)               return DRUM_COLOR_KICK;
        if (note == 37 || note == 38 || note == 39)  return DRUM_COLOR_SNARE;
        if (note == 42 || note == 44 || note == 46)  return DRUM_COLOR_HH;
        if (note == 49 || note == 51 || note == 57)  return DRUM_COLOR_CYMBAL;
        return DRUM_COLOR_TOM;
    }

    private void paintDrumMode() {
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                int idx = row * 4 + col;
                int[] color = drumColor(idx);
                setLed(LaunchpadPadLayout.DRUM_GRID_NOTES[row][col], color[0], color[1], color[2]);
            }
        }
    }

    // ── Instrument Mode ───────────────────────────────────────────────────────

    private void handleInstrument(int note, int velocity, boolean pressed, boolean released) {
        int midiNote = LaunchpadPadLayout.instNoteForPad(note, instRootNote, instRowInterval, instScale);
        if (midiNote < 0 || midiNote > 127) return;

        if (pressed) {
            int vel = Math.max(1, Math.min(127, velocity));
            instNoteInput.sendRawMidiEvent(0x90, midiNote, vel);
            setLed(note, INST_COLOR_HIT[0], INST_COLOR_HIT[1], INST_COLOR_HIT[2]);
            safeSendReply("/launchpad/note/played", midiNote, vel);
        } else {
            instNoteInput.sendRawMidiEvent(0x80, midiNote, 0);
            int[] col = instPadColor(midiNote);
            setLed(note, col[0], col[1], col[2]);
        }
    }


    private int[] instPadColor(int midiNote) {
        int interval = ((midiNote - instRootNote) % 12 + 12) % 12;
        if (interval == 0) return INST_COLOR_ROOT;
        for (int s : instScale) if (s == interval) return INST_COLOR_SCALE;
        return INST_COLOR_OUTSIDE;
    }

    private void paintInstrumentMode() {
        for (int row = 1; row <= 8; row++) {
            for (int col = 1; col <= 8; col++) {
                int padNote  = row * 10 + col;
                int midiNote = LaunchpadPadLayout.instNoteForPad(padNote, instRootNote, instRowInterval, instScale);
                if (midiNote < 0 || midiNote > 127) continue;
                int[] color = instPadColor(midiNote);
                setLed(padNote, color[0], color[1], color[2]);
            }
        }
    }

    // ── Translation Tables für NoteInput ─────────────────────────────────────

    private String midiNoteMask(int statusNibble, int note) {
        return String.format("%X?%02X??", statusNibble, note & 0x7F);
    }

    private void addNoteInputMasks(java.util.List<String> masks, int note) {
        masks.add(midiNoteMask(0x9, note));
        masks.add(midiNoteMask(0x8, note));
    }

    private String[] buildDrumInputMasks() {
        java.util.List<String> masks = new java.util.ArrayList<>();
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                addNoteInputMasks(masks, LaunchpadPadLayout.DRUM_GRID_NOTES[row][col]);
            }
        }
        return masks.toArray(new String[0]);
    }

    private String[] buildInstrumentInputMasks() {
        java.util.List<String> masks = new java.util.ArrayList<>();
        for (int row = 1; row <= 8; row++) {
            for (int col = 1; col <= 8; col++) {
                addNoteInputMasks(masks, row * 10 + col);
            }
        }
        return masks.toArray(new String[0]);
    }

    private void setDrumProfile(String pluginName) {
        String key = pluginName.toLowerCase().replace("-", "").replace(" ", "").replace("_", "");
        int[] profile;
        String profileName;
        if (key.startsWith("v0") || key.startsWith("v1") || key.startsWith("v8") || key.startsWith("v9")
                || key.contains("e-kick") || key.contains("e-snare") || key.contains("e-hat")) {
            profile = PROFILE_V9;
            profileName = "v9 (chromatisch C3)";
        } else if (key.contains("drummachine") || key.contains("drum machine")) {
            profile = PROFILE_DRUM_MACHINE;
            profileName = "drum-machine (GM)";
        } else {
            // Default: GM für VD-HEAVY, MT-PowerDrumKit und alle anderen Drum-VSTs
            profile = PROFILE_GM;
            profileName = "gm";
        }
        DRUM_NOTES = profile;
        drumNoteInput.setKeyTranslationTable(buildDrumTranslationTable());
        if (currentMode == Mode.DRUM) paintDrumMode(); // LEDs aktualisieren
        host.println("[Launchpad] Drum-Profil: " + profileName + " für '" + pluginName + "'");
    }

    private void setInstrumentLayout(int rootNote, String scaleType) {
        instRootNote = rootNote;
        switch (scaleType.toLowerCase()) {
            case "minor":      instScale = new int[]{0,2,3,5,7,8,10};          break;
            case "pentatonic": instScale = new int[]{0,2,4,7,9};               break;
            case "blues":      instScale = new int[]{0,3,5,6,7,10};            break;
            case "chromatic":  instScale = new int[]{0,1,2,3,4,5,6,7,8,9,10,11}; break;
            default:           instScale = new int[]{0,2,4,5,7,9,11};         break; // major
        }
        instNoteInput.setKeyTranslationTable(buildInstTranslationTable());
        if (currentMode == Mode.INSTRUMENT) paintInstrumentMode();
        host.println("[Launchpad] Instrument-Layout: root=" + rootNote + ", scale=" + scaleType);
    }

    private Integer[] buildDrumTranslationTable() {
        Integer[] table = new Integer[128];
        java.util.Arrays.fill(table, -1); // alle blockieren
        for (int row = 0; row < 4; row++) {
            for (int col = 0; col < 4; col++) {
                int padNote  = LaunchpadPadLayout.DRUM_GRID_NOTES[row][col];
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
                int midiNote = LaunchpadPadLayout.instNoteForPad(padNote, instRootNote, instRowInterval, instScale);
                if (padNote < 128 && midiNote >= 0 && midiNote <= 127)
                    table[padNote] = midiNote;
            }
        }
        return table;
    }

    // ── Modus wechseln ────────────────────────────────────────────────────────

    private void enterMode(Mode mode) {
        currentMode = mode;
        drumNoteInput.setShouldConsumeEvents(mode == Mode.DRUM);
        instNoteInput.setShouldConsumeEvents(mode == Mode.INSTRUMENT);
        suggestionPads.clear();
        clearAllLeds();

        switch (mode) {
            case SESSION:    paintSessionMode();    break;
            case DRUM:       paintDrumMode();       break;
            case INSTRUMENT: paintInstrumentMode(); break;
        }
        paintModeButtons();
        safeSendReply("/launchpad/mode/changed", mode.name());
        host.println("[Launchpad] Modus: " + mode);
    }

    /** Sendet OSC-Reply ohne die Extension bei Netzwerk-Fehlern zu killen. */
    private void safeSendReply(String address, Object... args) {
        if (modeReplyConn == null) return;
        try {
            modeReplyConn.sendMessage(address, args);
        } catch (Throwable t) {
            // Host down / no route — Agent ist nicht erreichbar. Nicht fatal.
            host.println("[Launchpad] Reply ignoriert (" + address + "): "
                + t.getClass().getSimpleName() + ": " + t.getMessage());
        }
    }

    private void paintModeButtons() {
        // Session/User1/User2: aktiver Modus hell, andere dunkel
        setLed(CC_BTN_SESSION,
            currentMode == Mode.SESSION    ? 63 : 8,
            currentMode == Mode.SESSION    ? 63 : 8,
            currentMode == Mode.SESSION    ? 63 : 8);
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
        // Rechte Spalte: Original Launchpad MK2 Labels
        setLed(BTN_RECORD_ARM,   63,  0,  0);  // Rot    = Record Arm
        setLed(BTN_TRACK_SELECT,  0, 30, 63);  // Blau   = Track Select
        setLed(BTN_MUTE,         50, 15,  0);  // Orange = Mute
        setLed(BTN_SOLO,         63, 63,  0);  // Gelb   = Solo
        setLed(49,                0,  0,  0);  // aus    = Volume (ungenutzt)
        setLed(39,                0,  0,  0);  // aus    = Pan (ungenutzt)
        setLed(29,                0,  0,  0);  // aus    = Sends (ungenutzt)
        setLed(BTN_STOP_CLIP,    50, 20,  0);  // Orange-Rot = Stop Clip
    }

    // ── LED Hilfsmethoden ─────────────────────────────────────────────────────

    // ── OSC LED-Server (Port 8003) ────────────────────────────────────────────

    private void setupLedOsc() {
        try {
            OscModule       osc   = host.getOscModule();
            OscAddressSpace space = osc.createAddressSpace();

            // Outbound: Reply-Verbindung zu Agent (Port 9005)
            String ah = (agentHost != null && !agentHost.get().isBlank()) ? agentHost.get() : "127.0.0.1";
            modeReplyConn = osc.connectToUdpServer(ah, MODE_REPLY_PORT, space);
            host.println("[Launchpad] Reply → " + ah + ":" + MODE_REPLY_PORT);

            // /launchpad/mode/get  — aktuellen Modus zurückschicken
            space.registerMethod("/launchpad/mode/get", "*", "Get current mode",
                (src, msg) -> safeSendReply("/launchpad/mode/response", currentMode.name()));

            // /launchpad/drum/profile <plugin_name>  — Drum-Note-Mapping wechseln
            space.registerMethod("/launchpad/drum/profile", "*", "Set drum note profile",
                (src, msg) -> {
                    String name = msg.getString(0);
                    if (name != null && !name.isBlank()) setDrumProfile(name);
                });

            // /launchpad/led <pad> <r> <g> <b>  — einzelne Pad-Farbe setzen
            space.registerMethod("/launchpad/led", "*", "Set suggestion LED",
                (src, msg) -> {
                    int pad = (int) oscFloat(msg, 0, 11f);
                    int r   = (int) oscFloat(msg, 1, 0f);
                    int g   = (int) oscFloat(msg, 2, 0f);
                    int b   = (int) oscFloat(msg, 3, 0f);
                    if (currentMode == Mode.SESSION && isSessionGridPad(pad)) {
                        repaintSessionPad(pad);
                        return;
                    }
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
                    for (int pad : suggestionPads) {
                        if (currentMode == Mode.SESSION && isSessionGridPad(pad)) repaintSessionPad(pad);
                        else setLed(pad, 0, 0, 0);
                    }
                    suggestionPads.clear();
                    host.println("[Launchpad] Suggestion-LEDs gelöscht");
                });

            // Modus per OSC wechseln — scheduleTask sorgt für Bitwig-Hauptthread
            space.registerMethod("/launchpad/mode/session",    "*", "Enter SESSION mode",
                (src, msg) -> host.scheduleTask(() -> enterMode(Mode.SESSION), 0));
            space.registerMethod("/launchpad/mode/drum",       "*", "Enter DRUM mode",
                (src, msg) -> host.scheduleTask(() -> enterMode(Mode.DRUM), 0));
            space.registerMethod("/launchpad/mode/instrument", "*", "Enter INSTRUMENT mode",
                (src, msg) -> host.scheduleTask(() -> enterMode(Mode.INSTRUMENT), 0));
            // arm/track und note/on ebenfalls auf Hauptthread
            space.registerMethod("/launchpad/note/on",  "*", "Play note — main thread",
                (src, msg) -> {
                    int note = (int) oscFloat(msg, 0, 60f);
                    int vel  = Math.max(1, Math.min(127, (int) oscFloat(msg, 1, 100f)));
                    final Mode m = currentMode;
                    host.scheduleTask(() -> {
                        if (m == Mode.DRUM) drumNoteInput.sendRawMidiEvent(0x99, note, vel);
                        else if (m == Mode.INSTRUMENT) instNoteInput.sendRawMidiEvent(0x90, note, vel);
                    }, 0);
                });
            space.registerMethod("/launchpad/note/off", "*", "Stop note — main thread",
                (src, msg) -> {
                    int note = (int) oscFloat(msg, 0, 60f);
                    final Mode m = currentMode;
                    host.scheduleTask(() -> {
                        if (m == Mode.DRUM) drumNoteInput.sendRawMidiEvent(0x89, note, 0);
                        else if (m == Mode.INSTRUMENT) instNoteInput.sendRawMidiEvent(0x80, note, 0);
                    }, 0);
                });
            // /launchpad/layout <root_midi_note> <scale_type>  — Instrument-Grid Layout setzen
            space.registerMethod("/launchpad/layout", "*", "Set instrument layout root+scale",
                (src, msg) -> {
                    int root     = (int) oscFloat(msg, 0, 48f);
                    String scale = msg.getString(1);
                    if (scale == null || scale.isBlank()) scale = "major";
                    final int r = root; final String s = scale;
                    host.scheduleTask(() -> setInstrumentLayout(r, s), 0);
                });
            space.registerMethod("/launchpad/track/arm", "*", "Arm/disarm cursor track — main thread",
                (src, msg) -> {
                    int v = (int) oscFloat(msg, 0, 1f);
                    host.scheduleTask(() -> cursorTrack.arm().set(v == 1), 0);
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
