package id.optionflow.mw;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Tiny zero-dependency JSON parser. Supports objects, arrays, strings, numbers,
 * booleans, and null. Strings, doubles, and longs returned as Java equivalents.
 * Sufficient for the OptionFlow /levels API response shape.
 *
 * Usage:
 *   Object root = JsonParser.parse(jsonText);
 *   if (root instanceof Map) ...
 */
final class JsonParser {

    private final String src;
    private int pos;

    private JsonParser(String s) {
        this.src = s;
        this.pos = 0;
    }

    static Object parse(String text) {
        JsonParser p = new JsonParser(text);
        p.skipWs();
        Object v = p.readValue();
        p.skipWs();
        if (p.pos != p.src.length()) {
            throw new RuntimeException("trailing chars at pos " + p.pos);
        }
        return v;
    }

    private Object readValue() {
        skipWs();
        if (pos >= src.length()) throw err("unexpected EOF");
        char c = src.charAt(pos);
        if (c == '{') return readObject();
        if (c == '[') return readArray();
        if (c == '"') return readString();
        if (c == 't' || c == 'f') return readBool();
        if (c == 'n') return readNull();
        if (c == '-' || (c >= '0' && c <= '9')) return readNumber();
        throw err("unexpected char '" + c + "'");
    }

    private Map<String, Object> readObject() {
        expect('{');
        Map<String, Object> m = new LinkedHashMap<>();
        skipWs();
        if (peek() == '}') { pos++; return m; }
        while (true) {
            skipWs();
            String key = readString();
            skipWs();
            expect(':');
            Object val = readValue();
            m.put(key, val);
            skipWs();
            char c = src.charAt(pos++);
            if (c == ',') continue;
            if (c == '}') return m;
            throw err("expected , or } got '" + c + "'");
        }
    }

    private List<Object> readArray() {
        expect('[');
        List<Object> a = new ArrayList<>();
        skipWs();
        if (peek() == ']') { pos++; return a; }
        while (true) {
            Object val = readValue();
            a.add(val);
            skipWs();
            char c = src.charAt(pos++);
            if (c == ',') continue;
            if (c == ']') return a;
            throw err("expected , or ] got '" + c + "'");
        }
    }

    private String readString() {
        expect('"');
        StringBuilder sb = new StringBuilder();
        while (true) {
            if (pos >= src.length()) throw err("unterminated string");
            char c = src.charAt(pos++);
            if (c == '"') return sb.toString();
            if (c == '\\') {
                if (pos >= src.length()) throw err("bad escape");
                char e = src.charAt(pos++);
                switch (e) {
                    case '"': sb.append('"'); break;
                    case '\\': sb.append('\\'); break;
                    case '/': sb.append('/'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case 'n': sb.append('\n'); break;
                    case 'r': sb.append('\r'); break;
                    case 't': sb.append('\t'); break;
                    case 'u':
                        if (pos + 4 > src.length()) throw err("bad \\u escape");
                        sb.append((char) Integer.parseInt(src.substring(pos, pos + 4), 16));
                        pos += 4;
                        break;
                    default: throw err("bad escape \\" + e);
                }
            } else {
                sb.append(c);
            }
        }
    }

    private Boolean readBool() {
        if (src.startsWith("true", pos)) { pos += 4; return Boolean.TRUE; }
        if (src.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
        throw err("bad bool");
    }

    private Object readNull() {
        if (src.startsWith("null", pos)) { pos += 4; return null; }
        throw err("bad null");
    }

    private Object readNumber() {
        int start = pos;
        if (peek() == '-') pos++;
        while (pos < src.length() && isNumberChar(src.charAt(pos))) pos++;
        String tok = src.substring(start, pos);
        if (tok.contains(".") || tok.contains("e") || tok.contains("E")) {
            return Double.valueOf(tok);
        }
        try {
            return Long.valueOf(tok);
        } catch (NumberFormatException ex) {
            return Double.valueOf(tok);
        }
    }

    private static boolean isNumberChar(char c) {
        return (c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-';
    }

    private void expect(char c) {
        if (pos >= src.length() || src.charAt(pos) != c) {
            throw err("expected '" + c + "'");
        }
        pos++;
    }

    private char peek() { return src.charAt(pos); }

    private void skipWs() {
        while (pos < src.length()) {
            char c = src.charAt(pos);
            if (c == ' ' || c == '\n' || c == '\r' || c == '\t') pos++;
            else break;
        }
    }

    private RuntimeException err(String msg) {
        int from = Math.max(0, pos - 20);
        int to = Math.min(src.length(), pos + 20);
        return new RuntimeException("JSON parse error: " + msg + " at pos " + pos
            + " near \"" + src.substring(from, to) + "\"");
    }
}
