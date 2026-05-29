package com.bitwigagent;

import com.bitwig.extension.api.PlatformType;
import com.bitwig.extension.controller.AutoDetectionMidiPortNamesList;
import com.bitwig.extension.controller.ControllerExtensionDefinition;
import com.bitwig.extension.controller.api.ControllerHost;
import java.util.UUID;

public class LaunchpadControllerDefinition extends ControllerExtensionDefinition {

    private static final UUID EXTENSION_UUID =
        UUID.fromString("b2c3d4e5-f6a7-8901-bcde-f12345678901");

    @Override public String getName()            { return "Launchpad Controller"; }
    @Override public String getAuthor()          { return "Bitwig Agent"; }
    @Override public String getVersion()         { return "1.0.0"; }
    @Override public UUID   getId()              { return EXTENSION_UUID; }
    @Override public String getHardwareVendor()  { return "Novation"; }
    @Override public String getHardwareModel()   { return "Launchpad MK2"; }
    @Override public int    getRequiredAPIVersion() { return 18; }
    @Override public int    getNumMidiInPorts()  { return 1; }
    @Override public int    getNumMidiOutPorts() { return 1; }

    @Override
    public void listAutoDetectionMidiPortNames(
            AutoDetectionMidiPortNamesList list, PlatformType platformType) {
        list.add(
            new String[]{"Launchpad MK2 MIDI 1"},
            new String[]{"Launchpad MK2 MIDI 1"}
        );
    }

    @Override
    public LaunchpadControllerExtension createInstance(ControllerHost host) {
        return new LaunchpadControllerExtension(this, host);
    }

    @Override public String getHelpFilePath() { return "README.txt"; }
}
