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

## Пользовательские сценарии JMeter

План [jmeter/api-users.jmx](jmeter/api-users.jmx) использует два существующих
GET-сценария. В этом API нет сущностей и операций POST/PUT, поэтому сценарии
записи не добавлены. Каждый пользователь последовательно вызывает
`/work/platform` и `/work/virtual`, затем повторяет цикл.

| Настройка | Значение по умолчанию |
| --- | --- |
| Thread Group | 10 пользователей, 10 циклов, всего 200 запросов |
| Ramp-up | 20 секунд: новый пользователь примерно каждые 2 секунды |
| Пауза перед каждым запросом | Uniform Random Timer: 500–1500 мс |
| Входные данные | [api-delays.csv](jmeter/api-delays.csv): 20 пар `delayMs` в диапазоне 100–1500 мс |
| HTTP-проверка | Статус строго `200`, перенаправления не скрываются |
| JSON-проверки | `delayMs` совпадает с входом; `virtual` равен `false`/`true`; `thread` соответствует `platform-worker-N`/`virtual-worker-N` |

CSV Data Set Config читает заголовки как имена переменных, выдаёт следующую строку
на каждый цикл и разделяет файл между всеми потоками (`All threads`). После
20 строк чтение начинается заново. Параметры отличаются между пользователями
и циклами; HTTP Cache Manager отсутствует, поэтому JMeter отправляет каждый
запрос на сервер. Keep-Alive включён. `fail=false`: это сценарии успешной работы,
не отдельный эксперимент с ошибками. Данные и паузы моделируют разнообразие
вызовов учебного I/O API; это не профиль реальной аудитории, полученный из логов.

Нужны запущенное приложение (см. выше), JDK 21+ и
[Apache JMeter 5.6.3](https://jmeter.apache.org/download_jmeter.cgi).
Проверьте SHA-512 скачанного ZIP по ссылке Apache и распакуйте его в `.tools`,
чтобы появился `.tools/apache-jmeter-5.6.3/bin/jmeter.bat`. Альтернатива — задать
`JMETER_HOME` или передать `-JMeterHome 'C:/tools/apache-jmeter-5.6.3'`.
Дополнительные плагины JMeter не нужны; Prometheus и Grafana необязательны.

Из корня проекта, обычный прогон и короткая проверка:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-jmeter.ps1
powershell -ExecutionPolicy Bypass -File scripts/run-jmeter.ps1 -Threads 3 -RampUpSeconds 3 -Loops 3 -ThinkTimeMs 100 -ThinkTimeRangeMs 200
```

Скрипт запускает JMeter в CLI, сохраняет `results.jtl`, `jmeter.log` и
`html/index.html` в отдельном каталоге `reports/jmeter/<время>/` на каждый прогон.
JTL включает URL, число активных потоков, CSV-параметры и результат проверок (`success`).
В HTML доступны доля ошибок, throughput, среднее время и перцентили по каждому
сценарию. Скрипт завершается ошибкой при провале запросов/assertions либо неполном
числе результатов, даже если сам JMeter вернул код 0. Генерируемые файлы исключены
из Git. Сервер задаётся через `-TargetHost`, `-Port`, `-Protocol`.

План также можно открыть в GUI: `jmeter.bat -t jmeter/api-users.jmx`.
Относительный путь `api-delays.csv` разрешается относительно JMX; в скрипте
передаётся абсолютный путь. Для отладки можно временно добавить View Results Tree.
Нагрузочные прогоны выполняйте в CLI. Пример прямого запуска из корня проекта
в новый каталог результатов (JMeter должен быть в `PATH`):

```powershell
$run = "reports/jmeter/manual-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
New-Item -ItemType Directory -Path $run -Force | Out-Null
jmeter.bat -n -t jmeter/api-users.jmx -Jthreads=10 -JrampUp=20 -Jloops=10 -l "$run/results.jtl" -j "$run/jmeter.log" -e -o "$run/html"
```

Параметры JMX: `host`, `port`, `protocol`, `threads`, `rampUp`, `loops`,
`thinkTimeMs`, `thinkTimeRangeMs`, `dataFile` задаются через `-Jимя=значение`.
Увеличивая нагрузку, учитывайте очередь пула platform: response timeout 65 секунд
позволяет увидеть и ошибки перегрузки. Этот смешанный пользовательский прогон
не заменяет изолированное сравнение пропускной способности исполнителей.

Результаты основного, короткого и отрицательного прогонов описаны в
[reports/JMETER.md](reports/JMETER.md).

Справка Apache: [Thread Group, CSV, JSON Assertion и таймеры](https://jmeter.apache.org/usermanual/component_reference.html),
[запуск в CLI и HTML-отчёт](https://jmeter.apache.org/usermanual/get-started.html#non_gui).

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

## Утечка памяти и GC

Сценарий включается только профилем `gc-leak`. Компонент
`MemoryLeakExperiment` каждые 100 мс добавляет новый `byte[128 * 1024]`
в статический `List<byte[]>`: номинально 1.25 МиБ/с без учёта заголовков
объектов и списка. Сильные ссылки сохраняются до завершения JVM.
В обычном запуске и в RED-замерах этот компонент отключён.

Из корня проекта:

```powershell
$env:MAVEN_USER_HOME = "$PWD/.cache/maven-user"
.\mvnw.cmd "-Dmaven.repo.local=$PWD/.cache/m2" --batch-mode --no-transfer-progress verify
python scripts/gc_experiment.py
python -m pip install --target .tools/python matplotlib==3.10.7
python scripts/plot_gc.py
```

Скрипт запускает собранное приложение с G1, `-Xms128m -Xmx128m`,
`-XX:+ExitOnOutOfMemoryError` и
`-Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags:filecount=0`.
Рабочий каталог JVM — `reports`, поэтому GC-лог находится в
`reports/gc.log`. Порт эксперимента — `127.0.0.1:18080`; он должен быть свободен.
Prometheus и Grafana для этого сценария не нужны.

Цель — `OutOfMemoryError: Java heap space` примерно через 1–2 минуты.
Ненулевой код завершения дочерней JVM при OOM ожидаем; Python-скрипт
возвращает успех только при подтверждённом сценарии: OOM, Full GC,
рост удерживаемых данных и 60–120 секунд до завершения.
При превышении 150 секунд скрипт останавливает свою JVM и сообщает ошибку.
Время зависит от компьютера и фоновой нагрузки.

Повторный запуск заменяет артефакты именно этого GC-эксперимента:

* `reports/gc.log` — исходные сообщения GC с UTC-смещением и uptime.
* `reports/gc-application.log` — запуск Spring Boot и причина завершения.
* `reports/heap.csv` — heap used/committed/max из `MemoryMXBean` и объём
  удерживаемых массивов примерно раз в секунду; время — uptime JVM.
* `reports/gc-experiment.json` — команда, версия Java, длительность,
  код завершения, образцы heap и разобранные паузы GC.
* `reports/gc-heap.png` — график heap, удерживаемых данных и памяти после GC.

В строках `A M -> B M (128 M)` сравнивайте `B` между сборками:
при утечке уровень памяти после GC растёт и даже Full GC в конце
освобождает мало памяти. `M` в этих строках — МиБ, значения округлены
до целых. Удерживаемые массивы остаются достижимыми, поэтому GC
не может их удалить. Исправление для реального приложения — убрать
неограниченное накопление или ограничить срок жизни/объём коллекции.

График строится по фактическим измерениям JVM; это не снимок VisualVM.
Опционально запустите VisualVM на той же машине и под тем же пользователем,
подключитесь к PID из вывода скрипта и откройте Monitor → Heap.
Не нажимайте Perform GC, если хотите сохранить исходную методику прогона.
Результаты выполненного эксперимента добавлены в [REPORT.md](reports/REPORT.md).

Источники для GC:

* [Java 21: Unified Logging, `-Xlog` и параметры heap](https://docs.oracle.com/en/java/javase/21/docs/specs/man/java.html#enable-logging-with-the-jvm-unified-logging-framework).
* [Java 21: G1, в том числе Full GC при нехватке heap](https://docs.oracle.com/en/java/javase/21/gctuning/garbage-first-g1-garbage-collector1.html).

## Проверки RED и источники

`mvnw verify` выполняет интеграционные проверки фактического типа потоков,
роста COUNT, экспорта гистограммы, валидации входа и HTTP 503.
Конфигурацию контейнеров можно проверить `docker compose config --quiet`.

* [Spring Boot: Actuator metrics](https://docs.spring.io/spring-boot/3.5/reference/actuator/metrics.html)
* [Spring Boot: virtual threads](https://docs.spring.io/spring-boot/3.5/reference/features/spring-application.html#features.spring-application.virtual-threads)
* [Prometheus: rate и histogram_quantile](https://prometheus.io/docs/prometheus/latest/querying/functions/)
* [Grafana: provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
* [Официальная Windows-сборка Grafana и SHA-256](https://grafana.com/grafana/download/13.3.0?edition=oss&platform=windows)
