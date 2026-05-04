package id.optionflow.mw;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class JsonParserTest {

    @Test
    void parsesPrimitives() {
        assertEquals(42L,    JsonParser.parse("42"));
        assertEquals(-1.5,   JsonParser.parse("-1.5"));
        assertEquals("hi",   JsonParser.parse("\"hi\""));
        assertEquals(Boolean.TRUE,  JsonParser.parse("true"));
        assertEquals(Boolean.FALSE, JsonParser.parse("false"));
        assertNull(JsonParser.parse("null"));
    }

    @Test
    void parsesNumberFormats() {
        assertEquals(1.0e10,  ((Number) JsonParser.parse("1e10")).doubleValue());
        assertEquals(1.0e-3,  ((Number) JsonParser.parse("1e-3")).doubleValue(), 1e-12);
        assertEquals(1234567890123L, JsonParser.parse("1234567890123"));
    }

    @Test
    void parsesEscapesInStrings() {
        assertEquals("a\"b",  JsonParser.parse("\"a\\\"b\""));
        assertEquals("a\nb",  JsonParser.parse("\"a\\nb\""));
        assertEquals("\u00e9", JsonParser.parse("\"\\u00e9\""));
    }

    @Test
    @SuppressWarnings("unchecked")
    void parsesNestedStructures() {
        String json = "{\"a\":1,\"b\":[1,2,{\"c\":\"x\"}],\"d\":null}";
        Map<String, Object> m = (Map<String, Object>) JsonParser.parse(json);
        assertEquals(3, m.size());
        assertEquals(1L, m.get("a"));
        List<Object> arr = (List<Object>) m.get("b");
        assertEquals(3, arr.size());
        assertEquals(1L, arr.get(0));
        Map<String, Object> inner = (Map<String, Object>) arr.get(2);
        assertEquals("x", inner.get("c"));
        assertNull(m.get("d"));
    }

    @Test
    void rejectsTrailingGarbage() {
        assertThrows(RuntimeException.class, () -> JsonParser.parse("[1, 2] junk"));
    }
}
