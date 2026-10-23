# Реестр архитектурных решений платформы

## Действующие дополнения 20.10.2026

Финальная оптимизация не меняет границы компонентов: request-scoped idle autocommit SQLite keeper уменьшает WAL/connection churn, не хранит ACL snapshot и закрывается после worker. Прежние final BEGIN IMMEDIATE/history/audit сохранены. Controlled A/B, побочные эффекты и решение KEEP — [PERFORMANCE-ANALYSIS](remediation/PERFORMANCE-ANALYSIS.md); актуальный строгий release HOLD — [FINAL-READINESS](remediation/FINAL-READINESS.md). Новая распределённая инфраструктура не добавлена.

ADR-P01–P06 ниже сохранены как исходные решения; устаревшие детали substring-only validator и destructive mirror superseded следующими ADR: [ADR-007 release snapshot / token budget](remediation/ADR-007-release-security.md) и [ADR-008 versioned delivery / quality](remediation/ADR-008-versioned-delivery.md). Grounding возвращает целые semantic units с offsets; данные авторизуются атомарным SQL release snapshot. Derived indices публикуются версиями, не очищаются перед rebuild. Model Card и фактические ограничения — отдельные актуальные документы.

## ADR-P01 Локальный inference и квантование

**Context.** Закрытый контур, русский язык, consumer RTX4070 с 12 GiB VRAM, pretrained модели без обучения. **Alternatives.** SaaS нарушает offline driver; DeepSeek-V3 полного размера превышает бюджет оборудования; FP16 7B оставляет недостаточный запас; llama.cpp GGUF удобен для offload, но отличается batching/serving API. **Decision.** GPU-профиль vLLM + Qwen2.5-7B-Instruct-AWQ, paged KV/prefix cache, AWQ Marlin kernel и capped concurrency. Generic AWQ оказался медленным на фактическом тесте; Marlin выбран по диагностике установленного vLLM и проверен повтором одинаковой нагрузки. Используем готовое quantized artifact, не deprecated AutoAWQ для обучения. **Consequences.** Меньше VRAM, автономность и поддержка русского языка; возможная потеря качества, зависимость от GPU kernels/драйвера, cold start. Extractive CPU path отдельно проверяет безопасность без подмены результатов GPU. **Gate.** Фактический generation benchmark и security cases выполнены. Широкий доменный Golden Set и сравнение quantized/reference качества остаются release gate для production, не подменяются синтетическим demo corpus.

## ADR-P02 Provenance GraphRAG

**Context.** Ответ требует соединить сведения в двух документах, а vector-only retrieval теряет связи. Онтология должна быть простой. **Alternatives.** Только Qdrant проще, но не выполняет GraphRAG requirement; LLM extraction любых типов связей даёт нестабильные triples и сложнее контролировать доступ. **Decision.** Document/Chunk/Entity с CO_MENTION edges, source chunk на каждом ребре, bounded 2-hop traversal. SQLite — canonical MVP graph, Neo4j — derived browser/index profile. **Consequences.** Реальные связи упоминаний и объяснимый provenance, легко проверить RBAC; co-mentions нельзя считать физической зависимостью, entity regex покрывает технические IDs, а не все сущности русского текста. При масштабе перейти на authoritative Neo4j/PostgreSQL graph queries с тем же prefilter.

## ADR-P03 Qdrant и локальные embeddings

**Context.** Self-hosted vector DB обязательна, запрещён runtime download; для security tests нужна воспроизводимость без весов. **Alternatives.** Managed Pinecone не air-gapped; Milvus имеет больший operational footprint; только in-memory индекс не даёт отдельного data-plane container. **Decision.** Qdrant derived payload index, ACL filter до ANN, каноническая проверка результатов в SQL. Для семантики только предварительно доставленный multilingual embedder; hash vectors используются явно как offline lexical test mode. **Consequences.** Изоляция индекса и repeatable tests; rebuild при изменении dimension/model, double authorization усложняет поток, состояние mirror может быть stale и не используется как единственный источник прав.

## ADR-P04 Stateful LangGraph

**Context.** Требуется stateful agent и нелинейный workflow, ограниченный tool execution. **Alternatives.** Последовательный скрипт запрещён заданием; network multi-agent избыточен для одного read-only сценария; LlamaIndex Workflows допустим, но примеры курса используют Python graph agents. **Decision.** LangGraph StateGraph с типизированным state, conditional edges, двумя attempts и scoped persistent memory. **Consequences.** Видимые переходы и bounded loop; одна process replica с SQLite write lock имеет ceiling throughput, для нескольких replicas нужен PostgreSQL/checkpointer. Planner намеренно ограничен read-only retrieval вместо произвольного выполнения кода.

## ADR-P05 RBAC и проверенные цитаты

**Context.** User B не должен видеть секретный документ через shared entity, history или generated answer. **Alternatives.** Фильтрация после LLM уже раскрывает secret модели; права только на document-level retrieval без edge provenance пропускают graph bridge; свободный ответ трудно автоматически доказать. **Decision.** Grant → document → chunks/edges, фильтр до поиска/traversal и повторно перед выдачей. Generator возвращает только exact quotes со source IDs, validator проверяет подстроку и актуальные grants. SSE выпускает только полностью проверенный результат. **Consequences.** Strong grounding и testable ACL, но меньше стилистической свободы и нет real token streaming. Regex/DLP недостаточны для production safety, нужны доменные guard models и red-team evaluation.

## ADR-P06 Наблюдаемость и изолированная поставка

**Context.** Нужно показать реальный trace, метрики и offline запуск. **Alternatives.** Hosted LangSmith/Langfuse в SaaS противоречит контуру; только print logs не связывает agent stages; большой K8s сразу увеличит operational cost MVP. **Decision.** OpenTelemetry → local Jaeger, Prometheus/Grafana, Docker Compose internal network, checksum/pinned artifacts. Vault/SSO/mTLS/DMZ входят в production design. **Consequences.** Прозрачный запрос без содержимого ПДн; локальный Compose не обеспечивает HA/сертификацию, production controls требуют отдельной поставки и проверки, не объявляются уже выполненными.
