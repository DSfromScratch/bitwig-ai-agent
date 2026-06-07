package com.bitwigagent;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the pure JSON helpers in {@link JsonStepParser}.
 * No Bitwig API state is involved — these are deterministic string transforms.
 */
class JsonStepParserTest {

    @Test
    void extractStringField_returnsValue() {
        assertEquals("Kick", JsonStepParser.extractStringField("{\"name\":\"Kick\"}", "name"));
        assertNull(JsonStepParser.extractStringField("{\"name\":\"Kick\"}", "missing"));
        assertNull(JsonStepParser.extractStringField(null, "name"));
    }

    @Test
    void extractNumField_parsesAndFallsBack() {
        assertEquals(0.5, JsonStepParser.extractNumField("{\"level\":0.5}", "level", 0.0));
        assertEquals(3.0, JsonStepParser.extractNumField("{\"send_index\":3}", "send_index", -1));
        assertEquals(-1.0, JsonStepParser.extractNumField("{\"a\":1}", "missing", -1.0));
    }

    @Test
    void extractArray_returnsBracketedSlice() {
        String json = "{\"pads\":[{\"pad\":0},{\"pad\":1}],\"x\":1}";
        assertEquals("[{\"pad\":0},{\"pad\":1}]", JsonStepParser.extractArray(json, "pads"));
        assertNull(JsonStepParser.extractArray(json, "missing"));
    }

    @Test
    void splitObjects_handlesFlatObjects() {
        String arr = "[{\"pad\":0,\"name\":\"Kick\"},{\"pad\":1,\"name\":\"Snare\"}]";
        List<String> parts = JsonStepParser.splitObjects(arr);
        assertEquals(2, parts.size());
        assertEquals("Kick", JsonStepParser.extractStringField(parts.get(0), "name"));
        assertEquals("Snare", JsonStepParser.extractStringField(parts.get(1), "name"));
        assertEquals(1.0, JsonStepParser.extractNumField(parts.get(1), "pad", -1));
    }

    @Test
    void splitObjects_isDepthAwareForNestedObjects() {
        String arr = "[{\"pad\":0,\"meta\":{\"a\":1}},{\"pad\":1}]";
        List<String> parts = JsonStepParser.splitObjects(arr);
        assertEquals(2, parts.size());
        assertEquals("{\"pad\":0,\"meta\":{\"a\":1}}", parts.get(0));
        assertEquals("{\"pad\":1}", parts.get(1));
    }

    @Test
    void splitObjects_emptyAndNull() {
        assertTrue(JsonStepParser.splitObjects(null).isEmpty());
        assertTrue(JsonStepParser.splitObjects("[]").isEmpty());
    }
}
