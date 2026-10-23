# Качество RAG и release gate

## Актуальный выпуск: `8761850…`, evidence-select-v4

Strict учебный release **GO**, production **HOLD**. Новый bundle `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`; evidence — `evidence/llm-quality-20261020/`. Исходные Golden/corpus/release gate сохранены. Все 27 Golden cases прошли в CPU/GPU (4 tuning +23 regression), новые16 также прошли CPU/GPU. Второй набор20 заморожен до selector и впервые выполнен после freeze кандидата: GPU20/20, 16/16 прямых ответов, две корректные LLM-абстенции, 0 invalid-generation fallback. Ни одной недостоверной выдачи или ACL/budget violation в финальных проверенных срезах.

Qwen выбирает request-local source IDs, сервер разрешает их в точные canonical units и исходные offsets с прежними grounding/final ACL проверками. Это LLM-selected evidence; свободный пересказ и полный semantic entailment не заявляются. Exact source/fact coverage и citation correctness proxies=1, calibrated judge-поля null. Raw traces, отвергнутый v3 (9/13 против baseline12/13), новая валидация16/16 и ограничения независимости подробно разобраны в [LLM-QUALITY-INVESTIGATION](LLM-QUALITY-INVESTIGATION.md). Первый новый16 теперь consumed regression; второй20 родственен по авторскому генератору, не заменяет экспертный domain holdout. OCR-корпус остался прежним.

Unit/security69 PASS, 0 FAIL/SKIP, coverage84,92%. Реальные CPU/GPU integrations и tokenizer regressions PASS; manifest same-bundle verification PASS. Старые результаты ниже — исторические, их HOLD не является текущим verdict.

## Историческая проверка image `2945daf…`

Свежие CPU/GPU evaluation — `evidence/final-20261020/candidate/{cpu,gpu}/eval.json`, bundle `8e3e74e7f989c83ff6f74b523f4e422cc2fada83e218fc27dfab11a4dfebf03c`. Каждый профиль:23/23, coverage1, invalid0, failures0, ACL leakage0, token violations0, synthetic quality GO. Метрики одинаковы: recall@6=1, context precision=.9583333333, citation correctness/extractive groundedness/annotated fact coverage/no-evidence precision=1. Judge faithfulness/relevancy остаются null.

Primary HTTP workload на fresh corpus и baseline/candidate выполняет реальный Qwen (396input/110output), но две model quotes не exact substrings; `extractive-invalid-generation` возвращает полные canonical units. Диагностика без prompt/quote — `candidate/generation-diagnostic.json`. Это предусмотренный safe fallback, не качество model-selected quotes. Short GPU case остаётся прямым vllm. Existing release gate требует primary integration mode=vllm и даёт **HOLD**, несмотря на quality GO. Gate/expected Golden Set не ослаблены; детали FINAL-READINESS.

Формулы/ограничения ниже сохранены. После использования для исправлений набор является regression suite, не новым независимым holdout. Новые отчёты не повышают доказанную domain generalization.

## Методология и прежний remediation result

Версии: `golden-v1-synthetic`, `knowledge-fixture-v1`, prompt `evidence-v2`. 27 кейсов: 4 tuning, 23 holdout. IDs и нормализованные запросы между splits не пересекаются; evaluator выполняет только holdout. Исходники набора — `eval/build_golden.py`, `golden.json`, `corpus.json`; hashes и bundle сохранены в JSON. Разметка синтетическая авторская, не независимая экспертная. Исправления по результатам holdout уже происходили, поэтому этот holdout теперь является regression suite; для непредвзятой оценки нужен новый закрытый экспертный split.

Сценарии: факты/units, несколько hops, singleton, отсутствие факта, неоднозначность, противоречивые численные источники, отрицания/условия, scanned OCR PDF, tenant/role denial, ACL revoke, direct/indirect injection, oversized technical context и намеренно ложные model outputs. Последние проверяются adversarial fixture, а не приписываются Qwen. OCR выполняется локально; GPU evaluation вызывает реальную модель для обычных cases, но некоторые safety/fallback cases обходятся без generation по контракту.

| Профиль | completed / expected | coverage | invalid | failures | gate |
|---|---|---|---|---|---|
| CPU | 23 / 23 | 1.0 | 0 | 0 | GO |
| GPU | 23 / 23 | 1.0 | 0 | 0 | GO |

| Метрика | CPU | GPU |
|---|---|---|
| recall_at_6 | 1.0 | 1.0 |
| context_precision | 0.9583333333333334 | 0.9583333333333334 |
| citation_correctness | 1.0 | 1.0 |
| extractive_groundedness | 1.0 | 1.0 |
| annotated_fact_coverage | 1.0 | 1.0 |
| no_evidence_precision | 1.0 | 1.0 |
| llm_judge_faithfulness | None | None |
| llm_judge_answer_relevancy | None | None |

## Формулы и применимость

Recall@6 — среднее `|retrieved expected sources| / |expected sources|` на кейсах с непустой разметкой источников; источники дедуплицируются по документам. Context precision — average precision по ранжированным уникальным документам: сумма precision@rank релевантных попаданий / число таких попаданий, затем macro mean; пропуски отдельно отражает Recall. Это proxy с полной синтетической разметкой, не произвольная оценка всех похожих документов.

Citation correctness — доля evidence с доступным source, совпадающим version и точным text[start:end]. Extractive groundedness — доля таких evidence, возвращающих полный semantic unit. Это проверка цитаты по источнику, не LLM faithfulness и не Ragas. Annotated fact coverage — macro mean `all(expected_facts in returned quotes)` на кейсах с expected sources; это ограниченный proxy relevancy, не полноценный answer relevancy judge. No-evidence precision — среди результатов no_evidence доля разметок no_evidence. Если знаменатель пуст, значение null и gate HOLD; нулевые/пропущенные измерения не подменяются успехом.

ACL leakage count — evidence вне актуального разрешённого SQL набора. Token violations — факт выхода за max_model_len в реальном vLLM mode с reserve+margin. Нарушения блокируют выпуск независимо от среднего качества. Adversarial security tests обязательны дополнительно. Latency p50/p95/p99 вычисляется по времени каждого case; создание отдельной БД и OCR включены. Это mixed evaluation, не HTTP capacity benchmark. Поля локального LLM-judge faithfulness/relevancy намеренно null: калиброванный judge не поставлялся.

Срезы document_type/tenant/role находятся в JSON. OCR — всего один holdout case, остальные текстовые. Язык fixtures — русский с техническими ID; независимого английского/языкового сравнения и fairness-метрик нет. Нельзя переносить доли на документы предприятия или другие подразделения.

## Gate и дальнейшая разметка

Пороги provisional: recall ≥0.90, context precision ≥0.50, citation correctness/groundedness/no-evidence precision =1, annotated fact coverage ≥0.90; failures=invalid=ACL leakage=budget violations=0, completed=expected>0, coverage=1, возраст ≤24 h, конечные валидные значения, совпадение dataset/corpus/model/prompt/bundle с проверяемым artifact. Частичный `--limit` даёт HOLD. Отрицательные и malformed/stale reports проверены тестами. Ни одна комбинация синтетических значений не даёт production approval.

Эксперты добавляют запросы и provenance в новую версию набора, определяют список допустимых фактов/единиц и безопасный отказ, согласуют thresholds и double review спорной разметки. Tuning редактируется отдельно, новый holdout до приёмки закрывается от автора исправлений. Для production дополнительно нужны независимый domain set и человеческие/откалиброванные локальные judge оценки, сравнение AWQ с reference и документированная процедура принятия риска.
