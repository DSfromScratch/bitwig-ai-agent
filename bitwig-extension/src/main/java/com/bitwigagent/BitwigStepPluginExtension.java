package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.*;
import com.bitwig.extension.callback.BooleanValueChangedCallback;
import com.bitwig.extension.controller.ControllerExtension;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.*;
import java.util.*;

/**
 * Bitwig Step Plugin — Command + State Pattern.
 *
 * Empfängt /step/exec JSON-Steps von Python, führt jeden Step mit
 * korrekt gestaffelten scheduleTask-Delays aus und sendet /step/done.
 * Eigenständige Extension (kein Erben von BitwigAgentBridgeExtension).
 *
 * Ports: OSC IN 8002, REPLY OUT 9002 (getrennt von BitwigOscBridge Port 8001 —
 * beide Extensions können gleichzeitig aktiv sein).
 */
public class BitwigStepPluginExtension extends ControllerExtension {

    private static final int OSC_IN = 8002;
    private static final int OSC_REPLY = 9002;
    private static final int TRACK_BANK_SIZE = 64;
    private static final int MAX_SENDS = 8;
    private static final int SLOT_BANK_SIZE = 8;
    private static final int CLIP_STEPS = 512;
    private static final int REMOTE_PARAMS = 8;
    private static final int BROWSER_SCAN = 128;
    private static final int MAX_DEVICES_PER_TRACK = 8;
    private static final int DRUM_PAD_COUNT = 16;   // Drum Machine hat 16 Pads
    // ── Bitwig API ────────────────────────────────────────────────────────────

    private ControllerHost host;
    private Transport transport;
    private TrackBank trackBank;
    private CursorTrack cursorTrack;
    private CursorDevice cursorDevice;
    private PopupBrowser popupBrowser;
    private Application application;
    private CursorRemoteControlsPage remoteControls;
    private ClipLauncherSlotBank clipSlotBank;
    private CursorClip cursorClip;
    private BrowserItemBank resultBank;

    // ── Arranger / Timeline ───────────────────────────────────────────────────

    private Arranger arranger;
    private CueMarkerBank cueMarkerBank;
    private static final int CUE_MARKER_COUNT = 16;

    // ── OSC Reply ─────────────────────────────────────────────────────────────

    private OscConnection replyV4;
    private OscConnection replyLocalhost;
    private SettableStringValue agentHost;

    // ── State Machine ─────────────────────────────────────────────────────────

    private final java.util.LinkedList<String[]> stepQueue = new java.util.LinkedList<>();
    private volatile boolean stepExecuting = false;
    private volatile OscConnection pendingStepSrc = null;
    private volatile String pendingStepType = null; // "load_instrument" | "append_effect"

    // ── Browser / Catalog ────────────────────────────────────────────────────

    private final Map<String, Integer> deviceCatalog = new HashMap<>();
    private BrowserFilterItemBank locationBank;
    private BrowserFilterItemBank deviceTypeBank; // "Art"-Filter (Devices / Plug-ins)
    private static final int LOC_BANK_SIZE = 16;
    private volatile String loadTarget = null;
    private volatile int loadWaitLeft = 0;
    // 0=kein Filter, 1="Plug-ins" gewählt (warte auf Baum-Expansion), 2=VST-Child
    // gewählt (warte auf Ergebnisse)
    private volatile int loadLocPhase = 0;

    // ── Note + Param Catalogs ────────────────────────────────────────────────

    private final Map<String, Integer> noteCountMap = new HashMap<>();
    private final Map<String, Integer> paramCatalog = new HashMap<>();

    // ── MIDI Clip Note Collection ─────────────────────────────────────────────

    private volatile boolean collectingClipNotes = false;
    private final java.util.concurrent.CopyOnWriteArrayList<String> clipNoteBuf = new java.util.concurrent.CopyOnWriteArrayList<>();
    private final boolean[] slotHasContent = new boolean[SLOT_BANK_SIZE];
    private com.bitwig.extension.controller.api.Clip readCursorClip;

    // ── Arranger Cursor Clip Note Collection ──────────────────────────────────

    private volatile boolean collectingArrangerNotes = false;
    private final java.util.concurrent.CopyOnWriteArrayList<String> arrangerNoteBuf = new java.util.concurrent.CopyOnWriteArrayList<>();

    // ── Device Banks (pro Track, für Project-Scan) ────────────────────────────

    private DeviceBank[] trackDeviceBanks;
    private DeviceBank cursorTrackDeviceBank;

    // ── Drum Pad Bank (vom cursorDevice, für Drum Machine Mapping) ────────────
    private com.bitwig.extension.controller.api.DrumPadBank drumPadBank;

    // ── Scene Bank ────────────────────────────────────────────────────────────

    private SceneBank sceneBank;

    // ── Per-Track Clip-Slot Content (für full-snapshot) ───────────────────────
    // trackSlotHasContent[trackIdx][slotIdx] = true wenn Clip vorhanden

    private final boolean[][] trackSlotHasContent = new boolean[TRACK_BANK_SIZE][SLOT_BANK_SIZE];

    // ── Konstante für Sub-Track Limit ─────────────────────────────────────────

    // ── Built-in Device UUIDs — delegiert an BuiltinDeviceUuids ────────────────

    private static final Map<String, String> BUILTIN_UUIDS = new HashMap<>(BuiltinDeviceUuids.MAP);

    // ── Constructor ───────────────────────────────────────────────────────────

    protected BitwigStepPluginExtension(ControllerExtensionDefinition def, ControllerHost host) {
        super(def, host);
    }

    // ── init ──────────────────────────────────────────────────────────────────

    @Override
    public void init() {
        host = (ControllerHost) getHost();

        transport = host.createTransport();
        trackBank = host.createMainTrackBank(TRACK_BANK_SIZE, MAX_SENDS, SLOT_BANK_SIZE);
        cursorTrack = host.createCursorTrack("step-cursor", "Step Cursor", 0, SLOT_BANK_SIZE, true);
        cursorDevice = cursorTrack.createCursorDevice();
        popupBrowser = host.createPopupBrowser();
        application = host.createApplication();
        remoteControls = cursorDevice.createCursorRemoteControlsPage(REMOTE_PARAMS);
        clipSlotBank   = cursorTrack.clipLauncherSlotBank();
        cursorClip     = cursorTrack.createLauncherCursorClip(CLIP_STEPS, 128); // Schreiben + Lesen
        readCursorClip = host.createArrangerCursorClip(CLIP_STEPS, 128);         // Arranger (Backup)
        cursorClip.setStepSize(0.25);
        cursorClip.getLoopLength().markInterested();
        // Step-Observer auf Launcher-Cursor: feuert wenn Clip-Inhalt geladen
        cursorClip.addStepDataObserver((step, pitch, state) -> {
            if (collectingClipNotes && state == 1) {
                clipNoteBuf.add(step + "," + pitch);
            }
        });
        resultBank = popupBrowser.resultsColumn().createItemBank(BROWSER_SCAN);
        locationBank = popupBrowser.locationColumn().createItemBank(LOC_BANK_SIZE);
        deviceTypeBank = popupBrowser.deviceTypeColumn().createItemBank(LOC_BANK_SIZE);

        // Mark interested — Track-Namen + Device-Banks für Project-Scan
        trackDeviceBanks = new DeviceBank[TRACK_BANK_SIZE];
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Channel t = (Channel) trackBank.getItemAt(i);
            t.name().markInterested();
            t.exists().markInterested();
            // Sends (für set_send → Return-/Effect-Track-Routing, C.1)
            SendBank sb = t.sendBank();
            for (int sIdx = 0; sIdx < MAX_SENDS; sIdx++) {
                Send send = (Send) sb.getItemAt(sIdx);
                send.exists().markInterested();
                send.value().markInterested();
                send.name().markInterested();
            }
            Track tr = (Track) trackBank.getItemAt(i);
            DeviceBank db = tr.createDeviceBank(MAX_DEVICES_PER_TRACK);
            trackDeviceBanks[i] = db;
            for (int j = 0; j < MAX_DEVICES_PER_TRACK; j++) {
                db.getDevice(j).name().markInterested();
                db.getDevice(j).exists().markInterested();
            }
        }

        // Cursor-Track Device-Bank (folgt dem ausgewählten Track)
        cursorTrackDeviceBank = cursorTrack.createDeviceBank(MAX_DEVICES_PER_TRACK);
        cursorTrack.isGroup().markInterested();
        for (int i = 0; i < MAX_DEVICES_PER_TRACK; i++) {
            cursorTrackDeviceBank.getDevice(i).name().markInterested();
            cursorTrackDeviceBank.getDevice(i).exists().markInterested();
        }

        // isGroup markieren + Clip-Slot-Content pro Track beobachten
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Track tr = (Track) trackBank.getItemAt(i);
            tr.isGroup().markInterested();
            final int trackIdx = i;
            tr.clipLauncherSlotBank().addHasContentObserver((slotIdx, hasContent) -> {
                if (slotIdx < SLOT_BANK_SIZE) trackSlotHasContent[trackIdx][slotIdx] = hasContent;
            });
        }

        // SceneBank: Szenen-Namen + Existenz markieren
        sceneBank = trackBank.sceneBank();
        for (int i = 0; i < SLOT_BANK_SIZE; i++) {
            sceneBank.getScene(i).getName().markInterested();
            sceneBank.getScene(i).clipCount().markInterested();
        }

        // Arranger / Cue Markers
        arranger = host.createArranger();
        cueMarkerBank = arranger.createCueMarkerBank(CUE_MARKER_COUNT);
        for (int i = 0; i < CUE_MARKER_COUNT; i++) {
            CueMarker cm = (CueMarker) cueMarkerBank.getItemAt(i);
            cm.getName().markInterested();
            cm.position().markInterested();
            cm.exists().markInterested();
        }


        // MIDI Lesen: Arranger-Cursor-Clip Step-Observer
        readCursorClip.setStepSize(0.25);
        readCursorClip.addStepDataObserver((step, pitch, state) -> {
            if (collectingClipNotes && state == 1) {
                clipNoteBuf.add(step + "," + pitch);
            }
            if (collectingArrangerNotes && state == 1) {
                arrangerNoteBuf.add(step + "," + pitch);
            }
        });
        readCursorClip.getLoopLength().markInterested();

        // Clip-Slot hasContent via indexed Observer (kein getItemAt-Cast nötig)
        clipSlotBank.addHasContentObserver((slotIdx, hasContent) -> {
            if (slotIdx < SLOT_BANK_SIZE) slotHasContent[slotIdx] = hasContent;
        });
        cursorTrack.name().markInterested();
        cursorDevice.name().markInterested();
        cursorDevice.exists().markInterested();
        cursorDevice.isWindowOpen().markInterested();
        cursorDevice.hasDrumPads().markInterested();

        // DrumPadBank: Pad-Namen + Note-Zuordnung für Drum Machine
        // getItemAt() returns ObjectProxy (raw type), cast to Channel for name()/exists()
        drumPadBank = cursorDevice.createDrumPadBank(DRUM_PAD_COUNT);
        for (int i = 0; i < DRUM_PAD_COUNT; i++) {
            com.bitwig.extension.controller.api.Channel pad =
                (com.bitwig.extension.controller.api.Channel) drumPadBank.getItemAt(i);
            pad.name().markInterested();
            pad.exists().markInterested();
        }

        popupBrowser.exists().markInterested();
        popupBrowser.selectedContentTypeIndex().markInterested();
        popupBrowser.contentTypeNames().markInterested();

        // Konfigurierbarer Reply-Host (Bitwig → Settings → BitwigStepPlugin)
        agentHost = host.getPreferences()
                .getStringSetting("Agent Host (IP)", "Network", 64, "127.0.0.1");
        agentHost.markInterested();
        transport.tempo().markInterested();
        application.projectName().markInterested();
        for (int i = 0; i < BROWSER_SCAN; i++) {
            resultBank.getItem(i).name().markInterested();
            resultBank.getItem(i).exists().markInterested();
            resultBank.getItem(i).isSelected().markInterested();
        }
        for (int i = 0; i < LOC_BANK_SIZE; i++) {
            locationBank.getItem(i).name().markInterested();
            locationBank.getItem(i).exists().markInterested();
            locationBank.getItem(i).isSelected().markInterested();
            deviceTypeBank.getItem(i).name().markInterested();
            deviceTypeBank.getItem(i).exists().markInterested();
            deviceTypeBank.getItem(i).isSelected().markInterested();
        }
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            remoteControls.getParameter(i).name().markInterested();
            remoteControls.getParameter(i).value().markInterested();
        }
        remoteControls.pageCount().markInterested();
        remoteControls.pageNames().markInterested();
        remoteControls.selectedPageIndex().markInterested();
        remoteControls.getName().markInterested();

        // Browser observer: fires when browser closes → stepDone für load/append
        popupBrowser.exists().addValueObserver(new BooleanValueChangedCallback() {
            @Override
            public void valueChanged(boolean open) {
                if (!open) {
                    loadLocPhase = 0;
                    if (pendingStepSrc != null) {
                        OscConnection src = pendingStepSrc;
                        String typ = pendingStepType != null ? pendingStepType : "load_instrument";
                        pendingStepSrc = null;
                        pendingStepType = null;
                        // Plugin-Fenster automatisch schließen
                        host.scheduleTask(() -> cursorDevice.isWindowOpen().set(false), 200);
                        stepDone(src, typ);
                    }
                }
            }
        });

        setupOsc();

        host.showPopupNotification("Bitwig Step Plugin v1 (Port " + OSC_IN + ")");
        host.println("[BitwigStep] gestartet — Port " + OSC_IN);
    }

    // ── OSC Setup ────────────────────────────────────────────────────────────

    private void setupOsc() {
        OscModule osc = host.getOscModule();
        OscAddressSpace space = osc.createAddressSpace();

        // Reply-Verbindungen zu Python (Port 9002)
        String ah = (agentHost != null && !agentHost.get().isBlank()) ? agentHost.get() : "127.0.0.1";
        replyV4 = osc.connectToUdpServer(ah, OSC_REPLY, space);
        replyLocalhost = osc.connectToUdpServer("localhost", OSC_REPLY, space);
        host.println("[BitwigStep] Reply → " + ah + ":" + OSC_REPLY);

        // ── Ping/Pong ──────────────────────────────────────────────────────
        space.registerMethod("/ping", "*", "Ping",
                (src, msg) -> {
                    sendReply("/pong", 1);
                    host.println("[BitwigStep] Pong");
                });

        // ── Alle Actions auflisten (Debugging) ────────────────────────────
        space.registerMethod("/agent/actions/list", "*", "List all Bitwig actions",
                (src, msg) -> {
                    com.bitwig.extension.controller.api.Action[] actions = application.getActions();
                    StringBuilder sb = new StringBuilder("[");
                    int count = 0;
                    for (com.bitwig.extension.controller.api.Action a : actions) {
                        try {
                            String id   = a.getId();
                            String name = a.getName();
                            if (count > 0) sb.append(",");
                            sb.append("{\"id\":\"").append(jsonEsc(id))
                              .append("\",\"name\":\"").append(jsonEsc(name)).append("\"}");
                            count++;
                        } catch (Exception ignore) {}
                    }
                    sb.append("]");
                    sendReply("/agent/actions/list/response", sb.toString());
                    host.println("[BitwigStep] /agent/actions/list → " + count + " Actions");
                });

        // ── Launcher-Clip auf Track starten ───────────────────────────────
        // Parameter: trackIdx [slotIdx]  — startet Clip im Launcher
        space.registerMethod("/agent/track/clip/launch", "*", "Launch clip on track",
                (src, msg) -> {
                    int trackIdx = 1;
                    int slotIdx  = 0;
                    try {
                        String raw0 = JsonStepParser.argStr(msg, 0);
                        if (raw0 != null) trackIdx = (int) Double.parseDouble(raw0);
                        String raw1 = JsonStepParser.argStr(msg, 1);
                        if (raw1 != null) slotIdx  = (int) Double.parseDouble(raw1);
                    } catch (Exception e) {}
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/clip/launch/response", "error: track not found");
                        return;
                    }
                    tr.selectInMixer();
                    final int slot = slotIdx;
                    host.scheduleTask(() -> {
                        // launch(index) ist auf dem SlotBank-Objekt, nicht auf dem Slot
                        clipSlotBank.launch(slot);
                        sendReply("/agent/track/clip/launch/response", "launched:" + ti + ":" + slot);
                        host.println("[BitwigStep] Clip launched: Track " + ti + " Slot " + slot);
                    }, 300);
                });

        // ── Beliebige Bitwig-Action via ID ausführen ──────────────────────
        space.registerMethod("/agent/action/invoke", "*", "Invoke any Bitwig action by ID",
                (src, msg) -> {
                    String actionId = JsonStepParser.argStr(msg, 0);
                    if (actionId != null && !actionId.isEmpty()) {
                        try {
                            application.getAction(actionId).invoke();
                            sendReply("/agent/action/invoke/response", "invoked:" + actionId);
                            host.println("[BitwigStep] Action invoked: " + actionId);
                        } catch (Exception e) {
                            sendReply("/agent/action/invoke/response", "error:" + e.getMessage());
                            host.println("[BitwigStep] Action error: " + e.getMessage());
                        }
                    } else {
                        sendReply("/agent/action/invoke/response", "error:no action id");
                    }
                });

        // ── Projekt-Name abfragen ──────────────────────────────────────────
        space.registerMethod("/agent/project/name", "*", "Get current project name",
                (src, msg) -> {
                    String name = application.projectName().get();
                    sendReply("/agent/project/name/response", name != null ? name : "");
                });

        // ── Neues Projekt anlegen ──────────────────────────────────────────
        space.registerMethod("/agent/project/new", "*", "Create new empty project",
                (src, msg) -> {
                    try {
                        sendReply("/agent/project/new/response", "triggered");
                        application.getAction("New").invoke();
                        host.println("[BitwigStep] Neues Projekt angelegt");
                    } catch (Exception e) {
                        host.println("[BitwigStep] New fehlgeschlagen: " + e.getMessage());
                    }
                });

        // ── Projekt speichern (Collect and Save — kein Dialog bei bekanntem Projekt) ──
        space.registerMethod("/agent/project/save", "*", "Save current project",
                (src, msg) -> {
                    try {
                        String name = application.projectName().get();
                        sendReply("/agent/project/save/response", name != null ? name : "saved");
                        // "Collect and Save" speichert mit allen Dateien ohne neuen Dialog
                        // Fallback auf "Save" wenn Projekt schon einen Namen hat
                        application.getAction("Save").invoke();
                        host.println("[BitwigStep] Projekt gespeichert: " + name);
                    } catch (Exception e) {
                        host.println("[BitwigStep] Save fehlgeschlagen: " + e.getMessage());
                    }
                });

        // ── Track-Zustand abfragen ─────────────────────────────────────────
        space.registerMethod("/agent/track/count", "*", "Track count + names",
                (src, msg) -> {
                    int count = 0;
                    StringBuilder names = new StringBuilder();
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Channel t = (Channel) trackBank.getItemAt(i);
                        if (t.exists().get()) {
                            if (count > 0)
                                names.append(",");
                            names.append(t.name().get());
                            count++;
                        }
                    }
                    sendReply("/agent/track/count/response", count, names.toString());
                });

        // ── Tracks löschen ────────────────────────────────────────────────
        space.registerMethod("/agent/tracks/clear", "*", "Clear all tracks",
                (src, msg) -> {
                    int n = 0;
                    for (int i = 0; i < TRACK_BANK_SIZE; i++)
                        if (trackBank.getItemAt(i).exists().get())
                            n++;
                    final int total = n;
                    noteCountMap.clear();
                    if (total == 0) {
                        sendReply("/agent/tracks/clear/response", 0);
                        return;
                    }
                    for (int i = 0; i < total; i++) {
                        final long d = i * 80L;
                        host.scheduleTask(() -> {
                            Channel first = (Channel) trackBank.getItemAt(0);
                            if (first.exists().get()) {
                                first.selectInMixer();
                                cursorTrack.deleteObject();
                            }
                        }, d);
                    }
                    host.scheduleTask(() -> {
                        sendReply("/agent/tracks/clear/response", total);
                        host.println("[BitwigStep] " + total + " Tracks gelöscht");
                    }, total * 80L + 200L);
                });

        // ── VST Plugin Scanner ────────────────────────────────────────────
        space.registerMethod("/plugins/scan", "*", "Scan installed VST plugins",
                (src, msg) -> {
                    // Temp-Track anlegen → leerer Instrument-Track → Instrument-Browser-Kontext
                    // garantiert
                    application.createInstrumentTrack(-1);
                    host.scheduleTask(() -> {
                        // Browser auf leerem Track öffnen (browseToInsertBeforeDevice =
                        // Instrument-Kontext)
                        popupBrowser.cancel();
                        boolean hasDevice = cursorDevice.exists().get();
                        if (hasDevice)
                            cursorDevice.browseToReplaceDevice();
                        else
                            cursorDevice.browseToInsertBeforeDevice();

                        host.scheduleTask(() -> {
                            // Content-Type auf Plug-ins setzen
                            String[] typeNames = popupBrowser.contentTypeNames().get();
                            int pluginsIdx = 2;
                            StringBuilder tLog = new StringBuilder("[BitwigStep] scan contentTypes: ");
                            if (typeNames != null) {
                                for (int i = 0; i < typeNames.length; i++) {
                                    String tn = typeNames[i];
                                    tLog.append(i).append("=").append(tn).append("|");
                                    if (tn != null && tn.toLowerCase().contains("plug-in")
                                            && !tn.toLowerCase().contains("preset")) {
                                        pluginsIdx = i;
                                    }
                                }
                            }
                            host.println(tLog.toString());
                            popupBrowser.selectedContentTypeIndex().set(pluginsIdx);
                            host.println("[BitwigStep] scan ContentType Plug-ins=" + pluginsIdx);

                            host.scheduleTask(() -> {
                                StringBuilder names = new StringBuilder();
                                int count = 0;
                                for (int i = 0; i < BROWSER_SCAN; i++) {
                                    BrowserItem item = resultBank.getItem(i);
                                    if (!item.exists().get())
                                        break;
                                    String n = item.name().get();
                                    if (n == null || n.isBlank())
                                        continue;
                                    count++;
                                    if (names.length() > 0)
                                        names.append(",");
                                    names.append(n.trim());
                                }
                                popupBrowser.cancel();
                                // Temp-Track löschen
                                host.scheduleTask(() -> {
                                    Channel first = (Channel) trackBank.getItemAt(0);
                                    if (first.exists().get()) {
                                        first.selectInMixer();
                                        cursorTrack.deleteObject();
                                    }
                                }, 200);
                                String result = names.toString();
                                host.println("[BitwigStep] /plugins/scan → " + count + " Items");
                                sendReply("/plugins/scan/response", result);
                            }, 2000);
                        }, 800);
                    }, 300);
                });

        // ── Note-Counter ───────────────────────────────────────────────────
        space.registerMethod("/clip/note/count/all", "*", "All note counts",
                (src, msg) -> {
                    int total = 0;
                    StringBuilder sb = new StringBuilder();
                    for (Map.Entry<String, Integer> e : noteCountMap.entrySet()) {
                        if (sb.length() > 0)
                            sb.append(";");
                        sb.append(e.getKey()).append("=").append(e.getValue());
                        total += e.getValue();
                    }
                    sendReply("/clip/note/count/response", total, sb.toString());
                });

        space.registerMethod("/clip/note/count/reset", "*", "Reset note counts",
                (src, msg) -> noteCountMap.clear());

        // ── Device UUID Export ────────────────────────────────────────────
        space.registerMethod("/devices/export", "*", "Export all builtin device UUIDs as JSON",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder("{");
                    boolean first = true;
                    for (Map.Entry<String, String> e : BUILTIN_UUIDS.entrySet()) {
                        if (!first)
                            sb.append(",");
                        sb.append("\"")
                                .append(e.getKey().replace("\\", "\\\\").replace("\"", "\\\""))
                                .append("\":\"")
                                .append(e.getValue())
                                .append("\"");
                        first = false;
                    }
                    sb.append("}");
                    sendReply("/devices/export/response", sb.toString());
                    host.println("[BitwigStep] /devices/export → " + BUILTIN_UUIDS.size() + " Einträge");
                });

        // ── Project-Scan: alle Tracks + ihre Device-Ketten ───────────────
        // Group-Tracks werden durch ihre Kinder ersetzt (ein Level tief).
        space.registerMethod("/agent/project/scan", "*", "Scan all tracks and devices",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder("{\"tracks\":[");
                    int trackCount = 0;
                    double tempo = transport.tempo().getRaw();
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Track tr = (Track) trackBank.getItemAt(i);
                        if (!tr.exists().get()) continue;

                        if (!tr.exists().get()) continue;
                        if (trackCount > 0) sb.append(",");
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(tr.name().get())).append("\"");
                        sb.append(",\"is_group\":").append(tr.isGroup().get());
                        sb.append(",\"devices\":[");
                        DeviceBank db = trackDeviceBanks[i];
                        int devCount = 0;
                        for (int j = 0; j < MAX_DEVICES_PER_TRACK; j++) {
                            Device d = db.getDevice(j);
                            if (!d.exists().get()) break;
                            String dn = d.name().get();
                            if (dn == null || dn.isBlank()) break;
                            if (devCount > 0) sb.append(",");
                            sb.append("\"").append(jsonEsc(dn)).append("\"");
                            devCount++;
                        }
                        sb.append("]}");
                        trackCount++;
                    }
                    sb.append("],\"tempo\":").append(String.format(java.util.Locale.US, "%.1f", tempo));
                    sb.append(",\"total\":").append(trackCount).append("}");
                    sendReply("/agent/project/scan/response", sb.toString());
                    host.println("[BitwigStep] /agent/project/scan → " + trackCount + " Tracks");
                });

        // ── Track-Hierarchie: Group-Tracks erkennen ───────────────────────
        space.registerMethod("/agent/project/hierarchy", "*", "Track group detection",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder("{\"groups\":[");
                    int groupCount = 0;
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Track tr = (Track) trackBank.getItemAt(i);
                        if (!tr.exists().get())
                            continue;
                        if (!tr.isGroup().get())
                            continue;
                        if (groupCount > 0)
                            sb.append(",");
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(tr.name().get())).append("\"}");
                        groupCount++;
                    }
                    sb.append("],\"total_groups\":").append(groupCount).append("}");
                    sendReply("/agent/project/hierarchy/response", sb.toString());
                    host.println("[BitwigStep] /agent/project/hierarchy → " + groupCount + " Groups");
                });

        // ── Cursor Track Info: Name + Devices des aktuell ausgewählten Tracks ──
        space.registerMethod("/agent/cursor/track/info", "*", "Get selected track info",
                (src, msg) -> {
                    String name = cursorTrack.name().get();
                    boolean isGroup = cursorTrack.isGroup().get();
                    StringBuilder sb = new StringBuilder("{\"name\":\"");
                    sb.append(jsonEsc(name != null ? name : "")).append("\"");
                    sb.append(",\"is_group\":").append(isGroup);
                    sb.append(",\"devices\":[");
                    int devCount = 0;
                    for (int i = 0; i < MAX_DEVICES_PER_TRACK; i++) {
                        Device d = cursorTrackDeviceBank.getDevice(i);
                        if (!d.exists().get()) break;
                        String dn = d.name().get();
                        if (dn == null || dn.isBlank()) break;
                        if (devCount > 0) sb.append(",");
                        sb.append("\"").append(jsonEsc(dn)).append("\"");
                        devCount++;
                    }
                    sb.append("]}");
                    sendReply("/agent/cursor/track/info/response", sb.toString());
                    host.println("[BitwigStep] /cursor/track/info → " + name);
                });

        // ── Cursor Clip Notes: MIDI-Noten aus dem Arranger Cursor Clip ────────
        space.registerMethod("/agent/cursor/clip/notes", "*", "Read MIDI notes from Arranger cursor clip",
                (src, msg) -> {
                    arrangerNoteBuf.clear();
                    collectingArrangerNotes = true;
                    readCursorClip.scrollToStep(0);
                    host.scheduleTask(() -> {
                        collectingArrangerNotes = false;
                        double loopLen = readCursorClip.getLoopLength().get();
                        StringBuilder sb = new StringBuilder("{");
                        sb.append("\"loop_beats\":").append(String.format(java.util.Locale.US, "%.2f", loopLen));
                        sb.append(",\"notes\":[");
                        java.util.List<String> snap = new java.util.ArrayList<>(arrangerNoteBuf);
                        for (int i = 0; i < snap.size(); i++) {
                            if (i > 0) sb.append(",");
                            String[] p = snap.get(i).split(",");
                            sb.append("{\"step\":").append(p[0]);
                            sb.append(",\"pitch\":").append(p[1]).append("}");
                        }
                        sb.append("],\"count\":").append(snap.size()).append("}");
                        sendReply("/agent/cursor/clip/notes/response", sb.toString());
                        host.println("[BitwigStep] /cursor/clip/notes → " + snap.size() + " Noten");
                    }, 800);
                });

        // ── Szenen-Slots mit Namen ─────────────────────────────────────────
        space.registerMethod("/agent/project/scenes", "*", "Scene slots with names",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder("{\"scenes\":[");
                    int count = 0;
                    for (int i = 0; i < SLOT_BANK_SIZE; i++) {
                        if (count > 0)
                            sb.append(",");
                        String sceneName = sceneBank.getScene(i).getName().get();
                        if (sceneName == null || sceneName.isBlank())
                            sceneName = "Scene " + (i + 1);
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(sceneName)).append("\"");
                        sb.append(",\"clip_count\":").append(sceneBank.getScene(i).clipCount().get());
                        sb.append("}");
                        count++;
                    }
                    sb.append("],\"total\":").append(count).append("}");
                    sendReply("/agent/project/scenes/response", sb.toString());
                    host.println("[BitwigStep] /agent/project/scenes → " + count + " Szenen");
                });

        // ── Cue Markers: Arranger-Sektionsmarker mit Taktposition ────────────
        space.registerMethod("/agent/project/cue-markers", "*", "Arranger cue markers",
                (src, msg) -> {
                    StringBuilder sb = new StringBuilder("{\"markers\":[");
                    int count = 0;
                    for (int i = 0; i < CUE_MARKER_COUNT; i++) {
                        CueMarker cm = (CueMarker) cueMarkerBank.getItemAt(i);
                        if (!cm.exists().get()) continue;
                        if (count > 0) sb.append(",");
                        String name = cm.getName().get();
                        double posBeats = cm.position().get();
                        double posBar   = posBeats / 4.0 + 1.0; // 4/4 → Bar (1-basiert)
                        if (name == null || name.isBlank()) name = "Marker " + (i + 1);
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(name)).append("\"");
                        sb.append(",\"beat\":").append(String.format(java.util.Locale.US, "%.2f", posBeats));
                        sb.append(",\"bar\":").append(String.format(java.util.Locale.US, "%.1f", posBar));
                        sb.append("}");
                        count++;
                    }
                    sb.append("],\"total\":").append(count).append("}");
                    sendReply("/agent/project/cue-markers/response", sb.toString());
                    host.println("[BitwigStep] /agent/project/cue-markers → " + count + " Marker");
                });

        // ── Full Project Snapshot: tracks + groups + scenes in einem Roundtrip ──
        space.registerMethod("/agent/project/full-snapshot", "*", "Full project snapshot",
                (src, msg) -> {
                    double tempo = transport.tempo().getRaw();
                    StringBuilder sb = new StringBuilder("{");

                    // tracks (Group-Tracks werden durch ihre Kinder ersetzt)
                    sb.append("\"tracks\":[");
                    int trackCount = 0;
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Track tr = (Track) trackBank.getItemAt(i);
                        if (!tr.exists().get()) continue;

                        if (trackCount > 0) sb.append(",");
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(tr.name().get())).append("\"");
                        sb.append(",\"is_group\":").append(tr.isGroup().get());
                        // devices
                        sb.append(",\"devices\":[");
                        DeviceBank db = trackDeviceBanks[i];
                        int devCount = 0;
                        for (int j = 0; j < MAX_DEVICES_PER_TRACK; j++) {
                            Device d = db.getDevice(j);
                            if (!d.exists().get()) break;
                            String dn = d.name().get();
                            if (dn == null || dn.isBlank()) break;
                            if (devCount > 0) sb.append(",");
                            sb.append("\"").append(jsonEsc(dn)).append("\"");
                            devCount++;
                        }
                        sb.append("]");
                        // Clip-Slot-Content: welche Szenen-Slots haben einen Clip?
                        sb.append(",\"slots\":[");
                        for (int s = 0; s < SLOT_BANK_SIZE; s++) {
                            if (s > 0) sb.append(",");
                            sb.append(trackSlotHasContent[i][s] ? "true" : "false");
                        }
                        sb.append("]}");
                        trackCount++;
                    }
                    sb.append("]");

                    // scenes
                    sb.append(",\"scenes\":[");
                    for (int i = 0; i < SLOT_BANK_SIZE; i++) {
                        if (i > 0) sb.append(",");
                        String sn = sceneBank.getScene(i).getName().get();
                        if (sn == null || sn.isBlank()) sn = "Scene " + (i + 1);
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(sn)).append("\"");
                        sb.append(",\"clip_count\":").append(sceneBank.getScene(i).clipCount().get());
                        sb.append("}");
                    }
                    sb.append("]");

                    // groups (group-track indices)
                    sb.append(",\"groups\":[");
                    int groupCount = 0;
                    for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                        Track tr = (Track) trackBank.getItemAt(i);
                        if (!tr.exists().get() || !tr.isGroup().get()) continue;
                        if (groupCount > 0) sb.append(",");
                        sb.append("{\"idx\":").append(i + 1);
                        sb.append(",\"name\":\"").append(jsonEsc(tr.name().get())).append("\"}");
                        groupCount++;
                    }
                    sb.append("]");

                    // Cue Markers (Arranger-Sektionen)
                    sb.append(",\"cue_markers\":[");
                    int markerCount = 0;
                    for (int i = 0; i < CUE_MARKER_COUNT; i++) {
                        CueMarker cm = (CueMarker) cueMarkerBank.getItemAt(i);
                        if (!cm.exists().get()) continue;
                        if (markerCount > 0) sb.append(",");
                        String mn = cm.getName().get();
                        if (mn == null || mn.isBlank()) mn = "Marker " + (i + 1);
                        double posBeats = cm.position().get();
                        sb.append("{\"name\":\"").append(jsonEsc(mn)).append("\"");
                        sb.append(",\"beat\":").append(String.format(java.util.Locale.US, "%.2f", posBeats));
                        sb.append(",\"bar\":").append(String.format(java.util.Locale.US, "%.1f", posBeats / 4.0 + 1.0));
                        sb.append("}");
                        markerCount++;
                    }
                    sb.append("]");

                    sb.append(",\"tempo\":").append(String.format(java.util.Locale.US, "%.1f", tempo));
                    sb.append(",\"total_tracks\":").append(trackCount).append("}");
                    sendReply("/agent/project/full-snapshot/response", sb.toString());
                    host.println("[BitwigStep] /agent/project/full-snapshot → " + trackCount + " Tracks, " + markerCount + " CueMarker");
                });

        // ── MIDI Clip Notes aus Launcher-Clip ────────────────────────────
        // Parameter: trackIdx [sceneIdx]  — sceneIdx optional (0=erster mit Inhalt)
        space.registerMethod("/agent/track/clip/notes", "*", "Read MIDI notes from launcher clip",
                (src, msg) -> {
                    int trackIdx = 1;
                    int sceneIdx = 0; // 0 = erster Slot mit Inhalt
                    try {
                        String raw0 = JsonStepParser.argStr(msg, 0);
                        if (raw0 != null) trackIdx = (int) Double.parseDouble(raw0);
                        String raw1 = JsonStepParser.argStr(msg, 1);
                        if (raw1 != null) sceneIdx = (int) Double.parseDouble(raw1);
                    } catch (Exception e) {}
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    final int requestedScene = sceneIdx;

                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/clip/notes/response", ti, "{}");
                        return;
                    }
                    tr.selectInMixer();

                    host.scheduleTask(() -> {
                        // Ziel-Slot bestimmen
                        int _targetSlot = 0;
                        if (requestedScene > 0) {
                            _targetSlot = requestedScene - 1; // 1-basiert → 0-basiert
                        } else {
                            for (int s = 0; s < SLOT_BANK_SIZE; s++) {
                                if (trackSlotHasContent[ti - 1][s]) { _targetSlot = s; break; }
                            }
                        }
                        final int targetSlot = _targetSlot;

                        // Buffer leeren + Flag SETZEN bevor Select → Observer fängt sofort ein
                        clipNoteBuf.clear();
                        collectingClipNotes = true;

                        // Slot selektieren → cursorClip folgt → addStepDataObserver feuert
                        clipSlotBank.select(targetSlot);

                        // scrollToStep(0) nach kurzer Pause: sicherstellt dass alle Steps
                        // im Fenster neu geliefert werden (falls Observer schon gefeuert hat)
                        host.scheduleTask(() -> {
                            cursorClip.scrollToStep(0);

                            host.scheduleTask(() -> {
                                collectingClipNotes = false;
                                double loopLen = cursorClip.getLoopLength().get();
                                StringBuilder sb = new StringBuilder("{\"track\":");
                                sb.append(ti);
                                sb.append(",\"loop_beats\":").append(
                                        String.format(java.util.Locale.US, "%.2f", loopLen));
                                sb.append(",\"notes\":[");
                                java.util.List<String> noteSnap = new java.util.ArrayList<>(clipNoteBuf);
                                for (int i = 0; i < noteSnap.size(); i++) {
                                    if (i > 0) sb.append(",");
                                    String[] p = noteSnap.get(i).split(",");
                                    sb.append("{\"step\":").append(p[0]);
                                    sb.append(",\"pitch\":").append(p[1]).append("}");
                                }
                                sb.append("],\"count\":").append(noteSnap.size());
                                sb.append(",\"scene_slot\":").append(targetSlot + 1).append("}");
                                sendReply("/agent/track/clip/notes/response", ti, sb.toString());
                                host.println("[BitwigStep] /clip/notes → " + noteSnap.size()
                                        + " Noten, Track " + ti + " Szene-Slot " + (targetSlot + 1));
                            }, 800); // Fenster zum Sammeln
                        }, 300); // kurze Pause nach Select
                    }, 500); // warte bis cursorTrack dem selectInMixer folgt
                });

        // ── Track-Parameter: Remote Controls des ausgewählten Geräts ─────
        space.registerMethod("/agent/track/params", "*", "Remote control params for track",
                (src, msg) -> {
                    int trackIdx = 1;
                    try {
                        String raw = JsonStepParser.argStr(msg, 0);
                        if (raw != null)
                            trackIdx = (int) Double.parseDouble(raw);
                    } catch (Exception e) {
                    }
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/params/response", ti, "{}");
                        return;
                    }
                    tr.selectInMixer();
                    final int finalTi = ti;
                    host.scheduleTask(() -> {
                        StringBuilder sb = new StringBuilder("{");
                        sb.append("\"track\":").append(finalTi);
                        sb.append(",\"device\":\"").append(jsonEsc(cursorDevice.name().get())).append("\"");
                        sb.append(",\"params\":[");
                        for (int i = 0; i < REMOTE_PARAMS; i++) {
                            if (i > 0)
                                sb.append(",");
                            String pn = remoteControls.getParameter(i).name().get();
                            double pv = remoteControls.getParameter(i).value().get();
                            sb.append("{\"name\":\"").append(jsonEsc(pn != null ? pn : "")).append("\"");
                            sb.append(",\"value\":").append(String.format(java.util.Locale.US, "%.4f", pv)).append("}");
                        }
                        sb.append("]}");
                        sendReply("/agent/track/params/response", finalTi, sb.toString());
                    }, 450);
                });

        // ── Drum Machine Pad-Mapping ──────────────────────────────────────
        // Gibt Pad-Namen + MIDI-Note-Nummern für den ersten Device des Tracks zurück.
        // MIDI Note für Pad i = 36 + i (Bitwig Drum Machine Standard).
        // Response: {"track":N,"device":"Drum Machine","pads":[{"pad":0,"note":36,"name":"Kick"},…]}
        space.registerMethod("/agent/track/drum-pads", "*", "Drum Machine pad mapping",
                (src, msg) -> {
                    int trackIdx = 1;
                    try {
                        String raw = JsonStepParser.argStr(msg, 0);
                        if (raw != null)
                            trackIdx = (int) Double.parseDouble(raw);
                    } catch (Exception e) {}
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/drum-pads/response", ti, "{\"pads\":[]}");
                        return;
                    }
                    tr.selectInMixer();
                    final int finalTi = ti;
                    // Warte bis cursorDevice auf diesen Track gesetzt ist
                    host.scheduleTask(() -> {
                        String devName = cursorDevice.exists().get() ? cursorDevice.name().get() : "";
                        boolean hasPads = cursorDevice.hasDrumPads().get();
                        StringBuilder sb = new StringBuilder("{");
                        sb.append("\"track\":").append(finalTi);
                        sb.append(",\"device\":\"").append(jsonEsc(devName)).append("\"");
                        sb.append(",\"has_drum_pads\":").append(hasPads);
                        sb.append(",\"pads\":[");
                        if (hasPads) {
                            int padCount = 0;
                            for (int i = 0; i < DRUM_PAD_COUNT; i++) {
                                com.bitwig.extension.controller.api.Channel pad =
                                    (com.bitwig.extension.controller.api.Channel) drumPadBank.getItemAt(i);
                                if (!pad.exists().get()) continue;
                                String padName = pad.name().get();
                                if (padName == null) padName = "";
                                int midiNote = 36 + i; // Bitwig Drum Machine: Pad 0 = Note 36 (C2)
                                if (padCount > 0) sb.append(",");
                                sb.append("{\"pad\":").append(i);
                                sb.append(",\"note\":").append(midiNote);
                                sb.append(",\"name\":\"").append(jsonEsc(padName)).append("\"");
                                sb.append("}");
                                padCount++;
                            }
                        }
                        sb.append("]}");
                        sendReply("/agent/track/drum-pads/response", finalTi, sb.toString());
                        host.println("[BitwigStep] /agent/track/drum-pads Track " + finalTi
                                + " device=" + devName + " hasPads=" + hasPads);
                    }, 500);
                });

        // ── Device-Fenster öffnen (für Grid-Screenshot) ───────────────────
        space.registerMethod("/agent/track/device/open", "*", "Open device editor for track",
                (src, msg) -> {
                    int trackIdx = 1;
                    try {
                        String raw = JsonStepParser.argStr(msg, 0);
                        if (raw != null)
                            trackIdx = (int) Double.parseDouble(raw);
                    } catch (Exception e) {
                    }
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/device/open/response", ti, "not_found");
                        return;
                    }
                    tr.selectInMixer();
                    host.scheduleTask(() -> {
                        cursorDevice.isWindowOpen().set(true);
                        host.scheduleTask(() -> {
                            String devName = cursorDevice.name().get();
                            sendReply("/agent/track/device/open/response", ti, devName);
                            host.println("[BitwigStep] Device-Fenster geöffnet: " + devName + " (Track " + ti + ")");
                        }, 300);
                    }, 400);
                });

        // ── Alle Parameter-Seiten eines Tracks (vollständiger Grid-Scan) ──
        space.registerMethod("/agent/track/params/all", "*", "All remote control pages for track",
                (src, msg) -> {
                    int trackIdx = 1;
                    try {
                        String raw = JsonStepParser.argStr(msg, 0);
                        if (raw != null)
                            trackIdx = (int) Double.parseDouble(raw);
                    } catch (Exception e) {
                    }
                    final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));
                    Track tr = (Track) trackBank.getItemAt(ti - 1);
                    if (!tr.exists().get()) {
                        sendReply("/agent/track/params/all/response", ti, "{}");
                        return;
                    }
                    tr.selectInMixer();
                    final int finalTi = ti;

                    // Seite 0 auswählen, dann alle Seiten durchlaufen
                    host.scheduleTask(() -> {
                        // Zur ersten Seite gehen
                        remoteControls.selectNextPage(true); // wrap=true, geht zu Seite 0
                        host.scheduleTask(() -> {
                            int totalPages = remoteControls.pageCount().get();
                            String[] pnames = remoteControls.pageNames().get();
                            String devName = cursorDevice.name().get();

                            // Alle Seiten akkumulieren via rekursive scheduleTask-Kette
                            final StringBuilder sb = new StringBuilder();
                            sb.append("{\"track\":").append(finalTi);
                            sb.append(",\"device\":\"").append(jsonEsc(devName)).append("\"");
                            sb.append(",\"page_count\":").append(totalPages);
                            sb.append(",\"pages\":[");
                            final int[] pagesDone = { 0 };
                            final int pagesToScan = Math.min(totalPages, 16); // max 16 Seiten

                            // Seite 0 ist bereits aktiv — sammeln
                            collectPageAndNext(sb, pagesDone, pagesToScan, pnames, finalTi, devName);
                        }, 300);
                    }, 450);
                });

        // ── HAUPTENDPUNKT: /step/exec ─────────────────────────────────────
        space.registerMethod("/step/exec", "*", "Execute single step",
                (src, msg) -> {
                    String json = JsonStepParser.argStr(msg, 0);
                    if (json == null || json.isBlank()) {
                        sendReply("/step/done", "error:empty");
                        return;
                    }
                    synchronized (stepQueue) {
                        if (stepExecuting) {
                            stepQueue.add(new String[] { json });
                            host.println(
                                    "[BitwigStep] Step eingereiht: " + json.substring(0, Math.min(60, json.length())));
                            return;
                        }
                        stepExecuting = true;
                    }
                    executeStep(src, json);
                });

        space.registerDefaultMethod((src, msg) -> host.println("[BitwigStep] Unbekannt: " + msg.getAddressPattern()));

        osc.createUdpServer(OSC_IN, space);
        host.println("[BitwigStep] OSC auf UDP:" + OSC_IN);
    }

    // ── Step Dispatcher ───────────────────────────────────────────────────────

    private void executeStep(OscConnection src, String json) {
        String type = JsonStepParser.extractStringField(json, "type");
        String args = JsonStepParser.extractNestedObject(json, "args");
        if (args == null)
            args = "{}";
        host.println("[BitwigStep] exec: " + type);

        // Precondition: Steps die einen existierenden Track benötigen
        switch (type != null ? type : "") {
            case "load_instrument":
            case "append_effect":
            case "write_notes":
            case "set_param":
            case "set_send":
            case "setup_drum_machine":
            case "set_param_named": {
                int track = (int) JsonStepParser.extractNumField(args, "track_index", 0);
                if (track > 0 && !trackBank.getItemAt(
                        Math.max(0, Math.min(TRACK_BANK_SIZE - 1, track - 1))).exists().get()) {
                    host.println("[BitwigStep] Precondition: track " + track + " existiert nicht");
                    stepDone(src, "error:precondition:track_not_found:" + track);
                    return;
                }
                break;
            }
        }

        switch (type != null ? type : "") {
            case "set_tempo" -> execSetTempo(src, args);
            case "add_track" -> execAddTrack(src, args);
            case "select_track" -> execSelectTrack(src, args);
            case "load_instrument" -> execLoadInstrument(src, args);
            case "append_effect" -> execAppendEffect(src, args);
            case "set_param" -> execSetParam(src, args);
            case "set_param_named" -> execSetParamNamed(src, args);
            case "set_send" -> execSetSend(src, args);
            case "setup_drum_machine" -> execSetupDrumMachine(src, args);
            case "write_notes" -> execWriteNotes(src, args);
            case "clear_tracks" -> execClearTracks(src);
            case "play" -> {
                transport.play();
                stepDone(src, "play");
            }
            case "stop" -> {
                transport.stop();
                stepDone(src, "stop");
            }
            default -> stepDone(src, "error:unknown:" + type);
        }
    }

    private void stepDone(OscConnection src, String type) {
        sendReply("/step/done", type);
        host.println("[BitwigStep] done: " + type);
        synchronized (stepQueue) {
            if (stepQueue.isEmpty()) {
                stepExecuting = false;
                return;
            }
            String[] next = stepQueue.poll();
            executeStep(src, next[0]);
        }
    }

    // ── Step Handler ──────────────────────────────────────────────────────────

    private void execSetTempo(OscConnection src, String args) {
        double bpm = JsonStepParser.extractNumField(args, "bpm", 120.0);
        transport.tempo().setRaw(bpm);
        stepDone(src, "set_tempo");
    }

    private void execAddTrack(OscConnection src, String args) {
        String t = JsonStepParser.extractStringField(args, "track_type");
        if ("audio".equals(t))
            application.createAudioTrack(-1);
        else if ("return".equals(t) || "effect".equals(t))
            application.createEffectTrack(-1);
        else if ("group".equals(t)) {
            // Bitwig hat kein createGroupTrack — die Action gruppiert selektierte
            // Tracks bzw. legt einen leeren Group-Track an (C.2).
            try {
                application.getAction("create_group_track").invoke();
            } catch (Exception e) {
                host.println("[BitwigStep] create_group_track nicht verfügbar: " + e.getMessage());
                stepDone(src, "error:add_track:group_action_unavailable");
                return;
            }
        } else
            application.createInstrumentTrack(-1);
        host.scheduleTask(() -> stepDone(src, "add_track"), 80);
    }

    private void execClearTracks(OscConnection src) {
        // Zuerst alle offenen Plugin-Fenster schließen
        cursorDevice.isWindowOpen().set(false);
        int n = 0;
        for (int i = 0; i < TRACK_BANK_SIZE; i++)
            if (trackBank.getItemAt(i).exists().get())
                n++;
        final int total = n;
        noteCountMap.clear();
        if (total == 0) {
            stepDone(src, "clear_tracks");
            return;
        }
        for (int i = 0; i < total; i++) {
            final long d = i * 100L;
            host.scheduleTask(() -> {
                Channel first = (Channel) trackBank.getItemAt(0);
                if (first.exists().get()) {
                    first.selectInMixer();
                    cursorTrack.deleteObject();
                }
            }, d);
        }
        host.scheduleTask(() -> {
            host.println("[BitwigStep] " + total + " Tracks gelöscht");
            stepDone(src, "clear_tracks");
        }, total * 100L + 300L);
    }

    private void execSelectTrack(OscConnection src, String args) {
        int idx = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        if (idx <= TRACK_BANK_SIZE) {
            Channel ch = (Channel) trackBank.getItemAt(idx - 1);
            if (ch.exists().get())
                ch.selectInMixer();
        }
        host.scheduleTask(() -> stepDone(src, "select_track"), 40);
    }

    private void execLoadInstrument(OscConnection src, String args) {
        int track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        String name = JsonStepParser.extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:load_instrument:no_name");
            return;
        }
        String key = name.toLowerCase().trim();
        String uuidFromArgs = JsonStepParser.extractStringField(args, "uuid");
        String uuid = (uuidFromArgs != null && !uuidFromArgs.isBlank())
                ? uuidFromArgs
                : BUILTIN_UUIDS.get(key);

        Channel ch = (channel(track));
        ch.selectInMixer();

        if (uuid != null) {
            // Built-in via UUID — sofort nach Track-Select (40ms)
            final String uuidStr = uuid;
            host.scheduleTask(() -> {
                try {
                    cursorDevice.beforeDeviceInsertionPoint()
                            .insertBitwigDevice(UUID.fromString(uuidStr));
                    host.println("[BitwigStep] UUID-Load: " + name);
                } catch (Exception e) {
                    host.println("[BitwigStep] UUID-Fehler " + name + ": " + e.getMessage());
                }
                stepDone(src, "load_instrument");
            }, 40);
        } else {
            // Browser-Fallback für VST / Presets
            pendingStepSrc = src;
            pendingStepType = "load_instrument";
            // Normalisierter Key: "MT-PowerDrumKit" → "mtpowerdrumkit"
            final String normKey = key.replace("-", "").replace(" ", "").replace("_", "");
            host.scheduleTask(() -> {
                // T+40ms: Browser öffnen
                // Wenn Track schon ein Device hat → ersetzen (browseToReplace), sonst einfügen
                popupBrowser.cancel();
                boolean hasDevice = cursorDevice.exists().get();
                if (hasDevice) {
                    cursorDevice.browseToReplaceDevice();
                    host.println("[BitwigStep] browseToReplace (Track hat Device): " + key);
                } else {
                    cursorDevice.browseToInsertBeforeDevice();
                    host.println("[BitwigStep] browseToInsert (leerer Track): " + key);
                }

                // T+540ms: Content-Type auf "Plug-ins" umschalten via selectedContentTypeIndex
                host.scheduleTask(() -> {
                    // Content-Type-Namen scannen und "Plug-ins" Index finden
                    String[] typeNames = popupBrowser.contentTypeNames().get();
                    int pluginsIdx = -1;
                    int currentIdx = popupBrowser.selectedContentTypeIndex().get();
                    StringBuilder tLog = new StringBuilder("[BitwigStep] contentTypes(cur=" + currentIdx + "): ");
                    if (typeNames != null) {
                        for (int i = 0; i < typeNames.length; i++) {
                            String tn = typeNames[i];
                            tLog.append(i).append("=").append(tn != null ? tn : "null").append("|");
                            if (pluginsIdx < 0 && tn != null
                                    && tn.toLowerCase().contains("plug-in")
                                    && !tn.toLowerCase().contains("preset")) {
                                pluginsIdx = i;
                            }
                        }
                    }
                    host.println(tLog.toString());
                    if (pluginsIdx >= 0 && pluginsIdx != currentIdx) {
                        popupBrowser.selectedContentTypeIndex().set(pluginsIdx);
                        host.println("[BitwigStep] ContentType → Plug-ins idx=" + pluginsIdx);
                    } else if (pluginsIdx < 0) {
                        host.println("[BitwigStep] WARN: Plug-ins ContentType nicht gefunden, versuche idx=2");
                        popupBrowser.selectedContentTypeIndex().set(2);
                    }

                    // T+2040ms: Ergebnisse nach ContentType-Wechsel scannen
                    host.scheduleTask(() -> {
                        StringBuilder resLog = new StringBuilder("[BitwigStep] results@4000: ");
                        int foundIdx = -1;
                        String foundName = null;
                        for (int i = 0; i < BROWSER_SCAN; i++) {
                            BrowserItem item = resultBank.getItem(i);
                            if (!item.exists().get()) {
                                resLog.append("END@").append(i);
                                break;
                            }
                            String n = item.name().get();
                            if (i < 20 && n != null)
                                resLog.append(i).append("=").append(n).append("|");
                            if (n != null) {
                                // Normalisierter Vergleich: Bindestriche + Leerzeichen ignorieren
                                String normN = n.toLowerCase()
                                        .replace("-", "").replace(" ", "").replace("_", "");
                                if (normN.contains(normKey)) {
                                    foundIdx = i;
                                    foundName = n;
                                    break;
                                }
                            }
                        }
                        host.println(resLog.toString());

                        if (foundIdx >= 0) {
                            // Direktauswahl via isSelected() — kein Cursor-Offset-Problem
                            resultBank.getItem(foundIdx).isSelected().set(true);
                            final int fi = foundIdx;
                            final String fn = foundName;
                            // 600ms warten damit Bitwig die Selektion verarbeitet, dann committen
                            host.scheduleTask(() -> {
                                // Sicherstellen dass das richtige Item selektiert ist
                                String selectedName = resultBank.getItem(fi).name().get();
                                host.println("[BitwigStep] commit: '" + fn + "' idx=" + fi
                                        + " (selected='" + selectedName + "')");
                                popupBrowser.commit();
                            }, 600);
                        } else {
                            OscConnection ts = pendingStepSrc;
                            pendingStepSrc = null;
                            pendingStepType = null;
                            popupBrowser.cancel();
                            host.println("[BitwigStep] '" + key + "' nicht gefunden in Ergebnissen");
                            if (ts != null)
                                stepDone(ts, "error:load_instrument:not_found:" + key);
                        }
                    }, 1000);
                }, 1000);

                // Sicherheits-Timeout 15s — nur für DIESEN Step, nicht für spätere
                final OscConnection timeoutSrc = src;
                host.scheduleTask(() -> {
                    if (pendingStepSrc == timeoutSrc) { // noch unser Step?
                        pendingStepSrc = null;
                        pendingStepType = null;
                        popupBrowser.cancel();
                        host.println("[BitwigStep] browser_timeout: " + key);
                        stepDone(timeoutSrc, "error:browser_timeout:" + key);
                    }
                }, 15000);
            }, 40);
        }
    }

    private void execAppendEffect(OscConnection src, String args) {
        int track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        String name = JsonStepParser.extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:append_effect:no_name");
            return;
        }
        String key = name.toLowerCase().trim();
        String uuidFromArgs = JsonStepParser.extractStringField(args, "uuid");
        String uuid = (uuidFromArgs != null && !uuidFromArgs.isBlank())
                ? uuidFromArgs
                : BUILTIN_UUIDS.get(key);

        channel(track).selectInMixer();

        if (uuid != null) {
            final String uuidStr = uuid;
            host.scheduleTask(() -> {
                try {
                    // endOfDeviceChainInsertionPoint: immer ans Ende → korrekte Reihenfolge
                    // unabhängig von aktuellem cursorDevice
                    Channel ch = channel(track);
                    ch.endOfDeviceChainInsertionPoint()
                            .insertBitwigDevice(UUID.fromString(uuidStr));
                    host.println("[BitwigStep] UUID-Append (end): " + name);
                } catch (Exception e) {
                    host.println("[BitwigStep] UUID-Fehler " + name + ": " + e.getMessage());
                }
                stepDone(src, "append_effect");
            }, 80);
        } else {
            host.scheduleTask(() -> {
                popupBrowser.cancel();
                cursorDevice.browseToInsertAfterDevice();
                pendingStepSrc = src;
                pendingStepType = "append_effect";
                loadTarget = key;
                loadWaitLeft = 6;
                host.scheduleTask(() -> {
                    if (pendingStepSrc != null) {
                        host.println("[BitwigStep] Browser-Timeout (Effekt): " + name);
                        OscConnection ts = pendingStepSrc;
                        pendingStepSrc = null;
                        pendingStepType = null;
                        loadTarget = null;
                        popupBrowser.cancel();
                        if (ts != null)
                            stepDone(ts, "error:browser_timeout:" + key);
                    }
                }, 10000);
            }, 40);
        }
    }

    private void execSetParam(OscConnection src, String args) {
        int track = (int) JsonStepParser.extractNumField(args, "track_index", 0);
        int idx = Math.max(0, Math.min(7, (int) JsonStepParser.extractNumField(args, "index", 1) - 1));
        double val = JsonStepParser.extractNumField(args, "value", 0.0);

        if (track > 0)
            channel(track).selectInMixer();
        long delay = track > 0 ? 40L : 0L;
        final int fi = idx;
        final double fv = val;
        host.scheduleTask(() -> {
            remoteControls.getParameter(fi).value().set(fv);
            stepDone(src, "set_param");
        }, delay);
    }

    private void execSetParamNamed(OscConnection src, String args) {
        int track = (int) JsonStepParser.extractNumField(args, "track_index", 0);
        String pname = JsonStepParser.extractStringField(args, "param_name");
        double val = JsonStepParser.extractNumField(args, "value", 0.0);

        if (track > 0)
            channel(track).selectInMixer();
        long delay = track > 0 ? 40L : 0L;
        final String fp = pname;
        final double fv = val;
        host.scheduleTask(() -> {
            if (fp != null) {
                Integer pi = paramCatalog.get(fp.toLowerCase().trim());
                if (pi != null)
                    remoteControls.getParameter(pi).value().set(fv);
                else
                    host.println("[BitwigStep] Param nicht gefunden: " + fp);
            }
            stepDone(src, "set_param_named");
        }, delay);
    }

    // ── set_send: Send-Pegel eines Tracks zu einem Return-/Effect-Track (C.1) ──
    private void execSetSend(OscConnection src, String args) {
        int track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        int sendIdx = Math.max(0, (int) JsonStepParser.extractNumField(args, "send_index", 0));
        double level = JsonStepParser.extractNumField(args, "level", 0.0);
        if (sendIdx >= MAX_SENDS) {
            stepDone(src, "error:set_send:send_index_out_of_range:" + sendIdx);
            return;
        }
        final double clamped = Math.max(0.0, Math.min(1.0, level));
        channel(track).selectInMixer();
        host.scheduleTask(() -> {
            try {
                Send send = (Send) channel(track).sendBank().getItemAt(sendIdx);
                if (!send.exists().get()) {
                    host.println("[BitwigStep] set_send: Send " + sendIdx
                            + " existiert nicht (Track " + track + ") — kein Return-Track?");
                    stepDone(src, "error:set_send:send_not_found:" + sendIdx);
                    return;
                }
                send.value().set(clamped);
                host.println("[BitwigStep] set_send Track " + track
                        + " Send " + sendIdx + " → " + clamped);
                stepDone(src, "set_send");
            } catch (Exception e) {
                host.println("[BitwigStep] set_send Fehler: " + e.getMessage());
                stepDone(src, "error:set_send:" + e.getMessage());
            }
        }, 60);
    }

    // ── setup_drum_machine: Drum Machine laden + Pads mit Devices belegen (C.3) ─
    // args: {track_index, pads:[{pad|note, name, uuid?}, …]}
    //   pad  = Pad-Index 0..15 (alternativ note = 36+pad)
    //   name = Built-in-Instrument-Name (UUID-Auflösung via BUILTIN_UUIDS) oder
    //          explizite uuid. Sample-/VST-Pads (kein UUID-Treffer) werden geloggt
    //          und übersprungen (kein flakiger Multi-Browser-Flow).
    private void execSetupDrumMachine(OscConnection src, String args) {
        int track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        String padsArr = JsonStepParser.extractArray(args, "pads");
        List<String> padSpecs = padsArr != null
                ? JsonStepParser.splitObjects(padsArr) : new ArrayList<>();

        String dmUuid = BUILTIN_UUIDS.get("drum machine");
        if (dmUuid == null) {
            stepDone(src, "error:setup_drum_machine:no_drum_machine_uuid");
            return;
        }

        channel(track).selectInMixer();
        // T+80ms: Drum Machine in die Geräte-Kette des Tracks einfügen
        host.scheduleTask(() -> {
            try {
                channel(track).endOfDeviceChainInsertionPoint()
                        .insertBitwigDevice(UUID.fromString(dmUuid));
                host.println("[BitwigStep] Drum Machine geladen (Track " + track + ")");
            } catch (Exception e) {
                host.println("[BitwigStep] Drum-Machine-Fehler: " + e.getMessage());
                stepDone(src, "error:setup_drum_machine:" + e.getMessage());
                return;
            }
            // T+600ms: Pads sequenziell belegen (cursorDevice = Drum Machine → drumPadBank folgt)
            host.scheduleTask(() -> fillDrumPads(src, track, padSpecs, 0, 0), 600);
        }, 80);
    }

    // Belegt rekursiv Pad nach Pad (gestaffelt), damit Insertions nicht kollidieren.
    private void fillDrumPads(OscConnection src, int track, List<String> padSpecs,
                              int i, int loaded) {
        if (i >= padSpecs.size()) {
            host.println("[BitwigStep] setup_drum_machine fertig: " + loaded
                    + "/" + padSpecs.size() + " Pads belegt (Track " + track + ")");
            stepDone(src, "setup_drum_machine");
            return;
        }
        String spec = padSpecs.get(i);
        String name = JsonStepParser.extractStringField(spec, "name");
        int note = (int) JsonStepParser.extractNumField(spec, "note", -1);
        int padIdx = note >= 36 ? note - 36
                : (int) JsonStepParser.extractNumField(spec, "pad", i);
        String uuidArg = JsonStepParser.extractStringField(spec, "uuid");
        String uuid = (uuidArg != null && !uuidArg.isBlank())
                ? uuidArg
                : (name != null ? BUILTIN_UUIDS.get(name.toLowerCase().trim()) : null);

        if (padIdx < 0 || padIdx >= DRUM_PAD_COUNT || uuid == null) {
            host.println("[BitwigStep] Pad " + padIdx + " übersprungen (name="
                    + name + ", kein UUID-Treffer)");
            fillDrumPads(src, track, padSpecs, i + 1, loaded);
            return;
        }
        try {
            Channel pad = (Channel) drumPadBank.getItemAt(padIdx);
            pad.endOfDeviceChainInsertionPoint().insertBitwigDevice(UUID.fromString(uuid));
            host.println("[BitwigStep] Pad " + padIdx + " ← " + name);
        } catch (Exception e) {
            host.println("[BitwigStep] Pad " + padIdx + " Fehler: " + e.getMessage());
        }
        final int nextLoaded = loaded + 1;
        host.scheduleTask(() -> fillDrumPads(src, track, padSpecs, i + 1, nextLoaded), 250);
    }

    private void execWriteNotes(OscConnection src, String args) {
        int track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        int slot = Math.max(0, (int) JsonStepParser.extractNumField(args, "slot", 0));
        int length = Math.max(1, (int) JsonStepParser.extractNumField(args, "length_beats", 8));
        String notes = JsonStepParser.extractArray(args, "notes");
        // append=true → bestehende Noten behalten (Chunk-Modus)
        boolean append = JsonStepParser.extractNumField(args, "append", 0) > 0.5;

        // Track explizit selektieren — cursorTrack folgt selectInMixer(), aber die
        // Bitwig-Cursor-Sync braucht mehrere UI-Frames. Wir geben ihr genug Zeit
        // BEVOR wir auf cursorClip schreiben (sonst landen die Noten im Clip von
        // Track 1, weil cursorTrack noch dort steht).
        Channel selected = channel(track);
        selected.selectInMixer();

        final int fslot = slot;
        final int flen = length;
        final String fn = notes;
        final boolean fappend = append;
        final int ftrack = track;
        host.scheduleTask(() -> {
            // Verifizieren: ist cursorTrack jetzt wirklich auf dem Ziel-Track?
            // Falls Name leer/anders → nochmal selektieren und länger warten.
            String currentName = cursorTrack.name().get();
            String targetName = selected.name().get();
            if (currentName == null || targetName == null || !currentName.equals(targetName)) {
                selected.selectInMixer();
                host.scheduleTask(() -> writeNotesNow(src, fslot, flen, fn, fappend), 200);
            } else {
                writeNotesNow(src, fslot, flen, fn, fappend);
            }
        }, 250);
    }

    private void writeNotesNow(OscConnection src, int slot, int length, String notesJson, boolean append) {
        if (!append) {
            clipSlotBank.createEmptyClip(slot, length);
        }
        clipSlotBank.select(slot);
        host.scheduleTask(() -> {
            cursorClip.setStepSize(0.25);
            if (!append) {
                cursorClip.clearSteps();
            }
            int written = 0;
            if (notesJson != null && !notesJson.isBlank()) {
                try {
                    written = parseAndWriteNoteBatch(notesJson);
                } catch (Exception e) {
                    host.println("[BitwigStep] Batch-Fehler: " + e.getMessage());
                }
            }
            String tn = cursorTrack.name().get();
            if (tn != null && !tn.isEmpty())
                noteCountMap.merge(tn, written, Integer::sum);
            host.println("[BitwigStep] " + written + " Noten → '" + tn + "'" + (append ? " [append]" : ""));
            stepDone(src, "write_notes");
        }, 200);
    }

    // ── Hilfe ────────────────────────────────────────────────────────────────

    /**
     * Liest Parameter der aktuellen Remote-Controls-Seite und navigiert
     * rekursiv zur nächsten Seite via scheduleTask bis alle Seiten gelesen sind.
     * Sendet am Ende /agent/track/params/all/response.
     */
    private void collectPageAndNext(StringBuilder sb, int[] pagesDone,
            int pagesToScan, String[] pnames,
            int trackIdx, String devName) {
        // Aktuelle Seite lesen
        String pageName = (pnames != null && pagesDone[0] < pnames.length)
                ? pnames[pagesDone[0]]
                : "Page " + pagesDone[0];
        if (pagesDone[0] > 0)
            sb.append(",");
        sb.append("{\"page\":").append(pagesDone[0]);
        sb.append(",\"name\":\"").append(jsonEsc(pageName)).append("\"");
        sb.append(",\"params\":[");
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            if (i > 0)
                sb.append(",");
            String pn = remoteControls.getParameter(i).name().get();
            double pv = remoteControls.getParameter(i).value().get();
            sb.append("{\"name\":\"").append(jsonEsc(pn != null ? pn : "")).append("\"");
            sb.append(",\"value\":").append(String.format(java.util.Locale.US, "%.4f", pv)).append("}");
        }
        sb.append("]}");
        pagesDone[0]++;

        if (pagesDone[0] < pagesToScan) {
            // Zur nächsten Seite navigieren und nach Delay weiterlesen
            remoteControls.selectNextPage(false);
            host.scheduleTask(() -> collectPageAndNext(sb, pagesDone, pagesToScan, pnames, trackIdx, devName), 250);
        } else {
            // Alle Seiten gelesen — Antwort senden
            sb.append("],\"total_pages\":").append(pagesToScan).append("}");
            sendReply("/agent/track/params/all/response", trackIdx, sb.toString());
            host.println("[BitwigStep] /agent/track/params/all → " + pagesToScan + " Seiten für Track " + trackIdx);
        }
    }

    private static String jsonEsc(String s) {
        if (s == null)
            return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "");
    }

    private Channel channel(int trackIndex) {
        return (Channel) trackBank.getItemAt(Math.max(0, Math.min(TRACK_BANK_SIZE - 1, trackIndex - 1)));
    }

    private void sendReply(String address, Object... args) {
        if (replyV4 != null) {
            try {
                replyV4.sendMessage(address, args);
            } catch (Exception e) {
                host.println("[BitwigStep] Reply V4 Fehler: " + e.getMessage());
            }
        }
        if (replyLocalhost != null) {
            try {
                replyLocalhost.sendMessage(address, args);
            } catch (Exception e) {
                /* lokaler Fehler OK */ }
        }
    }

    private int parseAndWriteNoteBatch(String json) {
        int count = 0;
        String stripped = json.replace("[", "").replace("]", "");
        for (String entry : stripped.split("\\},\\s*\\{")) {
            entry = entry.replace("{", "").replace("}", "").trim();
            if (entry.isBlank())
                continue;
            Map<String, Double> f = JsonStepParser.parseSimpleJsonObject(entry);
            double stepBeat = f.getOrDefault("step", 0.0);
            int step = (int) Math.round(stepBeat / 0.25);
            int pitch = f.getOrDefault("pitch", 60.0).intValue();
            // "velocity" 0-127 (Modell-Format) oder "vel" 0.0-1.0 (Legacy)
            double velRaw = f.containsKey("velocity") ? f.get("velocity") : f.getOrDefault("vel", 0.8) * 127.0;
            // "duration" in Beats (Modell-Format) oder "dur" in Beats (Legacy)
            float dur = f.containsKey("duration") ? f.get("duration").floatValue()
                                                   : f.getOrDefault("dur", 0.25).floatValue();
            if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch > 127 || dur <= 0)
                continue;
            int velInt = Math.max(1, Math.min(127, (int) velRaw));
            cursorClip.setStep(0, step, pitch, velInt, (double) dur);
            count++;
        }
        return count;
    }

    // ── flush — Browser-Katalog + Device-Navigation ───────────────────────────

    @Override
    public void flush() {
        // Browser-Katalog befüllen
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (item.exists().get()) {
                String n = item.name().get();
                if (n != null && !n.isBlank())
                    deviceCatalog.put(n.toLowerCase().trim(), i);
            }
        }

        // Parameter-Katalog der aktuellen Device-Seite
        paramCatalog.clear();
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            String n = remoteControls.getParameter(i).name().get();
            if (n != null && !n.isBlank())
                paramCatalog.put(n.toLowerCase().trim(), i);
        }

        // Warten und dann Browser navigieren (non-UUID Devices)
        if (loadTarget == null)
            return;
        if (loadWaitLeft > 0) {
            loadWaitLeft--;
            return;
        }

        String key = loadTarget;

        // ── Phase 0: aktuellen Tab ohne Filter scannen ───────────────────────
        if (loadLocPhase == 0) {
            // Debug: locationBank-Inhalt beim ersten Scan loggen
            StringBuilder locLog = new StringBuilder("[BitwigStep] locationBank: ");
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) {
                    locLog.append("[").append(i).append("=END]");
                    break;
                }
                locLog.append("[").append(i).append("=").append(li.name().get()).append("]");
            }
            host.println(locLog.toString());
            for (int i = 0; i < BROWSER_SCAN; i++) {
                BrowserItem item = resultBank.getItem(i);
                if (!item.exists().get())
                    break;
                String name = item.name().get();
                if (name != null && name.toLowerCase().contains(key)) {
                    loadTarget = null;
                    loadLocPhase = 0;
                    popupBrowser.selectFirstFile();
                    for (int j = 0; j < i; j++)
                        popupBrowser.selectNextFile();
                    popupBrowser.commit();
                    host.println("[BitwigStep] Browser geladen (Phase 0): " + name);
                    return;
                }
            }
            // Nicht gefunden → "Plug-ins" Parent-Location auswählen (expandiert Baum)
            boolean found = false;
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem item = locationBank.getItem(i);
                if (!item.exists().get())
                    break;
                String n = item.name().get();
                if (n != null && n.toLowerCase().contains("plug-in")) {
                    item.isSelected().set(true);
                    found = true;
                    host.println("[BitwigStep] Loc Phase 1 (parent): " + n);
                    break;
                }
            }
            if (found) {
                loadLocPhase = 1;
                loadWaitLeft = 5; // warten bis Baum expandiert
                return;
            }
            // Kein Plug-ins-Item → Diagnostik in Fehlermeldung kodieren
            StringBuilder locDiag = new StringBuilder();
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) {
                    locDiag.append("END@").append(i);
                    break;
                }
                String n = li.name().get();
                locDiag.append(i).append(":").append(n != null ? n.replace(":", "_") : "null").append("|");
            }
            loadTarget = null;
            loadLocPhase = 0;
            OscConnection s1 = pendingStepSrc;
            String t1 = pendingStepType;
            pendingStepSrc = null;
            pendingStepType = null;
            popupBrowser.cancel();
            if (s1 != null)
                stepDone(s1, "error:" + t1 + ":loc=[" + locDiag + "]:" + key);
            return;
        }

        // ── Phase 1: "Plug-ins" gewählt, jetzt VST-Child wählen ─────────────
        if (loadLocPhase == 1) {
            // Debug: locationBank nach Baum-Expansion
            StringBuilder locLog1 = new StringBuilder("[BitwigStep] locationBank Phase1: ");
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) {
                    locLog1.append("[").append(i).append("=END]");
                    break;
                }
                locLog1.append("[").append(i).append("=").append(li.name().get()).append("]");
            }
            host.println(locLog1.toString());
            // Suche "vst" im locationBank (jetzt sollte "My VST 3 Plug-ins" sichtbar sein)
            boolean found = false;
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem item = locationBank.getItem(i);
                if (!item.exists().get())
                    break;
                String n = item.name().get();
                if (n != null && n.toLowerCase().contains("vst")) {
                    item.isSelected().set(true);
                    found = true;
                    host.println("[BitwigStep] Loc Phase 2 (vst child): " + n);
                    break;
                }
            }
            if (found) {
                loadLocPhase = 2;
                loadWaitLeft = 5; // warten bis Ergebnisse geladen
                return;
            }
            // Kein VST-Child gefunden → abbrechen
            loadTarget = null;
            loadLocPhase = 0;
            OscConnection s2 = pendingStepSrc;
            String t2 = pendingStepType;
            pendingStepSrc = null;
            pendingStepType = null;
            popupBrowser.cancel();
            if (s2 != null)
                stepDone(s2, "error:" + t2 + ":vst_loc_not_found:" + key);
            return;
        }

        // ── Phase 2: VST-Child gewählt, Ergebnisse scannen ──────────────────
        loadTarget = null;
        loadLocPhase = 0;
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (!item.exists().get())
                break;
            String name = item.name().get();
            if (name != null && name.toLowerCase().contains(key)) {
                popupBrowser.selectFirstFile();
                for (int j = 0; j < i; j++)
                    popupBrowser.selectNextFile();
                popupBrowser.commit();
                host.println("[BitwigStep] Browser geladen (VST-Filter): " + name);
                return;
            }
        }
        // Auch mit VST-Filter nicht gefunden
        OscConnection s3 = pendingStepSrc;
        String t3 = pendingStepType;
        pendingStepSrc = null;
        pendingStepType = null;
        popupBrowser.cancel();
        host.println("[BitwigStep] '" + key + "' auch mit VST-Filter nicht gefunden.");
        if (s3 != null)
            stepDone(s3, "error:" + t3 + ":not_found:" + key);
    }

    @Override
    public void exit() {
        host.showPopupNotification("Bitwig Step Plugin beendet.");
    }
}
