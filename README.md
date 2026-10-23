# Закрытая платформа корпоративных знаний

## Материалы для проверки

[Состав сдачи и ограничения](SUBMISSION.md) · [ADD (PDF)](docs/ADD.pdf) · [ADR (PDF)](docs/ADR.pdf) · [Диаграммы C4 / Deployment / Sequence / ER / Data Flow](docs/архитектура.pdf) · [Видео 6:14](docs/демо.mp4) · [Нагрузочный отчёт](docs/remediation/PERFORMANCE-ANALYSIS.md) · [Итоговые проверки](docs/remediation/FINAL-READINESS.md).

Код и результаты учебного GPU-прогона зафиксированы 20.10.2026. Видео показывает предыдущую версию; актуальные selector/качество/скорость описаны в итоговых отчётах. Промышленный пилот остаётся HOLD. GitHub Actions повторяет CPU-проверки; GPU-проверки требуют локального стенда. Данные, credentials, веса модели и локальные Docker images не публикуются: подготовка описана ниже и в runbook.

Реализован MVP GraphRAG: локальные документы → чанки с RBAC → граф упоминаний → ограниченный LangGraph → проверенные цитаты. Демонстрационный corpus синтетический. Пользователь B не получает секретный бюджет, даже когда секретный и открытый документы упоминают один насос. LLM не требуется для проверки графа и прав: extractive режим честно отдаёт найденные цитаты. GPU-профиль вызывает только внутренний vLLM, никаких облачных inference API.

## Исправления 20.10.2026

Финальная проверка: 69 тестов PASS, 0 FAIL/SKIP; F01–F06/security сохранены. Qwen выбирает доказательные фрагменты по коротким source IDs, сервер восстанавливает точный исходный текст и проверяемые offsets с прежней final ACL проверкой. Это LLM-selected canonical evidence, не свободный пересказ. Первопричина и границы качества — [LLM investigation](docs/remediation/LLM-QUALITY-INVESTIGATION.md); измерения — [производительность](docs/remediation/PERFORMANCE-ANALYSIS.md), [итоговая готовность](docs/remediation/FINAL-READINESS.md).

Строгий учебный release gate — **GO**, промышленный пилот — **HOLD**. Primary GPU case имеет `mode=vllm`; исходные 27 Golden cases, новые 16 regressions и frozen GPU validation20 прошли. GPU 48/C4: 8,66 RPS / p95 690,80 мс; 192/C4: 9,32 RPS /468,75 мс; HTTP errors=0. Gate/Golden/ACL не ослаблены. Проверенный application image: `sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e`; [manifest и evidence](docs/remediation/evidence/llm-quality-20261020/release-manifest.json). Прежние HOLD и неудачный prompt-only кандидат сохранены.

Локальная проверка: установить `requirements-lock.txt` и `requirements-dev.txt`, затем `python tools/verify.py`. Evaluation: `python -m backend.evaluate --output data/eval-report.json`; GPU вариант требует локального LLM_URL и `--gpu`. Полный свежий dataset и совпадающий artifact обязательны; partial/stale отчёт даёт HOLD. `/health` — liveness, `/ready` — необходимые SQL/identity/index/model dependencies. API 1.1 возвращает проверяемые offsets цитат и явные fallback modes.

## Локальный запуск

Python 3.12, из каталога проекта:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m backend.init_demo
.venv\Scripts\python -m backend.check
.venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 18080
```

Открыть http://127.0.0.1:18080. Ключ engineer-a или engineer-b берётся из локального `data/identities.json`, не вставляется в URL и не публикуется. Граф доступен через `/graph` с тем же Bearer token. Swagger `/docs` поддерживает схему BearerToken (Authorize). `python -m backend.benchmark` сохраняет измеренный ASGI benchmark, ограниченный extractive CPU path.

## Контейнеры

После инициализации demo credentials:

```powershell
docker compose -f infra/compose.yaml build backend
docker compose -f infra/compose.yaml up -d
```

Базовый набор создаёт изолированную сеть без исходящего доступа. Для включения реальных производных индексов добавить `-f infra/compose.indexes.yaml`. Для GPU добавить `-f infra/compose.gpu.yaml`, предварительно подготовив локальные Qwen2.5-7B-Instruct-AWQ weights в `models/qwen-awq`: `python infra/prepare-models.py` на staging-машине с сетью. SHA-256 проверяется по официальным LFS hashes, revision закреплён в скрипте и manifest. Модель имеет лицензию Apache-2.0; обучение не выполняется. Runtime не скачивает модель. Сборка образов/перенос weights выполняются на staging машине до отключения сети; внутри закрытого контура используются `docker load` и wheelhouse с проверенными hashes.

Jaeger: http://127.0.0.1:16686. Neo4j browser: http://127.0.0.1:17474. Prometheus: http://127.0.0.1:19090. Grafana: http://127.0.0.1:13000. Все ports привязаны к loopback. Neo4j browser доступен только администратору с паролем из `data/neo4j-password.txt`; пользователи получают отфильтрованный граф через API. Backend читает authoritative ACL из SQL. Это dev-профиль, не production policy. Vault, mTLS/SSO, backup и сетевые зоны описаны в ADD, не выдаются за уже развёрнутые сервисы.

```powershell
python -m backend.ingest examples/01-equipment.txt --tenant factory --roles staff
python -m backend.ingest document.pdf --tenant factory --roles restricted
```

Для сканов требуется локальный Tesseract rus+eng, включённый в Dockerfile. Документ с подозрительными инструкциями помещается в отказ загрузки. ACL задаёт администратор через CLI, публичного ingest API с произвольными ролями нет.

В контейнерном профиле ingest выполняется через CLI внутри backend с корректными tenant/roles. После изменения corpus/ACL выполнить `python -m backend.index_admin build` внутри configured backend, затем `status` и `/ready`. Индексы versioned: build → validate → publish SQL pointer; прежние версии сохраняются. На startup build выполняется автоматически; destructive rebuild больше не используется. Backup, rollback, retention и продвижение закреплённого image — в `docs/remediation/RUNBOOK.md`.

## Состав сдачи

После финальной проверки 20.10 временный стенд `course-remediation-20261020` остановлен; его новые тестовые контейнеры и тома удалены, проверенный образ сохранён. Исходные данные, weights и пользовательские volumes не заменены. Запуск нового образа выполняется явно по runbook.

Последующая финальная итерация использует отдельный `course-final-20261020` и новые synthetic data в игнорируемом `data/final-20261020`. Управление этим стендом — `tools/finalize_runtime.py`; результаты — `docs/remediation/evidence/final-20261020`. Не запускать исторический `tools/final_runtime.py` для новой итерации. Актуальные команды восстановления стенда и его финальный статус — в RUNBOOK и FINAL-READINESS.

Актуальное состояние и commands — `docs/remediation/REGRESSION-RESULTS.md` и `RUNBOOK.md`. Проверки выполнялись в отдельном `course-remediation-20261020`, пользовательские volumes не продвигались автоматически. Видео 05.10 — историческая демонстрация; исправления 20.10 в нём не показаны.

`backend/` — API, state machine, ingestion, GraphRAG, checks и benchmark. `infra/` — Compose, Dockerfile, наблюдаемость. `docs/` — ADD, ADR, C4 1–4, Deployment, Sequence, ER/Data Flow, нагрузочный отчёт и сценарий демо. `frontend/` — локальная форма поиска с безопасным textContent.

Ограничения и фактически выполненные проверки приведены в `docs/проверки.md`. Не подменять ASGI throughput замером реального GPU serving. Готовое видео `docs/демо.mp4` показывает фактически работающий GPU-профиль, Neo4j, Jaeger и метрики. Это смонтированный deep dive из реальных снимков интерфейсов и журналов с локально синтезированной озвучкой; расшифровка и таймкоды приложены.
