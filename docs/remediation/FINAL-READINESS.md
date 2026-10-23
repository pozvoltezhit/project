# Итоговая готовность: 20.10.2026

**Учебный release: GO. Промышленный пилот: HOLD.** Неизменённый strict gate вернул `decision=GO`, `reasons=[]`, `production_approval=false`. Это результат завершённого повторного прогона. Историческая оценка 83/100 относилась к предыдущему HOLD; новая числовая оценка без повторного полного аудита не назначалась.

Основной GPU-сценарий теперь выполняет реальный выбор доказательств Qwen с валидными источниками. Контракт `evidence-select-v4`: модель выбирает request-local source IDs; сервер восстанавливает точные полные semantic units и реальные offsets, затем выполняет прежние grounding и final ACL проверки. Это LLM-selected canonical evidence, не свободный русский пересказ. Исходные Golden Set, corpus и код release gate сохранены байт-в-байт.

## Проверенный артефакт

| Артефакт | Идентичность / evidence |
|---|---|
| Application image | `sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e` — локальный content-addressed image ID, не registry digest |
| Application bundle | `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`; checkout = frozen candidate = runtime = обязательные reports |
| Strict manifest / verification | [release-manifest.json](evidence/llm-quality-20261020/release-manifest.json), [manifest-validation.json](evidence/llm-quality-20261020/manifest-validation.json) |
| Source/config/test/tool delivery | `evidence/llm-quality-20261020/source-inventory.json`, `source-archive.json`; архив `data/llm-quality-20261020/source-bundle.zip` |
| Model/tokenizer | Qwen2.5-7B-Instruct-AWQ revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`, 11/11 file hashes PASS, прежний chat template |
| Prepared OS/OCR base | `sha256:185bfd1525b668d3483118d9203e2d80e4e502f14174a6b9b48fcb7ebb5227d1`; offline application rebase PASS, fresh OS/OCR air-gap build NOT RUN |

Manifest связывает обязательные отчёты, дополнительные quality/performance evidence, serving configuration, модель и полный source delivery. `/app` не перекрывался исходниками при runtime проверках; диагностические инструменты монтировались read-only отдельно в `/instrument`. Модель смонтирована read-only, runtime downloads отключены. Commit не создавался; отсутствующий commit SHA не выдумывается. Для promotion использовать именно проверенный image ID без rebuild. Изменение артефакта или старение evidence требует нового прогона.

## Завершённые проверки

| Проверка | Результат |
|---|---|
| Unit/security/F01–F06 | **69 PASS, 0 FAIL, 0 SKIP**, coverage **84,92%**; прежние 51 тест и 18 новых quote/selection regressions |
| Lint / mypy / existing check | PASS; дополнительный lint delivery scripts PASS |
| Runtime dependency pins / pip check | PASS, `No broken requirements found` |
| CPU HTTP integration | PASS, `generation_mode=extractive` |
| GPU HTTP integration | PASS, primary `generation_mode=vllm` |
| Исходный Golden Set | Все **27/27** в CPU/GPU: 4 tuning + 23 regression, synthetic gate GO |
| Первый новый набор | **16/16** CPU/GPU; после использования для доработки считается regression suite |
| Второй frozen validation | **20/20** GPU, первый запуск после freeze финального selector; 16/16 прямых ответов, 2 корректных LLM-абстенции, 0 invalid-generation fallback |
| Grounding / ACL / budget | Ни одной недостоверной выдачи/утечки/budget violation в завершённых финальных наборах |
| Real tokenizer/F02 | PASS: oversized context → безопасный context fallback; oversized вопрос → controlled rejection; short-case real vllm |
| Versioned index / restore | PASS: publish, retain, rollback, reject failed staged build; новый restore, SQL integrity, A/B ACL, audit chain, Qdrant/Neo4j rebuild |
| Strict release / manifest hashes | **GO / PASS**, обязательные reports одного bundle и свежие |

GPU integration также проверила tenant/role/session/injection guards, реальный image-only OCR, Qdrant ACL, Neo4j mirror, Jaeger, Prometheus и blocked backend egress. F01 atomic final authorization/audit, request-scope keeper и F05/F06 transport accounting сохранены. Numeric conflict по-прежнему требует human review. Неизвестные IDs, model-supplied offsets, смешанные схемы и некорректные legacy quotes отклоняются; safe fallback сохранён.

Подробная первопричина, отклонённый prompt-only кандидат, raw до/после и методология — [LLM-QUALITY-INVESTIGATION](LLM-QUALITY-INVESTIGATION.md). Прямые модельные ответы, допустимые fallback и ошибки в отчётах разделены. Три adversarial fixtures исходного Golden не приписаны Qwen. Citation/source-faithfulness и annotated relevancy proxies =1 в финальных проверенных срезах; calibrated judge и полный semantic entailment не установлены.

## Скорость на прежнем workload

Модель/quantization/serving, GPU, corpus/index и вопрос не менялись. Temperature=0, context=4096, output reserve=700, margin=64, prefix cache, max-num-seqs=4, max-num-batched-tokens=1024, GPU memory fraction=.80. Перед каждым прогоном 8 warmup; capacity не совмещалась с другими тестами/сборкой, server profiler выключен.

| GPU вариант | N/C | RPS | p95 мс | HTTP errors |
|---|---:|---:|---:|---:|
| Исторический reference | 48/4 | 2,53 | 1631,63 | 0 |
| Повтор baseline | 48/4 | 2,52 | 1632,45 | 0 |
| Повтор baseline | 192/4 | 2,48 | 1685,90 | 0 |
| Финальный selector | 48/4 | **8,66** | **690,80** | **0** |
| Финальный selector | 192/4 | **9,32** | **468,75** | **0** |

Все 240 measured selector ответов — vllm. Счётчики подтверждают ровно N генераций на N запросов, 415/18 tokens per primary answer вместо 396/110. Retry/corrective generation не добавлялась. Это локальный тёплый повторяющийся workload, не soak/mixed-corpus capacity. Старое CPU300/C8=20,80 RPS остаётся историческим измерением; CPU capacity в этой итерации заново не измерялась.

## Ограничения и промышленный HOLD

- Новые наборы авторские синтетические; второй frozen до selector, но родственен первому по генератору и тематике. Отсутствие точного query overlap не доказывает отсутствия переобучения. Нужен закрытый экспертный domain holdout.
- OCR проверен на прежнем scanned PDF с новыми вопросами; сложные таблицы, геометрия и visual reasoning не реализованы. Полнота семантического вывода за пределами аннотаций не подтверждена.
- CPU остаётся детерминированным extractive профилем. Специальная проверка селективности среди нерелевантных источников второго набора относится к GPU LLM selector.
- SSO/OIDC, TLS/secret lifecycle, полноценный DLP/red team, HA/checkpointer, внешний audit anchor и реальные RPO/RTO требуют отдельных acceptance tests и owners.
- Первый commit, remote CI и fresh import/build/run всего air-gap inventory остаются NOT RUN. Локальный offline rebase на подготовленной базе не заменяет эти проверки.
- Видео 374,046 с сохранено; прежние chapters не доказывают новый selector. Для защиты использовать новые traces/live smoke и актуальные оговорки DEFENSE-PACK.

Предыдущий HOLD и evidence сохранены: [prior-final-readiness.md](evidence/llm-quality-20261020/prior-final-readiness.md), `evidence/final-20261020/` и неуспешный v3 candidate. Неизвестные файлы/volumes/индексы, `portal_qdrant`, weights, реальные credentials и global Docker/Git config не изменялись. Commit/push не выполнялись. Финальное состояние только собственного disposable стенда фиксируется `evidence/llm-quality-20261020/stand-final.json`; private synthetic data и его volumes сохраняются для повторения.
