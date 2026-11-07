# Application Performance Management

Учебный стенд Spring Boot 3.5.7 / Java 21 с Actuator, Prometheus и Grafana.
Два метода выполняют одну блокирующую операцию, имитирующую ожидание внешнего I/O:

| Метод | Исполнитель работы | По умолчанию |
| --- | --- | --- |
| `GET /work/platform` | Пул из 16 обычных потоков | `delayMs=500` |
| `GET /work/virtual` | Новый виртуальный поток на каждую задачу | `delayMs=500` |

Ответ содержит имя рабочего потока и `virtual: true/false`. Параметр
`delayMs` допускает 1–5000 мс; `fail=true` возвращает HTTP 503 после ожидания.
Оба метода возвращают `CompletableFuture`: HTTP-поток не удерживается во время
работы. Общий транспорт Tomcat использует виртуальные потоки, а сравниваются
именно два явно заданных исполнителя в методах. Это исключает общий небольшой
пул HTTP-потоков как ограничитель обоих методов.
Размер обычного пула меняется через `WORK_PLATFORM_THREADS`.

## Запуск в Windows без Docker

Нужны JDK 21+ и Python 3.12+. Команды выполняются из корня проекта:

```powershell
$env:MAVEN_USER_HOME = "$PWD/.cache/maven-user"
.\mvnw.cmd "-Dmaven.repo.local=$PWD/.cache/m2" --batch-mode --no-transfer-progress verify
python scripts/install_monitoring.py
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
python scripts/benchmark.py --with-errors
python scripts/analyze.py
```

Установщик помещает официальные сборки Prometheus 3.16.0 и Grafana OSS 13.3.0
в `.tools`, проверяет SHA-256 и не устанавливает системные службы.
Данные мониторинга и логи находятся в `.run`. Скрипт запуска оставляет три
локальных процесса работающими; остановка:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop-local.ps1
```

После первого запуска можно собирать и запускать одной командой:
`powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1 -Build`.

## Запуск через Docker Compose

При работающем Docker Engine с Linux-контейнерами:

```powershell
docker compose up --build -d
python scripts/benchmark.py --with-errors
python scripts/analyze.py
docker compose down
```

В Compose приложение собирается из исходников. Данные Prometheus/Grafana
сохраняются в именованных volumes. Одновременно запускайте только один вариант
стенда: порты у них одинаковые.

| Сервис | Адрес |
| --- | --- |
| Приложение | http://127.0.0.1:8080/actuator/health |
| Метрики Actuator | http://127.0.0.1:8080/actuator/metrics/http.server.requests |
| Экспорт Prometheus | http://127.0.0.1:8080/actuator/prometheus |
| Prometheus targets | http://127.0.0.1:9090/targets |
| Grafana RED dashboard | http://127.0.0.1:3000/d/apm-red |

Grafana автоматически получает источник данных и dashboard из
`monitoring/grafana`; доступ к просмотру локального учебного стенда анонимный.
Все опубликованные порты ограничены loopback.

## Измерение COUNT за 10 секунд

Фактический адрес метрики: `/actuator/metrics/http.server.requests`.
`COUNT` — поле в массиве `measurements`, отдельного endpoint `/count` нет.
Счётчик появляется после первого завершённого запроса.

Для ручной проверки долгого запроса:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8080/work/platform?delayMs=5000'
Invoke-RestMethod 'http://127.0.0.1:8080/work/virtual?delayMs=5000'
```

Во время непрерывной нагрузки для обычных потоков:

```powershell
$url = 'http://127.0.0.1:8080/actuator/metrics/http.server.requests?tag=uri:/work/platform&tag=method:GET'
$first = Invoke-RestMethod $url
$c1 = ($first.measurements | Where-Object statistic -eq 'COUNT').value
Start-Sleep -Seconds 10
$second = Invoke-RestMethod $url
$c2 = ($second.measurements | Where-Object statistic -eq 'COUNT').value
($c2 - $c1) / 10
```

Повторите с `uri:/work/virtual`. Считаются завершённые запросы данного метода,
включая ошибочные. Без параллельной нагрузки один долгий запрос не показывает
предельную пропускную способность.

`scripts/benchmark.py` автоматизирует процедуру: 64 постоянных клиента,
6 секунд прогрева, два чтения COUNT с интервалом 10 секунд и завершение
оставшихся запросов перед переключением метода. Измеряет реальный интервал
монотонными часами; сохраняет формулы и исходные ответы Actuator в
`reports/benchmark.json`. HTTP-вызовы мониторинга исключены фильтром URI.
Основные замеры выполняются без ошибок. Опция `--with-errors` добавляет
отдельные фазы, в которых каждый клиент посылает каждый десятый запрос с
`fail=true`. Их результаты не подменяют основные замеры.

```text
throughput = (COUNT_2 - COUNT_1) / (t_2 - t_1)   [запросов/с]
```

Точность 10-секундного окна ограничена временем двух чтений Actuator.
Сырые снимки содержат длительность чтения, UTC и COUNT; для сравнения также
сохраняется результат деления на номинальные 10 секунд. COUNT и TOTAL_TIME
читаются Actuator последовательно, поэтому средняя Duration из их разностей
имеет небольшую погрешность при продолжающейся нагрузке.

## Rate, Errors, Duration

Prometheus опрашивает `/actuator/prometheus` каждые 2 секунды. В Grafana
используется `$__rate_interval`, минимум четыре scrape-интервала.
Каждая панель показывает отдельные серии по URI.

* **Rate**: `sum by (uri) (rate(http_server_requests_seconds_count{job="apm-lab",uri=~"/work/(platform|virtual)",method="GET"}[$__rate_interval]))`.
* **Errors**: аналогичный `rate` с `status=~"5.."`; отдельная панель делит
  ошибки на все запросы и показывает процент. До первой ошибки выводится 0;
  при отсутствии трафика процент имеет разрыв.
* **Duration mean**: `rate(..._sum) / rate(..._count)` в секундах.
* **Duration p95**: `histogram_quantile(0.95, sum by (le, uri) (rate(..._bucket[$__rate_interval])))`.
  Это приближение по гистограмме. Среднее и p95 включают ожидание очереди.
* **Application scrape health**: `up{job="apm-lab"}`.

`scripts/analyze.py` проверяет targets и provisioned dashboard, выполняет
запросы через источник данных Grafana, сохраняет временные ряды и формирует
[отчёт о выполненном замере](reports/REPORT.md). Для просмотра исторического
прогона используйте абсолютный временной диапазон из отчёта: текущий диапазон
после остановки нагрузки показывает нулевую Rate.

Для экспорта тех же временных рядов в отдельный PNG:

```powershell
python -m pip install --target .tools/python matplotlib==3.10.7
python scripts/plot.py
```

Полученный `reports/red-metrics.png` — график по данным источника Grafana,
а не снимок её интерфейса.

Ожидаемое ограничение обычного пула при 500 мс: `16 / 0.5 = 32 запросов/с`.
Для 64 одновременно ожидающих клиентов без ограничения исполнителя:
`64 / 0.5 = 128 запросов/с` до накладных расходов.
Это сравнение конкретного пула и конкретной I/O-модели. Увеличение обычного
пула изменит результат; для вычислений на CPU такой выигрыш не следует
из свойств виртуальных потоков. Один прогон не заменяет статистическое
исследование; параметры можно менять аргументами нагрузочного скрипта.

## Проверки и источники

`mvnw verify` выполняет интеграционные проверки фактического типа потоков,
роста COUNT, экспорта гистограммы, валидации входа и HTTP 503.
Конфигурацию контейнеров можно проверить `docker compose config --quiet`.

* [Spring Boot: Actuator metrics](https://docs.spring.io/spring-boot/3.5/reference/actuator/metrics.html)
* [Spring Boot: virtual threads](https://docs.spring.io/spring-boot/3.5/reference/features/spring-application.html#features.spring-application.virtual-threads)
* [Prometheus: rate и histogram_quantile](https://prometheus.io/docs/prometheus/latest/querying/functions/)
* [Grafana: provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
* [Официальная Windows-сборка Grafana и SHA-256](https://grafana.com/grafana/download/13.3.0?edition=oss&platform=windows)
