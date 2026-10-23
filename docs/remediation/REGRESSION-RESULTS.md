# Фактические регрессии: финальная итерация 20.10.2026

Актуальный image `8761850…`, bundle `96d03e4…`: **69 PASS, 0 FAIL/SKIP**, coverage84,92%, lint/mypy/check PASS. CPU/GPU integration PASS, исходные27 Golden cases и новые16 PASS в обоих профилях; frozen GPU validation20 PASS. Real tokenizer/oversize, restore/index lifecycle и manifest verification PASS; неизменённый strict release gate **GO**, production **HOLD**. Новое evidence — `evidence/llm-quality-20261020/`, детали — FINAL-READINESS и LLM-QUALITY-INVESTIGATION.

## История предыдущего image

Следующие таблицы относятся к image `2945daf…`, bundle `8e3e74…`; пути ниже относительно `evidence/final-20261020/`. Они сохранены как история и не являются текущим verdict.

| Проверка | Реальный результат | Новое evidence |
|---|---|---|
| Исходный набор до изменений | 38 PASS, исходный checkout = image bundle | `baseline/verification.json`, `baseline/*bundle.json` |
| Independent RED на исходном коде | 9 PASS /2 FAIL: F06 cancellation/send | `baseline/independent/run.log`, JUnit |
| После F06, до WAL | 49 PASS | `candidate/security-check/verification.json` |
| Первый новый WAL тест | 50 PASS /1 FAIL: raw connection самого теста оставлен открытым | `candidate/final-tests/unit.log`, JUnit |
| Финальный полный набор | **51 PASS, 0 FAIL, 0 SKIP; coverage84.81%** | `candidate/verified-tests/verification.json`, JUnit/coverage |
| Lint / mypy / existing_check / compile / pip | PASS; mypy scope прежние6 модулей, compile49 .py | verified-tests; `candidate/final-lint.log`, `pip-check.log` |
| CPU / GPU integration | Функционально PASS: RBAC/tenant/session/injection/OCR/stores/traces/egress; GPU primary fallback после реальной модели | `candidate/{cpu,gpu}/integration.json` |
| CPU / GPU synthetic regression dataset | 23/23 каждый; invalid/failures/leakage/budget violations=0, quality GO | `candidate/{cpu,gpu}/eval.json` |
| Actual tokenizer / short inference / oversize | PASS; short mode=vllm, 214input/51output | `candidate/gpu/gpu-regression.json` |
| Versioned index / failed stage / backup/restore | PASS; fixture restore .6777s, не production RTO | `candidate/cpu/stack.json` |
| Qdrant down/recovery | ready503/query503/health200, затем ready200 | `candidate/dependency-recovery.json` |
| Prometheus / traces | Promtool/integration PASS; новый visual browser review NOT RUN | `candidate/promtool.log`, `targets.json`, integration |
| Offline fresh venv / model hashes | 66wheels PASS; 11/11 model files PASS | `candidate/offline-smoke.json`, `model-hashes.json` |
| HTTP capacity | GPU48/C4 без profiler:2.53RPS/p95 1631.63ms; 192/C4:2.55/1628.33; CPU300/C8:20.80/474.02; errors0 | benchmark JSON + raw samples/profiles/GPU CSV |
| Current manifest identity | PASS привязок; **release HOLD** по strict primary mode predicate | `release-manifest.json`, `manifest-validation.json` |
| Workflow | Local YAML/bash -n PASS; remote Actions NOT RUN | `candidate/workflow-local.json` |
| Fresh Git checkout / full offline OS+OCR / mixed capacity | NOT RUN; первый commit не создан | FINAL-READINESS / RUNBOOK |

Final review не обнаружил нового critical security defect. Tests не равны внешнему red team/semantic entailment proof. `git diff --check` working tree PASS с CRLF warnings; cached check на прежних staged raw logs/metrics находит historical trailing whitespace — evidence/index не переписывались.

## Исторический результат предыдущего remediation candidate `6ee26fe…`

| Проверка | Результат | Доказательство |
|---|---|---|
| F01 / F02 / F03 / F04 / F05 | PASS в автоматических регрессиях | `tests/test_remediation.py`, `tests/test_grounding_http.py`, `evidence/junit.xml` |
| Набор unit/security/API/eval/backup/admission/release | 38 tests; exit 0 | `verification.json`, `unit.log`, `coverage.json` |
| Lint / six-module mypy / backend.check | {'lint': 0, 'types': 0, 'unit': 0, 'existing_check': 0, 'literal_secret_scan': 0, 'tree_unchanged': 0} | `lint.log`, `types.log`, `existing_check.log` |
| CPU: HTTP A/B, tenant, session, injection, OCR, индексы, egress | PASS: HTTP RBAC/tenant/session/injection, scanned PDF OCR, Qdrant ACL, Neo4j mirror, Jaeger spans, Prometheus, blocked backend egress | `integration-cpu.json` |
| GPU: тот же integration suite | PASS: HTTP RBAC/tenant/session/injection, scanned PDF OCR, Qdrant ACL, Neo4j mirror, Jaeger spans, Prometheus, blocked backend egress | `integration-gpu.json` |
| F02 actual tokenizer / реальная генерация / oversized question | PASS | `gpu-regression.json` |
| Versioned build/publish/rollback/failed stage | PASS | `stack-regression.json` |
| Backup → отдельный restore → A/B → audit → index rebuild | PASS: new directory, SQL integrity, A/B, audit chain, Qdrant/Neo4j rebuild | `stack-regression.json` |
| Qdrant unavailable / recovered, liveness vs readiness | PASS | `readiness-failure.json` |
| Promtool / dashboard expressions / scrape targets | PASS | `promtool.log`, `observability.json` |
| Fresh venv + pinned wheels, без сети | PASS | `offline-smoke.json`, `wheelhouse-manifest.json` |
| CPU / GPU holdout | 0 / 0 failures; 23 / 23 completed | `eval-cpu.json`, `eval-gpu.json` |
| Полная offline apt/base-image сборка | NOT CONFIRMED | использован подготовленный runtime; Python wheels проверены отдельно |
| GitHub Actions на remote runner | NOT RUN | workflow подготовлен локально; GPU на обычном runner явно PENDING |
| Production HA / chaos / сертификация / экспертный corpus / calibrated judge | NOT RUN | нет соответствующего стенда и размеченных данных |

Временная среда: Docker Linux/Python 3.12, Windows/WSL2, RTX 4070, vLLM 0.10.2 AWQ Marlin. Результаты предыдущего кандидата сохранены отдельно и не являются доказательством финального tree. Цикл red→green первоначальных исправлений: `baseline-red.log`, `p1-unit.log`, `p1-security-extra.log`; финальный прогон привязан к image/bundle в manifest.

## Сопоставимая нагрузка

Дополнительно PASS: UI-поиск и запрет B (`ui-regression.json`, PNG), 11/11 model hashes (`model-hashes-final.json`), соответствие текущего source bundle release manifest. Временный Docker namespace закрыт (`cleanup.json`); проверенный образ сохранён для воспроизводимого запуска.

| Профиль | N / C | RPS: до → после | p95 ms: до → после | Errors |
|---|---|---|---|---|
| CPU | 300 / 8 | 6.38 → 6.7 | 1526.88 → 1497.26 | 0 |
| GPU | 48 / 4 | 2.44 → 1.81 | 2085.22 → 2319.26 | 0 |

Сырые p50/p99, elapsed, generation_modes — `benchmark-cpu.json` и `benchmark-gpu.json`. GPU conditional цель p95 ≤5000 ms оценивается только на этом запросе и C=4. Отдельные ASGI/старые исторические результаты не смешиваются с Docker HTTP.

RTO восстановления тестового набора: 0.6144 s; возраст snapshot на момент теста: 0.6156 s. Фикстуры не потеряны. Это время локальной процедуры, а не обещанный production RTO/RPO; нет расписания backup, больших объёмов и испытания аварии площадки.
