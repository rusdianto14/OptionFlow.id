package id.optionflow.mw;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test using {@link com.sun.net.httpserver.HttpServer} (built into
 * the JDK) to exercise the ApiClient against a real local HTTP endpoint that
 * mimics the OptionFlow REST API. No network/DB required.
 */
class ApiClientTest {

    private static final String SAMPLE_BODY = """
        {
          "underlying": "SPXW",
          "computed_at": "2026-05-01T18:00:00Z",
          "expiration": "2026-05-01",
          "f_synth": 7251.80,
          "spot_implied": 7251.75,
          "zero_gamma": {"value": 7248.90, "in_bracket": true, "fallback_used": false, "note": null},
          "call_wall": {"strike": 7340.0, "oi": 30715},
          "put_wall":  {"strike": 5300.0, "oi": 47359},
          "n_major": 3,
          "major_long_gex":  [{"strike": 7260.0, "gex": 9.17e10, "by": "volume"}],
          "major_short_gex": [{"strike": 7240.0, "gex": -5.85e10, "by": "volume"}],
          "diagnostics": {"n_strikes_used": 348}
        }
        """;

    private HttpServer server;
    private int port;
    private final AtomicReference<String> lastApiKeyHeader = new AtomicReference<>();

    @BeforeEach
    void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/levels/SPXW", this::handleLevels);
        server.createContext("/levels/MISSING", ex -> {
            ex.sendResponseHeaders(404, 0);
            ex.close();
        });
        server.createContext("/levels/UNAUTH", ex -> {
            ex.sendResponseHeaders(401, 0);
            ex.close();
        });
        server.start();
        port = server.getAddress().getPort();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private void handleLevels(HttpExchange ex) throws java.io.IOException {
        lastApiKeyHeader.set(ex.getRequestHeaders().getFirst("X-API-Key"));
        byte[] body = SAMPLE_BODY.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    @Test
    void fetchesAndParsesLevels() throws Exception {
        ApiClient client = new ApiClient("http://127.0.0.1:" + port, "test-key");
        LevelsResponse r = client.fetchLevels("SPXW");
        assertEquals("SPXW", r.underlying);
        assertEquals(7251.80, r.fSynth, 1e-6);
        assertEquals("test-key", lastApiKeyHeader.get(), "X-API-Key header must be sent");
    }

    @Test
    void mapsHttp404ToApiException() {
        ApiClient client = new ApiClient("http://127.0.0.1:" + port, "test-key");
        ApiClient.ApiException ex = assertThrows(ApiClient.ApiException.class,
                () -> client.fetchLevels("MISSING"));
        assertEquals(404, ex.statusCode);
    }

    @Test
    void mapsHttp401ToApiException() {
        ApiClient client = new ApiClient("http://127.0.0.1:" + port, "test-key");
        ApiClient.ApiException ex = assertThrows(ApiClient.ApiException.class,
                () -> client.fetchLevels("UNAUTH"));
        assertEquals(401, ex.statusCode);
    }

    @Test
    void rejectsEmptyBaseUrl() {
        ApiClient client = new ApiClient("", "test-key");
        assertThrows(IllegalStateException.class, () -> client.fetchLevels("SPXW"));
    }

    @Test
    void rejectsEmptyApiKey() {
        ApiClient client = new ApiClient("http://127.0.0.1:" + port, "");
        assertThrows(IllegalStateException.class, () -> client.fetchLevels("SPXW"));
    }

    @Test
    void stripsTrailingSlashFromBaseUrl() throws Exception {
        ApiClient client = new ApiClient("http://127.0.0.1:" + port + "/", "test-key");
        LevelsResponse r = client.fetchLevels("SPXW");
        assertEquals("SPXW", r.underlying);
    }
}
