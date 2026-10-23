# Решение о готовности

## Текущий финальный candidate: GO

Image `sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e`, bundle `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`. Неизменённый strict gate фактически вернул GO, reasons=[], production_approval=false. Полный same-bundle прогон69 tests/CPU-GPU/Golden/token budget, новые16+20 quality cases и manifest verification завершены. Primary Qwen выбирает валидные evidence source IDs; сервер восстанавливает точные canonical units с прежней final ACL проверкой. Детали и ограничения — [FINAL-READINESS](FINAL-READINESS.md), [LLM investigation](LLM-QUALITY-INVESTIGATION.md); manifest — `evidence/llm-quality-20261020/release-manifest.json`. Промышленный пилот **HOLD**.

## Исторический candidate `2945daf…`: HOLD

Image `sha256:2945daf417c2ff073a4cb3be97bbb5036fae0936710ee09545cac429459bd3bd`, bundle `8e3e74…`. Историческое решение:83/100, учебный release HOLD, production HOLD. Unit51/CPU-GPU integration/synthetic quality/restore/recovery/model identity были PASS, но strict primary mode predicate gate не был выполнен. Основной GPU ответ использовал safe invalid-generation fallback после настоящей модели, short GPU case mode=vllm. Этот срез не является текущим состоянием.

Новый manifest и binding check — `evidence/final-20261020/release-manifest.json`, `manifest-validation.json`. Source/config/test inventory/archive SHA добавлены отдельно к runtime bundle. Старый manifest не подтверждает новый код; promotion без rebuild. Команды — RUNBOOK. Первый commit/remote Actions — NOT RUN.

## Исторический предыдущий candidate `6ee26fe…`

**Учебный синтетический MVP: GO. Промышленный пилот: HOLD.** Дата 20.10.2026. Это инженерная оценка по шкале исходного аудита, не оценка преподавателя и не сертификация.

| Раздел исходной шкалы | До | После | Основание изменения |
|---|---|---|---|
| Сценарии работы /20 | 15 | 18 | F04 singleton, CPU/GPU/OCR, semantic citations; узкий synthetic corpus и нет геометрии |
| Архитектура /20 | 18 | 19 | Сохранён bounded LangGraph, реальные SQL release snapshot и versioned index pointer, code/sequence/dataflow обновлены |
| Безопасность /25 | 11 | 21 | F01–F03, adversarial/barrier/SSE, safe errors, bounded admission, audit chain; нет OIDC/mTLS/external immutability и полного red team |
| Эксплуатация и поставка /20 | 10 | 15 | Readiness/failure recovery, проверенный restore/index rollback, wheels offline, manifest, real alerts; нет remote CI GPU/HA/полного air-gap base build |
| Качество и Governance /15 | 8 | 10 | Исполняемый evaluator с coverage/freshness/HOLD и synthetic holdout; нет репрезентативной независимой экспертизы/калибровки |
| Всего /100 | 62 | 83 | Баллы даны за выполняемые проверки; наличие новых документов само по себе балл не повышает |

Оценка 83 применима при PASS финального unit/security/integration и GO synthetic gate в manifest. При устаревании evidence или FAIL выпуск снова HOLD. Число не означает 83% вероятности безопасности. Блокирующий P1 cap исходного аудита снят после детерминированных конкурентных regressions и реального tokenizer check; production ограничения остаются.

Образ `sha256:6ee26fe97239ead672a5fabb03b995d6e22584485dfa96cf5b36862a00274e1e`. Bundle и dependency lock — `evidence/release-manifest.json`; commit SHA отсутствует, потому что репозиторий ещё не имеет commit. Продвижение должно использовать именно этот content-addressed image, не пересборку по tag. Release command проверяет свежесть и совпадение bundle всех обязательных unit/CPU/GPU/eval/regression отчётов. Model weights external mount закреплены отдельным manifest; image digest не включает их bytes.

## Что курсом реально подтверждено

Итоговое GraphRAG задание: локальное inference, bounded stateful LangGraph, document/chunk/entity provenance, multi-hop и A/B RBAC, OCR, VectorDB/graph profile; C4 1–4/Sequence/ER/Data Flow, ADR и разделение planes. Практики quality engineering: исполняемые regression и versioned metrics/gate. Наблюдаемость: stage spans, HTTP/business denominators, alerts. Reliability/MLOps/FinOps: readiness, versioned publication/rollback, restore smoke, immutable artifact evidence и конфигурируемые оценки затрат. SSO/Vault/HA, полноценный semantic embedder, calibrated judge и multimodal geometry остаются проектными prerequisites; работающий учебный MVP не превращает их в выполненные компоненты.

## Блокеры промышленного пилота

Нужны назначенные service/data/security owners и решение об условиях пилота; анонимная демонстрационная Grafana и loopback Compose не корпоративный access control. Требуются SSO/OIDC, TLS/mTLS, secret manager, проверенная сегментация и provisioning lifecycle; PostgreSQL/HA/checkpointer при нескольких репликах; резервирование/restore на реальном объёме и установленные RPO/RTO; внешний защищённый audit/архив; независимый real corpus с разметкой, red team и калибровкой quality/quantization. Нужны полный supply-chain inventory/SBOM/signatures по выбранной политике, delivery rehearsal всех OS/model artifacts, подтверждённый CI и длительная/mixed нагрузка. Эти функции не разворачивались декоративно.

Автоматическая проверка разрешений несколько раз не завершалась до deadline для дополнительных Docker/браузерных действий. Альтернативные проверяемые запуски оформлены отдельными протоколами; timeout не был засчитан как PASS. Прежний runtime не продвигался и пользовательские volumes не мигрировались во время тестов. Оператор запускает новый образ после review, делает backup и явную индексацию; команды — RUNBOOK.
