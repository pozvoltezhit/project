# Состав сдачи

Учебный MVP защищённой платформы корпоративных знаний: локальная Qwen/vLLM, GraphRAG, LangGraph, разграничение доступа и наблюдаемость. Рабочие данные синтетические. Репозиторий содержит исходники, инфраструктуру, документы, видео и сохранённые результаты проверок.

## Материалы

| Что проверять | Материал |
|---|---|
| Архитектурное описание | [ADD.md](docs/ADD.md), [ADD.pdf](docs/ADD.pdf) |
| Выбор стека и trade-offs | [ADR.md](docs/ADR.md), [ADR.pdf](docs/ADR.pdf), [дополнения ADR-007](docs/remediation/ADR-007-release-security.md) и [ADR-008](docs/remediation/ADR-008-versioned-delivery.md) |
| C4 1–4, Deployment, Sequence, ER, Data Flow | [PDF, восемь страниц](docs/архитектура.pdf), [редактируемый Draw.io](docs/архитектура.drawio) |
| Демонстрация, 6 минут 14 секунд | [Видео MP4](docs/демо.mp4), [расшифровка](docs/демо-текст.md), [метаданные длительности](docs/evidence/video-check.json) |
| RPS, latency, hardware и ограничения измерений | [PERFORMANCE-ANALYSIS.md](docs/remediation/PERFORMANCE-ANALYSIS.md) |
| Итоговая готовность | [FINAL-READINESS.md](docs/remediation/FINAL-READINESS.md) |
| Исправление качества LLM, raw до/после, frozen validation | [LLM-QUALITY-INVESTIGATION.md](docs/remediation/LLM-QUALITY-INVESTIGATION.md) |
| Сохранённые machine-readable результаты | [Evidence 20.10.2026](docs/remediation/evidence/llm-quality-20261020), [исходный strict gate verdict](docs/remediation/evidence/llm-quality-20261020/release-manifest.gate.json) |
| Запуск и эксплуатация | [README](README.md), [RUNBOOK](docs/remediation/RUNBOOK.md) |
| Защита проекта и матрица требований | [DEFENSE-PACK.md](docs/remediation/DEFENSE-PACK.md) |

## Код и воспроизведение

- `backend/`: API, state machine, ingestion/OCR, canonical ACL, GraphRAG, локальный inference и проверки.
- `frontend/`: форма поиска и отображение проверенных источников.
- `infra/`: Docker Compose, Dockerfiles, конфигурация gateway/метрик/дашбордов, подготовка модели.
- `examples/`: только синтетические документы, в том числе image-only PDF и явно синтетический секретный бюджет для RBAC-теста.
- `eval/`, `tests/`, `tools/`: зафиксированные наборы, unit/security tests и инструменты проверки.
- `.github/workflows/verify.yml`: CPU verification на GitHub Actions; отсутствие GPU на runner явно обозначается, не подменяется mock.

Нужны Docker с Linux containers; для GPU — совместимые NVIDIA driver/passthrough и достаточная VRAM. Pre-trained Qwen weights подготавливаются локально по [manifest](models/qwen-manifest.json); модель не обучается. Runtime не обращается к облачным inference API. Внешняя загрузка зависимостей/images/weights выполняется на подготовительном этапе до работы закрытого контура. Полная поставка в чистую air-gap среду с нуля ещё не подтверждена.

## Статус доказательств

Сохранённый прогон **20.10.2026**: 69 PASS, 0 FAIL/SKIP; исходные27 Golden cases, новые16 regressions и GPU validation20 прошли. GPU48/C4:8,66 RPS,p95=690,80 мс;192/C4:9,32 RPS,p95=468,75 мс, HTTP errors0. Это тёплый синтетический повторяющийся workload. Исходный strict gate дал учебный GO; production_approval=false. Эти датированные результаты не означают автоматический свежий допуск любого последующего checkout: внутренний gate требует свежих same-bundle reports≤24ч.

Source-code bundle проверенной реализации: `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`. При публикации этот код сохранён; добавлена навигация и отключена Git-конвертация переводов строк. Исторические manifest/inventory/archive/checksum files фиксируют материалы на момент проверки, включая прежний README, `.gitattributes` и отсутствие Git-коммита. Они не переписаны под новую публикацию и не являются инвентаризацией всего текущего репозитория. Новая CPU CI-проверка связана уже с опубликованным Git-коммитом.

## Ограничения

- Видео историческое: финальные source selectors и новые benchmark numbers в него не перемонтированы. Для текущей реализации использовать новые отчёты/traces и live smoke по runbook.
- Qwen выбирает доказательные фрагменты; сервер восстанавливает точный исходный текст. Свободный пересказ и полный semantic entailment не заявляются.
- OCR сканов реализован; геометрия чертежей и сложные таблицы не реализованы. Calibrated LLM-as-a-Judge отсутствует; synthetic annotation proxies не заменяют доменную экспертизу.
- Часть исходных ADD/ADR/PDF сохраняет исторический срез. Актуальный технический verdict — FINAL-READINESS и LLM-QUALITY-INVESTIGATION; прежние HOLD/GO относятся к своим artifact IDs.
- Промышленный пилот HOLD: SSO/TLS/DLP/HA, независимый domain holdout и реальные RPO/RTO требуют отдельных работ.

Не публикуются `data/`, provisioning tokens/passwords, локальные SQL databases/backups, Docker image archives, model weights и caches. Их создают или доставляют отдельно по runbook. В `docs/evidence` — разрешённые синтетические traces и замаскированные screenshots.

По заданию работу нужно передать минимум за восемь дней до защиты. Дата защиты здесь не задана; соблюдение календарного срока этим репозиторием не подтверждается.
