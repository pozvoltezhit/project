# Финальная оптимизация: измерения и ограничения

## Актуальное исправление LLM: evidence-select-v4

Image `876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e`, bundle `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`. Исходный workload/корпус/индекс/модель/serving/hardware сохранены; перед каждым отдельно8 warmup, server profiler выключен, capacity не совмещалась с тестами/сборками. Изменился контракт: модель выбирает короткие source IDs вместо перепечатывания цитат; сервер восстанавливает точный текст и выполняет прежнюю final authorization. Повторных генераций нет. Все selector HTTP ответы mode=vllm, ошибки0; качество выбранных доказательств проверено отдельно, не по одной метке режима.

| Вариант | N/C | RPS | p50 мс | p95 мс | p99 мс |
|---|---:|---:|---:|---:|---:|
| Повтор baseline v2 | 48/4 | 2,52 | 1574,03 | 1632,45 | 1670,07 |
| Повтор baseline v2 | 192/4 | 2,48 | 1597,78 | 1685,90 | 1769,03 |
| Selector | 48/4 | **8,66** | 428,39 | **690,80** | 728,64 |
| Selector | 192/4 | **9,32** | 416,92 | **468,75** | 834,10 |

Относительно исторического2,53 RPS/p95=1631,63 ms: 48/C4 throughput×3,42, p95−57,66%. На одинаковом повторном192/C4 — ×3,76 и −72,20%. vLLM before/after counters подтверждают ровно N генераций на N HTTP запросов и415/18 input/output tokens per selector primary answer против396/110 baseline. Это single-run тёплый повторяющийся workload, не soak/mixed-corpus capacity. Host GPU CSV для прямых selected запусков не собирался; HTTP raw samples и реальные model counters сохранены.

Артефакты: `evidence/llm-quality-20261020/{baseline,selected}/gpu-*.json`, `*-samples.json`, `*-{before,after}.prom`, `performance-summary.json`. Причина и неудачный prompt-only вариант — [LLM investigation](LLM-QUALITY-INVESTIGATION.md). Учебный release после полного same-bundle прогона — GO, production — HOLD. CPU capacity заново не измерялась: старое20,80 RPS относится к предыдущей итерации. Ниже сохранена история оптимизации WAL/HTTP.

## История предыдущей итерации

20.10.2026. Все новые raw результаты — `evidence/final-20261020/`. Основной workload сохранён: HTTP client внутри backend → Nginx gateway → API, вопрос «Как связан насос Н-17 с датчиком Д-8?», engineer-b, один неизменный synthetic corpus. CPU — 300/C8, GPU — сначала 48/C4, затем C1/C2/C4. Перед каждым измерением отдельно 8 warmup requests. Нагрузочные прогоны последовательны; integration/eval/сборка/установка зависимостей с ними не совмещались.

## Артефакты и конфигурация

Baseline image `sha256:6ee26fe97239ead672a5fabb03b995d6e22584485dfa96cf5b36862a00274e1e` действительно совпал с исходным application bundle `bc4d439567d13f277a9091875f4c9c031538b0a350e28282393617a420f9932f` (два baseline bundle JSON). Candidate — `sha256:2945daf417c2ff073a4cb3be97bbb5036fae0936710ee09545cac429459bd3bd`, application bundle `8e3e74e7f989c83ff6f74b523f4e422cc2fada83e218fc27dfab11a4dfebf03c`. Commit отсутствует; существующие Git index/worktree не сбрасывались. Полный source/config/test delivery имеет отдельную SHA inventory, поскольку application bundle намеренно не включает инструменты/infra/docs.

Serving одинаковый во всех основных A/B: Qwen2.5-7B-Instruct-AWQ, revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`, vLLM 0.10.2, AWQ Marlin, half, context 4096, max-num-seqs 4, max-num-batched-tokens 1024, gpu-memory-utilization .80, prefix caching включён. Temperature 0, output reserve/max_tokens 700, margin 64, prompt evidence-v2. Tokenizer/chat template — те же локальные model artifacts. В baseline/candidate основном вопросе input=396, output=110 tokens; никаких внешних inference API или mock GPU.

RTX4070 12282 MiB, driver 617.42; Docker Desktop 29.9.1, WSL2 kernel 6.18.33.2, 28 доступных CPU, MemTotal 33494319104 bytes. Модель смонтирована read-only; VRAM budget не повышался. Привязки/args/model hashes/index release и source inventory сохранены в machine-readable evidence. Derived index создан только в новом namespace. Между A/B он не перестраивался; active collection/version — `candidate/active-index.json`. Corpus/dataset/prompt hashes дополнительно находятся в обоих evaluation JSON и release manifest.

## Сопоставление с историей

| Профиль / этап | N/C | RPS | p50 ms | p95 ms | p99 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|
| CPU до remediation | 300/8 | 6.38 | 1161.20 | 1526.88 | 3812.60 | 0 |
| CPU после remediation | 300/8 | 6.70 | 1118.49 | 1497.26 | 2913.73 | 0 |
| CPU fresh baseline этой итерации | 300/8 | 7.49 | 1017.97 | 1421.58 | 1735.24 | 0 |
| CPU candidate, без server profiler | 300/8 | 20.80 | 374.56 | 474.02 | 526.36 | 0 |
| GPU до remediation | 48/4 | 2.44 | 1589.89 | 2085.22 | 2102.74 | 0 |
| GPU после remediation | 48/4 | 1.81 | 2174.23 | 2319.26 | 2349.25 | 0 |
| GPU fresh baseline A1/A2/A3, median показателей | 48/4 ×3 | 2.24 | 1766.55 | 1851.54 | 1955.91 | 0 |
| GPU candidate R1/R2/R3, median показателей | 48/4 ×3 | 2.52 | 1578.33 | 1669.54 | 1691.21 | 0 |
| GPU candidate без server profiler | 48/4 | 2.53 | 1572.59 | 1631.63 | 1658.46 | 0 |
| GPU candidate более длинный прогон | 192/4 | 2.55 | 1560.38 | 1628.33 | 1652.65 | 0 |

Исторические исходники чисел: `Аудит-проекта-2026-10-20/evidence/benchmark-{cpu,gpu}.json` и прежние `docs/remediation/evidence/benchmark-{cpu,gpu}.json`. Старые результаты не перезаписаны. Исторический corpus имеет другое состояние/IDs/версии: в старых GPU reports mode=vllm, в fresh baseline и candidate primary query — extractive-invalid-generation после реального inference. Поэтому исторические столбцы — ориентир, не строгий причинный A/B. Уже исходный старый image в новой сессии даёт 2.18–2.25 вместо исторических 1.81 RPS без изменения кода: всю историческую разницу приписывать оптимизации нельзя.

На текущей одинаковой нагрузке GPU median RPS +12.5%, median p95 −9.8%. Один unprofiled candidate даёт +12.9% RPS и −11.9% p95 относительно median fresh baseline; это подтверждение отсутствия большого profiler overhead, а не более сильная статистическая оценка. CPU — +177.7% RPS / −66.7% p95 относительно fresh baseline, но всего один before/after CPU run. Условный SLO p95≤5000 ms при C4 выполнен во всех этих GPU runs; production capacity этим не доказана.

## Контролируемый WAL эксперимент

На одном исходном image опциональный числовой profiler менял единственный фактор: существование одного idle autocommit SQLite connection на время Agent.run. Никакие авторизационные результаты в нём не хранятся. Порядок: A1/A2 → C1/C2 baseline → B1/B2 → A3 → B3; перед каждым run отдельный warmup, модель остаётся загруженной. Исходные A/B файлы и профили сохранены отдельно.

| Вариант | RPS | p95 ms | Решение |
|---|---:|---:|---|
| A1, исходный | 2.18 | 1936.54 | baseline |
| A2, исходный | 2.25 | 1851.54 | baseline |
| B1, только keeper | 2.59 | 1591.76 | кандидат |
| B2, только keeper | 2.53 | 1635.04 | повтор |
| A3, убрать keeper | 2.24 | 1845.05 | slowdown вернулся |
| B3, вернуть keeper | 2.55 | 1607.86 | выигрыш вернулся |

Результат B не объясняется только единичным удачным p95: диапазоны трёх RPS не перекрылись, reversal восстановил исходные задержки. Тем не менее это короткие зависимые последовательные runs на рабочей GPU, не randomized controlled trial и не формальный confidence interval.

В A1 mean generation=1438.49 ms, tokenize=4.68 ms, Store.record=54.47 ms, finalize=61.50 ms, cumulative connection/process-lock wait=218.34 ms на request. В B1 generation=1422.18 ms, tokenize остаётся одним вызовом, record=16.07 ms, finalize=23.82 ms, cumulative connection/process-lock wait=60.27 ms. SQL execute API time упало с 71.86 до 25.01 ms, commit/rollback с 21.88 до 12.18 ms на request. Timings inclusive, складывать их нельзя. Это локализует устраняемый overhead в lifecycle SQLite connections/WAL и lock contention; отдельного kernel-level fsync/checkpoint trace нет.

Обычный Store.connect закрывал последний SQLite client между стадиями: WAL checkpoint/close lifecycle повторялся на Windows bind mount. Keeper удерживает attachment, полностью заканчивает единственное чтение и не сохраняет read transaction. Existing fresh connections, BEGIN IMMEDIATE, synchronous policy, обе audit-записи и final ACL snapshot сохранены. В конце последнего request keeper закрывается, включая exceptions. Полный независимый security набор пройден после переноса изменения в production code.

## Полный lifecycle и round trips

Отдельный diagnostic `candidate/lifecycle-detailed-16-c4` измеряет HTTP, auth, admission, agent stages, serialization и ASGI send. Это 16 наблюдений; p95/p99 в таком наборе равны максимуму и не являются точной оценкой редких tails. Raw `*-profile.jsonl`, `*-samples.json`, `*-before.prom`, `*-after.prom`, `*-gpu.csv` сохранены. Агрегация всех runs — `profile-summary.json`, воспроизведение — `python tools/final_evidence.py summary`.

| Stage (inclusive) | p50 ms | p95 ms | p99 ms | Total ms /16 | Invocations |
|---|---:|---:|---:|---:|---:|
| HTTP.total | 1568.862 | 1624.643 | 1624.643 | 25037.617 | 16 |
| auth | 1.585 | 2.436 | 2.436 | 26.801 | 16 |
| admission.wait | 0.002 | 0.003 | 0.003 | 0.035 | 16 |
| Agent.retrieve | 22.399 | 50.586 | 50.586 | 381.412 | 16 |
| network.qdrant | 1.647 | 2.175 | 2.175 | 25.610 | 16 |
| Agent.expand | 11.544 | 37.225 | 37.225 | 198.874 | 16 |
| Agent.rerank | 0.045 | 0.051 | 0.051 | 0.728 | 16 |
| budget.pack | 4.720 | 5.480 | 5.480 | 76.356 | 16 |
| Generator.count_tokens | 4.696 | 5.457 | 5.457 | 75.967 | 16 |
| network.generation | 1418.530 | 1435.651 | 1435.651 | 22710.990 | 16 |
| Agent.validate | 8.427 | 24.680 | 24.680 | 170.809 | 16 |
| Store.record | 11.743 | 38.072 | 38.072 | 244.589 | 16 |
| Store.finalize | 25.596 | 48.511 | 48.511 | 433.458 | 16 |
| serialization | 0.315 | 0.371 | 0.371 | 4.671 | 16 |
| asgi.send | 0.201 | 0.274 | 0.274 | 3.214 | 32 |
| sql.connection_and_process_lock_wait | 87.689 | 137.846 | 137.846 | 1386.569 | 128 |
| sql.execute | 29.789 | 37.031 | 37.031 | 473.125 | 576 |
| sql.commit_or_rollback | 6.509 | 39.969 | 39.969 | 146.813 | 128 |

Для каждого stage JSON содержит invocation count, cumulative wall total, p50/p95/p99 и thread CPU seconds. CPU time покрывает только измеренный thread, не процесс/GPU и не всякое async ожидание. SQL execute count — число Python execute calls, не trigger-expanded VM instructions; row consumption не входит в этот sub-timer. Connection/process-lock wait объединяет открытие DB/PRAGMA и ожидание RLock, не является отдельным физическим fsync timer. Retry count внутренних клиентов не инструментирован: раннее поле retries=0 было default profiler, не доказательство отсутствия retries; summary явно указывает это ограничение.

На основном C4 run: 48 вызовов `/tokenize` на 48 requests, 229776 request bytes, input tokens=19008, output=5280. Сервис не перекодирует одинаковый контекст несколько раз в обычном fast path. Context packing измеряет complete chat JSON с template, output reserve и margin; oversize fallback отдельно проверен actual tokenizer. Tokenizer cache не введён: его возможный выигрыш ограничен примерно 5 ms из ~1.6–1.8 s, а сложность privacy/cache invalidation не обоснована.

Один Qdrant search/request подтверждён отдельным network timer. Neo4j online round trip в данном Agent path отсутствует: canonical GraphRAG выполняется SQLite; Neo4j участвует в startup/mirror validation/readiness, и ему нельзя приписывать задержку запроса. Rerank — bounded lexical, доли ms. Auth/admission/serialization отдельно малы; полный HTTP residual включает threadpool/framework work, JSON encoding и gateway/client overhead, не объявлен отдельной измеренной стадией.

vLLM histogram deltas A1: queue sum 0.000446 s /48 ≈0.0093 ms/request; prefill sum .695493 s /48 ≈14.49 ms; decode sum 67.599903 s /48 ≈1408.33 ms; server TTFT sum .988352 s /48 ≈20.59 ms. Это server TTFT histogram mean, не клиентский streaming TTFT. Одновременно HTTP requests генерируют по 110 tokens; decode доминирует, queue практически отсутствует. Prefix cache hit/query counters и KV snapshots находятся в raw .prom. Точечный scrape после завершения показывает idle KV/queue, а не peak; peak series KV не собиралась. Host GPU utilization/VRAM/power — 1 Hz CSV, включая desktop нагрузку; отдельная power/energy экономия модели не доказана.

## Принятые и отклонённые изменения

| Hypothesis → Change | Measurement → Result | Keep / Revert |
|---|---|---|
| Лишний connection/WAL churn → request-scoped idle keeper | B1/B2/A3/B3 + final image repeats; SQL stages уменьшились, generation почти та же; 51 tests и CPU/GPU eval PASS | KEEP |
| Redundant tokenizer RPC — главная причина | Ровно 1 call/request, ~4.7–4.9 ms | НЕ ПРИНИМАТЬ cache/approximate counting |
| Удалить final ACL/audit для скорости | Противоречит invariants; эксперимент не выполнялся | REJECTED |
| Настроить vLLM batching/memory/prefix cache | Queue минимальна, модель и 12 GB budget стабильны; смена параметров смешала бы факторы | НЕ МЕНЯТЬ в этой итерации |
| Новые SQL indexes / graph batching / HTTP pool | На этом маленьком corpus не локализованы как устраняемый bottleneck после keeper | НЕ ВНЕДРЯТЬ без нового profiling |
| Ослабить quote matching ради primary mode=vllm | Реальные две цитаты не exact substrings; fallback работает и сохраняет semantic units | REJECTED; release HOLD честно сохранён |

## Пределы вывода

Устранимый текущий SQL overhead подтверждён контролируемым экспериментом; полная первопричина исторической регрессии 2.44→1.81 RPS не восстановлена причинно. Старый prompt ограничивал quotes 250 символами, новый просит полные units; без старого token distribution/идентичного SQL snapshot нельзя доказать долю этой разницы. Generation остаётся главным временем, его не ускоряли уменьшением token cap/контекста/качества или сменой модели.

192-request run длится ~75 s, а не несколько часов soak. Mixed функциональный workload покрыт 23 evaluation cases; отдельный mixed HTTP capacity run NOT RUN. Production-scale documents, больше tenants, долгие writer storms, холодный KV, сетевые задержки и multi-replica fairness не измерены. Нельзя экстраполировать эти RPS на предприятие или объявлять подтверждённой финансовую экономию.
