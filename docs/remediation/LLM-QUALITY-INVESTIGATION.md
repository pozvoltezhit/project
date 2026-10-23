# Причина release HOLD и качество выбора доказательств

20.10.2026. Полные синтетические traces и результаты сохранены в `evidence/llm-quality-20261020/`. Исходные evidence в `evidence/final-20261020/` сохранены. Итоговый статус выпуска и точный image ID указаны в FINAL-READINESS и новом release manifest.

## Воспроизведение и первопричина

Baseline — image `sha256:2945daf417c2ff073a4cb3be97bbb5036fae0936710ee09545cac429459bd3bd`, bundle `8e3e74e7f989c83ff6f74b523f4e422cc2fada83e218fc27dfab11a4dfebf03c`, prompt `evidence-v2`. Повторный запрос: «Как связан насос Н-17 с датчиком Д-8?». Модель, tokenizer/chat template, корпус, активный индекс, ACL, temperature=0, max_tokens=700 и бюджет 4096/700/64 оставлены прежними. Веса — Qwen2.5-7B-Instruct-AWQ revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`; GPU RTX4070, vLLM 0.10.2, AWQ Marlin, half. Параметры serving не менялись.

`baseline/primary-01.json` содержит retrieved chunks с tenant/version/page/doc/chunk IDs, graph edges, packed context и сообщения, реальный ответ Qwen до grounding, диагностику каждой цитаты и итоговый ответ. Это разрешённые синтетические данные; full-content debug не добавлен в production telemetry. Проверены отсутствие закрытого demo-маркера в staff-контексте и неизменность активного индекса.

Поиск и packing передали оба правильных документа: сначала `02-control.txt`, затем `01-equipment.txt`. Graph содержал мост `Н-17 → К-2 → Д-8`. При input=396/output=110 модель:

- присвоила источнику control цитату `Насос Н-17 подключен к контуру К-2` — это текст другого документа, также пропущена точка;
- присвоила equipment цитату про контролирующий датчик из другого документа и заменила ASCII-точки на `。` (U+3002).

Это ошибки генерации/привязки, а не ложное отклонение grounding. Валидатор обоснованно отбросил модельные цитаты и вернул полные canonical units в `extractive-invalid-generation`. Скрывать этот факт переименованием режима или переносить ошибочную цитату к другому источнику нельзя.

## Проверенные варианты

Первый общий prompt `evidence-v3` явно требовал дословного копирования и правильного chunk_id. Он исправил основной вопрос: input=569/output=91, обе цитаты приняты. Четыре исходных tuning-примера также прошли. Но на заранее замороженных 16 новых случаях число прямых ответов снизилось с 12/13 до 9/13: в двух multi-hop случаях и OCR снова возникла U+3002, в multi-source пропущена точка. Все ошибки были безопасно перехвачены fallback, однако такой кандидат не принят. Его image `sha256:6a18883618782a868ee68a69bd1c10351e5a0e3aa70814a9f75be83361fd1f13`, freeze и raw traces сохранены в `candidate/` и `experiment/`.

Принятый контракт `evidence-select-v4` разделяет семантический выбор доказательств и восстановление точного текста. Для каждого упакованного контекста сервер создаёт короткие request-local ID `S1`, `S2`, … Модель выбирает только доказательные фрагменты. Сервер разрешает ID в полный исходный semantic unit, затем применяет прежние exact-span, version и final ACL проверки. Модель не генерирует текст цитаты или offsets. Фактические offsets вычисляются по исходнику; канонический полный unit по-прежнему сохраняет соседние условия и отрицания.

Raw ответ основного вопроса теперь:

```json
{"evidence":[{"source_id":"S1"},{"source_id":"S2"}]}
```

В этом запросе S1 соответствует control, S2 — equipment. Возвращены исходные русские предложения про `К-2 → Д-8` и `Н-17 → К-2` с проверяемой provenance и полным контекстом. Один реальный вызов Qwen: input=415/output=18. `selected/primary-01.json` содержит точное отображение ID в chunk, исходный текст, spans и итоговый `mode=vllm`; active index unchanged=true.

Это **LLM-selected canonical evidence**, а не свободная генерация русского пересказа. Режим vllm означает реальный выбор источников моделью. Полнота фактов, правильность выбора и отказ при отсутствии ответа проверяются отдельно; одна метка режима не является доказательством качества. Существующий интерфейс показывает полные русские цитаты, не неподтверждённую синтезированную формулировку.

Неизвестные/повторные ID, смешанные схемы и любые model-supplied offsets/quotes в selection-схеме отклоняются. Legacy quote-схема сохраняет прежнюю exact same-source проверку. Ошибочная генерация по-прежнему отбрасывается целиком перед безопасным fallback. `verified_span`, ACL и atomic release не ослаблены. Повторной/корректирующей генерации нет: дополнительные calls, tokens и latency на неё равны нулю.

## Проверка качества и границы независимости

Исходные `golden.json` и `corpus.json`, все expected ответы и release predicates сохранены. Пройдены все 27 исходных случаев: 4 tuning и 23 regression. Намеренно ложные ответы clip/hallucination/revoked исходного evaluator — adversarial fixtures, не результаты Qwen. Остальные подходящие GPU-сценарии используют реальную модель; CPU извлечение, guard, conflict и context-limited ветви отражены отдельными режимами.

Первый новый набор: 16 случаев, SHA `60622bc4b3da49fae16cb0dba1cdef4ab4fd8c3c2f968137ed50dc07b59c6604`. Заморожен до первого prompt-кандидата. После выявленных ошибок v3 он считается использованным регрессионным набором. Второй: 20 случаев, SHA `3bb9bba35a49a337c5f48efcd27ceae5e0700ddbed38cdcf55e9ba98a0e8fc95`. Он заморожен до реализации selector; финальный selector зафиксирован до первого запуска этого набора. После его результатов код/контракт не подгонялись. Новые случаи проверяют factual/multi-hop/multi-source, отрицания, условия/исключения, числа/единицы, технические аббревиатуры, OCR, противоречия, no-evidence и tenant isolation. Дополнительно во втором наборе есть лишние источники, совпадающий объект без ответа и полезный источник в конце контекста. Проверяется точное множество ожидаемых источников, не только наличие одного подходящего.

| GPU набор | Baseline прямые валидные / ответные | v3 | Финальный selector | Ошибки финального ответа |
|---|---:|---:|---:|---:|
| Исходные ordinary Golden QA | 9/10 | Не измерялось отдельно | 10/10 | 0 |
| Новые 16, затем regression | 12/13 | 9/13 | 13/13 | 0 |
| Frozen validation 20 | Не запускался | Не запускался | 16/16 | 0 |

Из знаменателя прямых ответов исключены no-evidence и обязательные conflict/context-budget fallback. Baseline на 16 случаях имел ещё один OSError в no-evidence (`wrong-asset`), а не недостоверный выпущенный ответ. В первом baseline trace этого исключения raw response не сохранён; точная причина OSError не выдумывается.

| Финальный GPU набор | vllm answered | vllm abstention | pre-generation no-evidence/guard | conflict | context-limited | invalid-generation fallback |
|---|---:|---:|---:|---:|---:|---:|
| Golden23 | 10 | 0 | 7 | 1 | 1 | 0 |
| Regression16 | 13 | 1 | 1 | 1 | 0 | 0 |
| Validation20 | 16 | 2 | 1 | 1 | 0 | 0 |

Оставшиеся четыре Golden23 — три adversarial-fixture и один ingest-quarantine. Таким образом таблица не приписывает все 23 кейса генерации Qwen. На новых 16/20 никакие GPU ответы не подменены mock.

Citation correctness и extractive source faithfulness proxy =1 на финальных наборах; annotated fact coverage/relevancy =1. Grounding rejections финального selector =0. Это проверка принадлежности исходнику, фактов и размеченного множества источников. Полный semantic entailment, calibrated LLM-judge faithfulness/relevancy и domain acceptance не установлены; judge-поля остаются null. Ошибочный выбор допустимого источника всё ещё возможен на неизвестном запросе, несмотря на отсутствие выдуманного текста.

Разметка авторская синтетическая. У новых наборов нет совпадающих нормализованных запросов с Golden и друг с другом, но генератор/тематика родственны; это ограниченная проверка обобщения, не доказательство отсутствия переобучения. OCR использует прежний image-only PDF с новым вопросом, а не независимый новый OCR-корпус. Для промышленного допуска нужен закрытый экспертный domain holdout.

## Производительность и выпуск

Все benchmark используют прежний primary вопрос, corpus/index, hardware и vLLM конфигурацию; перед каждым отдельно 8 warmup requests. Capacity-прогоны не совмещались с unit/evaluation/build. Server profiler выключен. Raw HTTP samples и vLLM before/after metrics сохранены рядом с JSON, сводка — `performance-summary.json`. Для прямых selected запусков host GPU CSV не собирался; модельные counters и фактический serving проверены отдельно.

| Вариант | N/C | RPS | p50 мс | p95 мс | p99 мс | HTTP errors | mode |
|---|---:|---:|---:|---:|---:|---:|---|
| Исторический reference | 48/4 | 2,53 | 1572,59 | 1631,63 | 1658,46 | 0 | invalid-generation fallback |
| Повтор baseline | 48/4 | 2,52 | 1574,03 | 1632,45 | 1670,07 | 0 | invalid-generation fallback |
| Повтор baseline | 192/4 | 2,48 | 1597,78 | 1685,90 | 1769,03 | 0 | invalid-generation fallback |
| Selector | 48/4 | **8,66** | 428,39 | **690,80** | 728,64 | 0 | vllm |
| Selector | 192/4 | **9,32** | 416,92 | **468,75** | 834,10 | 0 | vllm |

Для 48/C4 относительно исторического reference throughput вырос в 3,42 раза, p95 уменьшился на 57,66%. Для одинаковых повторных 192/C4 — 3,76 раза и −72,20%. Это локальные single-run сравнения тёплого повторяющегося запроса, не soak, mixed workload или гарантия для большого корпуса. Рост не получен ослаблением критериев ответа: новые quality cases дополнительно проверяют факты и точный выбор источников.

Модельные counters подтверждают N завершённых генераций на N HTTP запросов; для selector каждый primary request использует 415 input /18 output tokens. Исправление не добавляет retry/corrective call. Старые 396/110 — реальные вызовы baseline, а не отсутствие GPU. Уменьшение decode work одновременно устраняет ошибки перепечатывания и улучшает measured end-to-end speed.

В функциональных quality traces latency включает создание fixture, SQL/Agent и при OCR — распознавание PDF; это не изолированная latency GPU inference. Например validation20 p50=183,04 мс, p95=2374,16 мс, включая OCR. Tokens/usage и latency каждого случая сохранены, усреднение по разным категориям не заменяет одинаковый нагрузочный workload.

На одинаковых 13 ответных случаях первого нового набора средние input/output tokens: baseline 248,692/79,462 → selector 277,385/13,385. На 16 ответных validation-случаях — 284,5/13,5. Выходных токенов стало меньше за счёт выбора ID вместо перепечатывания исходника; точные русские цитаты восстанавливает сервер. Это изменение контракта учтено явно, а выигрыш end-to-end подтверждается отдельным одинаковым HTTP benchmark.

Исходный strict release gate в `backend/release.py` сохранён и фактически вернул **GO**, `reasons=[]`, `production_approval=false`. Завершены same-bundle unit/CPU/GPU/Golden/budget проверки, CPU restore/index lifecycle, manifest verification и измерения скорости. CPU: Golden27 и первый новый16 PASS; GPU дополнительно прошёл второй20, проверяющий именно LLM селективность среди лишних источников. Image `sha256:876185015815686554dcf4d223d674ec571433d27e6281792b952c1af6ae203e`, bundle `96d03e4d965d0b1a694da71b2f7f4093c5d9c9594abe8e25a56227d869934f51`. Новый manifest — `evidence/llm-quality-20261020/release-manifest.json`; binding validation PASS. Промышленный пилот остаётся **HOLD**.

69 unit tests покрывают прежние F01–F06/security и 18 новых quote/selection regressions; 0 FAIL/SKIP, coverage 84,918957%. Lint/mypy/existing check/локальный literal-secret scan прошли. Первые неуспешные fixture/lint/build попытки сохранены: неверный mock URL, затем исправленный localhost; синтаксис release helper исправлен; BuildKit требовал проверенный локальный base tag вместо bare image ID. Read-only rootfs не ослаблялся: frozen fixture передаётся через существующий writable data mount. Повторные тайм-ауты автоматического согласования Docker-команд не считаются выполненными тестами; фактические completed results сохранены отдельно. Commit/push не выполнялись.
