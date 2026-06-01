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

    // ── Built-in Device UUIDs ────────────────────────────────────────────────

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
        BUILTIN_UUIDS.put("v9 closed hat",      "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 closed hi-hat",   "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 closed hihat",    "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hi-hat closed",   "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hihat closed",    "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hi-hat",          "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hihat",           "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hat",             "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("v9 hat open",        "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("v9 open hat",        "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("v9 open hi-hat",     "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("v9 open hihat",      "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("v9 kick",            "32a4c607-039a-4998-be9c-578468f25454");
        BUILTIN_UUIDS.put("v9 ride",            "38f52e07-2339-491e-9dd4-8bf6a95c2dae");
        BUILTIN_UUIDS.put("v9 rimshot",         "f88c7dda-c8cd-456f-8bdf-ac25fa5bfea1");
        BUILTIN_UUIDS.put("v9 snare",           "90600c24-04c5-412e-b978-6d3cef1522da");
        BUILTIN_UUIDS.put("v9 tom",             "60f69854-fda1-4538-9ff1-c1553ea25224");
        // Plain-Name-Aliase (ohne Versions-Prefix) — LLM generiert oft kurze Namen
        BUILTIN_UUIDS.put("kick",               "32a4c607-039a-4998-be9c-578468f25454"); // → v9 kick
        BUILTIN_UUIDS.put("snare",              "90600c24-04c5-412e-b978-6d3cef1522da"); // → v9 snare
        BUILTIN_UUIDS.put("hi-hat",             "5c147bc8-7b62-408b-b057-c4023c4e1adb"); // → v9 hat closed
        BUILTIN_UUIDS.put("hihat",              "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("hat",                "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("closed hat",         "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("closed hi-hat",      "5c147bc8-7b62-408b-b057-c4023c4e1adb");
        BUILTIN_UUIDS.put("open hat",           "94fc934e-a4ba-44f1-aaaa-ae30920fab17"); // → v9 hat open
        BUILTIN_UUIDS.put("open hi-hat",        "94fc934e-a4ba-44f1-aaaa-ae30920fab17");
        BUILTIN_UUIDS.put("clap",               "3df67ed2-4d70-4a86-a966-14762e2aeea4"); // → v9 clap
        BUILTIN_UUIDS.put("tom",                "60f69854-fda1-4538-9ff1-c1553ea25224"); // → v9 tom
        BUILTIN_UUIDS.put("cymbal",             "84bd7819-2007-46e0-b930-b4dacff1974a"); // → v9 crash
        BUILTIN_UUIDS.put("crash",              "84bd7819-2007-46e0-b930-b4dacff1974a");
        BUILTIN_UUIDS.put("ride",               "38f52e07-2339-491e-9dd4-8bf6a95c2dae"); // → v9 ride
        BUILTIN_UUIDS.put("rimshot",            "f88c7dda-c8cd-456f-8bdf-ac25fa5bfea1");
    }

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

        // Mark interested
        for (int i = 0; i < TRACK_BANK_SIZE; i++) {
            Channel t = (Channel) trackBank.getItemAt(i);
            t.name().markInterested();
            t.exists().markInterested();
        }
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
                        // Plugin-Fenster automatisch schließen (öffnet sich ~300ms nach Browser-Close)
                        host.scheduleTask(() -> cursorDevice.isWindowOpen().set(false), 500);
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

        // ── HAUPTENDPUNKT: /step/exec ─────────────────────────────────────
        space.registerMethod("/step/exec", "*", "Execute single step",
            (src, msg) -> {
                String json = argStr(msg, 0);
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
        String type = extractStringField(json, "type");
        String args = extractNestedObject(json, "args");
        if (args == null) args = "{}";
        host.println("[BitwigStep] exec: " + type);

        // Precondition: Steps die einen existierenden Track benötigen
        switch (type != null ? type : "") {
            case "load_instrument":
            case "append_effect":
            case "write_notes":
            case "set_param":
            case "set_param_named": {
                int track = (int) extractNumField(args, "track_index", 0);
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
        double bpm = extractNumField(args, "bpm", 120.0);
        transport.tempo().setRaw(bpm);
        stepDone(src, "set_tempo");
    }

    private void execAddTrack(OscConnection src, String args) {
        String t = extractStringField(args, "track_type");
        if ("audio".equals(t))
            application.createAudioTrack(-1);
        else if ("return".equals(t) || "effect".equals(t))
            application.createEffectTrack(-1);
        else
            application.createInstrumentTrack(-1);
        host.scheduleTask(() -> stepDone(src, "add_track"), 80);
    }

    private void execClearTracks(OscConnection src) {
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
        int idx = Math.max(1, (int) extractNumField(args, "track_index", 1));
        if (idx <= TRACK_BANK_SIZE) {
            Channel ch = (Channel) trackBank.getItemAt(idx - 1);
            if (ch.exists().get()) ch.selectInMixer();
        }
        host.scheduleTask(() -> stepDone(src, "select_track"), 40);
    }

    private void execLoadInstrument(OscConnection src, String args) {
        int    track = Math.max(1, (int) extractNumField(args, "track_index", 1));
        String name  = extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:load_instrument:no_name");
            return;
        }
        String key          = name.toLowerCase().trim();
        String uuidFromArgs = extractStringField(args, "uuid");
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
        int    track = Math.max(1, (int) extractNumField(args, "track_index", 1));
        String name  = extractStringField(args, "name");
        if (name == null || name.isBlank()) {
            stepDone(src, "error:append_effect:no_name");
            return;
        }
        String key          = name.toLowerCase().trim();
        String uuidFromArgs = extractStringField(args, "uuid");
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
        int    track = (int) extractNumField(args, "track_index", 0);
        int    idx   = Math.max(0, Math.min(7, (int) extractNumField(args, "index", 1) - 1));
        double val   = extractNumField(args, "value", 0.0);

        if (track > 0) channel(track).selectInMixer();
        long delay = track > 0 ? 40L : 0L;
        final int fi = idx; final double fv = val;
        host.scheduleTask(() -> {
            remoteControls.getParameter(fi).value().set(fv);
            stepDone(src, "set_param");
        }, delay);
    }

    private void execSetParamNamed(OscConnection src, String args) {
        int    track = (int) extractNumField(args, "track_index", 0);
        String pname = extractStringField(args, "param_name");
        double val   = extractNumField(args, "value", 0.0);

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
        int    track  = Math.max(1, (int) extractNumField(args, "track_index", 1));
        int    slot   = Math.max(0, (int) extractNumField(args, "slot",         0));
        int    length = Math.max(1, (int) extractNumField(args, "length_beats",  8));
        String notes  = extractArray(args, "notes");

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

    private String argStr(OscMessage msg, int idx) {
        try { return msg.getString(idx); }
        catch (Exception e) {
            try { return String.valueOf(msg.getFloat(idx)); }
            catch (Exception ex) { return null; }
        }
    }

    // ── JSON-Hilfsmethoden ────────────────────────────────────────────────────

    private String extractStringField(String json, String key) {
        if (json == null) return null;
        int ki = json.indexOf("\"" + key + "\"");
        if (ki < 0) return null;
        int colon = json.indexOf(':', ki);
        if (colon < 0) return null;
        int s = colon + 1;
        while (s < json.length() && Character.isWhitespace(json.charAt(s))) s++;
        if (s >= json.length() || json.charAt(s) != '"') return null;
        int end = json.indexOf('"', s + 1);
        return end > s ? json.substring(s + 1, end) : null;
    }

    private double extractNumField(String json, String key, double def) {
        if (json == null) return def;
        int ki = json.indexOf("\"" + key + "\"");
        if (ki < 0) return def;
        int colon = json.indexOf(':', ki);
        if (colon < 0) return def;
        int s = colon + 1;
        while (s < json.length() && Character.isWhitespace(json.charAt(s))) s++;
        int e = s;
        while (e < json.length()) {
            char c = json.charAt(e);
            if (Character.isDigit(c) || c == '-' || c == '.') e++;
            else break;
        }
        if (e <= s) return def;
        try { return Double.parseDouble(json.substring(s, e)); }
        catch (NumberFormatException ex) { return def; }
    }

    private String extractNestedObject(String json, String key) {
        if (json == null) return null;
        int ki = json.indexOf("\"" + key + "\"");
        if (ki < 0) return null;
        int colon = json.indexOf(':', ki);
        if (colon < 0) return null;
        int start = json.indexOf('{', colon);
        if (start < 0) return null;
        int depth = 0;
        for (int i = start; i < json.length(); i++) {
            char c = json.charAt(i);
            if (c == '{') depth++;
            else if (c == '}' && --depth == 0) return json.substring(start, i + 1);
        }
        return null;
    }

    private String extractArray(String json, String key) {
        if (json == null) return null;
        int ki = json.indexOf("\"" + key + "\"");
        if (ki < 0) return null;
        int colon = json.indexOf(':', ki);
        if (colon < 0) return null;
        int start = json.indexOf('[', colon);
        if (start < 0) return null;
        int depth = 0;
        for (int i = start; i < json.length(); i++) {
            char c = json.charAt(i);
            if (c == '[') depth++;
            else if (c == ']' && --depth == 0) return json.substring(start, i + 1);
        }
        return null;
    }

    private int parseAndWriteNoteBatch(String json) {
        int count = 0;
        String stripped = json.replace("[", "").replace("]", "");
        for (String entry : stripped.split("\\},\\s*\\{")) {
            entry = entry.replace("{", "").replace("}", "").trim();
            if (entry.isBlank()) continue;
            Map<String, Double> f = parseSimpleJsonObject(entry);
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

    private Map<String, Double> parseSimpleJsonObject(String kvPairs) {
        Map<String, Double> result = new HashMap<>();
        for (String pair : kvPairs.split(",")) {
            pair = pair.trim();
            int colon = pair.indexOf(':');
            if (colon < 0) continue;
            String k = pair.substring(0, colon).trim().replace("\"", "");
            String v = pair.substring(colon + 1).trim().replace("\"", "");
            try { result.put(k, Double.parseDouble(v)); }
            catch (NumberFormatException ignored) {}
        }
        return result;
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
