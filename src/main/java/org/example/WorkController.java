package org.example;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class WorkController {
    private final ExecutorService platformWorkers;
    private final ExecutorService virtualWorkers;

    public WorkController(@Qualifier("platformWorkers") ExecutorService platformWorkers,
                          @Qualifier("virtualWorkers") ExecutorService virtualWorkers) {
        this.platformWorkers = platformWorkers;
        this.virtualWorkers = virtualWorkers;
    }

    @GetMapping("/work/platform")
    public CompletableFuture<WorkResult> platform(
            @RequestParam(defaultValue = "500") long delayMs,
            @RequestParam(defaultValue = "false") boolean fail) {
        validateDelay(delayMs);
        return CompletableFuture.supplyAsync(() -> blockingWork(delayMs, fail), platformWorkers);
    }

    @GetMapping("/work/virtual")
    public CompletableFuture<WorkResult> virtual(
            @RequestParam(defaultValue = "500") long delayMs,
            @RequestParam(defaultValue = "false") boolean fail) {
        validateDelay(delayMs);
        return CompletableFuture.supplyAsync(() -> blockingWork(delayMs, fail), virtualWorkers);
    }

    private static void validateDelay(long delayMs) {
        if (delayMs < 1 || delayMs > 5000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "delayMs must be 1..5000");
        }
    }

    private static WorkResult blockingWork(long delayMs, boolean fail) {
        try {
            // Controlled model of a blocking database/downstream I/O operation.
            Thread.sleep(delayMs);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Interrupted", e);
        }
        if (fail) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Injected demo error");
        }
        Thread worker = Thread.currentThread();
        return new WorkResult(delayMs, worker.getName(), worker.isVirtual());
    }

    public record WorkResult(long delayMs, String thread, boolean virtual) { }
}
