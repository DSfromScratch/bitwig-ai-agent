package com.bitwigagent;

import com.bitwig.extension.api.PlatformType;
import com.bitwig.extension.controller.AutoDetectionMidiPortNamesList;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.ControllerHost;
import java.util.UUID;

public class BitwigOscBridgeDefinition extends ControllerExtensionDefinition {

    private static final UUID EXTENSION_UUID =
        UUID.fromString("c3d4e5f6-a7b8-9012-cdef-123456789012");

    @Override public String getName()            { return "Bitwig OSC Bridge"; }
    @Override public String getAuthor()          { return "Bitwig Agent"; }
    @Override public String getVersion()         { return "2.0.0"; }
    @Override public UUID   getId()              { return EXTENSION_UUID; }
    @Override public String getHardwareVendor()  { return "Bitwig Agent"; }
    @Override public String getHardwareModel()   { return "OSC Bridge"; }
    @Override public int    getRequiredAPIVersion() { return 18; }
    @Override public int    getNumMidiInPorts()  { return 0; }
    @Override public int    getNumMidiOutPorts() { return 0; }

    @Override
    public void listAutoDetectionMidiPortNames(
            AutoDetectionMidiPortNamesList list, PlatformType platformType) {
        // Kein MIDI — reine OSC-Bridge
    }

    @Override
    public BitwigOscBridgeExtension createInstance(ControllerHost host) {
        return new BitwigOscBridgeExtension(this, host);
    }

    @Override public String getHelpFilePath() { return "README.txt"; }
}
