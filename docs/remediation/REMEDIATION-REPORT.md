# Исправление проекта: 20.10.2026

Этот отчёт сохраняет исторический remediation candidate `6ee26fe…`. Следующий исторический candidate `2945daf…` имел quality GO, но строгий release HOLD по primary model mode. Актуальный selector image `8761850…` прошёл новый полный same-bundle прогон и неизменённый strict gate: учебный **GO**, production **HOLD**. Доказательства и границы — [FINAL-READINESS](FINAL-READINESS.md), [LLM investigation](LLM-QUALITY-INVESTIGATION.md), [PERFORMANCE-ANALYSIS](PERFORMANCE-ANALYSIS.md). Исторические GO ниже не переносятся на новые деревья автоматически.

F01–F05 устранены в исходном проекте. LangGraph, FastAPI, SQLite, Qdrant, Neo4j, OCR, Qwen AWQ/vLLM и разделение Control/Data Plane сохранены. Исходная оценка — 62/100. Решение для учебного синтетического MVP: **GO**. Промышленный запуск: **HOLD**.

## Причины и изменения

| Дефект | Причина | Исправление и постоянные проверки |
|---|---|---|
| F01 / P1 | Evidence переживало поздний отзыв grant, последний ACL-read обновлял только graph | `core.Store.finalize`: BEGIN IMMEDIATE, новый identity/tenant/session snapshot, сравнение version/text/title/page, единая проверка evidence и graph, согласованные history/audit, сериализация до commit. `tests/test_remediation.py`: отзыв во время генерации, после validate, barrier конкурентного writer, tenant/version/session, shared entity, SSE. |
| F02 / P1 | Символы и top-6 не ограничивали tokens | `budget.py`, `Generator`: реальный `/tokenize` и тот же chat template, полный JSON overhead, output reserve 700 + margin 64, max 4096, упаковка целых units. Oversize вопрос → 422, непоместившийся context → явный extractive fallback без inference. `gpu_check` повторяет техническую фикстуру 1910 символов/6 chunks и реальный Qwen. |
| F03 / P2 | Проверка подстроки принимала обрезанное отрицание | `grounding.py`: границы предложений, offsets и полный исходный unit, без вырезания условий/чисел/единиц; adversarial quote отклоняется. В `Generator` некорректная цитата реальной модели целиком отбрасывается, заменяется полными источниками с `extractive-invalid-generation`; затем обычные validator и final ACL snapshot. |
| F04 / P2 | Traversal опирался на edges и терял singleton chunks | `Store.graph`: Entity → mentions → authorized chunks → entities; visited, дедупликация, детерминированный порядок, ≤2 hops / 32 chunks / 128 entities, затем rerank top-6 и token budget. Проверены циклы, ветви, секретный shared entity и К-2 → 120 °C. |
| F05 / P2 | Счётчик business outcome запускался после auth/validation | ASGI `telemetry.HTTPAccounting` считает каждый завершённый запрос один раз; ограниченные route/method/status_class/outcome. Отдельный business counter сохранён. Проверены 200/401/403/422/500/503 и unknown route без сырого URL. |

## Дополнительная реализация

`evaluate.py`, `eval/` — версионированные фикстуры, holdout и исполняемый quality gate. `adapters.py`/`index_admin.py` — build/validate/publish единого SQL pointer на две подготовленные версии; прежние коллекции не удаляются. `backup.py`/`stack_check.py` — SQL backup и реальное восстановление в новом каталоге с rebuild обоих индексов. `admission.py` — per-process предел 8 active + 8 queued, wait 2 s, 600/min и 429. `/ready` проверяет необходимые SQL/identity/index/model зависимости; `/health` остаётся liveness.

`telemetry.py`, `quality_export.py`, `finops.py`, Compose, 16 Grafana panels и 8 alerts — stage/queue/dependency/token/quality/accounting. Старая бизнес-метрика не используется как знаменатель всех HTTP-ошибок. `release.py`, `bundle.py`, `tools/verify.py`, `tools/release.ps1`, workflow — evidence-bound HOLD/GO и продвижение того же image ID. `retention.py` удаляет только явно датированную истёкшую history по отдельному `--apply`; audit chain сохраняется целиком.

## Доказательства и найденные побочные эффекты

Свежий набор: 38 тестов, coverage 84.54%, lint/types/existing_check — см. [verification.json](evidence/verification.json), [JUnit](evidence/junit.xml) и журналы. Типизация охватывает шесть policy/evaluation модулей; lint проверяет критичные ошибки Python, а не весь style debt.

Первый GPU holdout выявил безопасную блокировку multi-hop цитаты: 1 FAIL и HOLD сохранены в `evidence/candidate-1/eval-gpu.json`. Ожидаемые ответы не ослаблялись. Добавлена проверяемая политика полного extractive fallback для неверной модельной цитаты, новый тест и новый собранный image; итоговые evidence привязаны к новому bundle hash. При code review также устранён teardown индексов через изменяемый глобальный agent: закрываются именно клиенты, созданные lifespan.

Проверенный образ: `sha256:6ee26fe97239ead672a5fabb03b995d6e22584485dfa96cf5b36862a00274e1e`. Источники в финальном runtime не монтировались поверх `/app`. В Git ещё нет commit, поэтому commit SHA в manifest отсутствует; существующий index/worktree не сбрасывался. Подтверждены Linux/Python 3.12 зависимости из 66 проверенных wheels в новом venv с `--network none`; свежая offline apt/base-image сборка не подтверждена, использован подготовленный OCR runtime.

## Производительность и границы

| Профиль | Запросы / concurrency | Успешный RPS: аудит → сейчас | p95 ms: аудит → сейчас | Ошибки |
|---|---|---|---|---|
| CPU | 300 / 8 | 6.38 → 6.7 | 1526.88 → 1497.26 | 0 |
| GPU | 48 / 4 | 2.44 → 1.81 | 2085.22 → 2319.26 | 0 |

Клиент внутри backend → Nginx gateway:18080 → API; GPU использует реальный локальный Qwen. Прогоны последовательны, CPU 300/8, GPU 48/4; вопрос и corpus сценария сохранены. Это короткая повторяющаяся синтетическая нагрузка, не производственная capacity. Дополнительные tokenize round trips и SQL/security проверки имеют цену. Разница одного прогона не является статистической оценкой ускорения. Сравнение mixed типов есть в evaluation, отдельный mixed HTTP capacity benchmark не выполнялся.

RTX 4070 / 12282 MiB; снимок до нагрузки — 11139 MiB занятой VRAM, 7% GPU utilization и 12.96 W (`gpu-resources-before.txt`), а не пиковое/среднее потребление за benchmark. Более мощная GPU не потребовалась. Измеренное сравнение энергии до/после не выполнено.

## Финальный контроль артефактов

Текущий code bundle совпал с bundle проверенного image и release manifest. Все 11 локальных model artifacts повторно совпали по размеру и SHA-256 с manifest (`evidence/model-hashes-final.json`). Браузерная проверка синтетического B: multi-hop ответ в режиме vllm с двумя разрешёнными источниками и graph, закрытый П-9 — no_evidence без цитат и graph. Снимки и результат: `evidence/ui-regression.json`, `ui-b-final.png`, `ui-b-denied-final.png`.

Временный стенд остановлен: удалены только 8 контейнеров и 2 новых тома namespace `course-remediation-20261020`; image сохранён. `cleanup.json` фиксирует отсутствие оставшихся контейнеров тестового namespace. Исходный `portal_qdrant` тем же container ID и StartedAt наблюдался остановленным/unhealthy при финальном чтении; команды изменения к нему не применялись. Пользовательские данные и исходный стек автоматически не продвигались. `git diff --check` не выявил whitespace errors; Git index не перезаписывался.

Последний сопоставимый GPU прогон: p95 2085,22 → 2319,26 ms (+11,2%), успешный RPS 2,44 → 1,81 (−25,8%), 0 ошибок; условная цель ADD ≤5000 ms при C=4 выполнена только для этого сценария. Полный-context fast path уменьшил лишние tokenizer round trips; оставшаяся разница измерена, но не локализована контролируемым профилированием. Ускорение CPU по одному короткому прогону не заявляется.

## Сохранность и ограничения

Все destructive/failure тесты выполнялись в `course-remediation-20261020`, на копии SQL/identity и новых volumes. Исходные data, credentials, weights и индексы не удалялись; `portal_qdrant` не изменялся. Тестовые секреты не публикуются. Административный отзыв, зафиксированный до финального SQL snapshot, учитывается; writer после захвата write reservation завершится после commit выдачи. Переданные клиенту байты отозвать нельзя. Файловые identities требуют атомарного provisioning; это не распределённый OIDC lease.

Полные semantic units гарантируют точность цитирования относительно текста, но не достоверность самого документа, OCR или произвольное логическое entailment. Старые chunks автоматически не переписываются: для новой нарезки нужен явный re-ingest исходников. Numeric conflict detection ограничен реализованными инженерными атрибутами и не заменяет экспертную проверку. Production prerequisites и конкретный backlog — [RELEASE-READINESS](RELEASE-READINESS.md), [TECH-DEBT](TECH-DEBT.md).
