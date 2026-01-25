# LLM QA Service

Сервис для извлечения информации о победителях из протоколов закупок с использованием LLM (GLM-4.7).

## Описание

LLM QA Service предоставляет REST API для автоматической обработки протоколов закупок и извлечения структурированной информации о победителях тендеров. Сервис использует GLM-4.7 через Z.ai API для анализа текстовых документов.

### Возможности

- Обработка одиночных документов и пакетная обработка
- Параллельная обработка с настраиваемым уровнем параллелизма
- Автоматический retry для failed документов
- Валидация извлечённых данных (ИНН, КПП)
- Интеграция с MongoDB для хранения результатов

## Требования

- Python 3.11+
- MongoDB 4.4+
- GLM API ключ (Z.ai)

## Установка

```bash
# Клонирование репозитория
git clone git@github.com:mikiminimouse/llm_qa_service.git
cd llm_qa_service

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Конфигурация
cp .env.example .env
# Заполнить .env реальными значениями
```

## Конфигурация

Все настройки задаются через переменные окружения в файле `.env`:

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `MONGO_URI` | URI подключения к MongoDB | - |
| `MONGO_DATABASE` | Имя базы данных | `docling_metadata` |
| `MONGO_PROTOCOLS_COLLECTION` | Коллекция с протоколами | `docling_results` |
| `MONGO_QA_COLLECTION` | Коллекция для результатов QA | `qa_results` |
| `GLM_API_KEY` | API ключ для GLM | - |
| `GLM_BASE_URL` | URL API | `https://api.z.ai/api/coding/paas/v4` |
| `GLM_MODEL` | Модель | `GLM-4.7` |
| `GLM_TIMEOUT` | Таймаут запроса (сек) | `120.0` |
| `HOST` | Хост сервера | `0.0.0.0` |
| `PORT` | Порт сервера | `8001` |
| `BATCH_SIZE` | Размер пакета | `10` |
| `SKIP_PROCESSED` | Пропускать обработанные | `true` |

## Запуск

```bash
# Активация окружения
source venv/bin/activate

# Запуск сервера
python main.py

# Или через uvicorn напрямую
uvicorn main:app --host 0.0.0.0 --port 8001
```

## API Endpoints

Base URL: `http://localhost:8001/api/v1/qa`

### Health & Stats

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/health` | Проверка состояния сервиса |
| GET | `/stats` | Статистика обработки |
| GET | `/documents` | Список доступных документов |

### Processing

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/process` | Обработка одного документа |
| POST | `/process/batch` | Пакетная обработка |
| POST | `/process/batch-parallel` | Параллельная обработка |
| POST | `/process/batch-parallel-retry` | Параллельная обработка с retry |

### Results

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/result/{unit_id}` | Получить результат по unit_id |
| DELETE | `/result/{unit_id}` | Удалить результат |

### Примеры запросов

```bash
# Health check
curl http://localhost:8001/api/v1/qa/health

# Статистика
curl http://localhost:8001/api/v1/qa/stats

# Список документов
curl "http://localhost:8001/api/v1/qa/documents?limit=10"

# Обработка одного документа
curl -X POST http://localhost:8001/api/v1/qa/process \
  -H "Content-Type: application/json" \
  -d '{"unit_id": "UNIT_123"}'

# Параллельная обработка
curl -X POST http://localhost:8001/api/v1/qa/process/batch-parallel \
  -H "Content-Type: application/json" \
  -d '{"unit_ids": ["UNIT_1", "UNIT_2"], "max_concurrent": 5}'
```

## Тестирование

```bash
# Запуск всех тестов
pytest tests/ -v

# С покрытием
pytest tests/ -v --cov=. --cov-report=term-missing
```

## Структура проекта

```
llm_qa_service/
├── api/                    # FastAPI роуты и схемы
│   ├── dependencies.py     # DI контейнер
│   ├── routes.py          # API endpoints
│   └── schemas.py         # Pydantic модели
├── application/           # Бизнес-логика
│   ├── orchestrator.py    # Оркестратор обработки
│   ├── response_parser.py # Парсер ответов LLM
│   └── validators/        # Валидаторы
├── config/               # Конфигурация
│   └── settings.py       # Pydantic Settings
├── domain/               # Доменные сущности
│   ├── entities/         # Модели данных
│   └── interfaces/       # Абстрактные интерфейсы
├── infrastructure/       # Инфраструктура
│   ├── llm/             # LLM клиент
│   ├── loaders/         # Загрузчики данных
│   ├── repositories/    # Репозитории MongoDB
│   └── prompt_manager.py # Управление промптами
├── prompts/             # YAML промпты
│   ├── system/          # Системные промпты
│   ├── user/            # Пользовательские промпты
│   └── validation/      # Правила валидации
├── scripts/             # Вспомогательные скрипты
├── tests/               # Тесты
├── main.py              # Точка входа
├── requirements.txt     # Зависимости
└── pyproject.toml       # Конфигурация проекта
```

## Интеграция с docling_multitender

Сервис использует ту же MongoDB что и docling_multitender. Коллекция `docling_results` содержит исходные протоколы, `qa_results` - результаты извлечения.

## Лицензия

Proprietary
