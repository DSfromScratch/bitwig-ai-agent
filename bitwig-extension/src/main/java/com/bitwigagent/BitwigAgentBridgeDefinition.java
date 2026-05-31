package com.bitwigagent;

import com.bitwig.extension.api.PlatformType;
import com.bitwig.extension.controller.AutoDetectionMidiPortNamesList;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.ControllerHost;

import java.util.UUID;

public class BitwigAgentBridgeDefinition extends ControllerExtensionDefinition {

    private static final UUID EXTENSION_UUID =
        UUID.fromString("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

    @Override
    public String getName() {
        return "Bitwig Agent Bridge";
    }

    @Override
    public String getAuthor() {
        return "Bitwig Agent";
    }

    @Override
    public String getVersion() {
        return "1.0.0";
    }

    @Override
    public UUID getId() {
        return EXTENSION_UUID;
    }

    @Override
    public String getHardwareVendor() {
        return "Bitwig Agent";
    }

    @Override
    public String getHardwareModel() {
        return "Agent Bridge";
    }

    @Override
    public int getRequiredAPIVersion() {
        return 18;
    }

    @Override
    public int getNumMidiInPorts() {
        return 0;  // kein MIDI — LED-Steuerung läuft über LaunchpadControllerExtension
    }

    @Override
    public int getNumMidiOutPorts() {
        return 0;
    }

    @Override
    public void listAutoDetectionMidiPortNames(
        AutoDetectionMidiPortNamesList list, PlatformType platformType) {
        // Kein MIDI-Port — Bridge kommuniziert nur via OSC (Port 8001)
    }

    @Override
    public BitwigAgentBridgeExtension createInstance(ControllerHost host) {
        return new BitwigAgentBridgeExtension(this, host);
    }

    @Override
    public String getHelpFilePath() {
        return "README.txt";
    }
}
