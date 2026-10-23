# ADR-008: versioned indices, quality gate и закрытая поставка

Статус: принято для MVP. Дата: 20.10.2026.

Контекст: destructive rebuild терял rollback candidate, единичный успешный demo не доказывал качество/готовность. Требовалась проверяемая поставка без новых облачных сервисов.

Решение: canonical SQL остаётся источником truth. Создать новую immutable Qdrant collection и Neo4j partition index_version, проверить payload ACL/hash/version/count и graph nodes/edges, сравнить canonical epoch, затем publish один SQL pointer. Старые версии сохраняются, запрос считывает pointer один раз. Rollback разрешён лишь при совместимом canonical hash/dimensions; retire по умолчанию dry run с grace и защитой active/legacy. Это app-level publication, не distributed transaction между Qdrant и Neo4j.

Evaluation имеет versioned synthetic regression corpus, separate tuning, полный expected/completed/invalid/freshness/hash. Missing/partial/stale/ACL/token violations → HOLD. Provisional thresholds разрешают только synthetic MVP, production_approval всегда false. Один content-addressed Docker image проходит integration и GPU evaluation; manifest связывает code/dependency/model/prompt/index/evidence. При отсутствии Git commit SHA честно null. Нет подписи/SBOM/сертификации по факту наличия JSON.

Альтернативы: удалять active store проще, но лишает rollback; распределённый transaction coordinator и Kubernetes не нужны для single-host MVP; cloud eval нарушает контур. Trade-offs: время build/валидации и объём retained indices, grace/drain перед retire, длительные tests. Очистка безопасна в рамках MVP timeout, несколько replicas потребуют coordination. Полный offline base/apt поставляется staging, отдельно реально проверены wheels + новый venv.

Дополнение по результату GPU holdout: неверная модельная цитата не исправляется текстовыми эвристиками. Generator отбрасывает её полностью, выдаёт полные исходные units с явным fallback mode; Agent validator и final ACL snapshot остаются обязательными. Произвольный adversarial generator с искажённым отрицанием по-прежнему получает output_blocked. Неопределённый model transport/usage остаётся fail-closed ошибкой, не маскируется успехом.
