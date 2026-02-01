# Prompts для развертывания llm_qa_service

Эта директория содержит готовые промпты для Claude Code, которые выполняют автоматическое развертывание сервиса `llm_qa_service` на новом сервере.

---

## Содержание

| Файл | Описание | Когда использовать |
|------|----------|-------------------|
| `deploy_llm_qa_service_short.md` | Краткая версия промпта | Быстрое развертывание на новом сервере |
| `deploy_llm_qa_service_detailed.md` | Подробная инструкция | Полное развертывание с объяснениями |
| `deploy_llm_qa_service_example.md` | Примеры использования | Для понимания формата и плейсхолдеров |

---

## Быстрый старт

### Шаг 1: Выбери промпт

- Для быстрого развертывания используй `deploy_llm_qa_service_short.md`
- Для первого развертывания с пониманием процесса — `deploy_llm_qa_service_detailed.md`

### Шаг 2: Открой файл и скопируй содержимое

```bash
cat prompts/deploy_llm_qa_service_short.md
```

### Шаг 3: Вставь в Claude Code

1. Открой Claude Code
2. Вставь скопированный промпт
3. Замени плейсхолдеры на реальные значения
4. Отправь

---

## Плейсхолдеры для замены

Перед отправкой промпта замени следующие плейсхолдеры:

| Плейсхолдер | Что указать |
|-------------|-------------|
| `<SERVER_SSH_HOST>` | IP адрес или hostname сервера (например, `192.168.1.100`) |
| `<MONGO_PASSWORD>` | Пароль пользователя `admin` в MongoDB |
| `<GLM_API_KEY>` | API ключ от [Z.ai](https://z.ai) |
| `<SERVER_IP>` | IP адрес сервера (для доступа из браузера) |

---

## Предусловия развертывания

Перед использованием промптов убедись, что на сервере:

- [x] **Python 3.11+** установлен
- [x] **MongoDB** установлен и работает на `localhost:27018`
- [x] **SSH доступ** настроен
- [x] **Git** установлен (для клонирования репозитория)

---

## Что делает промпт

Промпт автоматизирует следующие шаги:

1. **SSH подключение** к указанному серверу
2. **Создание директории** `/home/pak/projects` если отсутствует
3. **Клонирование репозитория** `git@github.com:mikiminimouse/llm_qa_service.git`
4. **Создание виртуального окружения** Python
5. **Установка зависимостей** из `requirements.txt`
6. **Создание .env файла** с указанной конфигурацией
7. **Запуск сервиса** через `nohup` в фоновом режиме
8. **Верификация** работы сервиса через health endpoint

---

## Верификация успешного развертывания

После выполнения Claude Code промпта, проверь:

### 1. Health Check

```bash
curl http://localhost:8001/api/v1/qa/health
```

Ожидаемый ответ:
```json
{"status":"ok","mongodb":true,"llm":true,"version":"1.0.0"}
```

### 2. Статус процесса

```bash
ps aux | grep "python main.py"
```

Должен быть виден процесс `python main.py`

### 3. Логи

```bash
tail -50 llm_qa.log
```

Не должно быть ошибок (ERROR)

### 4. Swagger UI

Открой в браузере: `http://<SERVER_IP>:8001/docs`

---

## Управление сервисом

### Остановить

```bash
pkill -f "python main.py"
```

### Перезапустить

```bash
cd /home/pak/projects/llm_qa_service
source venv/bin/activate
nohup python main.py > llm_qa.log 2>&1 &
```

### Посмотреть логи

```bash
tail -f llm_qa.log
```

### Проверить статус

```bash
ps aux | grep "python main.py"
curl http://localhost:8001/api/v1/qa/health
```

---

## Структура .env файла

```env
# MongoDB
MONGO_URI=mongodb://admin:<PASSWORD>@localhost:27018/?authSource=admin
MONGO_DATABASE=docling_metadata
MONGO_PROTOCOLS_COLLECTION=docling_results
MONGO_QA_COLLECTION=qa_results

# GLM-4.7 API
GLM_API_KEY=<API_KEY>
GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
GLM_MODEL=GLM-4.7
GLM_TIMEOUT=120.0
GLM_MAX_RETRIES=5
GLM_RETRY_DELAY=2.0
GLM_MAX_TOKENS=4096
GLM_TEMPERATURE=0.1

# Server
HOST=0.0.0.0
PORT=8001
DEBUG=false

# Processing
BATCH_SIZE=10
SKIP_PROCESSED=true
SAVE_TO_UNIT_DIR=false
UNIT_BASE_PATHS=[]
```

---

## API Endpoints

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/` | GET | Информация о сервисе |
| `/api/v1/qa/health` | GET | Health check |
| `/api/v1/qa/stats` | GET | Статистика |
| `/api/v1/qa/documents` | GET | Список документов |
| `/api/v1/qa/process` | POST | Обработать документ |
| `/api/v1/qa/process/batch` | POST | Пакетная обработка |
| `/api/v1/qa/process/batch-parallel` | POST | Параллельная обработка |
| `/docs` | GET | Swagger UI |

---

## Поиск проблем

### Сервис не запускается

```bash
# Проверь логи
cat llm_qa.log

# Проверь порт
netstat -tlnp | grep 8001

# Пробный запуск
python main.py
```

### MongoDB не доступна

```bash
# Проверь соединение
mongosh "mongodb://admin:<PASSWORD>@localhost:27018/?authSource=admin"
```

### Проблемы с зависимостями

```bash
pip install --upgrade -r requirements.txt
```

---

## Дополнительная информация

- **Документация сервиса**: `../README.md`
- **Инструкция по развертыванию**: `../DEPLOYMENT.md`
- **GitHub репозиторий**: https://github.com/mikiminimouse/llm_qa_service

---

**Примечание:** LLM health check отключен для экономии средств — поле `llm` всегда возвращает `true`.
