package id.optionflow.mw;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class LevelsResponseTest {

    /**
     * Sample taken from a live SPXW snapshot computed by the Python writer.
     * Shape MUST match {@code src/optionflow/api.py::LevelsResponse}.
     */
    private static final String SAMPLE = """
        {
          "underlying": "SPXW",
          "computed_at": "2026-05-01T18:00:00Z",
          "expiration": "2026-05-01",
          "f_synth": 7251.80,
          "spot_implied": 7251.75,
          "zero_gamma": {
            "value": 7248.90,
            "in_bracket": true,
            "fallback_used": false,
            "note": null
          },
          "call_wall": {"strike": 7340.0, "oi": 30715},
          "put_wall":  {"strike": 5300.0, "oi": 47359},
          "n_major": 3,
          "major_long_gex":  [
            {"strike": 7260.0, "gex":  9.17e10, "by": "volume"},
            {"strike": 7265.0, "gex":  5.82e10, "by": "volume"},
            {"strike": 7270.0, "gex":  5.68e10, "by": "volume"}
          ],
          "major_short_gex": [
            {"strike": 7240.0, "gex": -5.85e10, "by": "volume"},
            {"strike": 7245.0, "gex": -3.97e10, "by": "volume"},
            {"strike": 7235.0, "gex": -3.88e10, "by": "volume"}
          ],
          "diagnostics": {"n_strikes_used": 348}
        }
        """;

    @Test
    void parsesFullSnapshot() {
        LevelsResponse r = LevelsResponse.fromJson(SAMPLE);
        assertEquals("SPXW", r.underlying);
        assertEquals("2026-05-01", r.expiration);
        assertEquals(7251.80, r.fSynth, 1e-6);
        assertEquals(7251.75, r.spotImplied, 1e-6);
        assertNotNull(r.zeroGamma);
        assertEquals(7248.90, r.zeroGamma, 1e-6);
        assertTrue(r.zgInBracket);
        assertFalse(r.zgFallbackUsed);
        assertNull(r.zgNote);
        assertEquals(7340.0, r.callWallStrike);
        assertEquals(30715L, r.callWallOi);
        assertEquals(5300.0, r.putWallStrike);
        assertEquals(47359L, r.putWallOi);
        assertEquals(3, r.nMajor);
        assertEquals(3, r.majorLong.size());
        assertEquals(7260.0, r.majorLong.get(0).strike);
        assertEquals(9.17e10, r.majorLong.get(0).gex, 1e-3);
        assertEquals("volume", r.majorLong.get(0).by);
        assertEquals(3, r.majorShort.size());
        assertEquals(7240.0, r.majorShort.get(0).strike);
        assertEquals(-5.85e10, r.majorShort.get(0).gex, 1e-3);
    }

    @Test
    void handlesNullZeroGamma() {
        String body = SAMPLE.replace("\"value\": 7248.90", "\"value\": null");
        LevelsResponse r = LevelsResponse.fromJson(body);
        assertNull(r.zeroGamma);
    }
}
