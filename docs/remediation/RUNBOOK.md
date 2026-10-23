# Эксплуатационный runbook

## Проверенный учебный выпуск 20.10.2026

Учебный strict release **GO**, production **HOLD**. Основание — FINAL-READINESS и `evidence/llm-quality-20261020/release-manifest.json`; исходный gate не ослаблялся. Primary GPU case использует реальный Qwen selector. Сервер восстанавливает точные canonical units по request-local source IDs, валидирует их и повторно авторизует выдачу. Unknown/mixed/offset schema или некорректная legacy quote всё ещё приводят к отказу/безопасному fallback.

Проверенный image: `sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e`; bundle `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`. Для promotion использовать этот image ID без rebuild. Source inventory/archive находятся в новом evidence; архив — `data/llm-quality-20261020/source-bundle.zip`. Docs/video/evidence передаются отдельно. Tokens, private data, weights и `.git` в source archive не входят.

Существующий disposable project `course-final-20261020` сохранён с собственными synthetic данными/volumes. `prepare` повторно не выполнять: он откажется перезаписывать стенд. Не использовать scripts этой проверки на чужих Docker projects. Перед новым прогоном сверить namespace, ownership labels и image. Git index/worktree не очищать и не stage автоматически.

Backend требует Linux/Python3.12. Host Python3.14 использовался только для stdlib harness. Модель — прежняя Qwen2.5-7B-Instruct-AWQ по 11-file manifest, read-only `/models/qwen`; runtime downloads отключены. Serving: vLLM0.10.2/AWQ Marlin/half,4096 context,700 output reserve,64 margin,max-num-seqs4,max-num-batched-tokens1024,GPU memory fraction.80,prefix cache. Локальный offline rebase проверен на prepared OS/OCR base `sha256:185bfd1525b668d3483118d9203e2d80e4e502f14174a6b9b48fcb7ebb5227d1`; fresh OS/OCR/весь air-gap перенос не проверялись.

```powershell
# Из корня проекта; только существующий собственный disposable стенд.
$qualityImage = 'sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e'
python tools/llm_quality_runtime.py start --gpu --image $qualityImage
Invoke-RestMethod http://127.0.0.1:18080/ready
python tools/llm_quality_runtime.py probe --label rerun/primary-01
python tools/llm_quality_runtime.py checks --gpu --label rerun/gpu-01
python tools/llm_quality_runtime.py unit --label rerun/unit-01
# Выполнять последовательно, без других тестов/сборок/LLM нагрузки.
python tools/llm_quality_runtime.py benchmark --label rerun/gpu-48-c4-01
python tools/llm_quality_runtime.py benchmark --label rerun/gpu-192-c4-01 --count 192
# CPU integration/evaluation того же immutable image.
python tools/llm_quality_runtime.py start --image $qualityImage
python tools/llm_quality_runtime.py checks --label rerun/cpu-01
python tools/llm_quality_runtime.py stack --label rerun/cpu-stack-01
python tools/llm_quality_runtime.py stop
```

Выбирать новые labels; не перезаписывать предыдущие JSON/logs. `checks` выполняет integration и исходный Golden23, GPU также real-tokenizer regression. Все четыре tuning cases выполняются отдельной фазой `tuning`; первые новые16 — `holdout`, второй20 — `validation --gpu`. При следующих изменениях оба новых набора уже являются regression suite: повторный запуск не делает их снова blind. Frozen JSON/expected не менять ради PASS.

Для фактической текущей итерации wrapper agreement иногда истекал по тайм-ауту до запуска. Альтернатива — одноцелевые `docker exec` команды к тому же собственному backend: `python -m backend.integration_check`, `python -m backend.gpu_check`, отдельно warmup8/C4 через `backend.benchmark`, затем `/instrument/measure_http.py --requests 48|192 --concurrency 4 --output /app/data/measurement.json`. Перед следующим measurement скопировать JSON/samples/before+after metrics из private runtime в новый evidence label. Время согласования не является latency benchmark и не учитывается как выполненный прогон.

`tools/llm_quality_release.py manifest` создал текущий manifest один раз и откажется его перезаписывать. Для следующего выпуска нужны новые пути evidence, совпадающие fresh unit/CPU/GPU/eval/GPU-regression reports и новый фактически проверенный image; вызвать неизменённый `backend.release` с этими отчётами. Старый GO не переносится на другой bundle. Report freshness≤24h, полный набор, отсутствие critical ACL/budget failures обязательны. Production approval остаётся false.

Ниже — общие процедуры эксплуатации; исторический `tools/finalize_runtime.py` и прежние image/evidence относятся к прошлой итерации, не заменяют новый manifest.


## Запуск и проверка

Для подготовки с сетью: `docker compose -f infra/compose.yaml build backend`. В закрытом контуре доставить подготовленные Docker images, model artifacts и wheels по manifest. `infra/Dockerfile.offline` допускает rebase только на уже подготовленный образ с совпадающим lock и проверенными installed pins; OS/OCR не создаются из воздуха.

Базовый запуск: `docker compose -f infra/compose.yaml -f infra/compose.indexes.yaml up -d --no-build`. Для GPU добавить `-f infra/compose.gpu.yaml` ко всем compose-командам; предварительно разместить проверенные Qwen weights. Для продвижения добавить override с `services.backend.image: sha256:...` из release-manifest, исключить build/rebuild и дождаться healthy. Проверить `/ready` и `backend.integration_check` в нужном профиле. `/health=200` сам по себе не разрешает запросы/релиз.

HTTP API 1.1: Bearer header, POST `/query` и `/query/stream`; SSE — один проверенный результат. Swagger `/docs` поддерживает BearerToken. `/graph` и `/history/{session_id}` применяют актуальные права. Evidence содержит source version/page/start/end и selection offsets; ошибки имеют safe code, слишком большой token question — 422 `token_budget_exceeded`, dependency failure — 503, admission — 429 + Retry-After. Never retry oversized input unchanged.

## dependencies

При not-ready сверить `knowledge_dependency_ready`, логи без содержимого документов, доступность Qdrant/Neo4j и активной версии; в GPU — `/health`, `/v1/models` и реальный context limit vLLM. Сохранить отказ/версию/время, восстановить зависимость, дождаться `/ready=200`, повторить security smoke. Не подменять обязательные индексы тихим режимом без фильтрации. CPU профиль не требует vLLM. Ошибка SQL/audit/identity тоже делает систему not-ready.

## Индексация, rollback и cleanup

После CLI ingest/изменения канонических документов выполнить внутри configured backend `python -m backend.index_admin build`, затем `status`. На старте тот же build выполняется автоматически с bounded retries. Новые Qdrant/Neo4j версии сначала валидируются по canonical epoch/hash/ACL/count/graph, затем один SQL active pointer публикуется. Запрос читает pointer один раз; это не распределённая атомарная транзакция двух stores.

`python -m backend.index_admin rollback --version <version>` разрешён только для сохранённой версии, совместимой с текущим canonical corpus/hash/dimensions. При изменении canonical данных старая версия не считается безопасным rollback; требуется восстановление согласованного snapshot и новый build. Старые in-flight запросы читают сохранённую immutable версию. `retire --version <version>` — dry run; отдельный `--apply` после окна обслуживания удаляет лишь manifest-owned inactive v2 version. Default grace 3600 s, минимум 300 s; долгоживущие запросы/несколько replicas требуют согласованного drain. Не удалять legacy/active collections и не запускать cleanup на неизвестном проекте.

## Backup и restore

`python -m backend.backup create --db data/knowledge.db --identities data/identities.json --sources examples --model-manifest models/qwen-manifest.json --output <новый-приватный-backup>` использует consistent SQLite backup и hashes файлов. `--sources` должен охватывать весь реальный source archive, а не только demo examples. Модельные weights этим backup не копируются: переносить по отдельному manifest. Защитить backup средствами ОС/шифрованием и политикой доступа.

`python -m backend.backup restore --backup <backup> --output <новый-каталог>` проверяет hashes, пути, SQL integrity/FK и очищает active pointer только в восстановленной SQL. Запускать с отдельными DB_PATH/AUTH_FILE и отдельными Qdrant/Neo4j; build → A/B security smoke → audit verification → ready. Время fixture restore не является production RTO/RPO.

History retention: `python -m backend.retention --history-days 30 --audit-days 365` — dry run. `--apply` удаляет лишь известные датированные history rows. Legacy без даты и полная audit chain сохраняются. Audit-days задаёт eligible archive count, а не разрешение удаления. Внешнее архивирование/удаление требует отдельной реализации и владельца политики. Jaeger in-memory ограничен 10000 traces, после restart теряется; Docker backend logs 3×10 MiB. Оценка storage = observed bytes/event × events/day × retention days плюс index/replica overhead, фактические production значения ещё не измерены.

## errors

HTTP error rate = 5xx query requests / все query requests; auth/validation идут в 4xx и отдельные outcome. Сверить RPS/429/queue/зависимости, не смотреть только business success counter. Сохранять request ID и status без токена/вопроса. После исправления выполнить соответствующий regression и smoke.

## latency

Сравнить p95 по тому же маршруту/profile/concurrency, stage histogram, queue wait и `llm.generate`. При насыщении GPU снизить admission/concurrency, не увеличивать max context произвольно. Нагрузка 48/4 не доказывает SLO availability. Порог alert provisional 5 s на query при достаточном объёме.

## budget

`KNOWLEDGE_MODEL_CONTEXT=4096`, `KNOWLEDGE_OUTPUT_TOKENS=700`, `KNOWLEDGE_TOKEN_MARGIN=64` согласованы backend/vLLM Compose. `/tokenize` использует тот же model/chat template. Oversized вопрос требует сокращения; context fallback возвращает полные цитаты и явный mode. `extractive-invalid-generation` означает, что модельная цитата отвергнута и заменена исходными units, это следует отслеживать как quality feedback.

## evaluation

`python -m backend.evaluate --output data/eval-report.json`; с локальным LLM_URL — добавить `--gpu`. `--limit` означает частичный отчёт/HOLD. Сверить completed/expected/invalid/failures/hash/model/time и rerun после изменения artifact, prompt, corpus или прав. Report ≤24 h, полный dataset; critical ACL/budget failures всегда HOLD. Старый/отсутствующий report не является нулём ошибок. Качество синтетического набора не даёт production approval.

## telemetry

Проверить scrape targets, Promtool rules, соответствие GPU scrape профилю и доставку OTel в локальный Jaeger. 16 dashboard panels показывают HTTP/business/stage/dependency/budget/quality/cost. Missing metrics → отдельный alert. Стоимость появляется только после явных `COST_LOCAL_RUB_PER_HOUR`, `COST_ESTIMATED_POWER_WATTS`, `COST_RUB_PER_KWH`: C = uptime_hours × hourly + uptime_hours × W/1000 × electricity; cost/answer = C / answered, GPU-hours = uptime GPU-профиля, включая idle. Это allocation estimate, не измеренная электроэнергия/биллинг. Для traces/audit/history нужны фактические объёмы и тариф storage; в отсутствие их расходы не выдумываются.

## Release и incident

`python tools/verify.py`; затем CPU/GPU integration, quality evaluation и GPU regression на одном собранном artifact. `tools/release.ps1 -ImageId sha256:...` формирует manifest из обязательных evidence; HOLD при отсутствии/несовпадении/старении. GPU-free CI явно PENDING, удалённый workflow ещё не выполнялся. `tools/final_runtime.py` — конкретный изолированный стенд этой проверки, не универсальная команда production deployment.

При инциденте остановить admission/изолировать маршрут, сохранить защищённые audit/trace IDs и версии, уведомить назначенного service/security owner по корпоративной процедуре, отозвать доступ, воспроизвести на synthetic fixture. Автоматической отправки внешних сообщений нет. Rollback использует прежний проверенный image и совместимый index/snapshot; readiness/security smoke до маршрутизации трафика. Новый feedback от экспертов проходит review и отдельную версию eval, без бесконтрольного дообучения.
