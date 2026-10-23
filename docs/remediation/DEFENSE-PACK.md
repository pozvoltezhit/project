# Защита учебной платформы корпоративных знаний

Актуальное дополнение: учебный strict release **GO**, production **HOLD**, image `8761850…`, 69 tests PASS. Primary Qwen выбирает source IDs, сервер восстанавливает точные canonical citations с прежней final ACL проверкой; это выбор доказательств, не свободный пересказ. Исходные27 + regression16 и frozen GPU validation20 прошли. GPU48/C4=8,66 RPS/p95=690,80 ms,192/C4=9,32/468,75, errors0. Новые traces/manifest — `evidence/llm-quality-20261020/`, объяснение и ограничения — LLM-QUALITY-INVESTIGATION. Старое видео и evidence ниже исторические; для новой демонстрации показать `selected/primary-01.json` и актуальный manifest. Calibrated judge/domain acceptance/production prerequisites остаются открытыми.

Основание: оригинал `Задания/Проект.txt`, исходная `Аудит-проекта-2026-10-20/Матрица-курса.md`, ADD/ADR и текущий код. Это инженерная матрица, не оценка преподавателя. Итоговые проверки этой итерации хранятся отдельно в `evidence/final-20261020/`; прежние evidence сохранены. Срок «за 8 дней» остаётся непроверенным: дата защиты и подтверждение сдачи отсутствуют.

## Подтверждение требований

| Категория / требование | Реализация | Демонстрация | Evidence | Статус |
|---|---|---|---|---|
| Обязательное: закрытый End-to-End pipeline | ingestion → canonical SQL → versioned Qdrant/Neo4j → LangGraph → проверяемые evidence | Сценарии 1–4 ниже | integration CPU/GPU; `backend/ingest.py`, `core.py`, `adapters.py` | PASS для synthetic MVP |
| Архитектура: C4 Context, Container, Component, Code | 4 страницы Draw.io/PDF, ADD | Открыть первые 4 страницы `../архитектура.pdf` | `../архитектура.drawio`, `../ADD.md` | PASS |
| Deployment и Data Flow — условия допуска | Отдельные страницы 5 и 8; Internal/Edge, GPU, target DMZ/Vault/HA обозначены как design | Показать реальный single-host Compose и целевой deployment раздельно | `infra/compose*.yaml`, ADD | PASS документация; PARTIAL production deployment |
| Sequence, ER, Control/Data Plane | Страницы 6–7; API/Agent управляют, SQL/индексы/vLLM обслуживают данные | Проследить запрос и финальный commit | `core.Store.finalize`, `Agent.run`, ADD/ADR | PASS |
| Обоснование стека | ADR-P01–P06, ADR-007/008 | AWQ/VRAM, SQLite vs replicas, SQL vs derived graph | `../ADR.md`, `ADR-007-release-security.md`, `ADR-008-versioned-delivery.md` | PASS |
| Self-hosted русская pretrained LLM, consumer GPU, quantization/KV | Qwen2.5-7B-Instruct-AWQ, vLLM 0.10.2, AWQ Marlin, FP16 KV, prefix cache, 4096 | Сценарий 1; показать actual token usage | GPU integration/regression, model hashes и vLLM log | PASS в проверенном профиле |
| Self-hosted vector DB и GraphRAG | Qdrant ACL filter; canonical mentions traversal, Neo4j mirror | Двухдокументный мост Н-17 → К-2 → Д-8 | independent graph probe + integration | PASS bounded provenance GraphRAG; semantic retrieval PARTIAL |
| Stateful нелинейный LangGraph | guard conditional exit, plan/retrieve retry ≤2, history ownership | Сценарий 5 | `stages`, independent/unit tests | PASS |
| User B не получает secret | tenant + roles + session checks + final transaction | Сценарий 3, конкурентный отзыв | independent tests, integration, GPU regression | PASS в проверенных контрактах |
| Input/output guards, PII | NFKC, regex quarantine/masking, canonical quotes, source ACL | Negative query и poisoned fixture | unit/eval cases | PARTIAL: нет полного DLP или сертификата безопасности |
| Сложные PDF/сканы/чертежи | Реальный Tesseract rus+eng для image-only PDF | Сценарий 4 | integration OCR, holdout OCR case | PARTIAL: геометрия/таблицы/visual reasoning не реализованы |
| OTel, Prometheus, Grafana | agent/LLM spans, HTTP/business/queue/dependency/token metrics, alerts | Сценарий 6 | integration; observability snapshot | PASS базовый; эксплуатационная HA не заявляется |
| Monorepo, ADD Markdown/PDF, нагрузочный отчёт | backend/infra/docs и evidence | Открыть репозиторий и PERFORMANCE-ANALYSIS | manifest/source inventory, benchmark JSON | PASS локально; первый commit/remote CI не выполнены |
| Видео 5–7 минут с traces/logs/graph | Готовые 374,046 с, смонтированные реальные screens + локальная TTS | Историческое видео + свежая live проверка | `../демо.mp4`, `../демо-текст.md`, video-check.json | PASS формат; содержание обновить фрагментами ниже |
| Желательно: streaming | Один SSE result после полной авторизации | `/query/stream` | independent slow-client / accounting tests | PARTIAL: нет token streaming |
| Желательно: LLM-as-a-Judge | Детерминированные extractive tests и synthetic regression dataset | Quality gate с явно пустыми judge-полями | QUALITY-REPORT, eval JSON | GAP для calibrated judge |
| Перенос ДЗ 5–10 | Versioned indexes, release/quality gate, backup/retention, Model Card, FinOps estimate | Сценарии 7–8, manifest | stack/unit/eval, SYSTEM-MODEL-CARD | PASS реализованных механизмов; реальный domain acceptance PARTIAL |
| Production prerequisites | SSO/TLS/Vault/HA, независимый domain set, внешний audit anchor, RPO/RTO | Только объяснение границ | TECH-DEBT | GAP; не обязательная декоративная инфраструктура MVP |

## Выступление на 5–7 минут

**0:00–0:50. Задача и границы.** Я реализовал учебное ядро закрытой платформы корпоративных знаний. Пользователь задаёт инженерный вопрос и получает проверяемые выдержки с документом, страницей и версией. Для демонстрации использованы синтетические документы, а не информация предприятия. Система работает с локальной моделью и локальными базами. Важно различать работающий single-host MVP и целевую промышленную архитектуру: корпоративная идентификация, отказоустойчивый кластер и полноценная обработка чертежей здесь ещё не реализованы.

**0:50–1:45. Архитектура.** На схеме Control Plane — FastAPI и ограниченный LangGraph. Data Plane — каноническая SQLite, Qdrant, производный граф Neo4j и vLLM. В SQLite хранятся документы, версии, grants, chunks, mentions, история и audit. Канонические права проверяются независимо от состояния производных индексов. Индексы строятся как новая версия, проверяются, затем публикуются одним SQL pointer. Старые версии сохраняются. Это даёт понятную границу публикации без заявления о распределённой транзакции между тремя базами. Deployment отдельно показывает реально запущенный Compose и будущие зоны с Vault и балансировкой.

**1:45–2:40. GraphRAG и агент.** Первый документ связывает насос Н-17 с контуром К-2, второй — контур с датчиком Д-8. Traversal проходит через mentions разрешённых chunks и возвращает оба источника, включая односущностного соседа. CO_MENTION означает совместное упоминание, а не доказанную физическую причинность. После rerank модель выбирает evidence, затем система проверяет цитаты и повторно авторизует выдачу. LangGraph имеет условный выход guard и повторный поиск при отсутствии контекста, максимум две попытки. Это конечная state machine, а не линейная цепочка и не автономный агент с shell-доступом.

**2:40–3:40. Безопасность.** Роли и tenant берутся из серверного provisioning, не из пользовательского JSON. Пользователь A может читать секретный синтетический документ, B — нет, даже если они упоминают общий объект. Для конкурентного отзыва используется финальная транзакция BEGIN IMMEDIATE: отзыв, зафиксированный до неё, наблюдается, а поздний writer ждёт завершения snapshot выдачи. Генерация и передача клиенту проходят вне SQL-транзакции. Переданные байты нельзя отозвать задним числом. Цитата возвращается как полный канонический смысловой unit с offsets: это сохраняет отрицания и условия, но не доказывает истинность документа или произвольное semantic entailment. Regex guards — дополнительный ограниченный слой, не абсолютная защита.

**3:40–4:35. Локальный inference и измерения.** На RTX 4070 с 12 ГБ используется Qwen AWQ через vLLM, контекст 4096, output reserve 700 и margin 64. Полные chat messages измеряются реальным tokenizer того же сервера. При нехватке контекста система явно возвращает безопасный extractive fallback, сохраняя источники целиком. Покажу текущую таблицу PERFORMANCE-ANALYSIS: отдельные CPU/GPU прогоны, concurrency, ошибки и ограничения сравнимости. Один удачный p95 не означает устойчивую capacity; историческую регрессию нельзя объяснять без разбивки SQL, tokenizer и generation.

**4:35–5:35. Доказательства.** Покажу реальный llm.generate trace в Jaeger, HTTP и business counters в Prometheus/Grafana и token usage в ответе. Эти два вида результата различаются: безопасный no_evidence может быть успешным HTTP-ответом; отменённый SSE не считается успешной доставкой. Независимые тесты включают raw SQLite writer, изменение grants и версий, медленного клиента, межtenant shared entities и транспортные ошибки. Synthetic holdout — 23 regression cases, а не независимая экспертная оценка качества предприятия. Quality gate отклоняет неполный, старый или относящийся к другому bundle отчёт.

**5:35–6:20. Поставка и вывод.** Release привязан к проверенному application bundle, model hashes и content-addressed image. При продвижении используется тот же image, а не новая сборка. Restore и отказ Qdrant проверяются в отдельном namespace. Готовое видео длится около шести минут и содержит исторические реальные screens; актуальные изменения подтверждаются свежими evidence. Учебная готовность и промышленный допуск оцениваются раздельно. Следующие шаги для предприятия — независимая разметка документов, SSO/TLS, lifecycle секретов, внешний audit anchor и измеренные RPO/RTO. Баллы не повышаются за наличие новых Markdown-файлов: основания — работающие проверки и воспроизводимые результаты.

## Воспроизводимая демонстрация

Предусловия всех live сценариев: отдельный `course-final-20261020`, `/ready=200`, проверенный image/model manifest, свободный RTX4070 для GPU. Стенд этой итерации хранит только новые synthetic credentials в игнорируемом `data/final-20261020/runtime`. Не выводить их в терминал/видео. Команды ниже из корня проекта; `$demoKey` получить локально из этого файла для выбранного пользователя без `Write-Output`. Для запроса:

```powershell
$demoIdentities = Get-Content -Raw data/final-20261020/runtime/identities.json | ConvertFrom-Json
$demoKey = ($demoIdentities | Where-Object user -eq 'engineer-b').token
$demoHeaders = @{Authorization = "Bearer $demoKey"}
$demoBody = @{question='Как связан насос Н-17 с датчиком Д-8?'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:18080/query -Method Post -Headers $demoHeaders -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($demoBody))
```

| Сценарий | Команда / действие | Ожидаемое и фактическое подтверждение | Fallback на защите |
|---|---|---|---|
| 1. Локальный inference | Запрос выше; `docker exec course-final-20261020-backend-1 python -m backend.gpu_check`; `docker logs --tail 30 course-final-20261020-vllm-1` | Основной вопрос сейчас даёт `extractive-invalid-generation` после реального вызова Qwen; отдельный short case GPU regression — `mode=vllm`, budget ≤4096. Показать оба режима | Открыть сохранённые integration/GPU JSON и явно сказать, что это запись прогона |
| 2. GraphRAG | Тот же запрос; `/graph` с Bearer; Neo4j admin только локально | Два открытых источника, provenance Н-17/К-2/Д-8; independent graph test | Архитектура + сохранённый JSON; не выдавать SQL traversal за online Neo4j reasoning |
| 3. A/B и отзыв | Вопрос `Бюджет проекта П-9`, последовательно A и B; independent tests для concurrent revoke | A видит синтетический marker, B `no_evidence`; grants/tenant/session тесты PASS | Сохранённые regression XML/логи и historical A/B video |
| 4. OCR | `docker exec course-final-20261020-backend-1 python -m backend.integration_check` | Tesseract читает image-only `examples/scan-regulation.pdf`; временная SQL выдаёт страницу 1 | Показать PDF и OCR integration evidence; не заявлять распознавание любых чертежей |
| 5. LangGraph | Обычный query, затем неизвестный объект, затем `ignore previous instructions` | В `stages`: generate/validate; повтор plan для miss; ранний guard exit для injection | Сохранённые deterministic tests и C3/Sequence |
| 6. Observability | Jaeger `localhost:16686`, Grafana `localhost:13000`, Prometheus `localhost:19090` | query/agent/llm spans, HTTP/queue/stage/token series; prompt contents отсутствуют | Архив trace/метрик; in-memory traces исчезают при restart |
| 7. Quality/security | `python tools/finalize_runtime.py unit --label defense-check` и `checks --gpu --label defense-gpu` | Полные tests и 23/23 synthetic regression cases; gate GO лишь на совпадающем bundle | Готовые JUnit/coverage/eval; не менять Golden Set во время защиты |
| 8. Отказ зависимости | Только в disposable namespace: `docker stop course-final-20261020-qdrant-1`; проверить `/ready`, `/health`, query; затем `docker start ...` | ready/query 503, health 200, затем ready 200; результат в runtime evidence | Сохранённый failure/recovery JSON, если live отказ запрещён организатором |

Сценарии нельзя запускать одновременно с capacity benchmark. Index/backup/failure проверки изменяют только synthetic namespace. Исторический `tools/final_runtime.py` относится к предыдущей итерации; новый harness — `tools/finalize_runtime.py`.

## Вопросы преподавателя

1. **Почему это GraphRAG?** Retrieval seeds расширяются по canonical mentions: Entity → разрешённые chunks → entities; provenance возвращается с источником. Neo4j — проверяемое производное представление, online traversal сейчас SQL.
2. **Что означает ребро?** CO_MENTION, совместное упоминание в конкретном chunk; физическая связь подтверждается текстом, не самим ребром.
3. **Как защищён общий узел двух tenants?** Разрешение применяется к source chunks до traversal, каждый edge имеет свой source. Общая строка entity не объединяет grants.
4. **Что происходит при отзыве во время генерации?** Final snapshot повторно проверяет актуальные grants/версии/session ownership; ответ блокируется, если отзыв committed раньше snapshot.
5. **Можно ли отозвать уже отправленный ответ?** Нет. Контракт линеаризует авторизацию на SQL release boundary, а не на последнем полученном TCP-байте.
6. **Удерживается ли SQL lock при SSE?** Нет, complete result материализуется и transaction commit заканчивается до начала StreamingResponse.
7. **Как исключается hallucination?** Выдача ограничена точными каноническими semantic units и доступными source IDs. Истинность источника и произвольное entailment этим не доказываются.
8. **Почему 4096 и AWQ?** Ограничение consumer GPU и контролируемого KV/weights бюджета. Изменение context/quantization требует отдельного measured experiment.
9. **Как считается budget?** Serving `/tokenize` для тех же chat messages с generation prompt; input + output reserve + margin ≤4096; usage сверяется после inference.
10. **Что делать с слишком длинным контекстом?** Явный extractive-context-limited fallback с полными units; oversized вопрос отклоняется управляемо.
11. **Есть ли внешнее API из-за OpenAI-compatible endpoint?** Это совместимый HTTP-формат внутреннего vLLM. Модель локальна, egress backend проверен отдельно.
12. **Где нелинейность LangGraph?** Guard conditional exit, bounded retry поиска и memory разрешённых source IDs; пользователь не управляет SQL/shell/tools.
13. **Почему SQLite?** Достаточна одному host/process и упрощает atomic ACL snapshot. Для нескольких replicas нужны согласованная shared SQL/checkpointer и новая проверка, а не копии SQLite.
14. **Что atomic при index publication?** Один SQL active pointer после проверки двух immutable derived stores. Распределённого commit Qdrant+Neo4j нет, старые версии сохраняются.
15. **Что доказывает 23/23?** Отсутствие регрессии на авторском synthetic dataset. После исправлений по нему это regression suite, не непредвзятая оценка предприятия.
16. **Почему не LLM judge?** Некалиброванный judge добавил бы неподтверждённую оценку и расход GPU. Judge-поля null; для pilot нужна экспертная разметка и calibration.
17. **Как измерялось ускорение?** Один query mix, модель/config, warmup, последовательные C1/C2/C4, raw latency, A/B и повторения. Итог — PERFORMANCE-ANALYSIS с пределами достоверности.
18. **Что доказывает image digest?** Идентичность локального image bytes. Внешние weights/config/data требуют собственных hashes; digest старого image не подтверждает новое дерево исходников.
19. **Как восстановить систему?** Consistent SQL backup + защищённые credentials/sources/model manifest; restore в новый каталог, проверка integrity/audit, rebuild derived indexes и A/B smoke.
20. **Что мешает промышленному допуску?** Независимый domain acceptance, SSO/TLS/secret lifecycle, full DLP/red team, HA/backup objectives, внешний audit anchor и supply-chain/CI rehearsal. Наличие demo не заменяет эти проверки.

## Видео и ограничения

Текущие численные результаты и release status читать в Markdown этого пакета. Ранее созданные PDF протокола проверок/ADR сохраняются как предыдущие редакции и не перегенерировались в этой итерации. Структура восьми архитектурных страниц проверена по Draw.io: новые keeper/transport accounting не меняют границы изображённых компонентов; повторная визуальная ревизия каждого PDF не выполнялась.

`../демо.mp4` (374,046 с) сохранено без пересоздания. Точные главы — `../демо-текст.md`. Для новой версии заменить:

- **00:41–01:22:** добавить полные semantic units/idempotent ingestion и versioned index publication вместо устаревшего поведения.
- **01:22–02:07:** актуализировать counts узлов/рёбер и version/tenant labels: они зависят от текущего index release; показать singleton mentions traversal.
- **02:07–03:42:** дополнить A/B финальным SQL snapshot и честным контрактом concurrent revoke; прежний A/B сам по себе не проверяет гонку.
- **03:42–04:32:** обновить agent trace финализацией и transport outcomes.
- **04:32–05:22:** добавить реальный token usage и reserve/margin; параметры модели остаются прежними.
- **05:22–06:14:** заменить исторические RPS/p95 таблицей текущей итерации, показать bundle/image и synthetic quality gate. Исторические цифры не выдавать за новые.

Границы live демонстрации: OCR всего одного synthetic scan, lexical embedding/rerank, CO_MENTION ≤2 hops/32 chunks/128 entities (API context ≤6), статические локальные identities, один backend/GPU, SSE после полной проверки, SQL audit chain без внешнего immutable anchor. Энергопотребление telemetry не равно доказанной финансовой экономии.

## Checklist перед защитой

- Проверить дату сдачи и доступность репозитория преподавателю; commit не создавался автоматически.
- Проверить model hashes, image ID и совпадение bundle с manifest; использовать этот же image без rebuild.
- Запустить стенд заранее, дождаться model/backend ready, выполнить короткий реальный GPU query и A/B denial.
- Сверить profile context/output/margin и свободную VRAM; прекратить benchmark перед live demo.
- Открыть C4/Deployment/Data Flow/ADR, Jaeger, Grafana, Neo4j и PDF scan. Пароли и Bearer не показывать.
- Подготовить offline копии JUnit/eval/benchmark/manifest и готовое видео; проверить воспроизведение звука.
- Обозначить synthetic scope, исторические фрагменты видео и production HOLD; не обещать сертификацию или geometry reasoning.
- Failure scenario выполнять только в disposable namespace и всегда восстановить Qdrant.
