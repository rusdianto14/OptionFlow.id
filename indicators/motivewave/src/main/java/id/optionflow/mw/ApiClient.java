package id.optionflow.mw;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Minimal HTTP client wrapper that fetches /levels/{underlying} from the
 * OptionFlow API. Uses java.net.http (built into JDK 11+, no extra deps).
 *
 * Authentication: X-API-Key header. The API key and base URL come from study
 * settings (configured by the trader in MotiveWave).
 */
final class ApiClient {

    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(5);
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(8);

    private final HttpClient http;
    private final String baseUrl;
    private final String apiKey;

    ApiClient(String baseUrl, String apiKey) {
        this.baseUrl = baseUrl == null ? "" : stripTrailingSlash(baseUrl.trim());
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.http = HttpClient.newBuilder()
                .connectTimeout(CONNECT_TIMEOUT)
                .followRedirects(HttpClient.Redirect.NORMAL)
                .build();
    }

    LevelsResponse fetchLevels(String underlying) throws Exception {
        if (baseUrl.isEmpty()) {
            throw new IllegalStateException("API base URL is empty");
        }
        if (apiKey.isEmpty()) {
            throw new IllegalStateException("API key is empty");
        }
        if (underlying == null || underlying.isEmpty()) {
            throw new IllegalArgumentException("underlying is empty");
        }

        URI uri = URI.create(baseUrl + "/levels/" + underlying);
        HttpRequest req = HttpRequest.newBuilder(uri)
                .timeout(REQUEST_TIMEOUT)
                .header("X-API-Key", apiKey)
                .header("Accept", "application/json")
                .GET()
                .build();

        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        int code = resp.statusCode();
        if (code == 404) {
            throw new ApiException(404, "no snapshot for " + underlying + " (writer not running yet?)");
        }
        if (code == 401) {
            throw new ApiException(401, "API key rejected");
        }
        if (code < 200 || code >= 300) {
            String body = resp.body() == null ? "" : resp.body();
            int max = Math.min(body.length(), 200);
            throw new ApiException(code, "HTTP " + code + " from " + uri + " body: " + body.substring(0, max));
        }
        return LevelsResponse.fromJson(resp.body());
    }

    private static String stripTrailingSlash(String s) {
        if (s.endsWith("/")) return s.substring(0, s.length() - 1);
        return s;
    }

    static final class ApiException extends Exception {
        private static final long serialVersionUID = 1L;
        final int statusCode;
        ApiException(int code, String msg) {
            super(msg);
            this.statusCode = code;
        }
    }
}
