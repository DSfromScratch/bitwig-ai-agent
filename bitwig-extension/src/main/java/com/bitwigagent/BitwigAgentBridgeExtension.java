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
    private SettableRangedValue  cfgBpm;
    private BrowserFilterItemBank    categoryBank;     // Kategorie-Spalte (linke Spalte)
    private BrowserFilterItemBank    smartCollBank;    // Smart-Collections
    private static final int         CAT_BANK_SIZE  = 64;
    private static final int         COLL_BANK_SIZE = 32;
    private volatile String          loadCollection = null;

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

    // 146 Bitwig Built-in Device UUIDs — direktes insertBitwigDevice() ohne Browser
    private static final Map<String, String> BUILTIN_UUIDS = new HashMap<>();
    static {
        BUILTIN_UUIDS.put("amp",                "41be8f3a-6d24-4442-9508-8548dbe62d47");
        BUILTIN_UUIDS.put("arpeggiator",        "4d407a2b-c91b-4e4c-9a89-c53c19fe6251");
        BUILTIN_UUIDS.put("audio mod",          "01c7c48f-40cd-40cd-8a9a-1f258f1cc7d5");
        BUILTIN_UUIDS.put("audio receiver",     "46b3e40a-629c-42c2-9e14-a1ccbcaa903b");
        BUILTIN_UUIDS.put("bend",               "6aec6e78-9c1e-4c0b-8a88-0c2c37890a1d");
        BUILTIN_UUIDS.put("bit-8",              "43875255-6f1f-4d54-a5ad-c45bff793477");
        BUILTIN_UUIDS.put("blur",               "72a3018d-788b-472c-b1d7-16419d00f4c6");
        BUILTIN_UUIDS.put("chain",              "03ec3a24-b3c9-4ba4-b6dc-855178d60de7");
        BUILTIN_UUIDS.put("channel filter",     "c5a1bb2d-a589-4fda-b3cf-911cfd6297be");
        BUILTIN_UUIDS.put("channel map",        "0f003fa3-adcc-4684-81f7-f0e11c09c5b4");
        BUILTIN_UUIDS.put("chorus",             "d275f9a6-0e4a-409c-9dc4-d74af90bc7ae");
        BUILTIN_UUIDS.put("chorus+",            "1b8f2226-c432-4a0a-9830-69bc76d1a276");
        BUILTIN_UUIDS.put("comb",               "20e18780-8438-48d3-b234-40dcbaa947b8");
        BUILTIN_UUIDS.put("compressor",         "2b1b4787-8d74-4138-877b-9197209eef0f");
        BUILTIN_UUIDS.put("compressor+",        "42b32cd2-6275-4ff1-970f-4fac71d15ad9");
        BUILTIN_UUIDS.put("convolution",        "528f7939-87c0-4997-8e71-6331d2eee388");
        BUILTIN_UUIDS.put("dc offset",          "ee445061-a0ee-4322-991a-b60212db04ed");
        BUILTIN_UUIDS.put("de-esser",           "8750db61-e9d3-4d0e-a610-e734006a64dc");
        BUILTIN_UUIDS.put("delay",              "2a7a7328-3f7a-4afb-95eb-5230c298bb90");
        BUILTIN_UUIDS.put("delay+",             "f2baa2a8-36c5-4a79-b1d9-a4e461c45ee9");
        BUILTIN_UUIDS.put("delay-1",            "2a7a7328-3f7a-4afb-95eb-5230c298bb90");
        BUILTIN_UUIDS.put("delay-2",            "71539d5d-1c7a-4dac-8f74-29e23b89b599");
        BUILTIN_UUIDS.put("delay-4",            "f95a0e18-5a8b-4f53-93ad-8be73fd668bd");
        BUILTIN_UUIDS.put("distortion",         "41b34699-8e5d-4534-a429-a67d488ba6ac");
        BUILTIN_UUIDS.put("dribble",            "d98f7ce5-564e-4b95-926a-4e7b50a251c6");
        BUILTIN_UUIDS.put("drum machine",       "8ea97e45-0255-40fd-bc7e-94419741e9d1");
        BUILTIN_UUIDS.put("dual pan",           "c94820f8-3779-438b-a85b-868e57b746cc");
        BUILTIN_UUIDS.put("dynamics",           "22e785a2-a187-41e9-a0f2-66343694014c");
        BUILTIN_UUIDS.put("echo",               "43c102c9-ce32-4dd8-b207-f0831733b17b");
        BUILTIN_UUIDS.put("eq+",                "e4815188-ba6f-4d14-bcfc-2dcb8f778ccb");
        BUILTIN_UUIDS.put("eq-2",               "01af068e-1e49-4777-a6e6-7f1dc679227a");
        BUILTIN_UUIDS.put("eq-5",               "227e2e3c-75d5-46f3-960d-8fb5529fe29f");
        BUILTIN_UUIDS.put("eq-dj",              "3cc1b71a-e22a-42cf-89f0-316475368fb3");
        BUILTIN_UUIDS.put("filter",             "4ccfc70e-59bd-4e97-a8a7-d8cdce88bf42");
        BUILTIN_UUIDS.put("filter+",            "6d621c1c-ab64-43b4-aea3-dad37e6f649c");
        BUILTIN_UUIDS.put("flanger",            "8393c436-b11b-4fee-85dd-b2ef0a2ed380");
        BUILTIN_UUIDS.put("flanger+",           "a99f8c3c-7813-4e6b-a18a-302c74286efc");
        BUILTIN_UUIDS.put("fm-4",               "7a0a94df-3aa4-4bb5-8e24-2511999871ad");
        BUILTIN_UUIDS.put("focus",              "42208fc5-02fd-42b4-9681-a8fadb46575f");
        BUILTIN_UUIDS.put("freq shifter",       "7ec87fdf-0bf8-42e7-b54b-5d8b68e330b1");
        BUILTIN_UUIDS.put("freq shifter+",      "eb28831d-2478-4918-bd51-bcc1ff4c7eed");
        BUILTIN_UUIDS.put("freq split",         "3f3c3200-e6aa-4578-8e06-f573ed65206e");
        BUILTIN_UUIDS.put("fx grid",            "a0cb2ec0-2464-461c-8165-296f98905539");
        BUILTIN_UUIDS.put("fx layer",           "96456481-4c52-423a-8485-4604b15d0183");
        BUILTIN_UUIDS.put("fx selector",        "8fd471db-15df-44c6-b497-4bb851d4fd46");
        BUILTIN_UUIDS.put("gate",               "556300ac-3a6e-4423-966a-5d5dde459a1b");
        BUILTIN_UUIDS.put("harmonic split",     "c90b6d52-898b-4dad-aa58-2c58add7c94f");
        BUILTIN_UUIDS.put("harmonize",          "ff299d28-d822-4686-ac0a-03c0ae69b32d");
        BUILTIN_UUIDS.put("humanize",           "f7b6f2a6-bfca-41ec-8646-b68e0f4cf12b");
        BUILTIN_UUIDS.put("hw cv instrument",   "c511bc17-9ebf-43de-a20c-4a9e40028fdf");
        BUILTIN_UUIDS.put("hw cv out",          "d0e71e2d-d491-4cce-a227-fbe118cc4e52");
        BUILTIN_UUIDS.put("hw clock out",       "a2b59797-2b25-4860-862d-6ab72393b4ca");
        BUILTIN_UUIDS.put("hw fx",              "29b93a99-eb3a-4b19-8c12-8b4391f5a1ea");
        BUILTIN_UUIDS.put("hw instrument",      "6a27aef7-bba5-4b0d-af98-7c192f84fbc2");
        BUILTIN_UUIDS.put("instrument layer",   "5024be2e-65d6-4d40-bbfe-8b2ea993c445");
        BUILTIN_UUIDS.put("instrument selector","9588fbcf-721a-438b-8555-97e4231f7d2c");
        BUILTIN_UUIDS.put("key filter",         "f14bacde-084c-4f14-8bdf-d8c4fda8b368");
        BUILTIN_UUIDS.put("key filter+",        "ad13588c-fe39-4bd0-8615-d56e495eb05d");
        BUILTIN_UUIDS.put("ladder",             "abfbbd63-8801-4bdb-a1ad-4b197f4d41e0");
        BUILTIN_UUIDS.put("latch",              "93c9d566-4cc9-4895-bf5b-475cab44eba9");
        BUILTIN_UUIDS.put("lfo mod",            "613dd120-9f55-4d24-97ac-f7902ffa7ce7");
        BUILTIN_UUIDS.put("limiter",            "8da7251e-2578-4bcc-b3c4-8f4ec2e115d0");
        BUILTIN_UUIDS.put("loud split",         "6e75a854-ceab-475b-94c5-75188ee998b8");
        BUILTIN_UUIDS.put("micro-pitch",        "4ac40334-99cc-43a3-b693-f3dc63211f0c");
        BUILTIN_UUIDS.put("mid-side split",     "a6c9b12f-45a5-43e3-b100-b74ecf77367b");
        BUILTIN_UUIDS.put("midi cc",            "a0b8f27a-128e-4f72-b9fc-a277060b87ee");
        BUILTIN_UUIDS.put("midi program change","429c7dcb-6863-48bc-becc-508463841e3b");
        BUILTIN_UUIDS.put("midi song select",   "754fdba1-2c16-494c-a47c-16f7a7ad9363");
        BUILTIN_UUIDS.put("multi-note",         "0a015261-7546-4f6d-9197-098a26ff2c20");
        BUILTIN_UUIDS.put("multiband fx-2",     "214857d6-b468-4257-9bc9-92f017af1782");
        BUILTIN_UUIDS.put("multiband fx-3",     "f97699d1-3b8e-4363-8ede-4994e276cc97");
        BUILTIN_UUIDS.put("note delay",         "9f3cc825-3284-4c5a-b51f-01219de13b7c");
        BUILTIN_UUIDS.put("note filter",        "ef7559c8-49ae-4657-95be-11abb896c969");
        BUILTIN_UUIDS.put("note grid",          "264d6f4e-5067-46c9-a4fa-a75a295d9e01");
        BUILTIN_UUIDS.put("note length",        "4c396eb6-953d-4de0-afaa-63276fc1150b");
        BUILTIN_UUIDS.put("note mod",           "1179be46-4d43-4a26-bb5f-430bc3fef9ba");
        BUILTIN_UUIDS.put("note receiver",      "c6153773-ed96-4cca-a767-5cf3d5dceacb");
        BUILTIN_UUIDS.put("note repeats",       "a68e0f1b-bcc6-45c2-b09e-8c8771f83e50");
        BUILTIN_UUIDS.put("note transpose",     "0815cd9e-3a31-4429-a268-dabd952a3b68");
        BUILTIN_UUIDS.put("organ",              "f2dcfe9a-7b66-4c84-984a-b25685a1c21a");
        BUILTIN_UUIDS.put("oscilloscope",       "ffe670a2-09aa-4c9b-8822-5161a9cca686");
        BUILTIN_UUIDS.put("peak limiter",       "8da7251e-2578-4bcc-b3c4-8f4ec2e115d0");
        BUILTIN_UUIDS.put("phase-4",            "252723bf-68a6-4ee6-81f8-95ba4d0fb467");
        BUILTIN_UUIDS.put("phaser",             "fc87ae07-1624-449f-8dae-2db5d93e1aa9");
        BUILTIN_UUIDS.put("phaser+",            "fd7a9e6c-6992-40c2-be3b-ac8ed48553e9");
        BUILTIN_UUIDS.put("pitch shifter",      "384fe469-6023-4f69-9560-e0c2eec2da49");
        BUILTIN_UUIDS.put("poly grid",          "a33bba66-8cd4-4f89-aee5-68bf67f70a54");
        BUILTIN_UUIDS.put("polymer",            "8f58138b-03aa-4e9d-83bd-a038c99a4ed5");
        BUILTIN_UUIDS.put("polysynth",          "a9ffacb5-33e9-4fc7-8621-b1af31e410ef");
        BUILTIN_UUIDS.put("quantize",           "1c116b76-2b07-4b16-bf2a-ed5f0bdcc661");
        BUILTIN_UUIDS.put("randomize",          "dc06a9a5-b0b7-41f1-af45-a3a1d2173fb8");
        BUILTIN_UUIDS.put("replacer",           "c8ed6372-d24f-47e0-9e9b-5b2a37949c45");
        BUILTIN_UUIDS.put("resonator bank",     "b64070ae-5a59-4640-bb6a-194619bc12d8");
        BUILTIN_UUIDS.put("reverb",             "5a1cb339-1c4a-4cc7-9cae-bd7a2058153d");
        BUILTIN_UUIDS.put("ricochet",           "0645879b-efea-4bbe-8e41-9a176247b808");
        BUILTIN_UUIDS.put("ring-mod",           "374feaeb-c785-4243-9d08-3f9099b4c0cb");
        BUILTIN_UUIDS.put("rotary",             "8fc25e70-b92b-4096-8270-42e492df501a");
        BUILTIN_UUIDS.put("sampler",            "468bc14b-b2e7-45a1-9666-e83117fe404e");
        BUILTIN_UUIDS.put("saturator",          "93d11348-86ae-4ead-9fe7-84ac03b9369c");
        BUILTIN_UUIDS.put("sculpt",             "8d9d63db-9991-4e46-8b4c-77755d1fcaab");
        BUILTIN_UUIDS.put("spectrum",           "fcd9aa65-ebbb-4337-a97e-69929322ef47");
        BUILTIN_UUIDS.put("step mod",           "18a37a4d-8613-442d-a6eb-931002ba9a36");
        BUILTIN_UUIDS.put("stepwise",           "c278d0d9-3e48-432a-a3b8-b33eff9533d2");
        BUILTIN_UUIDS.put("stereo split",       "96196ffe-658f-46c4-84ba-153799be3657");
        BUILTIN_UUIDS.put("strum",              "109d747c-ec75-4255-b495-7adba6ea66b6");
        BUILTIN_UUIDS.put("sweep",              "ab52804f-1169-4657-b8c8-8db5532cf717");
        BUILTIN_UUIDS.put("test tone",          "20b72dbc-0fe1-47c5-867c-f0ab1510f723");
        BUILTIN_UUIDS.put("tilt",               "061dcec6-543f-46f6-b679-f092eeefdbe4");
        BUILTIN_UUIDS.put("time shift",         "861bb5b0-5cd6-4066-9681-1cc561cb898f");
        BUILTIN_UUIDS.put("tool",               "e67b9c56-838d-4fba-8e3e-ae4e02cccbcb");
        BUILTIN_UUIDS.put("transient control",  "71e6dbd8-a117-4ff0-85e8-5650f5a76d98");
        BUILTIN_UUIDS.put("transient split",    "7c3c7bb2-625d-4915-ae95-943ee9aa807d");
        BUILTIN_UUIDS.put("transpose map",      "284a1949-29d5-4dd4-8315-86cef92fd2cd");
        BUILTIN_UUIDS.put("treemonster",        "e45e00d2-85a0-4c05-8321-819694befa09");
        BUILTIN_UUIDS.put("tremolo",            "f3b90fff-402b-4187-9aab-620f441577b9");
        BUILTIN_UUIDS.put("velocity curve",     "066d0065-99a4-47da-b0f7-9468ef69c1cf");
        BUILTIN_UUIDS.put("xy fx",              "51169152-c144-4a38-95ba-1390fb579a1f");
        BUILTIN_UUIDS.put("xy instrument",      "bab3f04d-d3b6-4dfa-86f9-506e0b091ca8");
        // Drum-Synthesizer
        BUILTIN_UUIDS.put("v0 cymbal",          "7b21c41e-67c3-4dd0-aa64-4fbb03d95cdb");
        BUILTIN_UUIDS.put("v0 hat",             "212c6aa0-04b6-49b7-a77f-c1fcee5d33a1");
        BUILTIN_UUIDS.put("v0 kick",            "8415c7af-1379-4730-97bf-16380f96d0fe");
        BUILTIN_UUIDS.put("v0 snare",           "446c58e3-ee39-4a22-b1e1-a62c614f98d4");
        BUILTIN_UUIDS.put("v0 tom",             "3c6105ad-176e-4403-993b-3eedefdf6dda");
        BUILTIN_UUIDS.put("v0 zap kick",        "eef2e851-925b-4e86-81c6-67463e17c5f7");
        BUILTIN_UUIDS.put("v1 clap",            "89eba41d-46d3-4506-8ce6-ba9fe3e3bee4");
        BUILTIN_UUIDS.put("v1 cowbell",         "dd594db1-a908-453f-a1b9-0a1b6c4c3b32");
        BUILTIN_UUIDS.put("v1 hat",             "742e4a89-df78-4ca5-b6b0-ca78889d5953");
        BUILTIN_UUIDS.put("v1 kick",            "c6d5de18-a6f1-4daa-90a9-d9254527601a");
        BUILTIN_UUIDS.put("v1 snare",           "db22eb41-c8a0-4055-b617-637614dfa185");
        BUILTIN_UUIDS.put("v1 tom",             "b5c7c298-e6af-42b3-8f14-26e25bb72d48");
        BUILTIN_UUIDS.put("v8 clap",            "b13d3937-6002-4e88-8e50-e99119708072");
        BUILTIN_UUIDS.put("v8 claves",          "1b709991-7d7d-45d1-aec8-847c01611bfb");
        BUILTIN_UUIDS.put("v8 cowbell",         "f3e8fa57-dd7a-4d94-91dd-1376c1c8304a");
        BUILTIN_UUIDS.put("v8 cymbal",          "0af9f363-ff81-4e72-b2b2-31c8c9682e28");
        BUILTIN_UUIDS.put("v8 hat",             "85d9c654-088f-4a8a-bbfc-e98af9eafb7b");
        BUILTIN_UUIDS.put("v8 kick",            "10fba33b-8e65-4eea-a5cf-312986178240");
        BUILTIN_UUIDS.put("v8 rimshot",         "9412c72e-acec-4345-acd1-ff5dc20bc2a4");
        BUILTIN_UUIDS.put("v8 snare",           "97938f59-c3d2-4b2c-8640-21c2fd2cc516");
        BUILTIN_UUIDS.put("v8 tom",             "e1be73d9-ba43-4011-91b7-2178bc4af5ea");
        BUILTIN_UUIDS.put("v9 clap",            "3df67ed2-4d70-4a86-a966-14762e2aeea4");
        BUILTIN_UUIDS.put("v9 crash",           "84bd7819-2007-46e0-b930-b4dacff1974a");
        BUILTIN_UUIDS.put("v9 hat closed",      "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hat open",        "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("v9 kick",            "32a4c607-039a-4998-be9c-578468f25454");
        BUILTIN_UUIDS.put("v9 ride",            "38f52e07-2339-491e-9dd4-8bf6a95c2dae");
        BUILTIN_UUIDS.put("v9 rimshot",         "f88c7dda-c8cd-456f-8bdf-ac25fa5bfea1");
        BUILTIN_UUIDS.put("v9 snare",           "90600c24-04c5-412e-b978-6d3cef1522da");
        BUILTIN_UUIDS.put("v9 tom",             "60f69854-fda1-4538-9ff1-c1553ea25224");
    }
    // Aktuell geladene Parameter-Namen (lowercase) → Index 0-7
    private final Map<String, Integer> paramCatalog  = new HashMap<>();

    // Ziel-Gerätename für asynchrones Laden via flush()
    private volatile String  loadTarget    = null;
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
                if (!isOpen && pendingLoadName != null) {
                    String pn = pendingLoadName;
                    String cn = lastCommittedName;
                    boolean ok = cn != null && cn.toLowerCase().contains(pn.toLowerCase());
                    sendReply(null, "/browser/device/loaded", pn, ok ? 1 : 0);
                    host.println("[BitwigAgent] Browser geschlossen — geladen: " + pn + " ok=" + ok);
                    pendingLoadName   = null;
                    lastCommittedName = null;
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
        replyLoopbackV4 = osc.connectToUdpServer("127.0.0.1", OSC_REPLY_PORT, space);
        replyLoopbackLocalhost = osc.connectToUdpServer("localhost", OSC_REPLY_PORT, space);
        agentUiLoopback = osc.connectToUdpServer("127.0.0.1", OSC_AGENT_UI_PORT, space);

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

        // Warten bis Browser geöffnet und Kategorie-Bank befüllt ist
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

        // Navigation + Commit: im Katalog suchen und sofort laden
        String key = loadTarget;
        loadTarget = null;
        Integer idx = deviceCatalog.get(key);
        if (idx != null) {
            popupBrowser.selectFirstFile();
            for (int i = 0; i < idx; i++) popupBrowser.selectNextFile();
            popupBrowser.commit();
            host.println("[BitwigAgent] Browser-Fallback geladen: " + key + " (Index " + idx + ")");
            host.showPopupNotification("Geladen: " + key);
        } else {
            host.println("[BitwigAgent] '" + key + "' nicht im Katalog ("
                + deviceCatalog.size() + " Einträge). Browser bleibt offen.");
        }
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
