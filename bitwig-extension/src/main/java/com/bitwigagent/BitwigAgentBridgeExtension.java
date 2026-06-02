package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.*;
import com.bitwig.extension.callback.BooleanValueChangedCallback;
import com.bitwig.extension.callback.StringValueChangedCallback;
import com.bitwig.extension.controller.ControllerExtension;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.*;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Bitwig Agent Bridge v2 — OSC-Server für Bitwig Studio 6.
 *
 * Neu in v2:
 *   /browser/device/load <name>  — Instrument nach Name laden (Katalog-Suche)
 *   /device/param/named <name> <val> — Parameter nach Name setzen
 *   /device/param/page/next|prev    — Parameter-Seiten wechseln
 *   /device/param/page/set <n>      — Direkt auf Seite n springen
 */
public class BitwigAgentBridgeExtension extends ControllerExtension {

    private static final int OSC_PORT        = 8001;
    private static final int OSC_REPLY_PORT  = 9001;
    private static final int OSC_AGENT_UI_PORT = 9003;
    private static final int TRACK_BANK_SIZE = 16;
    private static final int MAX_SENDS       = 8;
    private static final int BROWSER_SCAN    = 128;
    private static final int REMOTE_PARAMS   = 8;
    private static final int CLIP_STEPS      = 512;  // 32 bars @ 1/16 (128 Beats)
    private static final int SLOT_BANK_SIZE  = 8;

    protected ControllerHost     host;
    private Transport            transport;
    private TrackBank            trackBank;
    private TrackBank            effectTrackBank;
    private CursorTrack          cursorTrack;
    private CursorDevice         cursorDevice;
    private PopupBrowser         popupBrowser;
    private Application          application;
    private CursorRemoteControlsPage remoteControls;
    private BrowserItemBank      resultBank;
    private CursorClip           cursorClip;
    private ClipLauncherSlotBank clipSlotBank;
    private SceneBank            sceneBank;
    private OscConnection        replyLoopbackV4;
    private OscConnection        replyLoopbackLocalhost;
    private OscConnection        agentUiLoopback;
    private SettableStringValue  cfgPrompt;
    private SettableStringValue  agentHost;
    private SettableRangedValue  cfgBpm;
    private BrowserFilterItemBank    categoryBank;     // Kategorie-Spalte (linke Spalte)
    private BrowserFilterItemBank    smartCollBank;    // Smart-Collections
    private BrowserFilterItemBank    locationBank;     // Locations (Bitwig Studio, Plug-ins, …)
    private static final int         CAT_BANK_SIZE  = 64;
    private static final int         COLL_BANK_SIZE = 32;
    private static final int         LOC_BANK_SIZE  = 16;
    private volatile String          loadCollection   = null;
    private volatile boolean         loadPluginsFilter = false; // true nach Plug-ins-Filter

    // Device-Browser (zuverlässiger als PopupBrowser für Fallback)
    private Browser                  deviceBrowser;
    private DeviceBrowsingSession    deviceSession;
    private CursorBrowserResultItem  cursorResult;

    // Launchpad MK2 MIDI
    private MidiIn  launchpadIn;
    private MidiOut launchpadOut;
    private final Map<Integer, String> padMappings = new HashMap<>();

    // Katalog: Browser-Ergebnisname (lowercase) → Position im Bank
    private final Map<String, Integer> deviceCatalog = new HashMap<>();

    // Built-in Device UUIDs — delegiert an BuiltinDeviceUuids
    private static final Map<String, String> BUILTIN_UUIDS = new HashMap<>(BuiltinDeviceUuids.MAP);
    // Aktuell geladene Parameter-Namen (lowercase) → Index 0-7
    private final Map<String, Integer> paramCatalog  = new HashMap<>();

    // Ziel-Gerätename für asynchrones Laden via flush()
    private volatile String  loadTarget          = null;
    // Note-Count: pro Track+Slot beim Schreiben mitzählen (zuverlässiger als Observer)
    private final Map<String, Integer> noteCountMap = new HashMap<>(); // "track:slot" → count
    private volatile int     loadWaitLeft  = 0;   // Flush-Zyklen warten bevor navigiert wird

    // F11: Observer-State für Browser-ACK
    private volatile String  pendingLoadName   = null;  // Name des gerade ladenden Devices
    private volatile String  lastCommittedName = null;  // Zuletzt bestätigter Result-Name

    // Preset-Suche: Name → nach browseToReplaceDevice im resultBank scannen
    private volatile String  presetTarget   = null;
    private volatile int     presetWaitLeft = 0;

    // FX-Chain-Preset-Suche: Audioeffekte-Kategorie → browseToInsertAfterDevice
    private volatile String  fxPresetTarget   = null;
    private volatile int     fxPresetWaitLeft = 0;
    private volatile String  fxCategoryTarget = null;

    protected BitwigAgentBridgeExtension(
            ControllerExtensionDefinition definition, ControllerHost host) {
        super(definition, host);
    }

    @Override
    public void init() {
        host = (ControllerHost) getHost();

        transport    = host.createTransport();
        trackBank       = host.createMainTrackBank(TRACK_BANK_SIZE, MAX_SENDS, SLOT_BANK_SIZE);
        effectTrackBank = host.createEffectTrackBank(MAX_SENDS, SLOT_BANK_SIZE);
        cursorTrack  = host.createCursorTrack("agent-cursor", "Agent Cursor", 0, SLOT_BANK_SIZE, true);
        cursorDevice = cursorTrack.createCursorDevice();
        popupBrowser = host.createPopupBrowser();
        application  = host.createApplication();

        // Remote Controls — 8 Parameter der aktuellen Seite
        remoteControls = cursorDevice.createCursorRemoteControlsPage(REMOTE_PARAMS);

        // Clip-Launcher: Slot-Bank + Note-Editor + Scene-Bank
        clipSlotBank   = cursorTrack.clipLauncherSlotBank();
        sceneBank      = trackBank.sceneBank();
        cursorClip     = cursorTrack.createLauncherCursorClip(CLIP_STEPS, 128);
        // Device-Browser für zuverlässigen Fallback (VST, Presets etc.)
        deviceBrowser = cursorDevice.createDeviceBrowser(700, 500);
        deviceSession = deviceBrowser.getDeviceSession();
        cursorResult  = deviceSession.getCursorResult();
        cursorResult.name().markInterested();
        cursorResult.exists().markInterested();
        cursorResult.isSelected().markInterested();

        // F11: Observer — lastCommittedName mitschreiben sobald Cursor-Result wechselt
        cursorResult.name().addValueObserver(new StringValueChangedCallback() {
            @Override
            public void valueChanged(Object newName) {
                lastCommittedName = newName != null ? newName.toString() : null;
            }
        });

        // F11: Observer — Browser-ACK senden wenn PopupBrowser sich schließt
        popupBrowser.exists().addValueObserver(new BooleanValueChangedCallback() {
            @Override
            public void valueChanged(boolean isOpen) {
                if (!isOpen) {
                    loadPluginsFilter = false;
                    if (pendingLoadName != null) {
                        String pn = pendingLoadName;
                        String cn = lastCommittedName;
                        boolean ok = cn != null && cn.toLowerCase().contains(pn.toLowerCase());
                        sendReply(null, "/browser/device/loaded", pn, ok ? 1 : 0);
                        host.println("[BitwigAgent] Browser geschlossen — geladen: " + pn + " ok=" + ok);
                        pendingLoadName   = null;
                        lastCommittedName = null;
                    }
                }
            }
        });

        cursorClip.setStepSize(0.25); // default: 1/16-Noten

        setupBrowserCatalog();
        setupParamCatalog();
        setupTrackBank();
        setupOsc(host);
        setupExtras();

        host.showPopupNotification("Bitwig Agent Bridge v2 (Port " + OSC_PORT + ")");
        host.println("[BitwigAgent] v2 gestartet — Port " + OSC_PORT);
    }

    /** Optionale Extras — überschreibbar für Subklassen (z.B. BitwigOscBridgeExtension). */
    protected void setupExtras() {
        setupAgentUi();
        setupLaunchpad();
    }

    // ── Bitwig-internes Agent-UI (Preferences) ──────────────────────────────

    private void setupAgentUi() {
        Preferences prefs = host.getPreferences();

        cfgPrompt = prefs.getStringSetting("Prompt", "Agent", 400, "");
        cfgBpm = prefs.getNumberSetting("BPM (optional)", "Agent", 60.0, 200.0, 1.0, " bpm", 0.0);
        agentHost = prefs.getStringSetting("Agent Host (IP)", "Network", 64, "127.0.0.1");
        agentHost.markInterested();

        Signal sendPrompt = prefs.getSignalSetting(
            "Send",
            "Agent",
            "Prompt an Agent senden"
        );
        sendPrompt.addSignalObserver(() -> {
            String prompt = cfgPrompt != null ? cfgPrompt.get() : "";
            int bpm = cfgBpm != null ? (int) Math.round(cfgBpm.get()) : 0;
            if (prompt == null || prompt.isBlank()) {
                host.showPopupNotification("Prompt ist leer");
                return;
            }
            String payload = "{\"prompt\":\"" + escapeJson(prompt) + "\",\"bpm\":" + bpm + "}";
            boolean delivered = sendAgentUiPromptWithRetries(payload, 8, 350L);
            if (delivered) {
                host.println("[BitwigAgent] Prompt gesendet: " + prompt.substring(0, Math.min(80, prompt.length())));
                host.showPopupNotification("Prompt gesendet");
            } else {
                host.showPopupNotification("Agent nicht erreichbar (OSC 127.0.0.1:9003)");
            }
        });

        Signal playNow = prefs.getSignalSetting(
            "Play",
            "Agent Controls",
            "Transport starten"
        );
        playNow.addSignalObserver(() -> {
            transport.play();
            host.showPopupNotification("Agent UI: Play");
        });

        Signal stopNow = prefs.getSignalSetting(
            "Stop",
            "Agent Controls",
            "Transport stoppen"
        );
        stopNow.addSignalObserver(() -> {
            transport.stop();
            host.showPopupNotification("Agent UI: Stop");
        });

        Signal showStatus = prefs.getSignalSetting(
            "Show Status",
            "Agent Controls",
            "Track-/Transport-Status anzeigen"
        );
        showStatus.addSignalObserver(() -> {
            int trackCount = 0;
            for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                Channel t = (Channel) trackBank.getItemAt(i);
                if (t.exists().get()) trackCount++;
            }
            boolean playing = transport.isPlaying().get();
            float tempo = (float) transport.tempo().get();
            String msg = "Tracks=" + trackCount + " | playing=" + playing + " | bpm=" + Math.round(tempo);
            host.println("[BitwigAgent] Agent UI Status: " + msg);
            host.showPopupNotification(msg);
        });

    }

    private String escapeJson(String value) {
        if (value == null) return "";
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private boolean sendAgentUiPrompt(String payload) {
        if (agentUiLoopback == null) return false;
        try {
            agentUiLoopback.sendMessage("/agent/ui/config", payload);
            return true;
        } catch (Exception e) {
            host.println("[BitwigAgent] Agent-UI Sendefehler: " + e.getMessage());
            return false;
        }
    }

    private boolean sendAgentUiPromptWithRetries(String prompt, int attempts, long delayMs) {
        for (int i = 0; i < attempts; i++) {
            if (sendAgentUiPrompt(prompt)) return true;
            try {
                Thread.sleep(delayMs);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return false;
            }
        }
        return false;
    }

    // ── Browser-Katalog aufbauen ──────────────────────────────────────────────

    private void setupBrowserCatalog() {
        resultBank = popupBrowser.resultsColumn().createItemBank(BROWSER_SCAN);
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            item.name().markInterested();
            item.exists().markInterested();
            item.isSelected().markInterested();
        }
        // Linke Spalte (Kategorie-Filter) für direktes Selektieren per Name
        categoryBank = popupBrowser.categoryColumn().createItemBank(CAT_BANK_SIZE);
        for (int i = 0; i < CAT_BANK_SIZE; i++) {
            BrowserItem item = categoryBank.getItem(i);
            item.name().markInterested();
            item.exists().markInterested();
            item.isSelected().markInterested();
        }
        // Smart-Collections (Kollektion-Spalte) — z.B. "BitwigAgent" Collection
        smartCollBank = popupBrowser.smartCollectionColumn().createItemBank(COLL_BANK_SIZE);
        for (int i = 0; i < COLL_BANK_SIZE; i++) {
            BrowserItem item = smartCollBank.getItem(i);
            item.name().markInterested();
            item.exists().markInterested();
            item.isSelected().markInterested();
        }
        // Location-Spalte — für VST-Filter (Plug-ins vs. Bitwig Studio)
        locationBank = popupBrowser.locationColumn().createItemBank(LOC_BANK_SIZE);
        for (int i = 0; i < LOC_BANK_SIZE; i++) {
            BrowserItem item = locationBank.getItem(i);
            item.name().markInterested();
            item.exists().markInterested();
            item.isSelected().markInterested();
        }
    }

    // ── Parameter-Namen-Katalog ───────────────────────────────────────────────

    private void setupParamCatalog() {
        remoteControls.getName().markInterested();
        remoteControls.pageNames().markInterested();
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            RemoteControl param = remoteControls.getParameter(i);
            param.name().markInterested();
            param.value().markInterested();
        }
    }

    // ── TrackBank beobachten ──────────────────────────────────────────────────

    private void setupTrackBank() {
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Channel t = (Channel) trackBank.getItemAt(i);
            t.name().markInterested();
            t.exists().markInterested();
        }
        for (int i = 0; i < MAX_SENDS; i++) {
            Channel et = (Channel) effectTrackBank.getItemAt(i);
            et.name().markInterested();
            et.exists().markInterested();
        }
        cursorDevice.name().markInterested();
        cursorTrack.name().markInterested();
        popupBrowser.exists().markInterested();
        transport.isPlaying().markInterested();
        transport.tempo().markInterested();
    }

    // ── Hilfsmethoden ─────────────────────────────────────────────────────────

    private float argFloat(OscMessage msg, int idx, float def) {
        try { Float v = msg.getFloat(idx); return v != null ? v : def; }
        catch (Exception e) { return def; }
    }

    private String argStr(OscMessage msg, int idx) {
        try { return msg.getString(idx); }
        catch (Exception e) {
            try { return String.valueOf(msg.getFloat(idx)); }
            catch (Exception ex) { return null; }
        }
    }

    // ── OSC Setup ─────────────────────────────────────────────────────────────

    private void setupOsc(ControllerHost host) {
        OscModule       osc   = host.getOscModule();
        OscAddressSpace space = osc.createAddressSpace();
        String ah = (agentHost != null && !agentHost.get().isBlank()) ? agentHost.get() : "127.0.0.1";
        replyLoopbackV4        = osc.connectToUdpServer(ah,          OSC_REPLY_PORT,   space);
        replyLoopbackLocalhost = osc.connectToUdpServer("localhost",  OSC_REPLY_PORT,   space);
        agentUiLoopback        = osc.connectToUdpServer(ah,           OSC_AGENT_UI_PORT, space);
        host.println("[BitwigBridge] Reply → " + ah + ":" + OSC_REPLY_PORT);

        // ── Arranger — Scene in Timeline aufnehmen ────────────────────────
        // /arrange/record/start  — Arrangement-Recording + Arranger-View + Play
        space.registerMethod("/arrange/record/start", "*", "Record scene to arrangement",
                (src, msg) -> {
                    application.setPanelLayout(Application.PANEL_LAYOUT_ARRANGE);
                    transport.isArrangerRecordEnabled().set(true);
                    transport.play();
                    host.println("[BitwigAgent] Arrangement-Recording gestartet");
                });

        // /arrange/record/stop  — Recording stoppen
        space.registerMethod("/arrange/record/stop", "*", "Stop arrangement recording",
                (src, msg) -> {
                    transport.stop();
                    transport.isArrangerRecordEnabled().set(false);
                    host.println("[BitwigAgent] Arrangement-Recording gestoppt");
                });

        // /arrange/view  — Zur Arrange-Ansicht wechseln
        space.registerMethod("/arrange/view", "*", "Switch to Arrange view",
                (src, msg) -> {
                    application.setPanelLayout(Application.PANEL_LAYOUT_ARRANGE);
                    host.println("[BitwigAgent] Arrange-View aktiviert");
                });

        // ── Clip Note-Count ───────────────────────────────────────────────
        // /clip/note/count  → zählt Noten im aktuellen CursorClip und sendet zurück
        // /clip/note/count  → gibt Note-Count für aktuellen Track zurück
        space.registerMethod("/clip/note/count", "*", "Count notes in cursor clip",
                (src, msg) -> {
                    String trackName = cursorTrack.name().get();
                    int count = trackName != null ? noteCountMap.getOrDefault(trackName, 0) : 0;
                    sendReply(src, "/clip/note/count/response", count);
                    host.println("[BitwigAgent] Track '" + trackName + "': " + count + " Noten");
                });

        space.registerMethod("/clip/note/count/all", "*", "Count all notes",
                (src, msg) -> {
                    int total = 0;
                    StringBuilder sb = new StringBuilder();
                    for (Map.Entry<String, Integer> e : noteCountMap.entrySet()) {
                        if (sb.length() > 0) sb.append(";");
                        sb.append(e.getKey()).append("=").append(e.getValue());
                        total += e.getValue();
                    }
                    sendReply(src, "/clip/note/count/response", total, sb.toString());
                    host.println("[BitwigAgent] TOTAL " + total + " Noten");
                });

        // /clip/note/count/reset  → Counter zurücksetzen
        space.registerMethod("/clip/note/count/reset", "*", "Reset note counters",
                (src, msg) -> {
                    noteCountMap.clear();
                    host.println("[BitwigAgent] Note-Counter zurückgesetzt");
                });

        // F11: /clip/notes/write <json_array>  → Batch-Write + ACK
        space.registerMethod("/clip/notes/write", "*", "Batch write notes and send ACK",
                (src, msg) -> {
                    String json = argStr(msg, 0);
                    if (json == null || json.isBlank()) {
                        sendReply(src, "/clip/notes/written", 0, "error: empty payload");
                        return;
                    }
                    int written = 0;
                    try {
                        written = parseAndWriteNoteBatch(json);
                    } catch (Exception e) {
                        host.println("[BitwigAgent] Batch-Fehler: " + e.getMessage());
                        sendReply(src, "/clip/notes/written", 0, "error: " + e.getMessage());
                        return;
                    }
                    String tn = cursorTrack.name().get();
                    if (tn != null && !tn.isEmpty()) {
                        noteCountMap.merge(tn, written, Integer::sum);
                    }
                    sendReply(src, "/clip/notes/written", written, tn != null ? tn : "");
                    host.println("[BitwigAgent] Batch: " + written + " Noten auf '" + tn + "'");
                });

        // ── Agent Status — Vollständiger Projekt-Status ───────────────────
        // /agent/status  → sendet JSON-Status: tracks, playing, tempo
        space.registerMethod("/agent/status", "*", "Get full status",
                (src, msg) -> {
                    int trackCount = 0;
                    StringBuilder trackInfo = new StringBuilder();
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Channel t = (Channel) trackBank.getItemAt(i);
                        if (t.exists().get()) {
                            if (trackCount > 0) trackInfo.append(";");
                            String tName = t.name().get();
                            trackInfo.append(i + 1).append("=").append(tName != null ? tName : "?");
                            trackCount++;
                        }
                    }
                    boolean playing = transport.isPlaying().get();
                    float tempo = (float) transport.tempo().get();
                    String devName = cursorDevice.name().get();
                    sendReply(src, "/agent/status/response",
                        trackCount, trackInfo.toString(), playing ? 1 : 0,
                        tempo, devName != null ? devName : "");
                    host.println("[BitwigAgent] Status: " + trackCount + " Tracks, playing=" + playing);
                });

        // ── Agent State — Track-Anzahl und Namen ─────────────────────────
        space.registerMethod("/agent/track/count", "*", "Get track count",
                (src, msg) -> {
                    int count = 0;
                    StringBuilder names = new StringBuilder();
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Channel t = (Channel) trackBank.getItemAt(i);
                        if (t.exists().get()) {
                            if (count > 0) names.append(",");
                            names.append(t.name().get());
                            count++;
                        }
                    }
                    sendReply(src, "/agent/track/count/response", count, names.toString());
                    host.println("[BitwigAgent] Tracks: " + count + " → " + names);
                });

        // ── Ping/Pong — Verbindungstest ───────────────────────────────────
        space.registerMethod("/ping", "*", "Ping",
                (src, msg) -> {
                    sendReply(src, "/pong", 1);
                    host.println("[BitwigAgent] Pong → OSC-Client");
                });

        space.registerMethod("/agent/ui/response", "*", "Show agent UI response",
                (src, msg) -> {
                    String text = argStr(msg, 0);
                    if (text == null || text.isBlank()) text = "(leer)";
                    if (text.length() > 180) text = text.substring(0, 180) + "...";
                    host.println("[BitwigAgent] UI-Response: " + text);
                    host.showPopupNotification("Agent: " + text);
                });

        // ── Transport ──────────────────────────────────────────────────────
        space.registerMethod("/transport/play", "*", "Play/Stop",
                (src, msg) -> { if (argFloat(msg, 0, 1f) > 0) transport.play(); else transport.stop(); });
        space.registerMethod("/transport/stop", "*", "Stop",
                (src, msg) -> transport.stop());
        space.registerMethod("/transport/tempo", "*", "Tempo",
                (src, msg) -> { transport.tempo().setRaw(argFloat(msg, 0, 120f)); sendReply(src, "/ack/tempo/set", 1); });
        space.registerMethod("/record", "*", "Record",
                (src, msg) -> transport.record());
        space.registerMethod("/repeat", "*", "Loop",
                (src, msg) -> { float v = argFloat(msg, 0, -1f);
                    if (v < 0) transport.isArrangerLoopEnabled().toggle();
                    else transport.isArrangerLoopEnabled().set(v > 0); });

        // ── Tracks erstellen / löschen ─────────────────────────────────────
        space.registerMethod("/track/add/instrument", "*", "Add instrument track",
                (src, msg) -> { application.createInstrumentTrack(-1); host.scheduleTask(() -> sendReply(src, "/ack/track/added", 1), 80); });
        space.registerMethod("/track/add/audio", "*", "Add audio track",
                (src, msg) -> { application.createAudioTrack(-1); host.scheduleTask(() -> sendReply(src, "/ack/track/added", 1), 80); });
        space.registerMethod("/track/add/effect", "*", "Add effect/return track",
                (src, msg) -> { application.createEffectTrack(-1); host.scheduleTask(() -> sendReply(src, "/ack/track/added", 1), 80); });
        space.registerMethod("/track/add/group", "*", "Add group track via action",
                (src, msg) -> {
                    try {
                        application.getAction("create_group_track").invoke();
                    } catch (Exception e) {
                        host.println("[BitwigAgent] create_group_track action nicht verfügbar: " + e.getMessage());
                    }
                });
        space.registerMethod("/track/delete/last", "*", "Delete last (selected) track",
                (src, msg) -> { cursorTrack.deleteObject(); });

        // /agent/tracks/clear  → Alle Instrument-Tracks löschen + noteCountMap leeren
        // Verwendet scheduleTask mit Delay zwischen Löschungen, weil trackBank und
        // cursorTrack async sind — gleichzeitige deleteObject()-Calls löschen nur Track 0.
        space.registerMethod("/agent/tracks/clear", "*", "Delete all instrument tracks",
                (src, msg) -> {
                    int n = 0;
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        if (trackBank.getItemAt(i).exists().get()) n++;
                    }
                    final int total = n;
                    noteCountMap.clear();
                    if (total == 0) {
                        sendReply(src, "/agent/tracks/clear/response", 0);
                        host.println("[BitwigAgent] Keine Tracks vorhanden");
                        return;
                    }
                    // Jede Löschung mit 80ms Abstand damit Bitwig die Bank aktualisieren kann
                    for (int i = 0; i < total; i++) {
                        final long delayMs = i * 80L;
                        host.scheduleTask(() -> {
                            Channel first = (Channel) trackBank.getItemAt(0);
                            if (first.exists().get()) {
                                first.selectInMixer();
                                cursorTrack.deleteObject();
                            }
                        }, delayMs);
                    }
                    // ACK erst nach allen Löschungen + 200ms Sicherheitspuffer
                    host.scheduleTask(() -> {
                        sendReply(src, "/agent/tracks/clear/response", total);
                        host.println("[BitwigAgent] " + total + " Tracks gelöscht und Counter zurückgesetzt");
                    }, total * 80L + 200L);
                });

        space.registerMethod("/undo", "*", "Undo last action",
                (src, msg) -> application.undo());

        // ── Audio-Loop als Device in CursorTrack einfügen ────────────────
        // /arrange/insert/file <linux_path>
        // Fügt eine Audio-Datei als Device (Sampler) auf dem aktuellen Track ein.
        space.registerMethod("/arrange/insert/file", "*", "Insert audio file as device",
                (src, msg) -> {
                    String path = argStr(msg, 0);
                    if (path == null || path.isBlank()) return;
                    cursorDevice.afterDeviceInsertionPoint().insertFile(path);
                    host.println("[BitwigAgent] Audio-File eingefügt: " + path);
                });

        // /sampler/load <linux_path>
        // Ersetzt den aktuellen CursorDevice (Sampler) durch einen neuen Sampler
        // mit dem angegebenen Audio-File. Workflow:
        //   1. Leeren Sampler auf Track laden (/browser/device/load "Sampler")
        //   2. /sampler/load <path>  → Sampler wird durch neuen Sampler+Sample ersetzt
        space.registerMethod("/sampler/load", "*", "Replace cursor device with audio file",
                (src, msg) -> {
                    String path = argStr(msg, 0);
                    if (path == null || path.isBlank()) return;
                    // replaceDeviceInsertionPoint: ersetzt CursorDevice durch insertFile-Result
                    cursorDevice.replaceDeviceInsertionPoint().insertFile(path);
                    host.println("[BitwigAgent] Sampler ersetzt mit: " + path);
                });

        // ── Track-Steuerung ────────────────────────────────────────────────
        for (int i = 1; i <= TRACK_BANK_SIZE; i++) {
            final Channel t        = (Channel) trackBank.getItemAt(i - 1);
            final String  n        = String.valueOf(i);
            final int     trackNum = i;
            space.registerMethod("/track/" + n + "/select", "*", "Select " + n,
                    (src, msg) -> { t.selectInMixer(); host.scheduleTask(() -> sendReply(src, "/ack/track/selected", trackNum), 40); });
            space.registerMethod("/track/" + n + "/volume", "*", "Volume " + n,
                    (src, msg) -> t.volume().value().set(argFloat(msg, 0, 0.8f)));
            space.registerMethod("/track/" + n + "/pan", "*", "Pan " + n,
                    (src, msg) -> t.pan().value().set(argFloat(msg, 0, 0.5f)));
            space.registerMethod("/track/" + n + "/mute", "*", "Mute " + n,
                    (src, msg) -> { float v = argFloat(msg, 0, -1f);
                        if (v < 0) t.mute().toggle(); else t.mute().set(v > 0); });
            space.registerMethod("/track/" + n + "/solo", "*", "Solo " + n,
                    (src, msg) -> { float v = argFloat(msg, 0, -1f);
                        if (v < 0) t.solo().toggle(); else t.solo().set(v > 0); });
            // Send-Level: /track/{n}/send/{m} <level 0.0-1.0>
            for (int s = 0; s < MAX_SENDS; s++) {
                final int sendIdx = s;
                space.registerMethod("/track/" + n + "/send/" + s, "*", "Send " + n + "→" + s,
                        (src, msg) -> {
                            Send send = ((Track) t).getSend(sendIdx);
                            if (send != null) send.value().set(argFloat(msg, 0, 0f));
                        });
            }
        }

        // ── Effect-Track-Steuerung (Return Tracks) ────────────────────────
        for (int i = 1; i <= MAX_SENDS; i++) {
            final Channel et = (Channel) effectTrackBank.getItemAt(i - 1);
            final String   n = String.valueOf(i);
            space.registerMethod("/effect/" + n + "/select", "*", "Select effect " + n,
                    (src, msg) -> et.selectInMixer());
            space.registerMethod("/effect/" + n + "/volume", "*", "Effect volume " + n,
                    (src, msg) -> et.volume().value().set(argFloat(msg, 0, 0.8f)));
        }

        // ── Drum Machine — Pad-Device-Kette betreten ─────────────────────
        // /drum/pad/pitch/enter <midiPitch>
        // Navigiert CursorDevice in die Device-Kette des Drum-Pads für den angegebenen MIDI-Pitch.
        // Danach kann /browser/device/load <name> das Instrument für diesen Pad laden.
        space.registerMethod("/drum/pad/pitch/enter", "*", "Enter drum pad device chain by MIDI pitch",
                (src, msg) -> {
                    int pitch = Math.max(0, Math.min(127, (int) argFloat(msg, 0, 36f)));
                    cursorDevice.selectFirstInKeyPad(pitch);
                    host.println("[BitwigAgent] Drum Pad pitch=" + pitch + " betreten");
                });

        // ── Effect-Track Count abfragen ───────────────────────────────────
        space.registerMethod("/agent/effect/count", "*", "Get effect track count",
                (src, msg) -> {
                    int count = 0;
                    for (int i = 0; i < MAX_SENDS; i++) {
                        if (effectTrackBank.getItemAt(i).exists().get()) count++;
                    }
                    sendReply(src, "/agent/effect/count/response", count);
                    host.println("[BitwigAgent] Effect tracks: " + count);
                });

        // ── Browser — Standard-Navigation ─────────────────────────────────
        space.registerMethod("/browser/next", "*", "Browser next",
                (src, msg) -> { int s = (int) argFloat(msg, 0, 1f);
                    for (int i = 0; i < s; i++) popupBrowser.selectNextFile(); });
        space.registerMethod("/browser/prev", "*", "Browser prev",
                (src, msg) -> { int s = (int) argFloat(msg, 0, 1f);
                    for (int i = 0; i < s; i++) popupBrowser.selectPreviousFile(); });
        space.registerMethod("/browser/first",  "*", "First",  (src, msg) -> popupBrowser.selectFirstFile());
        space.registerMethod("/browser/last",   "*", "Last",   (src, msg) -> popupBrowser.selectLastFile());
        space.registerMethod("/browser/commit", "*", "Commit", (src, msg) -> popupBrowser.commit());
        space.registerMethod("/browser/cancel", "*", "Cancel", (src, msg) -> popupBrowser.cancel());

        // ── Device-Browser (zuverlässiger Fallback via Browser.commitSelectedResult) ──
        // Verwendet CursorBrowserResultItem statt PopupBrowser.selectFirstFile
        space.registerMethod("/device/browser/start", "*", "Start device browser",
                (src, msg) -> {
                    deviceBrowser.startBrowsing();
                    host.println("[BitwigAgent] Device-Browser gestartet");
                });

        space.registerMethod("/device/browser/cancel", "*", "Cancel device browser",
                (src, msg) -> {
                    deviceBrowser.cancelBrowsing();
                    host.println("[BitwigAgent] Device-Browser abgebrochen");
                });

        space.registerMethod("/device/browser/navigate", "*", "Navigate to index",
                (src, msg) -> {
                    int idx = Math.max(0, (int) argFloat(msg, 0, 0f));
                    cursorResult.selectFirst();
                    for (int i = 0; i < idx; i++) cursorResult.selectNext();
                    host.println("[BitwigAgent] Device-Browser navigiert zu Index " + idx);
                });

        space.registerMethod("/device/browser/navigate/name", "*", "Navigate to name",
                (src, msg) -> {
                    String target = argStr(msg, 0);
                    if (target == null) return;
                    String key = target.toLowerCase().trim();
                    Integer idx = deviceCatalog.get(key);
                    if (idx == null) {
                        host.println("[BitwigAgent] '" + target + "' nicht im Katalog");
                        return;
                    }
                    cursorResult.selectFirst();
                    for (int i = 0; i < idx; i++) cursorResult.selectNext();
                    host.println("[BitwigAgent] Device-Browser navigiert zu: " + target + " (Index " + idx + ")");
                });

        space.registerMethod("/device/browser/commit", "*", "Commit device browser",
                (src, msg) -> {
                    deviceBrowser.commitSelectedResult();
                    host.println("[BitwigAgent] Device-Browser commitSelectedResult()");
                    host.showPopupNotification("Device geladen");
                });

        // ── Browser — direkte Ergebnis-Navigation (aus OSC-Handler, nicht flush) ──
        // /browser/result/navigate <idx>  — navigiert zu Position idx in der Ergebnisliste
        // selectFirstFile() + idx × selectNextFile() — echter UI-Klick
        space.registerMethod("/browser/result/navigate", "*", "Navigate result",
                (src, msg) -> {
                    int idx = Math.max(0, (int) argFloat(msg, 0, 0f));
                    popupBrowser.selectFirstFile();
                    for (int i = 0; i < idx; i++) popupBrowser.selectNextFile();
                    host.println("[BitwigAgent] Navigiert zu Ergebnis Index " + idx);
                });

        // /browser/result/navigate/name <name>  — sucht im aktuellen Katalog nach Name + navigiert
        space.registerMethod("/browser/result/navigate/name", "*", "Navigate result by name",
                (src, msg) -> {
                    String target = argStr(msg, 0);
                    if (target == null) return;
                    String key = target.toLowerCase().trim();
                    Integer idx = deviceCatalog.get(key);
                    if (idx == null) {
                        host.println("[BitwigAgent] '" + target + "' nicht im Katalog. Verfügbar: "
                            + deviceCatalog.keySet());
                        return;
                    }
                    popupBrowser.selectFirstFile();
                    for (int i = 0; i < idx; i++) popupBrowser.selectNextFile();
                    host.println("[BitwigAgent] Navigiert zu: " + target + " (Index " + idx + ")");
                });
        space.registerMethod("/browser/tab",    "*", "Tab",
                (src, msg) -> popupBrowser.selectedContentTypeIndex().set((int) argFloat(msg, 0, 0f)));

        // ── Browser — Instrument nach Name laden ───────────────────────────
        // Öffnet Browser, sucht Name im Katalog, navigiert und lädt automatisch.
        space.registerMethod("/browser/device", "*", "Open device browser",
                (src, msg) -> {
                    loadTarget = null;
                    popupBrowser.cancel();
                    cursorDevice.browseToInsertBeforeDevice();
                });

        // ── Browser — Collection vorfiltern ──────────────────────────────────
        // /browser/collection <name>  — wählt eine Smart-Collection als Filter
        // Muss VOR /browser/device/load gesendet werden.
        // Leer-String ("") setzt Wildcard (alle Kollektionen) zurück.
        space.registerMethod("/browser/collection", "*", "Select collection",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    loadCollection = (name == null || name.isBlank()) ? null : name.toLowerCase().trim();
                    host.println("[BitwigAgent] Collection-Vorfilter: " + loadCollection);
                });

        space.registerMethod("/browser/device/load", "*", "Load device by name",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    if (name == null || name.isBlank()) return;
                    String key = name.toLowerCase().trim();

                    // ── Option 1: Built-in Device via UUID (kein Browser nötig) ──────
                    String uuidStr = BUILTIN_UUIDS.get(key);
                    if (uuidStr != null) {
                        try {
                            UUID uuid = UUID.fromString(uuidStr);
                            cursorDevice.beforeDeviceInsertionPoint().insertBitwigDevice(uuid);
                            host.println("[BitwigAgent] UUID-Insert: " + name + " (" + uuidStr + ")");
                            host.showPopupNotification("Geladen: " + name);
                            sendReply(null, "/browser/device/loaded", name, 1);
                            return;
                        } catch (Exception e) {
                            host.println("[BitwigAgent] UUID-Fehler für " + name + ": " + e.getMessage());
                        }
                    }

                    // ── Option 2: Browser für alle anderen (Surge XT, Presets, VST) ──
                    popupBrowser.cancel();
                    cursorDevice.browseToInsertBeforeDevice();
                    loadTarget      = key;
                    pendingLoadName = key;   // F11: Observer wartet auf Browser-Close
                    loadWaitLeft    = 3;
                    host.println("[BitwigAgent] Browser-Suche: " + name);
                });

        // /browser/device/append <name>  — fügt Device ANS ENDE der Chain ein (afterDeviceInsertionPoint)
        // Für Effects nach einem Instrument: Delay-2, Reverb, Chorus etc.
        space.registerMethod("/browser/device/append", "*", "Append device after current (end of chain)",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    if (name == null || name.isBlank()) return;
                    String key = name.toLowerCase().trim();

                    // Built-in Device via UUID — afterDeviceInsertionPoint
                    String uuidStr = BUILTIN_UUIDS.get(key);
                    if (uuidStr != null) {
                        try {
                            UUID uuid = UUID.fromString(uuidStr);
                            cursorDevice.afterDeviceInsertionPoint().insertBitwigDevice(uuid);
                            host.println("[BitwigAgent] UUID-Append: " + name + " (" + uuidStr + ")");
                            host.showPopupNotification("Hinzugefügt: " + name);
                            sendReply(null, "/browser/device/loaded", name, 1);
                            return;
                        } catch (Exception e) {
                            host.println("[BitwigAgent] UUID-Fehler für " + name + ": " + e.getMessage());
                        }
                    }

                    // Fallback: Browser mit browseToInsertAfterDevice
                    popupBrowser.cancel();
                    cursorDevice.browseToInsertAfterDevice();
                    loadTarget      = key;
                    pendingLoadName = key;
                    loadWaitLeft    = 3;
                    host.println("[BitwigAgent] Browser-Append-Suche: " + name);
                });

        space.registerMethod("/browser/preset", "*", "Open preset browser",
                (src, msg) -> cursorDevice.browseToReplaceDevice());

        // /browser/preset/load <name>  — öffnet Preset-Browser und navigiert zu Match
        space.registerMethod("/browser/preset/load", "*", "Load preset by name (fuzzy)",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    if (name == null || name.isBlank()) return;
                    popupBrowser.cancel();
                    cursorDevice.browseToReplaceDevice();
                    presetTarget   = name.toLowerCase().trim();
                    presetWaitLeft = 5;  // mehr Zyklen für Preset-Browser
                    host.println("[BitwigAgent] Preset-Suche: " + name);
                });

        // /browser/fx/load <name>  — lädt FX-Chain-Preset (Audioeffekte) nach Instrument
        // Öffnet Insert-After-Browser, sucht Preset-Name in resultBank und committ
        space.registerMethod("/browser/fx/load", "*", "Load FX chain preset (Audioeffekte)",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    if (name == null || name.isBlank()) return;
                    popupBrowser.cancel();
                    cursorDevice.browseToInsertAfterDevice();
                    fxPresetTarget   = name.toLowerCase().trim();
                    fxCategoryTarget = "guitar";
                    fxPresetWaitLeft = 8;  // mehr Zyklen für FX-Browser
                    host.println("[BitwigAgent] FX-Preset-Suche: " + name);
                });

        // ── Device-Parameter — nach Index ─────────────────────────────────
        for (int p = 1; p <= REMOTE_PARAMS; p++) {
            final int idx = p - 1;
            space.registerMethod("/device/param/" + p + "/value", "*", "Param " + p,
                    (src, msg) -> remoteControls.getParameter(idx).value()
                        .set(argFloat(msg, 0, 0f)));
        }

        // ── Device-Parameter — nach Name ──────────────────────────────────
        // Sucht in der aktuellen Seite nach dem Parameter-Namen.
        // Format: /device/param/named <name> <value>
        space.registerMethod("/device/param/named", "*", "Set param by name",
                (src, msg) -> {
                    String name = argStr(msg, 0);
                    float  val  = argFloat(msg, 1, 0f);
                    if (name == null) return;
                    Integer idx = paramCatalog.get(name.toLowerCase().trim());
                    if (idx != null) {
                        remoteControls.getParameter(idx).value().set(val);
                        host.println("[BitwigAgent] Param '" + name + "' [" + idx + "] = " + val);
                    } else {
                        host.println("[BitwigAgent] Parameter nicht gefunden: " + name
                            + " (verfügbar: " + paramCatalog.keySet() + ")");
                    }
                });

        // ── Parameter-Seiten ──────────────────────────────────────────────
        space.registerMethod("/device/param/page/next", "*", "Next param page",
                (src, msg) -> remoteControls.selectNextPage(true));
        space.registerMethod("/device/param/page/prev", "*", "Prev param page",
                (src, msg) -> remoteControls.selectPreviousPage(true));
        space.registerMethod("/device/param/page/set", "*", "Set param page",
                (src, msg) -> remoteControls.selectedPageIndex()
                    .set((int) argFloat(msg, 0, 0f)));

        // ── EQ ────────────────────────────────────────────────────────────
        for (int b = 1; b <= REMOTE_PARAMS; b++) {
            final int band = b - 1;
            space.registerMethod("/eq/freq/" + b, "*", "EQ freq " + b,
                    (src, msg) -> cursorDevice.getParameter(band * 3).value()
                        .set(argFloat(msg, 0, 0.5f)));
            space.registerMethod("/eq/gain/" + b, "*", "EQ gain " + b,
                    (src, msg) -> cursorDevice.getParameter(band * 3 + 1).value()
                        .set(argFloat(msg, 0, 0.5f)));
            space.registerMethod("/eq/q/" + b, "*", "EQ Q " + b,
                    (src, msg) -> cursorDevice.getParameter(band * 3 + 2).value()
                        .set(argFloat(msg, 0, 0.5f)));
        }

        // /tempo/raw alias (Python-Kompatibilität)
        space.registerMethod("/tempo/raw", "*", "Tempo raw",
                (src, msg) -> transport.tempo().setRaw(argFloat(msg, 0, 120f)));

        // ── Transport — Position & Loop ───────────────────────────────────
        space.registerMethod("/transport/position", "*", "Set position",
                (src, msg) -> transport.getPosition().set(argFloat(msg, 0, 0f)));
        space.registerMethod("/transport/loop/start", "*", "Loop start",
                (src, msg) -> transport.arrangerLoopStart().set(argFloat(msg, 0, 0f)));
        space.registerMethod("/transport/loop/end", "*", "Loop end",
                (src, msg) -> transport.arrangerLoopDuration().set(argFloat(msg, 0, 8f)));
        space.registerMethod("/transport/loop/active", "*", "Loop active",
                (src, msg) -> { float v = argFloat(msg, 0, -1f);
                    if (v < 0) transport.isArrangerLoopEnabled().toggle();
                    else transport.isArrangerLoopEnabled().set(v > 0); });

        // ── Scenes ────────────────────────────────────────────────────────
        for (int i = 0; i < SLOT_BANK_SIZE; i++) {
            final int slot = i;
            space.registerMethod("/scene/" + (i + 1) + "/launch", "*", "Launch scene " + (i + 1),
                    (src, msg) -> sceneBank.getScene(slot).launch());
            space.registerMethod("/scene/" + (i + 1) + "/stop", "*", "Stop scene " + (i + 1),
                    (src, msg) -> sceneBank.getScene(slot).launchRelease());
        }

        setupClipOsc(space);

        // ── Launchpad MK2 — Pad-Mapping per OSC ──────────────────────────────
        // /launchpad/map <pad_note> <action>  — weist einem Pad eine Bitwig-Aktion zu
        // Pad-Noten: untere Reihe=11–18, zweite Reihe=21–28 usw., rechte Buttons=19,29,...
        // Aktionen: play_stop, stop, record, undo, loop_toggle, mute_toggle, next_track, prev_track
        space.registerMethod("/launchpad/map", "*", "Map Launchpad pad to Bitwig action",
                (src, msg) -> {
                    int    pad    = (int) argFloat(msg, 0, 11f);
                    String action = argStr(msg, 1);
                    if (action == null || action.isBlank()) return;
                    action = action.toLowerCase().trim();
                    padMappings.put(pad, action);
                    int[] color = getActionColor(action);
                    setLaunchpadLed(pad, color[0], color[1], color[2]);
                    sendReply(src, "/launchpad/map/response", pad, action, 1);
                    host.println("[Launchpad] Pad " + pad + " → " + action);
                });

        // /launchpad/led <pad_note> <r> <g> <b>  — setzt LED-Farbe direkt (0–63)
        space.registerMethod("/launchpad/led", "*", "Set Launchpad pad LED color",
                (src, msg) -> {
                    int pad = (int) argFloat(msg, 0, 11f);
                    int r   = Math.max(0, Math.min(63, (int) argFloat(msg, 1, 0f)));
                    int g   = Math.max(0, Math.min(63, (int) argFloat(msg, 2, 0f)));
                    int b   = Math.max(0, Math.min(63, (int) argFloat(msg, 3, 0f)));
                    setLaunchpadLed(pad, r, g, b);
                    host.println("[Launchpad] LED " + pad + " = (" + r + "," + g + "," + b + ")");
                });

        // /launchpad/clear  — alle Mappings löschen + LEDs ausschalten
        space.registerMethod("/launchpad/clear", "*", "Clear all Launchpad mappings",
                (src, msg) -> {
                    for (int note : padMappings.keySet()) setLaunchpadLed(note, 0, 0, 0);
                    padMappings.clear();
                    sendReply(src, "/launchpad/clear/response", 1);
                    host.println("[Launchpad] Alle Mappings gelöscht");
                });

        // /launchpad/mappings  — aktuelle Mappings zurückgeben
        space.registerMethod("/launchpad/mappings", "*", "Get current Launchpad mappings",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder();
                    for (Map.Entry<Integer, String> e : padMappings.entrySet()) {
                        if (sb.length() > 0) sb.append(";");
                        sb.append(e.getKey()).append("=").append(e.getValue());
                    }
                    sendReply(src, "/launchpad/mappings/response", sb.toString());
                    host.println("[Launchpad] Mappings: " + sb);
                });

        // ── VST/Plugin-Scan ───────────────────────────────────────────────────
        space.registerMethod("/plugins/scan", "*", "Trigger VST plugin rescan",
                (src, msg) -> {
                    try {
                        application.getAction("rescan_plug_ins").invoke();
                        host.showPopupNotification("VST-Scan gestartet...");
                        host.println("[BitwigAgent] VST-Scan gestartet (rescan_plug_ins)");
                        sendReply(src, "/plugins/scan/response", 1, "scan started");
                    } catch (Exception e) {
                        host.println("[BitwigAgent] rescan_plug_ins nicht verfügbar: " + e.getMessage());
                        try {
                            application.getAction("scan_plug_ins").invoke();
                            host.showPopupNotification("VST-Scan (scan_plug_ins)...");
                            sendReply(src, "/plugins/scan/response", 1, "scan started");
                        } catch (Exception e2) {
                            sendReply(src, "/plugins/scan/response", 0, e.getMessage());
                            host.println("[BitwigAgent] Kein VST-Scan-Action gefunden: " + e2.getMessage());
                        }
                    }
                });

        space.registerDefaultMethod((src, msg) ->
            host.println("[BitwigAgent] Unbekannt: " + msg.getAddressPattern()));

        osc.createUdpServer(OSC_PORT, space);
        host.println("[BitwigAgent] OSC auf UDP:" + OSC_PORT);
    }

    private void sendReply(OscConnection src, String address, Object... args) {
        boolean delivered = false;
        if (replyLoopbackV4 != null) {
            try {
                replyLoopbackV4.sendMessage(address, args);
                delivered = true;
            } catch (Exception e) {
                host.println("[BitwigAgent] loopback-v4 reply fehlgeschlagen: " + e.getMessage());
            }
        }
        if (replyLoopbackLocalhost != null) {
            try {
                replyLoopbackLocalhost.sendMessage(address, args);
                delivered = true;
            } catch (Exception e) {
                host.println("[BitwigAgent] localhost reply fehlgeschlagen: " + e.getMessage());
            }
        }
        if (!delivered && src != null) {
            try {
                src.sendMessage(address, args);
                delivered = true;
            } catch (Exception e) {
                host.println("[BitwigAgent] direkte reply fehlgeschlagen: " + e.getMessage());
            }
        }
    }

    // ── Launchpad MK2 — MIDI Setup & Hilfsmethoden ───────────────────────────

    private void setupLaunchpad() {
        try {
            launchpadIn  = host.getMidiInPort(0);
            launchpadOut = host.getMidiOutPort(0);
            launchpadIn.setMidiCallback((status, data1, data2) -> {
                int type = status & 0xF0;
                if (type == 0x90 && data2 > 0) {
                    String action = padMappings.get(data1);
                    if (action != null) executeAction(action);
                }
            });
            host.println("[Launchpad] MIDI bereit (Port 0)");
        } catch (Exception e) {
            host.println("[Launchpad] MIDI nicht verfügbar: " + e.getMessage());
        }
    }

    private void setLaunchpadLed(int note, int r, int g, int b) {
        if (launchpadOut == null) return;
        // SysEx: F0 00 20 29 02 18 0B note r g b F7
        String hex = String.format("F0 00 20 29 02 18 0B %02X %02X %02X %02X F7", note, r, g, b);
        launchpadOut.sendSysex(hex);
    }

    private int[] getActionColor(String action) {
        switch (action) {
            case "play_stop":   return new int[]{0,  63, 0};   // grün
            case "stop":        return new int[]{63, 20, 0};   // orange
            case "record":      return new int[]{63, 0,  0};   // rot
            case "undo":        return new int[]{63, 63, 0};   // gelb
            case "loop_toggle": return new int[]{63, 0,  63};  // lila
            case "mute_toggle": return new int[]{63, 30, 0};   // bernstein
            case "next_track":  return new int[]{0,  63, 63};  // cyan
            case "prev_track":  return new int[]{0,  30, 63};  // blau
            default:            return new int[]{20, 20, 20};  // grau
        }
    }

    private void executeAction(String action) {
        host.println("[Launchpad] Aktion: " + action);
        switch (action) {
            case "play_stop":   transport.play(); break;
            case "stop":        transport.stop(); break;
            case "record":      transport.record(); break;
            case "undo":        application.undo(); break;
            case "loop_toggle": transport.isArrangerLoopEnabled().toggle(); break;
            case "mute_toggle": cursorTrack.mute().toggle(); break;
            case "next_track":  cursorTrack.selectNext(); break;
            case "prev_track":  cursorTrack.selectPrevious(); break;
            default: host.println("[Launchpad] Unbekannte Aktion: " + action);
        }
    }

    // ── Clip & Note Programming ───────────────────────────────────────────────

    private void setupClipOsc(OscAddressSpace space) {

        // /clip/select <slot>  — Clip-Slot auf CursorTrack auswählen
        space.registerMethod("/clip/select", "*", "Select slot",
                (src, msg) -> {
                    int slot = Math.max(0, Math.min(SLOT_BANK_SIZE - 1, (int) argFloat(msg, 0, 0f)));
                    clipSlotBank.select(slot);
                });

        // /clip/create <slot> <length_beats>  — leeren Clip anlegen + auswählen
        space.registerMethod("/clip/create", "*", "Create clip",
                (src, msg) -> {
                    int slot = Math.max(0, Math.min(SLOT_BANK_SIZE - 1, (int) argFloat(msg, 0, 0f)));
                    int len  = Math.max(1, (int) argFloat(msg, 1, 8f));
                    clipSlotBank.createEmptyClip(slot, len);
                    clipSlotBank.select(slot);
                    host.println("[BitwigAgent] Clip erstellt: Slot " + slot + ", " + len + " Beats");
                    host.scheduleTask(() -> sendReply(src, "/ack/clip/created", 1), 150);
                });

        // /clip/launch <slot>  — Clip starten
        space.registerMethod("/clip/launch", "*", "Launch clip",
                (src, msg) -> {
                    int slot = Math.max(0, Math.min(SLOT_BANK_SIZE - 1, (int) argFloat(msg, 0, 0f)));
                    clipSlotBank.launch(slot);
                });

        // /clip/step_size <beats>  — Schrittauflösung (0.25=1/16, 0.5=1/8, 1.0=1/4)
        space.registerMethod("/clip/step_size", "*", "Step size",
                (src, msg) -> cursorClip.setStepSize(argFloat(msg, 0, 0.25f)));

        // /clip/note <step> <pitch> <velocity_0_1> <duration_beats>
        // velocity=0 entfernt die Note; velocity>0 setzt sie mit der angegebenen Dauer.
        space.registerMethod("/clip/note", "*", "Set note",
                (src, msg) -> {
                    int   step  = (int) argFloat(msg, 0, 0f);
                    int   pitch = (int) argFloat(msg, 1, 60f);
                    float vel   = argFloat(msg, 2, 0.8f);
                    float dur   = argFloat(msg, 3, 0.25f);
                    if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch >= 128) return;
                    int velInt = Math.max(0, Math.min(127, (int)(vel * 127)));
                    if (velInt == 0) {
                        cursorClip.clearStep(step, pitch);
                    } else {
                        cursorClip.setStep(0, step, pitch, velInt, (double) dur);
                    }
                });

        // /clip/clear  — alle Noten im aktiven Clip löschen
        space.registerMethod("/clip/clear", "*", "Clear notes",
                (src, msg) -> {
                    cursorClip.clearSteps();
                    host.println("[BitwigAgent] Clip geleert");
                });

        // /clip/note/beat <beat_pos> <pitch> <vel_0_1> <duration_beats>
        space.registerMethod("/clip/note/beat", "*", "Set note by beat",
                (src, msg) -> {
                    float beatPos  = argFloat(msg, 0, 0f);
                    int   pitch    = (int) argFloat(msg, 1, 60f);
                    float vel      = argFloat(msg, 2, 0.8f);
                    float durBeats = argFloat(msg, 3, 1.0f);
                    float stepSize = 0.25f;
                    int   step     = Math.round(beatPos / stepSize);
                    if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch >= 128) return;
                    int velInt = Math.max(1, Math.min(127, (int)(vel * 127)));
                    cursorClip.setStep(0, step, pitch, velInt, (double) durBeats);
                    // Mitzählen (try/catch damit kein Crash)
                    try {
                        String tn = cursorTrack.name().get();
                        if (tn != null && !tn.isEmpty()) {
                            int prev = noteCountMap.containsKey(tn) ? noteCountMap.get(tn) : 0;
                            noteCountMap.put(tn, prev + 1);
                        }
                    } catch (Exception ignored) {}
                });

        // /browser/catalog/save <win_path>
        // Schreibt den aktuellen Browser-Katalog als JSON in eine Datei.
        // Default: C:\Users\Public\bitwig_catalog.json (von WSL lesbar als /mnt/c/Users/Public/...)
        // Vorher Browser öffnen: /browser/device → 2-3s warten → /browser/catalog/save → /browser/cancel
        space.registerMethod("/browser/catalog/save", "*", "Save catalog to file",
                (src, msg) -> {
                    String filePath = argStr(msg, 0);
                    if (filePath == null || filePath.isBlank())
                        filePath = System.getProperty("user.home") + "/bitwig_catalog.json";

                    // Katalog direkt aus ResultBank lesen (original Groß-/Kleinschreibung)
                    StringBuilder json = new StringBuilder("[\n");
                    boolean first = true;
                    for (int i = 0; i < BROWSER_SCAN; i++) {
                        BrowserItem item = resultBank.getItem(i);
                        if (!item.exists().get()) continue;
                        String name = item.name().get();
                        if (name == null || name.isBlank()) continue;
                        if (!first) json.append(",\n");
                        json.append("  {\"pos\":").append(i)
                            .append(",\"name\":\"")
                            .append(name.replace("\\", "\\\\").replace("\"", "\\\""))
                            .append("\"}");
                        first = false;
                    }
                    json.append("\n]");

                    try {
                        java.nio.file.Files.writeString(
                            java.nio.file.Paths.get(filePath),
                            json.toString()
                        );
                        int count = deviceCatalog.size();
                        host.println("[BitwigAgent] Katalog gespeichert: " + filePath + " (" + count + " Einträge)");
                        host.showPopupNotification("Browser-Katalog: " + count + " Geräte gespeichert");
                    } catch (Exception e) {
                        host.println("[BitwigAgent] Speicherfehler: " + e.getMessage());
                    }
                });
    }

    // ── flush() — asynchrones Gerät-Laden ────────────────────────────────────

    @Override
    public void flush() {
        // Katalog aus Browser-Ergebnissen aktualisieren (Polling)
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (item.exists().get()) {
                String name = item.name().get();
                if (name != null && !name.isBlank()) {
                    deviceCatalog.put(name.toLowerCase().trim(), i);
                }
            }
        }

        // Parameter-Katalog der aktuellen Seite aktualisieren
        paramCatalog.clear();
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            String name = remoteControls.getParameter(i).name().get();
            if (name != null && !name.isBlank()) {
                paramCatalog.put(name.toLowerCase().trim(), i);
            }
        }

        // Tab-Scan fortsetzen falls aktiv
        if (loadTargetTabScan != null) { continueTabScan(); return; }

        // Gerät laden wenn Ziel gesetzt
        if (loadTarget == null && presetTarget == null && fxPresetTarget == null) return;

        // ── FX-Chain-Preset-Suche (Audioeffekte) ─────────────────────────────
        if (fxPresetTarget != null) {
            if (fxPresetWaitLeft > 0) { fxPresetWaitLeft--; return; }

            if (fxCategoryTarget != null) {
                boolean categoryFound = false;
                for (int i = 0; i < CAT_BANK_SIZE; i++) {
                    BrowserItem item = categoryBank.getItem(i);
                    if (!item.exists().get()) continue;
                    String name = item.name().get();
                    if (name != null && name.toLowerCase().trim().equals(fxCategoryTarget)) {
                        item.isSelected().set(true);
                        host.println("[BitwigAgent] FX-Kategorie aktiv: " + name);
                        categoryFound = true;
                        break;
                    }
                }
                if (!categoryFound) {
                    host.println("[BitwigAgent] FX-Kategorie '" + fxCategoryTarget + "' nicht gefunden — suche ohne Kategoriefilter.");
                }
                fxCategoryTarget = null;
                fxPresetWaitLeft = 4;
                return;
            }

            String key = fxPresetTarget;
            fxPresetTarget = null;
            // Fuzzy-Suche im resultBank (browseToInsertAfterDevice geöffnet)
            for (int i = 0; i < BROWSER_SCAN; i++) {
                BrowserItem item = resultBank.getItem(i);
                if (!item.exists().get()) break;
                String name = item.name().get();
                if (name != null && name.toLowerCase().contains(key)) {
                    popupBrowser.selectFirstFile();
                    for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                    popupBrowser.commit();
                    host.println("[BitwigAgent] FX-Preset geladen: " + name);
                    host.showPopupNotification("FX-Preset: " + name);
                    return;
                }
            }
            host.println("[BitwigAgent] FX-Preset '" + key + "' nicht gefunden — Browser bleibt offen.");
            popupBrowser.cancel();
            return;
        }

        // ── Preset-Browser-Suche ──────────────────────────────────────────────
        if (presetTarget != null) {
            if (presetWaitLeft > 0) { presetWaitLeft--; return; }
            String key = presetTarget;
            presetTarget = null;
            // Fuzzy-Suche: erstes Ergebnis das den Suchbegriff enthält
            for (int i = 0; i < BROWSER_SCAN; i++) {
                BrowserItem item = resultBank.getItem(i);
                if (!item.exists().get()) break;
                String name = item.name().get();
                if (name != null && name.toLowerCase().contains(key)) {
                    popupBrowser.selectFirstFile();
                    for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                    popupBrowser.commit();
                    host.println("[BitwigAgent] Preset geladen: " + name);
                    host.showPopupNotification("Preset: " + name);
                    return;
                }
            }
            host.println("[BitwigAgent] Preset '" + key + "' nicht gefunden — Browser bleibt offen.");
            popupBrowser.cancel();
            return;
        }

        // Warten bis Browser geöffnet ist
        if (loadWaitLeft > 0) {
            loadWaitLeft--;
            return;
        }

        // ── Collection vorfiltern (optional) ─────────────────────────────────────
        if (loadCollection != null) {
            boolean collFound = false;
            for (int i = 0; i < COLL_BANK_SIZE; i++) {
                BrowserItem item = smartCollBank.getItem(i);
                if (!item.exists().get()) continue;
                String n = item.name().get();
                if (n != null && n.toLowerCase().trim().equals(loadCollection)) {
                    item.isSelected().set(true);
                    host.println("[BitwigAgent] Collection aktiv: " + n);
                    collFound = true;
                    break;
                }
            }
            if (!collFound)
                host.println("[BitwigAgent] Collection '" + loadCollection + "' nicht gefunden — ohne Filter");
            loadCollection = null;
        }

        // ── Phase 1: aktuellen Tab ohne Filter scannen ───────────────────────────
        String key = loadTarget;
        if (!loadPluginsFilter) {
            for (int i = 0; i < BROWSER_SCAN; i++) {
                BrowserItem item = resultBank.getItem(i);
                if (!item.exists().get()) break;
                String name = item.name().get();
                if (name != null && name.toLowerCase().contains(key)) {
                    loadTarget        = null;
                    loadPluginsFilter = false;
                    popupBrowser.selectFirstFile();
                    for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                    popupBrowser.commit();
                    host.println("[BitwigAgent] Browser geladen (Phase 1): " + name);
                    host.showPopupNotification("Geladen: " + name);
                    return;
                }
            }
            // Nicht im aktuellen Tab — Plug-ins-Location-Filter setzen (VST-Fallback)
            boolean filterApplied = false;
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem item = locationBank.getItem(i);
                if (!item.exists().get()) break;
                String n = item.name().get();
                if (n != null && n.toLowerCase().contains("plug-in")) {
                    item.isSelected().set(true);
                    filterApplied = true;
                    host.println("[BitwigAgent] Location-Filter 'Plug-ins' gesetzt: " + n);
                    break;
                }
            }
            if (filterApplied) {
                loadPluginsFilter = true;
                loadWaitLeft      = 6;   // ~300 ms warten damit Ergebnisse neu laden
                return;
            }
            // Kein Plug-ins-Item gefunden — aufgeben
            loadTarget        = null;
            loadPluginsFilter = false;
            host.println("[BitwigAgent] '" + key + "' nicht gefunden (kein Plug-ins-Filter).");
            popupBrowser.cancel();
            return;
        }

        // ── Phase 2: nach Plug-ins-Filter scannen ────────────────────────────────
        loadTarget        = null;
        loadPluginsFilter = false;
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (!item.exists().get()) break;
            String name = item.name().get();
            if (name != null && name.toLowerCase().contains(key)) {
                popupBrowser.selectFirstFile();
                for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                popupBrowser.commit();
                host.println("[BitwigAgent] Browser geladen (Plug-ins-Filter): " + name);
                host.showPopupNotification("Geladen: " + name);
                return;
            }
        }
        host.println("[BitwigAgent] '" + key + "' nicht gefunden — Browser abgebrochen.");
        popupBrowser.cancel();
    }

    // Tab-Scan-State für loadTarget
    private volatile String loadTargetTabScan = null;
    private volatile int    loadTargetTabIdx  = 0;

    private void continueTabScan() {
        if (loadTargetTabScan == null) return;
        if (loadWaitLeft > 0) { loadWaitLeft--; return; }

        String key = loadTargetTabScan;
        // Aktuellen Tab durchsuchen
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (!item.exists().get()) break;
            String name = item.name().get();
            if (name != null && name.toLowerCase().contains(key)) {
                loadTargetTabScan = null;
                popupBrowser.selectFirstFile();
                for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                popupBrowser.commit();
                host.println("[BitwigAgent] Tab-Scan geladen (Tab " + loadTargetTabIdx + "): " + name);
                host.showPopupNotification("Geladen: " + name);
                sendReply(null, "/browser/device/loaded", name, 1);
                return;
            }
        }

        // Nächster Tab
        loadTargetTabIdx++;
        if (loadTargetTabIdx > 8) {
            host.println("[BitwigAgent] Tab-Scan: '" + key + "' in keinem Tab (0-8) gefunden.");
            sendReply(null, "/browser/device/loaded", key, 0);
            loadTargetTabScan = null;
            popupBrowser.cancel();
            return;
        }
        if (popupBrowser != null) popupBrowser.selectedContentTypeIndex().set(loadTargetTabIdx);
        loadWaitLeft = 2;
        host.println("[BitwigAgent] Tab-Scan: wechsle zu Tab " + loadTargetTabIdx);
    }

    // F11: Batch-Note-Writer ──────────────────────────────────────────────────

    /** Parst [{step,pitch,vel,dur},...] und schreibt alle Noten in cursorClip. */
    private int parseAndWriteNoteBatch(String json) {
        int count = 0;
        // Strip outer brackets and split on object boundaries
        String stripped = json.replace("[", "").replace("]", "");
        for (String entry : stripped.split("\\},\\s*\\{")) {
            entry = entry.replace("{", "").replace("}", "").trim();
            if (entry.isBlank()) continue;
            Map<String, Double> fields = parseSimpleJsonObject(entry);
            double stepBeat = fields.getOrDefault("step", 0.0);
            int    step     = (int) Math.round(stepBeat / 0.25);
            int    pitch    = fields.getOrDefault("pitch", 60.0).intValue();
            float  vel      = fields.getOrDefault("vel",   0.8).floatValue();
            float  dur      = fields.getOrDefault("dur",   0.25).floatValue();
            if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch > 127 || dur <= 0) continue;
            int velInt = Math.max(1, Math.min(127, (int) (vel * 127)));
            cursorClip.setStep(0, step, pitch, velInt, (double) dur);
            count++;
        }
        return count;
    }

    /** Minimaler Key:Value-Parser für flache JSON-Objekte mit nur numerischen Werten. */
    private Map<String, Double> parseSimpleJsonObject(String kvPairs) {
        Map<String, Double> result = new HashMap<>();
        for (String pair : kvPairs.split(",")) {
            pair = pair.trim();
            int colon = pair.indexOf(':');
            if (colon < 0) continue;
            String key = pair.substring(0, colon).trim().replace("\"", "");
            String val = pair.substring(colon + 1).trim().replace("\"", "");
            try {
                result.put(key, Double.parseDouble(val));
            } catch (NumberFormatException ignored) {
                // non-numeric value — skip
            }
        }
        return result;
    }

    @Override
    public void exit() {
        host.showPopupNotification("Bitwig Agent Bridge beendet.");
    }
}
