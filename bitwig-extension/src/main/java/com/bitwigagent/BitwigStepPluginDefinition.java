package com.bitwigagent;

import com.bitwig.extension.api.PlatformType;
import com.bitwig.extension.controller.AutoDetectionMidiPortNamesList;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.ControllerHost;
import java.util.UUID;

public class BitwigStepPluginDefinition extends ControllerExtensionDefinition {

    private static final UUID EXTENSION_UUID =
        UUID.fromString("e5f6a7b8-c9d0-1234-ef56-78901234abcd");

    @Override public String getName()              { return "Bitwig Step Plugin"; }
    @Override public String getAuthor()            { return "Bitwig Agent"; }
    @Override public String getVersion()           { return "1.0.0"; }
    @Override public UUID   getId()                { return EXTENSION_UUID; }
    @Override public String getHardwareVendor()    { return "Bitwig Agent"; }
    @Override public String getHardwareModel()     { return "Step Plugin"; }
    @Override public int    getRequiredAPIVersion() { return 18; }
    @Override public int    getNumMidiInPorts()    { return 0; }
    @Override public int    getNumMidiOutPorts()   { return 0; }

    @Override
    public void listAutoDetectionMidiPortNames(
            AutoDetectionMidiPortNamesList list, PlatformType platformType) {
        // Kein MIDI
    }

    @Override
    public BitwigStepPluginExtension createInstance(ControllerHost host) {
        return new BitwigStepPluginExtension(this, host);
    }

    @Override public String getHelpFilePath() { return "README.txt"; }
}
