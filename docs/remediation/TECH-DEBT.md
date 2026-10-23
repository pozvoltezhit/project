# Оставшийся технический долг

Актуальная итерация20.10:69 tests PASS,0 FAIL/SKIP; F01–F06/security сохранены. P2 primary-generation blocker **CLOSED**: selector image `8761850…` дал валидный primary vllm result, исходные Golden/новые frozen случаи/нагрузка/полный same-bundle прогон и неизменённый strict gate прошли; учебный release **GO**. Причина и сохранённый неудачный prompt-only вариант — LLM-QUALITY-INVESTIGATION. F07 workflow binding исправлен, remote execution NOT RUN. Production **HOLD** и долг ниже сохраняются: calibrated judge/экспертный domain holdout, identity/TLS/DLP/HA/audit/RPO/RTO не заменяются синтетическими PASS. Historical staged raw evidence имеет whitespace; первый commit требует ручного review, raw logs/index автоматически не переписывать.

Статус OPEN означает незавершённое требование; роль — предлагаемый ответственный, конкретные лица ещё не назначены.

| Приоритет | Статус / работа | Владелец по роли | Проверяемый критерий завершения |
|---|---|---|---|
| P2, блокер пилота | OPEN: независимый domain Golden Set, multilingual/OCR сложные документы | Domain expert + QA/ML | Новая закрытая holdout версия, double reviewed facts/provenance, согласованные thresholds, свежий полный GPU evaluation |
| P2, блокер пилота | OPEN: human/calibrated local judge, quantized/reference comparison | ML Engineer | Человеческая шкала, inter-rater agreement и calibration protocol, bias/error slices; никаких cloud API |
| P2, блокер пилота | OPEN: OIDC/SSO, TLS/mTLS, secret lifecycle, атомарный provisioning | Security + Platform | Revocation/rotation/least privilege интеграционные tests, корпоративная идентификация, закрытые admin UI |
| P2, блокер пилота | OPEN: независимый security review/red team, PII/DLP | Security Engineer | Threat model и атакующие кейсы indirect injection/OCR/tenant, устранение critical/high; regex не объявлен гарантией |
| P2, блокер пилота | OPEN: HA и несколько replicas, durable checkpoint | Backend + SRE | Обоснованный PostgreSQL/координация admission, failover и concurrent auth/index tests, измеренный availability |
| P2, блокер пилота | PARTIAL: backup schedule, real-size restore / RPO / RTO | SRE + Data owner | Расписание/шифрование/доступ, все исходники и artifacts учтены, аварийный restore на реальном объёме укладывается в согласованный SLO |
| P2, блокер пилота | PARTIAL: audit retention/archive/disposal | Security + Compliance | Внешний защищённый anchor/архив, доказанная верификация и законный срок; local SHA chain не защищает от DB admin |
| P2 | PARTIAL: remote CI GPU promotion / rollback rehearsal | MLOps | Реально выполненный workflow CPU+GPU на одном digest, evidence retention; GitHub remote пока NOT RUN |
| P2 | PARTIAL: полная закрытая поставка OS/base/OCR/model | Platform + Security | Проверенная staging inventory, offline load/build rehearsal, approved SBOM/signatures policy; только wheels уже проверены |
| P2 | PARTIAL: duration/mixed load, quotas, cost telemetry | SRE + FinOps | Длительный mixed HTTP профиль, реальные тарифы/мощность, VRAM/util series, per-tenant quotas при необходимости; сейчас per-process caps |
| P2 | OPEN: legacy chunk re-ingestion и source archive ownership | Data owner | Явная миграция с backup, полные semantic units/версии и ACL, реестр всех исходников; автоматическая перезапись старых данных не выполнялась |
| P3 | OPEN: semantic embedder/reranker и архитектурная декомпозиция legacy core | ML + Backend | Независимый retrieval quality uplift против baseline, budget/ACL nonregression; typing шире шести модулей без переписывания стека |
| P3 | OPEN: инженерные таблицы/геометрия/мультимодальность | Domain + ML | Размеченные чертежи и ошибки OCR/геометрии, локальная модель в доступной памяти, safety review |

Закрытые F01–F05 сюда не переносятся как долг. Активное удаление прежних пользовательских индексов, migration данных и развёртывание тяжёлой инфраструктуры не входят в выполненные тестовые операции. Отдельный mixed capacity benchmark и измеренное energy before/after остаются OPEN, хотя mixed functional cases покрыты evaluator.
