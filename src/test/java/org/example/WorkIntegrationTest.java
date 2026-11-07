package org.example;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureObservability
class WorkIntegrationTest {
    @Autowired
    private TestRestTemplate http;

    @Test
    void executesWorkOnTheRequestedThreadType() {
        JsonNode platform = http.getForObject("/work/platform?delayMs=1", JsonNode.class);
        JsonNode virtual = http.getForObject("/work/virtual?delayMs=1", JsonNode.class);
        assertThat(platform.get("virtual").asBoolean()).isFalse();
        assertThat(platform.get("thread").asText()).startsWith("platform-worker-");
        assertThat(virtual.get("virtual").asBoolean()).isTrue();
        assertThat(virtual.get("thread").asText()).startsWith("virtual-worker-");
    }

    @Test
    void actuatorCountsCompletedRequestsAndExportsHistogram() {
        String metric = "/actuator/metrics/http.server.requests?tag=uri:/work/virtual&tag=method:GET";
        http.getForObject("/work/virtual?delayMs=1", String.class);
        await().atMost(Duration.ofSeconds(3)).untilAsserted(() -> {
            JsonNode data = http.getForObject(metric, JsonNode.class);
            assertThat(count(data)).isPositive();
        });
        double before = count(http.getForObject(metric, JsonNode.class));
        http.getForObject("/work/virtual?delayMs=1", String.class);
        await().atMost(Duration.ofSeconds(3)).untilAsserted(() ->
                assertThat(count(http.getForObject(metric, JsonNode.class))).isEqualTo(before + 1));
        String scrape = http.getForObject("/actuator/prometheus", String.class);
        assertThat(scrape).contains("http_server_requests_seconds_count{");
        assertThat(scrape).contains("http_server_requests_seconds_bucket{");
    }

    @Test
    void rejectsInvalidDelayAndCanInjectServerErrorsForRedDashboard() {
        for (String mode : new String[]{"platform", "virtual"}) {
            assertThat(http.getForEntity("/work/" + mode + "?delayMs=0", String.class)
                    .getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
            assertThat(http.getForEntity("/work/" + mode + "?delayMs=5001", String.class)
                    .getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
            assertThat(http.getForEntity("/work/" + mode + "?delayMs=1&fail=true", String.class)
                    .getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        }
    }

    private static double count(JsonNode metric) {
        for (JsonNode measurement : metric.get("measurements")) {
            if ("COUNT".equals(measurement.get("statistic").asText())) {
                return measurement.get("value").asDouble();
            }
        }
        throw new AssertionError("COUNT missing from Actuator response");
    }
}
