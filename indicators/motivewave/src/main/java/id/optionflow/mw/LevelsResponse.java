package id.optionflow.mw;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * In-memory representation of a /levels/{underlying} response.
 *
 * Field shape (from src/optionflow/api.py):
 *   underlying       : "SPXW" or "NDXP"
 *   computed_at      : ISO-8601 timestamp string
 *   expiration       : "YYYY-MM-DD"
 *   f_synth          : double — synthetic forward in cash space
 *   spot_implied     : double
 *   zero_gamma       : { value: double|null, in_bracket: bool, fallback_used: bool, note: string|null }
 *   call_wall        : { strike: double, oi: long }
 *   put_wall         : { strike: double, oi: long }
 *   n_major          : int
 *   major_long_gex   : [ { strike: double, gex: double, by: "volume" }, ... ]
 *   major_short_gex  : [ { strike: double, gex: double, by: "volume" }, ... ]
 *   diagnostics      : { ... }  (opaque, kept as-is)
 */
final class LevelsResponse {
    final String underlying;
    final String computedAt;
    final String expiration;
    final double fSynth;
    final double spotImplied;
    final Double zeroGamma;             // null if no root found
    final boolean zgInBracket;
    final boolean zgFallbackUsed;
    final String zgNote;
    final double callWallStrike;
    final long callWallOi;
    final double putWallStrike;
    final long putWallOi;
    final int nMajor;
    final List<MajorLevel> majorLong;
    final List<MajorLevel> majorShort;

    LevelsResponse(String underlying, String computedAt, String expiration,
                   double fSynth, double spotImplied,
                   Double zeroGamma, boolean zgInBracket, boolean zgFallbackUsed, String zgNote,
                   double callWallStrike, long callWallOi,
                   double putWallStrike, long putWallOi,
                   int nMajor,
                   List<MajorLevel> majorLong, List<MajorLevel> majorShort) {
        this.underlying = underlying;
        this.computedAt = computedAt;
        this.expiration = expiration;
        this.fSynth = fSynth;
        this.spotImplied = spotImplied;
        this.zeroGamma = zeroGamma;
        this.zgInBracket = zgInBracket;
        this.zgFallbackUsed = zgFallbackUsed;
        this.zgNote = zgNote;
        this.callWallStrike = callWallStrike;
        this.callWallOi = callWallOi;
        this.putWallStrike = putWallStrike;
        this.putWallOi = putWallOi;
        this.nMajor = nMajor;
        this.majorLong = majorLong;
        this.majorShort = majorShort;
    }

    static final class MajorLevel {
        final double strike;
        final double gex;
        final String by;

        MajorLevel(double strike, double gex, String by) {
            this.strike = strike;
            this.gex = gex;
            this.by = by;
        }
    }

    @SuppressWarnings("unchecked")
    static LevelsResponse fromJson(String body) {
        Object root = JsonParser.parse(body);
        if (!(root instanceof Map)) {
            throw new RuntimeException("levels response is not a JSON object");
        }
        Map<String, Object> m = (Map<String, Object>) root;

        String underlying = asString(m, "underlying");
        String computedAt = asString(m, "computed_at");
        String expiration = asString(m, "expiration");
        double fSynth = asDouble(m, "f_synth");
        double spotImplied = asDouble(m, "spot_implied");

        Map<String, Object> zg = asMap(m, "zero_gamma");
        Double zgValue = (zg.get("value") == null) ? null : ((Number) zg.get("value")).doubleValue();
        boolean inBracket = asBool(zg, "in_bracket");
        boolean fallback = asBool(zg, "fallback_used");
        String zgNote = (zg.get("note") == null) ? null : (String) zg.get("note");

        Map<String, Object> cw = asMap(m, "call_wall");
        Map<String, Object> pw = asMap(m, "put_wall");
        double cwStrike = asDouble(cw, "strike");
        long cwOi = asLong(cw, "oi");
        double pwStrike = asDouble(pw, "strike");
        long pwOi = asLong(pw, "oi");

        int nMajor = (int) asLong(m, "n_major");

        List<MajorLevel> ml = readMajors((List<Object>) m.get("major_long_gex"));
        List<MajorLevel> ms = readMajors((List<Object>) m.get("major_short_gex"));

        return new LevelsResponse(underlying, computedAt, expiration, fSynth, spotImplied,
                zgValue, inBracket, fallback, zgNote,
                cwStrike, cwOi, pwStrike, pwOi,
                nMajor, ml, ms);
    }

    @SuppressWarnings("unchecked")
    private static List<MajorLevel> readMajors(List<Object> arr) {
        List<MajorLevel> out = new ArrayList<>();
        if (arr == null) return out;
        for (Object o : arr) {
            Map<String, Object> e = (Map<String, Object>) o;
            double strike = asDouble(e, "strike");
            double gex = asDouble(e, "gex");
            String by = (String) e.get("by");
            out.add(new MajorLevel(strike, gex, by == null ? "volume" : by));
        }
        return out;
    }

    private static String asString(Map<String, Object> m, String k) {
        Object v = m.get(k);
        if (v == null) throw new RuntimeException("missing field: " + k);
        return v.toString();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Map<String, Object> m, String k) {
        Object v = m.get(k);
        if (v == null) throw new RuntimeException("missing field: " + k);
        return (Map<String, Object>) v;
    }

    private static double asDouble(Map<String, Object> m, String k) {
        Object v = m.get(k);
        if (v == null) throw new RuntimeException("missing field: " + k);
        return ((Number) v).doubleValue();
    }

    private static long asLong(Map<String, Object> m, String k) {
        Object v = m.get(k);
        if (v == null) throw new RuntimeException("missing field: " + k);
        return ((Number) v).longValue();
    }

    private static boolean asBool(Map<String, Object> m, String k) {
        Object v = m.get(k);
        if (v == null) return false;
        return ((Boolean) v).booleanValue();
    }
}
