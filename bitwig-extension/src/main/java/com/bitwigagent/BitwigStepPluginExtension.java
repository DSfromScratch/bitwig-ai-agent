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

    private static final int OSC_IN          = 8002;
    private static final int OSC_REPLY       = 9002;
    private static final int TRACK_BANK_SIZE = 16;
    private static final int MAX_SENDS       = 8;
    private static final int SLOT_BANK_SIZE  = 8;
    private static final int CLIP_STEPS      = 512;
    private static final int REMOTE_PARAMS   = 8;
    private static final int BROWSER_SCAN    = 128;
    private static final int MAX_DEVICES_PER_TRACK = 8;

    // ── Bitwig API ────────────────────────────────────────────────────────────

    private ControllerHost               host;
    private Transport                    transport;
    private TrackBank                    trackBank;
    private CursorTrack                  cursorTrack;
    private CursorDevice                 cursorDevice;
    private PopupBrowser                 popupBrowser;
    private Application                  application;
    private CursorRemoteControlsPage     remoteControls;
    private ClipLauncherSlotBank         clipSlotBank;
    private CursorClip                   cursorClip;
    private BrowserItemBank              resultBank;

    // ── OSC Reply ─────────────────────────────────────────────────────────────

    private OscConnection        replyV4;
    private OscConnection        replyLocalhost;
    private SettableStringValue  agentHost;

    // ── State Machine ─────────────────────────────────────────────────────────

    private final java.util.LinkedList<String[]> stepQueue = new java.util.LinkedList<>();
    private volatile boolean        stepExecuting   = false;
    private volatile OscConnection  pendingStepSrc  = null;
    private volatile String         pendingStepType = null; // "load_instrument" | "append_effect"

    // ── Browser / Catalog ────────────────────────────────────────────────────

    private final Map<String, Integer> deviceCatalog   = new HashMap<>();
    private BrowserFilterItemBank      locationBank;
    private BrowserFilterItemBank      deviceTypeBank;   // "Art"-Filter (Devices / Plug-ins)
    private static final int           LOC_BANK_SIZE   = 16;
    private volatile String            loadTarget    = null;
    private volatile int               loadWaitLeft  = 0;
    // 0=kein Filter, 1="Plug-ins" gewählt (warte auf Baum-Expansion), 2=VST-Child gewählt (warte auf Ergebnisse)
    private volatile int               loadLocPhase  = 0;

    // ── Note + Param Catalogs ────────────────────────────────────────────────

    private final Map<String, Integer> noteCountMap = new HashMap<>();
    private final Map<String, Integer> paramCatalog = new HashMap<>();

    // ── MIDI Clip Note Collection ─────────────────────────────────────────────

    private volatile boolean            collectingClipNotes = false;
    private final java.util.concurrent.CopyOnWriteArrayList<String> clipNoteBuf
        = new java.util.concurrent.CopyOnWriteArrayList<>();

    // ── Device Banks (pro Track, für Project-Scan) ────────────────────────────

    private DeviceBank[]  trackDeviceBanks;

    // ── Konstante für Sub-Track Limit ─────────────────────────────────────────

    private static final int MAX_SUB_TRACKS = 8;

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

        transport    = host.createTransport();
        trackBank    = host.createMainTrackBank(TRACK_BANK_SIZE, MAX_SENDS, SLOT_BANK_SIZE);
        cursorTrack  = host.createCursorTrack("step-cursor", "Step Cursor", 0, SLOT_BANK_SIZE, true);
        cursorDevice = cursorTrack.createCursorDevice();
        popupBrowser = host.createPopupBrowser();
        application  = host.createApplication();
        remoteControls = cursorDevice.createCursorRemoteControlsPage(REMOTE_PARAMS);
        clipSlotBank = cursorTrack.clipLauncherSlotBank();
        cursorClip   = cursorTrack.createLauncherCursorClip(CLIP_STEPS, 128);
        cursorClip.setStepSize(0.25);
        resultBank     = popupBrowser.resultsColumn().createItemBank(BROWSER_SCAN);
        locationBank   = popupBrowser.locationColumn().createItemBank(LOC_BANK_SIZE);
        deviceTypeBank = popupBrowser.deviceTypeColumn().createItemBank(LOC_BANK_SIZE);

        // Mark interested — Track-Namen + Device-Banks für Project-Scan
        trackDeviceBanks = new DeviceBank[TRACK_BANK_SIZE];
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Channel t = (Channel) trackBank.getItemAt(i);
            t.name().markInterested();
            t.exists().markInterested();
            Track tr = (Track) trackBank.getItemAt(i);
            DeviceBank db = tr.createDeviceBank(MAX_DEVICES_PER_TRACK);
            trackDeviceBanks[i] = db;
            for (int j = 0; j < MAX_DEVICES_PER_TRACK; j++) {
                db.getDevice(j).name().markInterested();
                db.getDevice(j).exists().markInterested();
            }
        }

        // isGroup markieren
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Track tr = (Track) trackBank.getItemAt(i);
            tr.isGroup().markInterested();
        }

        // MIDI Clip Notes: Step-Data-Observer (state: 0=leer, 1=Note, 2=Sustain)
        cursorClip.addStepDataObserver((step, pitch, state) -> {
            if (collectingClipNotes && state == 1) {
                clipNoteBuf.add(step + "," + pitch);
            }
        });
        cursorClip.getLoopLength().markInterested();
        cursorTrack.name().markInterested();
        cursorDevice.name().markInterested();
        cursorDevice.exists().markInterested();
        cursorDevice.isWindowOpen().markInterested();
        popupBrowser.exists().markInterested();
        popupBrowser.selectedContentTypeIndex().markInterested();
        popupBrowser.contentTypeNames().markInterested();

        // Konfigurierbarer Reply-Host (Bitwig → Settings → BitwigStepPlugin)
        agentHost = host.getPreferences()
                        .getStringSetting("Agent Host (IP)", "Network", 64, "127.0.0.1");
        agentHost.markInterested();
        transport.tempo().markInterested();
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
                        String        typ = pendingStepType != null ? pendingStepType : "load_instrument";
                        pendingStepSrc  = null;
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
        OscModule       osc   = host.getOscModule();
        OscAddressSpace space = osc.createAddressSpace();

        // Reply-Verbindungen zu Python (Port 9002)
        String ah = (agentHost != null && !agentHost.get().isBlank()) ? agentHost.get() : "127.0.0.1";
        replyV4        = osc.connectToUdpServer(ah,          OSC_REPLY, space);
        replyLocalhost = osc.connectToUdpServer("localhost", OSC_REPLY, space);
        host.println("[BitwigStep] Reply → " + ah + ":" + OSC_REPLY);

        // ── Ping/Pong ──────────────────────────────────────────────────────
        space.registerMethod("/ping", "*", "Ping",
            (src, msg) -> {
                sendReply("/pong", 1);
                host.println("[BitwigStep] Pong");
            });

        // ── Track-Zustand abfragen ─────────────────────────────────────────
        space.registerMethod("/agent/track/count", "*", "Track count + names",
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
                sendReply("/agent/track/count/response", count, names.toString());
            });

        // ── Tracks löschen ────────────────────────────────────────────────
        space.registerMethod("/agent/tracks/clear", "*", "Clear all tracks",
            (src, msg) -> {
                int n = 0;
                for (int i = 0; i < TRACK_BANK_SIZE; i++)
                    if (trackBank.getItemAt(i).exists().get()) n++;
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
                // Temp-Track anlegen → leerer Instrument-Track → Instrument-Browser-Kontext garantiert
                application.createInstrumentTrack(-1);
                host.scheduleTask(() -> {
                    // Browser auf leerem Track öffnen (browseToInsertBeforeDevice = Instrument-Kontext)
                    popupBrowser.cancel();
                    boolean hasDevice = cursorDevice.exists().get();
                    if (hasDevice) cursorDevice.browseToReplaceDevice();
                    else           cursorDevice.browseToInsertBeforeDevice();

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
                                if (!item.exists().get()) break;
                                String n = item.name().get();
                                if (n == null || n.isBlank()) continue;
                                count++;
                                if (names.length() > 0) names.append(",");
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
                    if (sb.length() > 0) sb.append(";");
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
                    if (!first) sb.append(",");
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
        space.registerMethod("/agent/project/scan", "*", "Scan all tracks and devices",
            (src, msg) -> {
                StringBuilder sb = new StringBuilder("{\"tracks\":[");
                int trackCount = 0;
                double tempo = transport.tempo().get();
                for (int i = 0; i < TRACK_BANK_SIZE; i++) {
                    Channel t = (Channel) trackBank.getItemAt(i);
                    if (!t.exists().get()) continue;
                    if (trackCount > 0) sb.append(",");
                    sb.append("{\"idx\":").append(i + 1);
                    sb.append(",\"name\":\"").append(jsonEsc(t.name().get())).append("\"");
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
                    if (!tr.exists().get()) continue;
                    if (!tr.isGroup().get()) continue;
                    if (groupCount > 0) sb.append(",");
                    sb.append("{\"idx\":").append(i + 1);
                    sb.append(",\"name\":\"").append(jsonEsc(tr.name().get())).append("\"}");
                    groupCount++;
                }
                sb.append("],\"total_groups\":").append(groupCount).append("}");
                sendReply("/agent/project/hierarchy/response", sb.toString());
                host.println("[BitwigStep] /agent/project/hierarchy → " + groupCount + " Groups");
            });

        // ── Szenen-Slots des Cursor-Tracks ────────────────────────────────
        space.registerMethod("/agent/project/scenes", "*", "Scene slots from cursor track",
            (src, msg) -> {
                StringBuilder sb = new StringBuilder("{\"scenes\":[");
                int count = 0;
                for (int i = 0; i < SLOT_BANK_SIZE; i++) {
                    if (count > 0) sb.append(",");
                    sb.append("{\"idx\":").append(i + 1).append("}");
                    count++;
                }
                sb.append("],\"total\":").append(count).append("}");
                sendReply("/agent/project/scenes/response", sb.toString());
            });

        // ── MIDI Clip Notes aus dem ersten Launcher-Clip ──────────────────
        space.registerMethod("/agent/track/clip/notes", "*", "Read MIDI notes from first clip",
            (src, msg) -> {
                int trackIdx = 1;
                try {
                    String raw = JsonStepParser.argStr(msg, 0);
                    if (raw != null) trackIdx = (int) Double.parseDouble(raw);
                } catch (Exception e) {}
                final int ti = Math.max(1, Math.min(TRACK_BANK_SIZE, trackIdx));

                Track tr = (Track) trackBank.getItemAt(ti - 1);
                if (!tr.exists().get()) {
                    sendReply("/agent/track/clip/notes/response", ti, "{}");
                    return;
                }
                tr.selectInMixer();

                host.scheduleTask(() -> {
                    clipNoteBuf.clear();
                    collectingClipNotes = true;
                    double loopLen = cursorClip.getLoopLength().get();
                    // Observer durch scrollToStep(0) triggern
                    cursorClip.scrollToStep(0);

                    host.scheduleTask(() -> {
                        collectingClipNotes = false;
                        StringBuilder sb = new StringBuilder("{\"track\":");
                        sb.append(ti);
                        sb.append(",\"loop_beats\":").append(
                            String.format(java.util.Locale.US, "%.2f", loopLen));
                        sb.append(",\"notes\":[");
                        java.util.List<String> snapshot = new java.util.ArrayList<>(clipNoteBuf);
                        for (int i = 0; i < snapshot.size(); i++) {
                            if (i > 0) sb.append(",");
                            String[] p = snapshot.get(i).split(",");
                            sb.append("{\"step\":").append(p[0]);
                            sb.append(",\"pitch\":").append(p[1]).append("}");
                        }
                        sb.append("],\"count\":").append(snapshot.size()).append("}");
                        sendReply("/agent/track/clip/notes/response", ti, sb.toString());
                        host.println("[BitwigStep] /clip/notes → " + snapshot.size()
                            + " Noten, Track " + ti);
                    }, 600);
                }, 400);
            });

        // ── Track-Parameter: Remote Controls des ausgewählten Geräts ─────
        space.registerMethod("/agent/track/params", "*", "Remote control params for track",
            (src, msg) -> {
                int trackIdx = 1;
                try {
                    String raw = JsonStepParser.argStr(msg, 0);
                    if (raw != null) trackIdx = (int) Double.parseDouble(raw);
                } catch (Exception e) {}
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
                        if (i > 0) sb.append(",");
                        String pn = remoteControls.getParameter(i).name().get();
                        double pv = remoteControls.getParameter(i).value().get();
                        sb.append("{\"name\":\"").append(jsonEsc(pn != null ? pn : "")).append("\"");
                        sb.append(",\"value\":").append(String.format(java.util.Locale.US, "%.4f", pv)).append("}");
                    }
                    sb.append("]}");
                    sendReply("/agent/track/params/response", finalTi, sb.toString());
                }, 450);
            });

        // ── Device-Fenster öffnen (für Grid-Screenshot) ───────────────────
        space.registerMethod("/agent/track/device/open", "*", "Open device editor for track",
            (src, msg) -> {
                int trackIdx = 1;
                try {
                    String raw = JsonStepParser.argStr(msg, 0);
                    if (raw != null) trackIdx = (int) Double.parseDouble(raw);
                } catch (Exception e) {}
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
                    if (raw != null) trackIdx = (int) Double.parseDouble(raw);
                } catch (Exception e) {}
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
                        final int[] pagesDone = {0};
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
                        stepQueue.add(new String[]{json});
                        host.println("[BitwigStep] Step eingereiht: " + json.substring(0, Math.min(60, json.length())));
                        return;
                    }
                    stepExecuting = true;
                }
                executeStep(src, json);
            });

        space.registerDefaultMethod((src, msg) ->
            host.println("[BitwigStep] Unbekannt: " + msg.getAddressPattern()));

        osc.createUdpServer(OSC_IN, space);
        host.println("[BitwigStep] OSC auf UDP:" + OSC_IN);
    }

    // ── Step Dispatcher ───────────────────────────────────────────────────────

    private void executeStep(OscConnection src, String json) {
        String type = JsonStepParser.extractStringField(json, "type");
        String args = JsonStepParser.extractNestedObject(json, "args");
        if (args == null) args = "{}";
        host.println("[BitwigStep] exec: " + type);

        // Precondition: Steps die einen existierenden Track benötigen
        switch (type != null ? type : "") {
            case "load_instrument":
            case "append_effect":
            case "write_notes":
            case "set_param":
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
            case "set_tempo"       -> execSetTempo(src, args);
            case "add_track"       -> execAddTrack(src, args);
            case "select_track"    -> execSelectTrack(src, args);
            case "load_instrument" -> execLoadInstrument(src, args);
            case "append_effect"   -> execAppendEffect(src, args);
            case "set_param"       -> execSetParam(src, args);
            case "set_param_named" -> execSetParamNamed(src, args);
            case "write_notes"     -> execWriteNotes(src, args);
            case "clear_tracks"    -> execClearTracks(src);
            case "play"            -> { transport.play();  stepDone(src, "play"); }
            case "stop"            -> { transport.stop();  stepDone(src, "stop"); }
            default                -> stepDone(src, "error:unknown:" + type);
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
        else
            application.createInstrumentTrack(-1);
        host.scheduleTask(() -> stepDone(src, "add_track"), 80);
    }

    private void execClearTracks(OscConnection src) {
        // Zuerst alle offenen Plugin-Fenster schließen
        cursorDevice.isWindowOpen().set(false);
        int n = 0;
        for (int i = 0; i < TRACK_BANK_SIZE; i++)
            if (trackBank.getItemAt(i).exists().get()) n++;
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
            if (ch.exists().get()) ch.selectInMixer();
        }
        host.scheduleTask(() -> stepDone(src, "select_track"), 40);
    }

    private void execLoadInstrument(OscConnection src, String args) {
        int    track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        String name  = JsonStepParser.extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:load_instrument:no_name");
            return;
        }
        String key          = name.toLowerCase().trim();
        String uuidFromArgs = JsonStepParser.extractStringField(args, "uuid");
        String uuid         = (uuidFromArgs != null && !uuidFromArgs.isBlank())
                              ? uuidFromArgs : BUILTIN_UUIDS.get(key);

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
            pendingStepSrc  = src;
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
                                if (!item.exists().get()) { resLog.append("END@").append(i); break; }
                                String n = item.name().get();
                                if (i < 20 && n != null) resLog.append(i).append("=").append(n).append("|");
                                if (n != null) {
                                    // Normalisierter Vergleich: Bindestriche + Leerzeichen ignorieren
                                    String normN = n.toLowerCase()
                                                    .replace("-", "").replace(" ", "").replace("_", "");
                                    if (normN.contains(normKey)) {
                                        foundIdx  = i;
                                        foundName = n;
                                        break;
                                    }
                                }
                            }
                            host.println(resLog.toString());

                            if (foundIdx >= 0) {
                                // Direktauswahl via isSelected() — kein Cursor-Offset-Problem
                                resultBank.getItem(foundIdx).isSelected().set(true);
                                final int fi = foundIdx; final String fn = foundName;
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
                                pendingStepSrc  = null; pendingStepType = null;
                                popupBrowser.cancel();
                                host.println("[BitwigStep] '" + key + "' nicht gefunden in Ergebnissen");
                                if (ts != null) stepDone(ts, "error:load_instrument:not_found:" + key);
                            }
                        }, 1000);
                }, 1000);

                // Sicherheits-Timeout 15s — nur für DIESEN Step, nicht für spätere
                final OscConnection timeoutSrc = src;
                host.scheduleTask(() -> {
                    if (pendingStepSrc == timeoutSrc) {  // noch unser Step?
                        pendingStepSrc  = null; pendingStepType = null;
                        popupBrowser.cancel();
                        host.println("[BitwigStep] browser_timeout: " + key);
                        stepDone(timeoutSrc, "error:browser_timeout:" + key);
                    }
                }, 15000);
            }, 40);
        }
    }

    private void execAppendEffect(OscConnection src, String args) {
        int    track = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        String name  = JsonStepParser.extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:append_effect:no_name");
            return;
        }
        String key          = name.toLowerCase().trim();
        String uuidFromArgs = JsonStepParser.extractStringField(args, "uuid");
        String uuid         = (uuidFromArgs != null && !uuidFromArgs.isBlank())
                              ? uuidFromArgs : BUILTIN_UUIDS.get(key);

        channel(track).selectInMixer();

        if (uuid != null) {
            final String uuidStr = uuid;
            host.scheduleTask(() -> {
                try {
                    cursorDevice.afterDeviceInsertionPoint()
                        .insertBitwigDevice(UUID.fromString(uuidStr));
                    host.println("[BitwigStep] UUID-Append: " + name);
                } catch (Exception e) {
                    host.println("[BitwigStep] UUID-Fehler " + name + ": " + e.getMessage());
                }
                stepDone(src, "append_effect");
            }, 40);
        } else {
            host.scheduleTask(() -> {
                popupBrowser.cancel();
                cursorDevice.browseToInsertAfterDevice();
                pendingStepSrc  = src;
                pendingStepType = "append_effect";
                loadTarget      = key;
                loadWaitLeft    = 6;
                host.scheduleTask(() -> {
                    if (pendingStepSrc != null) {
                        host.println("[BitwigStep] Browser-Timeout (Effekt): " + name);
                        OscConnection ts = pendingStepSrc;
                        pendingStepSrc  = null;
                        pendingStepType = null;
                        loadTarget      = null;
                        popupBrowser.cancel();
                        if (ts != null) stepDone(ts, "error:browser_timeout:" + key);
                    }
                }, 10000);
            }, 40);
        }
    }

    private void execSetParam(OscConnection src, String args) {
        int    track = (int) JsonStepParser.extractNumField(args, "track_index", 0);
        int    idx   = Math.max(0, Math.min(7, (int) JsonStepParser.extractNumField(args, "index", 1) - 1));
        double val   = JsonStepParser.extractNumField(args, "value", 0.0);

        if (track > 0) channel(track).selectInMixer();
        long delay = track > 0 ? 40L : 0L;
        final int fi = idx; final double fv = val;
        host.scheduleTask(() -> {
            remoteControls.getParameter(fi).value().set(fv);
            stepDone(src, "set_param");
        }, delay);
    }

    private void execSetParamNamed(OscConnection src, String args) {
        int    track = (int) JsonStepParser.extractNumField(args, "track_index", 0);
        String pname = JsonStepParser.extractStringField(args, "param_name");
        double val   = JsonStepParser.extractNumField(args, "value", 0.0);

        if (track > 0) channel(track).selectInMixer();
        long delay = track > 0 ? 40L : 0L;
        final String fp = pname; final double fv = val;
        host.scheduleTask(() -> {
            if (fp != null) {
                Integer pi = paramCatalog.get(fp.toLowerCase().trim());
                if (pi != null) remoteControls.getParameter(pi).value().set(fv);
                else host.println("[BitwigStep] Param nicht gefunden: " + fp);
            }
            stepDone(src, "set_param_named");
        }, delay);
    }

    private void execWriteNotes(OscConnection src, String args) {
        int    track  = Math.max(1, (int) JsonStepParser.extractNumField(args, "track_index", 1));
        int    slot   = Math.max(0, (int) JsonStepParser.extractNumField(args, "slot",         0));
        int    length = Math.max(1, (int) JsonStepParser.extractNumField(args, "length_beats",  8));
        String notes  = JsonStepParser.extractArray(args, "notes");

        channel(track).selectInMixer();
        final int fslot = slot; final int flen = length; final String fn = notes;
        host.scheduleTask(() -> {
            clipSlotBank.createEmptyClip(fslot, flen);
            clipSlotBank.select(fslot);
            host.scheduleTask(() -> {
                cursorClip.setStepSize(0.25);
                cursorClip.clearSteps();
                int written = 0;
                if (fn != null && !fn.isBlank()) {
                    try { written = parseAndWriteNoteBatch(fn); }
                    catch (Exception e) { host.println("[BitwigStep] Batch-Fehler: " + e.getMessage()); }
                }
                String tn = cursorTrack.name().get();
                if (tn != null && !tn.isEmpty())
                    noteCountMap.merge(tn, written, Integer::sum);
                host.println("[BitwigStep] " + written + " Noten → '" + tn + "'");
                stepDone(src, "write_notes");
            }, 150);
        }, 40);
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
                ? pnames[pagesDone[0]] : "Page " + pagesDone[0];
        if (pagesDone[0] > 0) sb.append(",");
        sb.append("{\"page\":").append(pagesDone[0]);
        sb.append(",\"name\":\"").append(jsonEsc(pageName)).append("\"");
        sb.append(",\"params\":[");
        for (int i = 0; i < REMOTE_PARAMS; i++) {
            if (i > 0) sb.append(",");
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
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "");
    }

    private Channel channel(int trackIndex) {
        return (Channel) trackBank.getItemAt(Math.max(0, Math.min(TRACK_BANK_SIZE - 1, trackIndex - 1)));
    }

    private void sendReply(String address, Object... args) {
        if (replyV4 != null) {
            try { replyV4.sendMessage(address, args); }
            catch (Exception e) { host.println("[BitwigStep] Reply V4 Fehler: " + e.getMessage()); }
        }
        if (replyLocalhost != null) {
            try { replyLocalhost.sendMessage(address, args); }
            catch (Exception e) { /* lokaler Fehler OK */ }
        }
    }

    private int parseAndWriteNoteBatch(String json) {
        int count = 0;
        String stripped = json.replace("[", "").replace("]", "");
        for (String entry : stripped.split("\\},\\s*\\{")) {
            entry = entry.replace("{", "").replace("}", "").trim();
            if (entry.isBlank()) continue;
            Map<String, Double> f = JsonStepParser.parseSimpleJsonObject(entry);
            double stepBeat = f.getOrDefault("step",  0.0);
            int    step     = (int) Math.round(stepBeat / 0.25);
            int    pitch    = f.getOrDefault("pitch", 60.0).intValue();
            float  vel      = f.getOrDefault("vel",   0.8).floatValue();
            float  dur      = f.getOrDefault("dur",   0.25).floatValue();
            if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch > 127 || dur <= 0) continue;
            int velInt = Math.max(1, Math.min(127, (int) (vel * 127)));
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
        if (loadTarget == null) return;
        if (loadWaitLeft > 0) { loadWaitLeft--; return; }

        String key = loadTarget;

        // ── Phase 0: aktuellen Tab ohne Filter scannen ───────────────────────
        if (loadLocPhase == 0) {
            // Debug: locationBank-Inhalt beim ersten Scan loggen
            StringBuilder locLog = new StringBuilder("[BitwigStep] locationBank: ");
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) { locLog.append("[").append(i).append("=END]"); break; }
                locLog.append("[").append(i).append("=").append(li.name().get()).append("]");
            }
            host.println(locLog.toString());
            for (int i = 0; i < BROWSER_SCAN; i++) {
                BrowserItem item = resultBank.getItem(i);
                if (!item.exists().get()) break;
                String name = item.name().get();
                if (name != null && name.toLowerCase().contains(key)) {
                    loadTarget   = null;
                    loadLocPhase = 0;
                    popupBrowser.selectFirstFile();
                    for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                    popupBrowser.commit();
                    host.println("[BitwigStep] Browser geladen (Phase 0): " + name);
                    return;
                }
            }
            // Nicht gefunden → "Plug-ins" Parent-Location auswählen (expandiert Baum)
            boolean found = false;
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem item = locationBank.getItem(i);
                if (!item.exists().get()) break;
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
                loadWaitLeft = 5;   // warten bis Baum expandiert
                return;
            }
            // Kein Plug-ins-Item → Diagnostik in Fehlermeldung kodieren
            StringBuilder locDiag = new StringBuilder();
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) { locDiag.append("END@").append(i); break; }
                String n = li.name().get();
                locDiag.append(i).append(":").append(n != null ? n.replace(":", "_") : "null").append("|");
            }
            loadTarget   = null;
            loadLocPhase = 0;
            OscConnection s1 = pendingStepSrc; String t1 = pendingStepType;
            pendingStepSrc = null; pendingStepType = null;
            popupBrowser.cancel();
            if (s1 != null) stepDone(s1, "error:" + t1 + ":loc=[" + locDiag + "]:" + key);
            return;
        }

        // ── Phase 1: "Plug-ins" gewählt, jetzt VST-Child wählen ─────────────
        if (loadLocPhase == 1) {
            // Debug: locationBank nach Baum-Expansion
            StringBuilder locLog1 = new StringBuilder("[BitwigStep] locationBank Phase1: ");
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem li = locationBank.getItem(i);
                if (!li.exists().get()) { locLog1.append("[").append(i).append("=END]"); break; }
                locLog1.append("[").append(i).append("=").append(li.name().get()).append("]");
            }
            host.println(locLog1.toString());
            // Suche "vst" im locationBank (jetzt sollte "My VST 3 Plug-ins" sichtbar sein)
            boolean found = false;
            for (int i = 0; i < LOC_BANK_SIZE; i++) {
                BrowserItem item = locationBank.getItem(i);
                if (!item.exists().get()) break;
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
                loadWaitLeft = 5;   // warten bis Ergebnisse geladen
                return;
            }
            // Kein VST-Child gefunden → abbrechen
            loadTarget   = null;
            loadLocPhase = 0;
            OscConnection s2 = pendingStepSrc; String t2 = pendingStepType;
            pendingStepSrc = null; pendingStepType = null;
            popupBrowser.cancel();
            if (s2 != null) stepDone(s2, "error:" + t2 + ":vst_loc_not_found:" + key);
            return;
        }

        // ── Phase 2: VST-Child gewählt, Ergebnisse scannen ──────────────────
        loadTarget   = null;
        loadLocPhase = 0;
        for (int i = 0; i < BROWSER_SCAN; i++) {
            BrowserItem item = resultBank.getItem(i);
            if (!item.exists().get()) break;
            String name = item.name().get();
            if (name != null && name.toLowerCase().contains(key)) {
                popupBrowser.selectFirstFile();
                for (int j = 0; j < i; j++) popupBrowser.selectNextFile();
                popupBrowser.commit();
                host.println("[BitwigStep] Browser geladen (VST-Filter): " + name);
                return;
            }
        }
        // Auch mit VST-Filter nicht gefunden
        OscConnection s3 = pendingStepSrc; String t3 = pendingStepType;
        pendingStepSrc = null; pendingStepType = null;
        popupBrowser.cancel();
        host.println("[BitwigStep] '" + key + "' auch mit VST-Filter nicht gefunden.");
        if (s3 != null) stepDone(s3, "error:" + t3 + ":not_found:" + key);
    }

    @Override
    public void exit() {
        host.showPopupNotification("Bitwig Step Plugin beendet.");
    }
}
