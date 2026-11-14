package org.example;

import jakarta.annotation.PreDestroy;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryUsage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Intentionally retains about 1.25 MiB/s; enable only for the GC lab. */
@Component
@Profile("gc-leak")
public class MemoryLeakExperiment implements CommandLineRunner {
    private static final int BLOCK_BYTES = 128 * 1024;
    private static final List<byte[]> RETAINED = new ArrayList<>();

    private final Path metricsPath;
    private Thread loadThread;

    public MemoryLeakExperiment(@Value("${gc.leak.metrics:heap.csv}") String metricsPath) {
        this.metricsPath = Path.of(metricsPath);
    }

    @Override
    public void run(String... args) {
        loadThread = Thread.ofPlatform().name("gc-leak-load").start(this::generateLoad);
    }

    private void generateLoad() {
        try (BufferedWriter metrics = Files.newBufferedWriter(metricsPath)) {
            metrics.write("uptime_seconds,retained_blocks,retained_bytes,heap_used_bytes,heap_committed_bytes,heap_max_bytes\n");
            writeSample(metrics);
            while (!Thread.currentThread().isInterrupted()) {
                // Strong references remain reachable through a static GC root.
                RETAINED.add(new byte[BLOCK_BYTES]);
                if (RETAINED.size() % 10 == 0) {
                    writeSample(metrics);
                }
                Thread.sleep(100);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot record heap samples", e);
        }
    }

    private void writeSample(BufferedWriter metrics) throws IOException {
        MemoryUsage heap = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage();
        metrics.write(String.format(Locale.ROOT, "%.3f,%d,%d,%d,%d,%d%n",
                ManagementFactory.getRuntimeMXBean().getUptime() / 1000.0,
                RETAINED.size(), (long) RETAINED.size() * BLOCK_BYTES,
                heap.getUsed(), heap.getCommitted(), heap.getMax()));
        metrics.flush();
    }

    @PreDestroy
    void stop() {
        if (loadThread != null) {
            loadThread.interrupt();
        }
    }
}
