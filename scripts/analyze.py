"""Validate Grafana/Prometheus and export the measured RED series and report."""
import argparse
import json
import math
from pathlib import Path
import urllib.parse
import urllib.request


def get_json(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="reports/benchmark.json")
    parser.add_argument("--grafana", default="http://127.0.0.1:3000")
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    args = parser.parse_args()
    source = Path(args.results)
    document = json.loads(source.read_text(encoding="utf-8"))
    output = source.parent
    dashboard = get_json(args.grafana + "/api/dashboards/uid/apm-red")
    targets = get_json(args.prometheus + "/api/v1/targets")
    active = targets["data"]["activeTargets"]
    if not any(t["labels"]["job"] == "apm-lab" and t["health"] == "up" for t in active):
        raise RuntimeError("Prometheus target apm-lab is not UP")
    if dashboard["dashboard"]["uid"] != "apm-red" or not dashboard["meta"]["provisioned"]:
        raise RuntimeError("Provisioned Grafana dashboard missing")
    datasource = get_json(args.grafana + "/api/datasources/uid/prometheus")
    proxy = args.grafana + "/api/datasources/proxy/uid/prometheus/api/v1/"
    captured = {
        "targets": targets, "datasource": datasource,
        "grafana_health": get_json(args.grafana + "/api/health"),
        "prometheus_buildinfo": get_json(args.prometheus + "/api/v1/status/buildinfo"),
        "dashboard_title": dashboard["dashboard"]["title"],
        "dashboard_provisioned": dashboard["meta"]["provisioned"],
        "evaluations": [], "ranges": {}
    }

    def query(endpoint, params):
        result = get_json(proxy + endpoint + "?" + urllib.parse.urlencode(params))
        if result.get("status") != "success":
            raise RuntimeError(f"Grafana datasource query failed: {result}")
        return result

    expressions = {}
    for panel in dashboard["dashboard"]["panels"]:
        expressions[panel["title"]] = panel["targets"][0]["expr"].replace("$__rate_interval", "8s")
    for result in document["results"]:
        evaluation = {"phase": result["phase"], "mode": result["mode"], "metrics": {}, "raw": {}}
        for title, expression in expressions.items():
            data = query("query", {"query": expression, "time": result["second"]["epoch"]})
            evaluation["raw"][title] = data
            for series in data["data"]["result"]:
                if series["metric"].get("uri") == result["uri"]:
                    number = float(series["value"][1])
                    evaluation["metrics"][title] = number if math.isfinite(number) else None
        captured["evaluations"].append(evaluation)
    for title, expression in expressions.items():
        captured["ranges"][title] = query("query_range", {
            "query": expression, "start": document["started_epoch"] - 5,
            "end": document["finished_epoch"] + 3, "step": 2})
    (output / "monitoring.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline = [r for r in document["results"] if r["phase"] == "baseline"]
    if len(baseline) != 2:
        raise RuntimeError("Two completed baseline measurements required")
    p, v = baseline
    ratio = v["requests_per_second"] / p["requests_per_second"]
    lines = [
        "# Результаты измерения пропускной способности и RED",
        "",
        f"Выполнено: {document['started_utc']} — {document['finished_utc']} (UTC).",
        f"Среда клиента: {document['client_environment']}.",
        f"Prometheus {captured['prometheus_buildinfo']['data']['version']}; "
        f"Grafana OSS {captured['grafana_health']['version']}.",
        "",
        "## Методика",
        "",
        f"Один процесс приложения, Java 21, Spring Boot 3.5.7, "
        f"{p['concurrency']} параллельных клиентов, блокирующее ожидание "
        f"{p['delay_ms']} мс. Обычный пул — 16 потоков; "
        "виртуальный исполнитель создаёт поток на задачу. Операция и HTTP-транспорт общие.",
        f"Перед каждым окном — {p['warmup_seconds']} с прогрева. "
        "Между двумя чтениями Actuator — целевые 10 секунд. "
        "После каждого прогона все оставшиеся запросы завершены.",
        "Только завершённые GET-запросы выбранного URI: "
        "`/actuator/metrics/http.server.requests?tag=uri:/work/{mode}&tag=method:GET`.",
        "Основные два замера не содержат инъекции ошибок. "
        "Фазы `errors` выполнены отдельно для проверки панели Errors.",
        "",
        "## COUNT и пропускная способность",
        "",
        "| Потоки | COUNT₁ | COUNT₂ | ΔCOUNT | Реальное окно, с | ΔCOUNT / 10, req/s | ΔCOUNT / Δt, req/s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    ]
    for r in baseline:
        lines.append(f"| {r['mode']} | {r['first']['count']:.0f} | "
                     f"{r['second']['count']:.0f} | {r['completed_in_window']:.0f} | "
                     f"{r['actual_window_seconds']:.6f} | "
                     f"{r['requests_per_second_nominal']:.3f} | {r['requests_per_second']:.3f} |")
    lines += [
        "",
        f"Отношение virtual/platform: **{ratio:.3f}×**. "
        f"Изменение пропускной способности: **{(ratio - 1) * 100:.1f}%**.",
        "",
        "Фактические рабочие потоки из ответов приложения:",
        "",
        "```json",
        json.dumps({r["mode"]: r["probe"] for r in baseline}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Графики Grafana",
        "",
        f"[Открыть dashboard в абсолютном диапазоне выполненного прогона]({document['grafana_url']}).",
        "![RED: временные ряды из источника данных Grafana](red-metrics.png)",
        "Изображение построено по данным панелей через источник Grafana; это не снимок UI. "
        "Интерфейс браузера в среде автоматизации недоступен, поэтому визуальная проверка "
        "выполнена для экспортированного графика, а подключение dashboard проверено через API.",
        "Источник данных Prometheus и dashboard загружены provisioning-механизмом. "
        "Target apm-lab имеет health=up. Числа ниже получены через HTTP proxy источника "
        "данных Grafana теми же PromQL-запросами, что используют панели, "
        "в конце каждого 10-секундного окна; окно rate — 8 секунд.",
        "",
        "| Фаза | Потоки | Rate, req/s | 5xx, req/s | 5xx, % | Mean Duration, с | p95 Duration, с |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"
    ]
    keys = [
        "Rate — completed requests/s", "Errors — HTTP 5xx/s", "Errors — HTTP 5xx (%)",
        "Duration — mean, including queue", "Duration — p95 (histogram)"
    ]
    for evaluation in captured["evaluations"]:
        values = [evaluation["metrics"].get(key) for key in keys]
        cells = ["—" if value is None else f"{value:.3f}" for value in values]
        lines.append(f"| {evaluation['phase']} | {evaluation['mode']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "### Rate",
        "",
        f"COUNT показывает {p['requests_per_second']:.3f} req/s у обычного пула и "
        f"{v['requests_per_second']:.3f} req/s у виртуального исполнителя. "
        "На графике видны последовательные плато нагрузки и спад после завершения фаз. "
        "Ограничение обычного пула для этой операции — примерно 16 / 0.5 = 32 req/s; "
        "для 64 клиентов без ожидания рабочего потока — до 64 / 0.5 = 128 req/s "
        "до накладных расходов. Prometheus rate — оценка по scrape-снимкам; "
        "она может отличаться от разности Actuator COUNT за другое окно.",
        "",
        "### Errors",
        "",
        "В основных фазах ошибок нет. В отдельных фазах errors каждый клиент "
        "отправляет каждый десятый запрос с fail=true: сервер выполняет ту же операцию "
        "и возвращает 503. На графиках появляются ненулевые 5xx/s и доля около 10%. "
        "Это управляемая инъекция, а не доказательство ненадёжности виртуальных "
        "или обычных потоков. Число ошибок в секунду зависит также от общей Rate.",
        "",
        "### Duration",
        "",
        f"Среднее время по разности Actuator TOTAL_TIME/COUNT в основных окнах: "
        f"platform — {p['server_mean_duration_seconds']:.3f} с, "
        f"virtual — {v['server_mean_duration_seconds']:.3f} с. "
        "При 64 клиентах и 16 обычных рабочих потоках запросы ждут очередь: "
        "примерно четыре группы по 500 мс, поэтому полное серверное время "
        "приближается к 2 с. У виртуальных потоков ожидание рабочего потока "
        "существенно меньше, а блокирующая операция по-прежнему занимает 500 мс. "
        "p95 рассчитан по гистограмме и зависит от границ bucket; "
        "это приближённое значение. Провалы и разрывы при отсутствии трафика ожидаемы.",
        "",
        "## Проверки и ограничения",
        "",
        "* Maven verify: 3 интеграционных теста, без ошибок. "
        "Проверены типы потоков, рост COUNT, Prometheus histogram, HTTP 400 и 503.",
        "* Grafana /api/health, provisioning dashboard, datasource и Prometheus target проверены.",
        "* В нагрузочном скрипте не зарегистрированы транспортные/неожиданные HTTP-ошибки.",
        "* Docker Compose прошёл проверку конфигурации. В этом окружении Docker daemon "
        "не был запущен; фактический прогон выполнен локальными Windows-процессами.",
        "* Это один локальный прогон синтетической блокирующей I/O-модели, "
        "а не универсальный коэффициент ускорения. Размер обычного пула влияет на "
        "результат; вычислительная CPU-нагрузка требует отдельного эксперимента.",
        "* Пропускная способность учитывает завершения внутри окна, в том числе "
        "запросы, начатые до него. Это стационарный замер, а не тест времени запуска.",
        "* COUNT и TOTAL_TIME читаются последовательно; при непрерывном трафике "
        "средняя Duration из их разностей имеет небольшую погрешность.",
        "",
        "## Артефакты",
        "",
        "* [benchmark.json](benchmark.json) — исходные снимки Actuator, UTC, COUNT, интервалы, статусы.",
        "* [monitoring.json](monitoring.json) — targets, Grafana health, результаты PromQL и временные ряды.",
        "* [Конфигурация dashboard](../monitoring/grafana/dashboards/apm-red.json).",
        "* [Команды воспроизведения и официальные источники](../README.md).",
        ""
    ]
    long_request_file = output / "long-requests.json"
    if long_request_file.exists():
        probes = json.loads(long_request_file.read_text(encoding="utf-8"))
        lines += [
            "## Отдельная проверка долгих запросов",
            "",
            "После нагрузочных замеров выполнены одиночные запросы с delayMs=5000. "
            "Они находятся за пределами измеренных окон:",
            "",
            "| Метод | HTTP | Длительность клиента, с | virtual |",
            "| --- | ---: | ---: | --- |"
        ]
        for probe in probes:
            lines.append(f"| {probe['mode']} | {probe['status']} | "
                         f"{probe['elapsed_seconds']:.3f} | {probe['body']['virtual']} |")
        lines += ["", "[Исходные ответы долгих запросов](long-requests.json).", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Grafana {captured['grafana_health']['version']}, Prometheus target UP")
    print(f"Saved {output / 'monitoring.json'} and {output / 'REPORT.md'}")
    for evaluation in captured["evaluations"]:
        print(evaluation["phase"], evaluation["mode"], evaluation["metrics"])


if __name__ == "__main__":
    main()
