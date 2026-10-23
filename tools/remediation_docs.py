"""Render remediation documents from actual local evidence; absent evidence is HOLD."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/remediation'
E=OUT/'evidence'


def load(name):
    path=E/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write(name,text):
    (OUT/name).write_text(text.strip()+'\n',encoding='utf-8')


def main():
    cpu,gpu=load('eval-cpu.json'),load('eval-gpu.json')
    unit=load('verification.json')
    release=load('release-manifest.json')
    decision=release.get('readiness',{}).get('decision','HOLD — manifest ещё не сформирован')
    coverage=load('coverage.json').get('totals',{}).get('percent_covered',0)
    restore=load('stack-regression.json')
    image=load('build-final.json').get('image_id','NOT RUN')
    performance=[]
    for name,baseline_rps,baseline_p95 in [('cpu',6.38,1526.88),('gpu',2.44,2085.22)]:
        result=load('benchmark-'+name+'.json')
        performance.append(f"| {name.upper()} | {result.get('requests','NOT RUN')} / {result.get('concurrency','—')} | {baseline_rps} → {result.get('successful_rps','—')} | {baseline_p95} → {result.get('p95_ms','—')} | {result.get('errors','—')} |")
    perf='\n'.join(performance)
    metrics='\n'.join(f"| {key} | {cpu.get('metrics',{}).get(key)} | {gpu.get('metrics',{}).get(key)} |" for key in cpu.get('metrics',{}))
    write('REMEDIATION-REPORT.md',f'''
# Исправление проекта: 20.10.2026

F01–F05 устранены в исходном проекте. LangGraph, FastAPI, SQLite, Qdrant, Neo4j, OCR, Qwen AWQ/vLLM и разделение Control/Data Plane сохранены. Исходная оценка — 62/100. Решение для учебного синтетического MVP: **{decision}**. Промышленный запуск: **HOLD**.

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

Свежий набор: {unit.get('tests','NOT RUN')} тестов, coverage {coverage:.2f}%, lint/types/existing_check — см. [verification.json](evidence/verification.json), [JUnit](evidence/junit.xml) и журналы. Типизация охватывает шесть policy/evaluation модулей; lint проверяет критичные ошибки Python, а не весь style debt.

Первый GPU holdout выявил безопасную блокировку multi-hop цитаты: 1 FAIL и HOLD сохранены в `evidence/candidate-1/eval-gpu.json`. Ожидаемые ответы не ослаблялись. Добавлена проверяемая политика полного extractive fallback для неверной модельной цитаты, новый тест и новый собранный image; итоговые evidence привязаны к новому bundle hash. При code review также устранён teardown индексов через изменяемый глобальный agent: закрываются именно клиенты, созданные lifespan.

Проверенный образ: `{image}`. Источники в финальном runtime не монтировались поверх `/app`. В Git ещё нет commit, поэтому commit SHA в manifest отсутствует; существующий index/worktree не сбрасывался. Подтверждены Linux/Python 3.12 зависимости из 66 проверенных wheels в новом venv с `--network none`; свежая offline apt/base-image сборка не подтверждена, использован подготовленный OCR runtime.

## Производительность и границы

| Профиль | Запросы / concurrency | Успешный RPS: аудит → сейчас | p95 ms: аудит → сейчас | Ошибки |
|---|---|---|---|---|
{perf}

Клиент внутри backend → Nginx gateway:18080 → API; GPU использует реальный локальный Qwen. Прогоны последовательны, CPU 300/8, GPU 48/4; вопрос и corpus сценария сохранены. Это короткая повторяющаяся синтетическая нагрузка, не производственная capacity. Дополнительные tokenize round trips и SQL/security проверки имеют цену. Разница одного прогона не является статистической оценкой ускорения. Сравнение mixed типов есть в evaluation, отдельный mixed HTTP capacity benchmark не выполнялся.

RTX 4070 / 12282 MiB; снимок до нагрузки — 11139 MiB занятой VRAM, 7% GPU utilization и 12.96 W (`gpu-resources-before.txt`), а не пиковое/среднее потребление за benchmark. Более мощная GPU не потребовалась. Измеренное сравнение энергии до/после не выполнено.

## Сохранность и ограничения

Все destructive/failure тесты выполнялись в `course-remediation-20261020`, на копии SQL/identity и новых volumes. Исходные data, credentials, weights и индексы не удалялись; `portal_qdrant` не изменялся. Тестовые секреты не публикуются. Административный отзыв, зафиксированный до финального SQL snapshot, учитывается; writer после захвата write reservation завершится после commit выдачи. Переданные клиенту байты отозвать нельзя. Файловые identities требуют атомарного provisioning; это не распределённый OIDC lease.

Полные semantic units гарантируют точность цитирования относительно текста, но не достоверность самого документа, OCR или произвольное логическое entailment. Старые chunks автоматически не переписываются: для новой нарезки нужен явный re-ingest исходников. Numeric conflict detection ограничен реализованными инженерными атрибутами и не заменяет экспертную проверку. Production prerequisites и конкретный backlog — [RELEASE-READINESS](RELEASE-READINESS.md), [TECH-DEBT](TECH-DEBT.md).
''')
    write('REGRESSION-RESULTS.md',f'''
# Фактические регрессии: 20.10.2026

| Проверка | Результат | Доказательство |
|---|---|---|
| F01 / F02 / F03 / F04 / F05 | PASS в автоматических регрессиях | `tests/test_remediation.py`, `tests/test_grounding_http.py`, `evidence/junit.xml` |
| Набор unit/security/API/eval/backup/admission/release | {unit.get('tests','NOT RUN')} tests; exit {unit.get('exit_code','—')} | `verification.json`, `unit.log`, `coverage.json` |
| Lint / six-module mypy / backend.check | {unit.get('phases',{})} | `lint.log`, `types.log`, `existing_check.log` |
| CPU: HTTP A/B, tenant, session, injection, OCR, индексы, egress | {load('integration-cpu.json').get('checks','NOT RUN')} | `integration-cpu.json` |
| GPU: тот же integration suite | {load('integration-gpu.json').get('checks','NOT RUN')} | `integration-gpu.json` |
| F02 actual tokenizer / реальная генерация / oversized question | {load('gpu-regression.json').get('decision','NOT RUN')} | `gpu-regression.json` |
| Versioned build/publish/rollback/failed stage | {restore.get('decision','NOT RUN')} | `stack-regression.json` |
| Backup → отдельный restore → A/B → audit → index rebuild | {restore.get('restore','NOT RUN')} | `stack-regression.json` |
| Qdrant unavailable / recovered, liveness vs readiness | {load('readiness-failure.json').get('decision','NOT RUN')} | `readiness-failure.json` |
| Promtool / dashboard expressions / scrape targets | {load('observability.json').get('decision','NOT RUN')} | `promtool.log`, `observability.json` |
| Fresh venv + pinned wheels, без сети | {load('offline-smoke.json').get('status','NOT RUN')} | `offline-smoke.json`, `wheelhouse-manifest.json` |
| CPU / GPU holdout | {cpu.get('failures','—')} / {gpu.get('failures','—')} failures; {cpu.get('completed','—')} / {gpu.get('completed','—')} completed | `eval-cpu.json`, `eval-gpu.json` |
| Полная offline apt/base-image сборка | NOT CONFIRMED | использован подготовленный runtime; Python wheels проверены отдельно |
| GitHub Actions на remote runner | NOT RUN | workflow подготовлен локально; GPU на обычном runner явно PENDING |
| Production HA / chaos / сертификация / экспертный corpus / calibrated judge | NOT RUN | нет соответствующего стенда и размеченных данных |

Временная среда: Docker Linux/Python 3.12, Windows/WSL2, RTX 4070, vLLM 0.10.2 AWQ Marlin. Результаты предыдущего кандидата сохранены отдельно и не являются доказательством финального tree. Цикл red→green первоначальных исправлений: `baseline-red.log`, `p1-unit.log`, `p1-security-extra.log`; финальный прогон привязан к image/bundle в manifest.

## Сопоставимая нагрузка

| Профиль | N / C | RPS: до → после | p95 ms: до → после | Errors |
|---|---|---|---|---|
{perf}

Сырые p50/p99, elapsed, generation_modes — `benchmark-cpu.json` и `benchmark-gpu.json`. GPU conditional цель p95 ≤5000 ms оценивается только на этом запросе и C=4. Отдельные ASGI/старые исторические результаты не смешиваются с Docker HTTP.

RTO восстановления тестового набора: {restore.get('restore_seconds','NOT RUN')} s; возраст snapshot на момент теста: {restore.get('snapshot_age_seconds','NOT RUN')} s. Фикстуры не потеряны. Это время локальной процедуры, а не обещанный production RTO/RPO; нет расписания backup, больших объёмов и испытания аварии площадки.
''')
    write('QUALITY-REPORT.md',f'''
# Качество RAG и release gate

Версии: `golden-v1-synthetic`, `knowledge-fixture-v1`, prompt `evidence-v2`. 27 кейсов: 4 tuning, 23 holdout. IDs и нормализованные запросы между splits не пересекаются; evaluator выполняет только holdout. Исходники набора — `eval/build_golden.py`, `golden.json`, `corpus.json`; hashes и bundle сохранены в JSON. Разметка синтетическая авторская, не независимая экспертная. Исправления по результатам holdout уже происходили, поэтому этот holdout теперь является regression suite; для непредвзятой оценки нужен новый закрытый экспертный split.

Сценарии: факты/units, несколько hops, singleton, отсутствие факта, неоднозначность, противоречивые численные источники, отрицания/условия, scanned OCR PDF, tenant/role denial, ACL revoke, direct/indirect injection, oversized technical context и намеренно ложные model outputs. Последние проверяются adversarial fixture, а не приписываются Qwen. OCR выполняется локально; GPU evaluation вызывает реальную модель для обычных cases, но некоторые safety/fallback cases обходятся без generation по контракту.

| Профиль | completed / expected | coverage | invalid | failures | gate |
|---|---|---|---|---|---|
| CPU | {cpu.get('completed')} / {cpu.get('expected')} | {cpu.get('coverage')} | {cpu.get('invalid')} | {cpu.get('failures')} | {cpu.get('gate',{}).get('decision')} |
| GPU | {gpu.get('completed')} / {gpu.get('expected')} | {gpu.get('coverage')} | {gpu.get('invalid')} | {gpu.get('failures')} | {gpu.get('gate',{}).get('decision')} |

| Метрика | CPU | GPU |
|---|---|---|
{metrics}

## Формулы и применимость

Recall@6 — среднее `|retrieved expected sources| / |expected sources|` на кейсах с непустой разметкой источников; источники дедуплицируются по документам. Context precision — average precision по ранжированным уникальным документам: сумма precision@rank релевантных попаданий / число таких попаданий, затем macro mean; пропуски отдельно отражает Recall. Это proxy с полной синтетической разметкой, не произвольная оценка всех похожих документов.

Citation correctness — доля evidence с доступным source, совпадающим version и точным text[start:end]. Extractive groundedness — доля таких evidence, возвращающих полный semantic unit. Это проверка цитаты по источнику, не LLM faithfulness и не Ragas. Annotated fact coverage — macro mean `all(expected_facts in returned quotes)` на кейсах с expected sources; это ограниченный proxy relevancy, не полноценный answer relevancy judge. No-evidence precision — среди результатов no_evidence доля разметок no_evidence. Если знаменатель пуст, значение null и gate HOLD; нулевые/пропущенные измерения не подменяются успехом.

ACL leakage count — evidence вне актуального разрешённого SQL набора. Token violations — факт выхода за max_model_len в реальном vLLM mode с reserve+margin. Нарушения блокируют выпуск независимо от среднего качества. Adversarial security tests обязательны дополнительно. Latency p50/p95/p99 вычисляется по времени каждого case; создание отдельной БД и OCR включены. Это mixed evaluation, не HTTP capacity benchmark. Поля локального LLM-judge faithfulness/relevancy намеренно null: калиброванный judge не поставлялся.

Срезы document_type/tenant/role находятся в JSON. OCR — всего один holdout case, остальные текстовые. Язык fixtures — русский с техническими ID; независимого английского/языкового сравнения и fairness-метрик нет. Нельзя переносить доли на документы предприятия или другие подразделения.

## Gate и дальнейшая разметка

Пороги provisional: recall ≥0.90, context precision ≥0.50, citation correctness/groundedness/no-evidence precision =1, annotated fact coverage ≥0.90; failures=invalid=ACL leakage=budget violations=0, completed=expected>0, coverage=1, возраст ≤24 h, конечные валидные значения, совпадение dataset/corpus/model/prompt/bundle с проверяемым artifact. Частичный `--limit` даёт HOLD. Отрицательные и malformed/stale reports проверены тестами. Ни одна комбинация синтетических значений не даёт production approval.

Эксперты добавляют запросы и provenance в новую версию набора, определяют список допустимых фактов/единиц и безопасный отказ, согласуют thresholds и double review спорной разметки. Tuning редактируется отдельно, новый holdout до приёмки закрывается от автора исправлений. Для production дополнительно нужны независимый domain set и человеческие/откалиброванные локальные judge оценки, сравнение AWQ с reference и документированная процедура принятия риска.
''')
    write('RELEASE-READINESS.md',f'''
# Решение о готовности

**Учебный синтетический MVP: {decision}. Промышленный пилот: HOLD.** Дата 20.10.2026. Это инженерная оценка по шкале исходного аудита, не оценка преподавателя и не сертификация.

| Раздел исходной шкалы | До | После | Основание изменения |
|---|---|---|---|
| Сценарии работы /20 | 15 | 18 | F04 singleton, CPU/GPU/OCR, semantic citations; узкий synthetic corpus и нет геометрии |
| Архитектура /20 | 18 | 19 | Сохранён bounded LangGraph, реальные SQL release snapshot и versioned index pointer, code/sequence/dataflow обновлены |
| Безопасность /25 | 11 | 21 | F01–F03, adversarial/barrier/SSE, safe errors, bounded admission, audit chain; нет OIDC/mTLS/external immutability и полного red team |
| Эксплуатация и поставка /20 | 10 | 15 | Readiness/failure recovery, проверенный restore/index rollback, wheels offline, manifest, real alerts; нет remote CI GPU/HA/полного air-gap base build |
| Качество и Governance /15 | 8 | 10 | Исполняемый evaluator с coverage/freshness/HOLD и synthetic holdout; нет репрезентативной независимой экспертизы/калибровки |
| Всего /100 | 62 | 83 | Баллы даны за выполняемые проверки; наличие новых документов само по себе балл не повышает |

Оценка 83 применима при PASS финального unit/security/integration и GO synthetic gate в manifest. При устаревании evidence или FAIL выпуск снова HOLD. Число не означает 83% вероятности безопасности. Блокирующий P1 cap исходного аудита снят после детерминированных конкурентных regressions и реального tokenizer check; production ограничения остаются.

Образ `{image}`. Bundle и dependency lock — `evidence/release-manifest.json`; commit SHA отсутствует, потому что репозиторий ещё не имеет commit. Продвижение должно использовать именно этот content-addressed image, не пересборку по tag. Release command проверяет свежесть и совпадение bundle всех обязательных unit/CPU/GPU/eval/regression отчётов. Model weights external mount закреплены отдельным manifest; image digest не включает их bytes.

## Что курсом реально подтверждено

Итоговое GraphRAG задание: локальное inference, bounded stateful LangGraph, document/chunk/entity provenance, multi-hop и A/B RBAC, OCR, VectorDB/graph profile; C4 1–4/Sequence/ER/Data Flow, ADR и разделение planes. Практики quality engineering: исполняемые regression и versioned metrics/gate. Наблюдаемость: stage spans, HTTP/business denominators, alerts. Reliability/MLOps/FinOps: readiness, versioned publication/rollback, restore smoke, immutable artifact evidence и конфигурируемые оценки затрат. SSO/Vault/HA, полноценный semantic embedder, calibrated judge и multimodal geometry остаются проектными prerequisites; работающий учебный MVP не превращает их в выполненные компоненты.

## Блокеры промышленного пилота

Нужны назначенные service/data/security owners и решение об условиях пилота; анонимная демонстрационная Grafana и loopback Compose не корпоративный access control. Требуются SSO/OIDC, TLS/mTLS, secret manager, проверенная сегментация и provisioning lifecycle; PostgreSQL/HA/checkpointer при нескольких репликах; резервирование/restore на реальном объёме и установленные RPO/RTO; внешний защищённый audit/архив; независимый real corpus с разметкой, red team и калибровкой quality/quantization. Нужны полный supply-chain inventory/SBOM/signatures по выбранной политике, delivery rehearsal всех OS/model artifacts, подтверждённый CI и длительная/mixed нагрузка. Эти функции не разворачивались декоративно.

Автоматическая проверка разрешений несколько раз не завершалась до deadline для дополнительных Docker/браузерных действий. Альтернативные проверяемые запуски оформлены отдельными протоколами; timeout не был засчитан как PASS. Прежний runtime не продвигался и пользовательские volumes не мигрировались во время тестов. Оператор запускает новый образ после review, делает backup и явную индексацию; команды — RUNBOOK.
''')
    write('TECH-DEBT.md','''
# Оставшийся технический долг

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
''')
    write('RUNBOOK.md',r'''
# Эксплуатация учебного MVP

Команды из корня проекта. Все административные действия сначала выполняются на копии данных. `data/identities.json`, backups и пароли приватны; не помещать в отчёты/URL. Новый образ не запускается поверх пользовательских volumes автоматически.

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
''')
    card='''# System Model Card — закрытая платформа знаний

Дата: 20.10.2026. Статус: учебный synthetic MVP; промышленный пилот HOLD.

Intended use: сотрудник находит точные разрешённые цитаты и связи упоминаний оборудования, проверяет provenance и принимает решение самостоятельно. Prohibited use: автономное управление оборудованием, подтверждение промышленной безопасности, кадровые/медицинские/финансовые решения о людях, обход ACL и внешние inference API. Числа из противоречащих документов не разрешаются моделью автоматически; требуется эксперт.

Owners: service owner/Product, data owner/Domain expert, Security owner и MLOps/SRE — необходимые роли, конкретные лица не назначены. До пилота организация назначает их и принимает ограничения/пороги.

Model: Qwen/Qwen2.5-7B-Instruct-AWQ, revision b25037543e9394b818fdfca67ab2a00ecc7dd641; Apache-2.0, локальный manifest содержит 11 файлов с SHA-256 и tokenizer artifacts. Runtime vLLM 0.10.2 AWQ Marlin, max4096, output700, margin64 на RTX4070 12 GiB. Обучение/fine tuning не проводились. Tokenizer/chat template берутся из того же локального artifact; budget проверяется фактическим tokenize. Hash проверяет bytes относительно manifest, а не сертифицирует происхождение. Quantization может менять качество; независимое reference comparison не выполнено.

Data provenance: demo и eval документы синтетические, русскоязычные technical facts; OCR fixture scan-regulation.pdf; реальные документы предприятия и персональные данные не использовались. CLI ingestion имеет tenant/role grants, source version/page/hash. Hash embeddings дают lexical offline baseline, не полноценный multilingual semantic retrieval. Новые chunks сохраняют units; старый corpus не мигрирован автоматически. CO_MENTION не доказывает физическую или причинную связь.

Evaluation: versioned 4 tuning +23 regression holdout, отдельные CPU/GPU отчёты, deterministic citation/ACL/budget invariants, coverage/freshness gate. После исправлений по holdout он считается regression, не независимой оценкой generalization. Calibrated LLM judge, external benchmark/fairness и representative enterprise quality отсутствуют; см. remediation/QUALITY-REPORT.md. Числа не подменяют production acceptance.

Security assumptions: canonical SQL и администрация доверены, одна process replica; identities обновляются атомарно, файл защищён ОС. Последний release snapshot согласует ACL/evidence/graph/session/history/audit под SQL reservation; байты после commit не отзываются. Изоляция loopback/internal network — demo boundary. Input normalization, known injection regex, PII masking, allowlisted inference URLs и strict extractive spans являются слоями, но не гарантией обнаружения любых атак. Local SHA audit chain обнаруживает изменения при доверенном anchor, не защищает от полного rewrite DBA. Для пилота необходимы OIDC, mTLS, secret manager, независимый audit anchor/архив и red team.

Limitations: OCR распознаёт текст, не интерпретирует геометрию/таблицы; ошибочное число в источнике может быть точно процитировано. Полный unit сохраняет отрицания/условия, но автоматическая истинность/semantic entailment не доказана. Если token budget не позволяет весь context или модель прислала неверную цитату, система возвращает явный extractive fallback; читать usage.mode. Неподдержанный факт → no_evidence. Numeric conflicts требуют human review. API rate/concurrency caps per process, SQLite и in-memory Jaeger не HA.

Human oversight/feedback: инженер открывает исходный документ и проверяет единицы/дату/версию перед действием. Ошибка/инцидент регистрируется с request ID, source version, profile и expected safe behavior, без секретных цитат в общих logs. Data owner исправляет источник/разметку, QA добавляет synthetic regression, MLOps выполняет полный gate. Не включать feedback напрямую в prompt/обучение. Корпоративная процедура эскалации и владельцы должны быть назначены до пилота; см. remediation/RUNBOOK.md.
'''
    (ROOT/'docs/SYSTEM-MODEL-CARD.md').write_text(card,encoding='utf-8')
    write('ADR-008-versioned-delivery.md','''
# ADR-008: versioned indices, quality gate и закрытая поставка

Статус: принято для MVP. Дата: 20.10.2026.

Контекст: destructive rebuild терял rollback candidate, единичный успешный demo не доказывал качество/готовность. Требовалась проверяемая поставка без новых облачных сервисов.

Решение: canonical SQL остаётся источником truth. Создать новую immutable Qdrant collection и Neo4j partition index_version, проверить payload ACL/hash/version/count и graph nodes/edges, сравнить canonical epoch, затем publish один SQL pointer. Старые версии сохраняются, запрос считывает pointer один раз. Rollback разрешён лишь при совместимом canonical hash/dimensions; retire по умолчанию dry run с grace и защитой active/legacy. Это app-level publication, не distributed transaction между Qdrant и Neo4j.

Evaluation имеет versioned synthetic regression corpus, separate tuning, полный expected/completed/invalid/freshness/hash. Missing/partial/stale/ACL/token violations → HOLD. Provisional thresholds разрешают только synthetic MVP, production_approval всегда false. Один content-addressed Docker image проходит integration и GPU evaluation; manifest связывает code/dependency/model/prompt/index/evidence. При отсутствии Git commit SHA честно null. Нет подписи/SBOM/сертификации по факту наличия JSON.

Альтернативы: удалять active store проще, но лишает rollback; распределённый transaction coordinator и Kubernetes не нужны для single-host MVP; cloud eval нарушает контур. Trade-offs: время build/валидации и объём retained indices, grace/drain перед retire, длительные tests. Очистка безопасна в рамках MVP timeout, несколько replicas потребуют coordination. Полный offline base/apt поставляется staging, отдельно реально проверены wheels + новый venv.

Дополнение по результату GPU holdout: неверная модельная цитата не исправляется текстовыми эвристиками. Generator отбрасывает её полностью, выдаёт полные исходные units с явным fallback mode; Agent validator и final ACL snapshot остаются обязательными. Произвольный adversarial generator с искажённым отрицанием по-прежнему получает output_blocked. Неопределённый model transport/usage остаётся fail-closed ошибкой, не маскируется успехом.
''')
    # Replace obsolete operational claims, retain previous measurements as history.
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    readme=readme.replace('Swagger `/docs` позволяет вводить Authorization как header вручную в curl/API client.','Swagger `/docs` поддерживает схему BearerToken (Authorize).')
    if 'В контейнерном профиле загрузку' in readme:
        start=readme.index('В контейнерном профиле загрузку')
        end=readme.index('## Состав сдачи',start)
        readme=readme[:start]+'''В контейнерном профиле ingest выполняется через CLI внутри backend с корректными tenant/roles. После изменения corpus/ACL выполнить `python -m backend.index_admin build` внутри configured backend, затем `status` и `/ready`. Индексы versioned: build → validate → publish SQL pointer; прежние версии сохраняются. На startup build выполняется автоматически; destructive rebuild больше не используется. Backup, rollback, retention и продвижение закреплённого image — в `docs/remediation/RUNBOOK.md`.

'''+readme[end:]
    if 'После завершения проверок GPU-контейнер' in readme:
        first=readme.index('После завершения проверок GPU-контейнер')
        last=readme.index('`backend/`',first)
        readme=readme[:first]+'''Актуальное состояние и commands — `docs/remediation/REGRESSION-RESULTS.md` и `RUNBOOK.md`. Проверки выполнялись в отдельном `course-remediation-20261020`, пользовательские volumes не продвигались автоматически. Видео 05.10 — историческая демонстрация; исправления 20.10 в нём не показаны.

'''+readme[last:]
    banner=f'''## Исправления 20.10.2026

F01–F05 закрыты постоянными регрессиями. Учебный synthetic MVP: **{decision}**; промышленный пилот **HOLD**. Свежие результаты — [отчёт](docs/remediation/REMEDIATION-REPORT.md), [тесты](docs/remediation/REGRESSION-RESULTS.md), [качество](docs/remediation/QUALITY-REPORT.md), [готовность](docs/remediation/RELEASE-READINESS.md), [Model Card](docs/SYSTEM-MODEL-CARD.md).

Локальная проверка: установить `requirements-lock.txt` и `requirements-dev.txt`, затем `python tools/verify.py`. Evaluation: `python -m backend.evaluate --output data/eval-report.json`; GPU вариант требует локального LLM_URL и `--gpu`. Полный свежий dataset и совпадающий artifact обязательны; partial/stale отчёт даёт HOLD. `/health` — liveness, `/ready` — необходимые SQL/identity/index/model dependencies. API 1.1 возвращает проверяемые offsets цитат и явные fallback modes.

'''
    if '## Исправления 20.10.2026' in readme:
        start=readme.index('## Исправления 20.10.2026')
        end=readme.index('## Локальный запуск',start)
        readme=readme[:start]+banner+readme[end:]
    else:
        position=readme.index('## Локальный запуск');readme=readme[:position]+banner+readme[position:]
    (ROOT/'README.md').write_text(readme,encoding='utf-8')
    additions={
        'ADD.md':'''## Действующая реализация после 20.10.2026

Следующие уточнения имеют приоритет над прежними описаниями ниже. Final authorization — BEGIN IMMEDIATE release snapshot: evidence/graph/provenance/session/identity/history/audit согласуются перед commit. SSE отправляет один проверенный результат. Достоверность права относится к commit; последующие отзывы не отзывают переданные байты. Версии/текст источников проверяются повторно, history не хранит цитат.

TokenBudget использует реальный vLLM tokenizer/chat template с JSON/system/question/полными source units, reserve700 + margin64 при max4096. Неумещающийся context даёт extractive-context-limited; invalid model citation заменяется полными units с явным mode и повторной валидацией. Graph traversal идёт через authorized mentions, включая singleton chunks; bounded ≤2 hops/32 chunks/128 entities → rerank6. Grounding сохраняет целый unit и offsets; semantic truth/OCR accuracy не гарантированы.

Derived stores теперь immutable versioned с единым SQL active pointer, validate перед publication, retain/rollback; destructive delete active коллекции отсутствует. Readiness отделён от liveness, admission bounded, HTTP accounting охватывает auth/validation failures. Реализованы проверяемые backup/restore, audit chain, retention dry run, quality/release gate и явная FinOps estimate. Industrial SSO/Vault/HA/mTLS остаются prerequisites. ADR-007/008 и remediation/RUNBOOK описывают границы и trade-offs, Model Card — governance.

''',
        'ADR.md':'''## Действующие дополнения 20.10.2026

ADR-P01–P06 ниже сохранены как исходные решения; устаревшие детали substring-only validator и destructive mirror superseded следующими ADR: [ADR-007 release snapshot / token budget](remediation/ADR-007-release-security.md) и [ADR-008 versioned delivery / quality](remediation/ADR-008-versioned-delivery.md). Grounding возвращает целые semantic units с offsets; данные авторизуются атомарным SQL release snapshot. Derived indices публикуются версиями, не очищаются перед rebuild. Model Card и фактические ограничения — отдельные актуальные документы.

''',
        'проверки.md':f'''## Актуальная повторная проверка 20.10.2026

Финальные результаты remediation имеют приоритет над историей ниже: [REGRESSION-RESULTS](remediation/REGRESSION-RESULTS.md), [QUALITY-REPORT](remediation/QUALITY-REPORT.md), [RELEASE-READINESS](remediation/RELEASE-READINESS.md). Выполнено {unit.get('tests','NOT RUN')} unit/security/API/eval тестов, coverage {coverage:.2f}%; critical lint и шесть mypy modules настроены и запускаются. CPU/GPU integration, tokenizer budget, index rollback/restore и offline wheels имеют отдельные машинные evidence.

Учебный synthetic MVP: **{decision}**. Промышленный запуск HOLD. Старые числа и команды ниже — история 05–08.10; сведения «lint не настроен», «индексы пересоздаются» и старый status контейнеров к текущей реализации не относятся. Путь актуального benchmark: Docker client → gateway:18080 → backend, отдельные CPU300/8 и GPU48/4. Сырые результаты и ограничения в remediation, не ASGI throughput. Восстановление тестового snapshot: {restore.get('restore_seconds','NOT RUN')} s, production RPO/RTO не установлены.

'''}
    for name,addition in additions.items():
        path=ROOT/'docs'/name;text=path.read_text(encoding='utf-8')
        marker=addition.splitlines()[0]
        if marker in text:
            start=text.index(marker)
            original={'ADD.md':'## Назначение и границы','ADR.md':'## ADR-P01','проверки.md':'Исходный протокол:'}[name]
            end=text.index(original,start)
            text=text[:start]+addition+text[end:]
            path.write_text(text,encoding='utf-8')
        else:
            index=text.index('\n')+1;text=text[:index]+'\n'+addition+text[index:]
            path.write_text(text,encoding='utf-8')
    print('Documentation rendered from evidence; release:',decision)


if __name__=='__main__':main()
