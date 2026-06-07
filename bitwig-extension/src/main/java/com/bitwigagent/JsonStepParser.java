package com.bitwigagent;

import com.bitwig.extension.api.opensoundcontrol.OscMessage;
import java.util.HashMap;
import java.util.Map;

/**
 * Leichtgewichtige JSON- und OSC-Parsing-Hilfsmethoden für BitwigStepPlugin.
 * Kein Bitwig-API-State — reine Transformation von Strings/Bytes.
 */
final class JsonStepParser {

    private JsonStepParser() {}

    static String argStr(OscMessage msg, int idx) {
        try { return msg.getString(idx); }
        catch (Exception e) {
            try { return String.valueOf(msg.getFloat(idx)); }
            catch (Exception ex) { return null; }
        }
    }

    static String extractStringField(String json, String key) {
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

    static double extractNumField(String json, String key, double def) {
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

    static String extractNestedObject(String json, String key) {
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

    static String extractArray(String json, String key) {
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

    static Map<String, Double> parseSimpleJsonObject(String kvPairs) {
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

    /**
     * Zerlegt ein JSON-Array von Objekten in die einzelnen Objekt-Strings.
     * Eingabe z. B. {@code [{"pad":0,"name":"Kick"},{"pad":1,"name":"Snare"}]}
     * → {@code ["{\"pad\":0,\"name\":\"Kick\"}", "{\"pad\":1,...}"]}.
     * Tiefen-bewusst (verschachtelte Objekte/Arrays werden korrekt behandelt).
     */
    static java.util.List<String> splitObjects(String arrayJson) {
        java.util.List<String> out = new java.util.ArrayList<>();
        if (arrayJson == null) return out;
        int depth = 0, objStart = -1;
        for (int i = 0; i < arrayJson.length(); i++) {
            char c = arrayJson.charAt(i);
            if (c == '{') {
                if (depth == 0) objStart = i;
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0 && objStart >= 0) {
                    out.add(arrayJson.substring(objStart, i + 1));
                    objStart = -1;
                }
            }
        }
        return out;
    }
}
