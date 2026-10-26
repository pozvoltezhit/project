# Закрытая платформа корпоративных знаний

Учебный MVP для поиска сведений в технической документации. Система извлекает текст из документов и сканов, строит граф упоминаний оборудования и возвращает цитаты с указанием источников. Поиск и обход графа учитывают права пользователя. Модель работает локально, без внешних inference API.

## Материалы проекта

| Материал | Ссылка |
|---|---|
| Архитектурное описание (ADD) | [Markdown](docs/ADD.md), [PDF](docs/ADD.pdf) |
| Архитектурные решения (ADR) | [Markdown](docs/ADR.md), [PDF](docs/ADR.pdf) |
| C4 1–4, Deployment, Sequence, ER, Data Flow | [PDF](docs/архитектура.pdf), [Draw.io](docs/архитектура.drawio) |
| Видео-демонстрация, 6:14 | [MP4](docs/демо.mp4) |
| Нагрузочный отчёт | [PERFORMANCE.md](docs/PERFORMANCE.md) |
| Проверка функциональности | [TESTING.md](docs/TESTING.md) |
| Эксплуатация | [RUNBOOK.md](docs/RUNBOOK.md) |

## Стек и устройство

FastAPI и LangGraph образуют Control Plane: API, состояние агента, планирование и вызовы инструментов. Data Plane содержит SQLite, Qdrant, Neo4j, OCR и vLLM с Qwen2.5-7B-Instruct-AWQ. OpenTelemetry, Jaeger, Prometheus и Grafana обеспечивают наблюдаемость.

Поток запроса: проверка ввода → память сессии и план → поиск разрешённых чанков → обход графа до двух шагов → ранжирование → выбор источников локальной моделью → проверка цитат и прав → ответ. При недостатке данных агент делает ограниченную повторную попытку. Цитаты восстанавливаются из исходного текста; ответ содержит идентификаторы документов и точные смещения.

Пример объединяет насос Н-17, контур К-2 и датчик Д-8 по двум документам. Отдельный документ с бюджетом доступен только роли `restricted`. Корпус в `examples/` синтетический.

## Локальный запуск

Python 3.12, команды из корня репозитория:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m backend.init_demo
.venv\Scripts\python -m backend.check
.venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 18080
```

Интерфейс: http://127.0.0.1:18080. Ключи пользователей `engineer-a` и `engineer-b` находятся в локальном `data/identities.json`. В Swagger `/docs` ключ передаётся через Authorize (BearerToken). `/graph` использует ту же авторизацию.

Без `LLM_URL` используется extractive-режим: система возвращает найденные цитаты без обращения к модели. GPU-профиль подключает внутренний vLLM.

## Docker Compose

Сначала создайте демонстрационные данные командой `python -m backend.init_demo`.

```powershell
docker compose -f infra/compose.yaml build backend
docker compose -f infra/compose.yaml up -d
```

Для Qdrant и Neo4j добавьте `-f infra/compose.indexes.yaml`. Для GPU добавьте также `-f infra/compose.gpu.yaml`. Веса предварительно подготавливаются командой `python infra/prepare-models.py` на машине с доступом к сети и размещаются в `models/qwen-awq`. Версия и контрольные суммы указаны в [manifest](models/qwen-manifest.json). Runtime не скачивает модель. Для закрытого контура образы, зависимости и веса доставляются заранее.

Сервисы доступны локально: Jaeger http://127.0.0.1:16686, Neo4j http://127.0.0.1:17474, Prometheus http://127.0.0.1:19090, Grafana http://127.0.0.1:13000. Пароль администратора Neo4j находится в `data/neo4j-password.txt`. Пользовательский граф доступен через API с фильтрацией прав.

## Загрузка документов

```powershell
python -m backend.ingest examples/01-equipment.txt --tenant factory --roles staff
python -m backend.ingest document.pdf --tenant factory --roles restricted
python -m backend.index_admin build
python -m backend.index_admin status
```

В контейнерном профиле выполняйте эти команды внутри настроенного backend. Для сканов нужен Tesseract с языками `rus+eng` (включён в Dockerfile). Индексы строятся как новые версии и становятся активными после проверки; предыдущие версии сохраняются.

## Проверки

```powershell
python -m pip install -r requirements-dev.txt
python tools/verify.py
python -m backend.evaluate --output data/eval-report.json
```

GitHub Actions собирает образы и выполняет CPU-тесты. Проверка реальной генерации требует локального GPU-профиля.

## Границы реализации

OCR извлекает текст и подписи; интерпретация геометрии чертежей и сложных таблиц не реализована. Граф отражает совместные упоминания, а не автоматически доказанные физические связи. LLM выбирает подтверждающие фрагменты; итоговый ответ содержит точные цитаты. SSE передаёт один проверенный результат. Локальный Compose использует одну API-реплику; SSO, Vault, mTLS и высокая доступность описаны в целевой архитектуре.

`data/`, пароли, базы, кеши и веса модели исключены из Git. Модель распространяется по Apache-2.0; её лицензия приложена в `docs/Модель-LICENSE.txt`.
