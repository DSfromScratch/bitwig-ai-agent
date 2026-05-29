package com.bitwigagent;

import com.bitwig.extension.controller.api.ControllerHost;

/**
 * Bitwig OSC Bridge — pure OSC ↔ Bitwig API.
 *
 * Kein Agent-UI, kein Launchpad, kein MIDI.
 * Erbt alle OSC-Endpoints von BitwigAgentBridgeExtension:
 *   Transport, Tracks, Devices, Browser, Clips, Notes, Mixer, EQ, …
 */
public class BitwigOscBridgeExtension extends BitwigAgentBridgeExtension {

    protected BitwigOscBridgeExtension(BitwigOscBridgeDefinition def, ControllerHost host) {
        super(def, host);
    }

    @Override
    protected void setupExtras() {
        // Kein Agent-UI, kein Launchpad — reine OSC Bridge
        host.println("[BitwigOscBridge] Pure OSC mode — kein MIDI, kein Agent-UI");
    }
}
