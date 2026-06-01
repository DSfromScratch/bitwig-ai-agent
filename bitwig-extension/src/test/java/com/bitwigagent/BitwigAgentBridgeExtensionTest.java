package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.OscMessage;
import com.bitwig.extension.controller.api.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

// Note: SettableStringValue is used (not StringValue) because BrowserItem.name()
// and RemoteControl.name() both return SettableStringValue in Bitwig API 18.

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.objenesis.ObjenesisStd;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.*;

/**
 * Unit tests for BitwigAgentBridgeExtension.
 *
 * Objenesis is used to allocate the extension instance without invoking the constructor,
 * which avoids pulling in Bitwig API runtime dependencies. The final HashMap fields
 * (deviceCatalog, paramCatalog, noteCountMap) that are normally set by field initializers
 * are injected manually via reflection after allocation.
 */
class BitwigAgentBridgeExtensionTest {

    private BitwigAgentBridgeExtension ext;
    private ControllerHost mockHost;

    @BeforeEach
    void setUp() throws Exception {
        // Bypass the ControllerExtension constructor entirely — no Bitwig API calls.
        ext = new ObjenesisStd().newInstance(BitwigAgentBridgeExtension.class);
        // Field initializers don't run when bypassing the constructor; seed them here.
        setField("deviceCatalog", new HashMap<>());
        setField("paramCatalog",  new HashMap<>());
        setField("noteCountMap",  new HashMap<>());
        mockHost = mock(ControllerHost.class);
    }

    // ── Reflection helpers ────────────────────────────────────────────────────

    private void setField(String name, Object value) throws Exception {
        Field f = BitwigAgentBridgeExtension.class.getDeclaredField(name);
        f.setAccessible(true);
        f.set(ext, value);
    }

    @SuppressWarnings("unchecked")
    private <T> T getField(String name) throws Exception {
        Field f = BitwigAgentBridgeExtension.class.getDeclaredField(name);
        f.setAccessible(true);
        return (T) f.get(ext);
    }

    private Object invokePrivate(String name, Class<?>[] types, Object... args) throws Exception {
        Method m = BitwigAgentBridgeExtension.class.getDeclaredMethod(name, types);
        m.setAccessible(true);
        return m.invoke(ext, args);
    }

    // ── Mock factory helpers ──────────────────────────────────────────────────

    /** Creates a BrowserItem mock with exists() and name() stubbed. */
    private BrowserItem mockItem(boolean exists, String name) {
        BrowserItem          item        = mock(BrowserItem.class);
        BooleanValue         existsVal   = mock(BooleanValue.class);
        SettableStringValue  nameVal     = mock(SettableStringValue.class);
        SettableBooleanValue selectedVal = mock(SettableBooleanValue.class);
        when(item.exists()).thenReturn(existsVal);
        when(item.name()).thenReturn(nameVal);
        when(item.isSelected()).thenReturn(selectedVal);
        when(existsVal.get()).thenReturn(exists);
        when(nameVal.get()).thenReturn(name);
        return item;
    }

    /** Creates a BrowserItemBank whose getItem(i) returns specific items by index. */
    private BrowserItemBank mockBrowserBank(Map<Integer, BrowserItem> specific) {
        BrowserItemBank bank        = mock(BrowserItemBank.class);
        BrowserItem     defaultItem = mockItem(false, "");
        when(bank.getItem(anyInt())).thenReturn(defaultItem);
        for (Map.Entry<Integer, BrowserItem> e : specific.entrySet()) {
            when(bank.getItem(e.getKey())).thenReturn(e.getValue());
        }
        return bank;
    }

    /** Creates a BrowserFilterItemBank whose getItem(i) returns specific items by index. */
    private BrowserFilterItemBank mockFilterBank(Map<Integer, BrowserItem> specific) {
        BrowserFilterItemBank bank        = mock(BrowserFilterItemBank.class);
        BrowserItem           defaultItem = mockItem(false, "");
        when(bank.getItem(anyInt())).thenReturn(defaultItem);
        for (Map.Entry<Integer, BrowserItem> e : specific.entrySet()) {
            when(bank.getItem(e.getKey())).thenReturn(e.getValue());
        }
        return bank;
    }

    /** Creates a RemoteControl mock with a stubbed name. */
    private RemoteControl mockParam(String name) {
        RemoteControl       rc      = mock(RemoteControl.class);
        SettableStringValue nameVal = mock(SettableStringValue.class);
        when(rc.name()).thenReturn(nameVal);
        when(nameVal.get()).thenReturn(name);
        return rc;
    }

    /** Creates a CursorRemoteControlsPage with up to 8 named params. */
    private CursorRemoteControlsPage mockRemoteControlsPage(String... paramNames) {
        CursorRemoteControlsPage page = mock(CursorRemoteControlsPage.class);
        // Pre-create all param mocks BEFORE any when() calls on page, otherwise
        // Mockito detects an "unfinished stubbing" because mockParam() itself
        // calls when() internally while the outer when(page.getParameter()) is pending.
        RemoteControl[] params = new RemoteControl[8];
        for (int i = 0; i < 8; i++) {
            params[i] = mockParam(i < paramNames.length ? paramNames[i] : "");
        }
        for (int i = 0; i < 8; i++) {
            when(page.getParameter(i)).thenReturn(params[i]);
        }
        return page;
    }

    /** Injects the minimum fields required by flush(). */
    private void setUpFlushMocks(BrowserItemBank resultBank,
                                 CursorRemoteControlsPage controls) throws Exception {
        setField("resultBank",    resultBank);
        setField("remoteControls", controls);
        setField("host",           mockHost);
        setField("locationBank",   mockFilterBank(Map.of()));
        PopupBrowser mockBrowser = mock(PopupBrowser.class);
        setField("popupBrowser",   mockBrowser);
    }

    // ── argFloat ─────────────────────────────────────────────────────────────

    @Test
    void argFloat_returnsValueAtIndex() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getFloat(0)).thenReturn(0.75f);

        float result = (float) invokePrivate("argFloat",
                new Class[]{OscMessage.class, int.class, float.class}, msg, 0, 0.5f);

        assertEquals(0.75f, result);
    }

    @Test
    void argFloat_returnsDefaultWhenValueIsNull() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getFloat(0)).thenReturn(null);

        float result = (float) invokePrivate("argFloat",
                new Class[]{OscMessage.class, int.class, float.class}, msg, 0, 0.5f);

        assertEquals(0.5f, result);
    }

    @Test
    void argFloat_returnsDefaultOnException() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getFloat(0)).thenThrow(new RuntimeException("bad index"));

        float result = (float) invokePrivate("argFloat",
                new Class[]{OscMessage.class, int.class, float.class}, msg, 0, 1.0f);

        assertEquals(1.0f, result);
    }

    @Test
    void argFloat_returnsValueAtDifferentIndex() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getFloat(2)).thenReturn(3.14f);
        when(msg.getFloat(0)).thenReturn(null);

        float result = (float) invokePrivate("argFloat",
                new Class[]{OscMessage.class, int.class, float.class}, msg, 2, 0f);

        assertEquals(3.14f, result, 0.001f);
    }

    // ── argStr ───────────────────────────────────────────────────────────────

    @Test
    void argStr_returnsStringAtIndex() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getString(0)).thenReturn("hello");

        String result = (String) invokePrivate("argStr",
                new Class[]{OscMessage.class, int.class}, msg, 0);

        assertEquals("hello", result);
    }

    @Test
    void argStr_returnsNullWhenGetStringReturnsNull() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getString(0)).thenReturn(null);

        String result = (String) invokePrivate("argStr",
                new Class[]{OscMessage.class, int.class}, msg, 0);

        assertNull(result);
    }

    @Test
    void argStr_fallsBackToFloatStringOnStringException() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getString(0)).thenThrow(new RuntimeException("not a string"));
        when(msg.getFloat(0)).thenReturn(42.0f);

        String result = (String) invokePrivate("argStr",
                new Class[]{OscMessage.class, int.class}, msg, 0);

        assertEquals("42.0", result);
    }

    @Test
    void argStr_returnsNullWhenBothMethodsThrow() throws Exception {
        OscMessage msg = mock(OscMessage.class);
        when(msg.getString(0)).thenThrow(new RuntimeException("not a string"));
        when(msg.getFloat(0)).thenThrow(new RuntimeException("not a float either"));

        String result = (String) invokePrivate("argStr",
                new Class[]{OscMessage.class, int.class}, msg, 0);

        assertNull(result);
    }

    // ── flush() — device catalog building ────────────────────────────────────

    @Test
    void flush_populatesDeviceCatalogFromResultBank() throws Exception {
        BrowserItem item0 = mockItem(true, "Polymer");
        BrowserItem item1 = mockItem(true, "EQ+");
        setUpFlushMocks(mockBrowserBank(Map.of(0, item0, 1, item1)),
                        mockRemoteControlsPage());

        ext.flush();

        Map<String, Integer> catalog = getField("deviceCatalog");
        assertEquals(0, catalog.get("polymer"));
        assertEquals(1, catalog.get("eq+"));
    }

    @Test
    void flush_skipsNonExistentBrowserItems() throws Exception {
        BrowserItem existing = mockItem(true,  "Delay");
        BrowserItem missing  = mockItem(false, "Ghost");
        setUpFlushMocks(mockBrowserBank(Map.of(0, existing, 1, missing)),
                        mockRemoteControlsPage());

        ext.flush();

        Map<String, Integer> catalog = getField("deviceCatalog");
        assertTrue(catalog.containsKey("delay"));
        assertFalse(catalog.containsKey("ghost"));
    }

    @Test
    void flush_skipsBlankAndNullNamesInResultBank() throws Exception {
        BrowserItem blank = mockItem(true, "   ");
        BrowserItem nul   = mockItem(true, null);
        BrowserItem ok    = mockItem(true, "Reverb");
        setUpFlushMocks(mockBrowserBank(Map.of(0, blank, 1, nul, 2, ok)),
                        mockRemoteControlsPage());

        ext.flush();

        Map<String, Integer> catalog = getField("deviceCatalog");
        assertEquals(1, catalog.size());
        assertTrue(catalog.containsKey("reverb"));
    }

    @Test
    void flush_catalogKeysAreLowercased() throws Exception {
        BrowserItem item = mockItem(true, "Poly Grid");
        setUpFlushMocks(mockBrowserBank(Map.of(5, item)), mockRemoteControlsPage());

        ext.flush();

        Map<String, Integer> catalog = getField("deviceCatalog");
        assertTrue(catalog.containsKey("poly grid"));
        assertFalse(catalog.containsKey("Poly Grid"));
        assertEquals(5, catalog.get("poly grid"));
    }

    // ── flush() — param catalog building ────────────────────────────────────

    @Test
    void flush_rebuildsParamCatalogEachCall() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()),
                        mockRemoteControlsPage("Cutoff", "Resonance"));

        ext.flush();

        Map<String, Integer> paramCatalog = getField("paramCatalog");
        assertEquals(0, paramCatalog.get("cutoff"));
        assertEquals(1, paramCatalog.get("resonance"));
    }

    @Test
    void flush_paramCatalogIsClearedBeforeRebuild() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()),
                        mockRemoteControlsPage("Attack"));
        ext.flush();

        // Second flush with different params
        setField("remoteControls", mockRemoteControlsPage("Release"));
        ext.flush();

        Map<String, Integer> paramCatalog = getField("paramCatalog");
        assertFalse(paramCatalog.containsKey("attack"), "old param should be gone");
        assertTrue(paramCatalog.containsKey("release"));
    }

    @Test
    void flush_paramCatalogKeysAreLowercased() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()),
                        mockRemoteControlsPage("CUTOFF"));

        ext.flush();

        Map<String, Integer> paramCatalog = getField("paramCatalog");
        assertTrue(paramCatalog.containsKey("cutoff"));
        assertFalse(paramCatalog.containsKey("CUTOFF"));
    }

    // ── flush() — load state machine ─────────────────────────────────────────

    @Test
    void flush_doesNothingExtraWhenLoadTargetIsNull() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("loadTarget", null);

        assertDoesNotThrow(() -> ext.flush());
        assertNull(getField("loadTarget"));
    }

    @Test
    void flush_decrementsLoadWaitLeftAndReturnsEarly() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("loadTarget",   "polymer");
        setField("loadWaitLeft", 2);

        ext.flush();

        assertEquals(1, (int) getField("loadWaitLeft"));
        assertEquals("polymer", getField("loadTarget")); // not cleared yet
    }

    @Test
    void flush_multipleFlushesDecrementUntilZero() throws Exception {
        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("loadTarget",   "polymer");
        setField("loadWaitLeft", 3);

        ext.flush(); assertEquals(2, (int) getField("loadWaitLeft"));
        ext.flush(); assertEquals(1, (int) getField("loadWaitLeft"));
        ext.flush(); assertEquals(0, (int) getField("loadWaitLeft"));
        assertEquals("polymer", getField("loadTarget")); // still pending
    }

    @Test
    void flush_clearsLoadTargetWhenWaitIsZeroAndNoCollection() throws Exception {
        BrowserFilterItemBank smartCollBank = mockFilterBank(Map.of());
        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("smartCollBank", smartCollBank);
        setField("loadTarget",    "polymer");
        setField("loadWaitLeft",  0);
        setField("loadCollection", null);

        ext.flush();

        assertNull(getField("loadTarget")); // cleared after processing
    }

    @Test
    void flush_selectsMatchingSmartCollectionItem() throws Exception {
        SettableBooleanValue matchSelected = mock(SettableBooleanValue.class);
        BrowserItem          match         = mock(BrowserItem.class);
        BooleanValue         matchExists   = mock(BooleanValue.class);
        StringValue          matchName     = mock(StringValue.class);
        when(match.exists()).thenReturn(matchExists);
        when(match.name()).thenReturn(matchName);
        when(match.isSelected()).thenReturn(matchSelected);
        when(matchExists.get()).thenReturn(true);
        when(matchName.get()).thenReturn("BitwigAgent");

        BrowserFilterItemBank smartCollBank = mockFilterBank(Map.of(
                0, mockItem(true, "Factory"),
                1, match
        ));

        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("smartCollBank",  smartCollBank);
        setField("loadTarget",     "some-device");
        setField("loadWaitLeft",   0);
        setField("loadCollection", "bitwigagent");

        ext.flush();

        verify(matchSelected).set(true);
        assertNull(getField("loadCollection")); // reset after processing
        assertNull(getField("loadTarget"));
    }

    @Test
    void flush_clearsCollectionEvenWhenNotFound() throws Exception {
        BrowserFilterItemBank smartCollBank = mockFilterBank(Map.of(
                0, mockItem(true, "Factory")
        ));

        setUpFlushMocks(mockBrowserBank(Map.of()), mockRemoteControlsPage());
        setField("smartCollBank",  smartCollBank);
        setField("loadTarget",     "target");
        setField("loadWaitLeft",   0);
        setField("loadCollection", "nonexistent");

        ext.flush();

        assertNull(getField("loadCollection")); // cleared regardless
        assertNull(getField("loadTarget"));
    }

    // ── BUILTIN_UUIDS data integrity ─────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, String> getBuiltinUuids() throws Exception {
        Field f = BitwigAgentBridgeExtension.class.getDeclaredField("BUILTIN_UUIDS");
        f.setAccessible(true);
        return (Map<String, String>) f.get(null);
    }

    @Test
    void builtinUuids_isNotEmpty() throws Exception {
        Map<String, String> uuids = getBuiltinUuids();
        assertTrue(uuids.size() >= 100,
                "Expected at least 100 built-in devices, got " + uuids.size());
    }

    @Test
    void builtinUuids_allValuesAreValidUuids() throws Exception {
        Map<String, String> uuids = getBuiltinUuids();
        for (Map.Entry<String, String> entry : uuids.entrySet()) {
            assertDoesNotThrow(() -> UUID.fromString(entry.getValue()),
                    "Invalid UUID for device '" + entry.getKey() + "': " + entry.getValue());
        }
    }

    @Test
    void builtinUuids_keysAreLowercaseTrimmed() throws Exception {
        Map<String, String> uuids = getBuiltinUuids();
        for (String key : uuids.keySet()) {
            assertEquals(key.toLowerCase().trim(), key,
                    "Key is not lowercase/trimmed: '" + key + "'");
        }
    }

    @Test
    void builtinUuids_noNullOrBlankValues() throws Exception {
        Map<String, String> uuids = getBuiltinUuids();
        for (Map.Entry<String, String> entry : uuids.entrySet()) {
            assertNotNull(entry.getValue(), "Null UUID for: " + entry.getKey());
            assertFalse(entry.getValue().isBlank(), "Blank UUID for: " + entry.getKey());
        }
    }

    @Test
    void builtinUuids_containsEssentialDevices() throws Exception {
        Map<String, String> uuids = getBuiltinUuids();
        assertAll(
            () -> assertTrue(uuids.containsKey("sampler"),      "missing: sampler"),
            () -> assertTrue(uuids.containsKey("reverb"),       "missing: reverb"),
            () -> assertTrue(uuids.containsKey("compressor"),   "missing: compressor"),
            () -> assertTrue(uuids.containsKey("delay"),        "missing: delay"),
            () -> assertTrue(uuids.containsKey("eq+"),          "missing: eq+"),
            () -> assertTrue(uuids.containsKey("polymer"),      "missing: polymer"),
            () -> assertTrue(uuids.containsKey("poly grid"),    "missing: poly grid"),
            () -> assertTrue(uuids.containsKey("drum machine"), "missing: drum machine")
        );
    }
}
