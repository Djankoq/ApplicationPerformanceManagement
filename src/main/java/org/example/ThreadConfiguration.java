package org.example;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ThreadConfiguration {
    @Bean(destroyMethod = "close")
    ExecutorService platformWorkers(@Value("${work.platform-threads:16}") int threads) {
        return Executors.newFixedThreadPool(threads,
                Thread.ofPlatform().name("platform-worker-", 0).factory());
    }

    @Bean(destroyMethod = "close")
    ExecutorService virtualWorkers() {
        return Executors.newThreadPerTaskExecutor(
                Thread.ofVirtual().name("virtual-worker-", 0).factory());
    }
}
