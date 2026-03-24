# Развертывание llm_qa_service (подробная инструкция)

Скопируй и вставь этот промпт в Claude Code для полного развертывания сервиса с пошаговыми объяснениями:

---

## Задача: Развернуть llm_qa_service на новом сервере

### О сервисе
**llm_qa_service** — это FastAPI сервис для извлечения информации о победителях из протоколов закупок с использованием LLM (GLM-4.7).

**Технический стек:**
- Python 3.11+
- FastAPI + Uvicorn
- MongoDB (Motor async driver)
- GLM-4.7 через Z.ai API

---

### Параметры развертывания

| Параметр | Значение |
|----------|----------|
| SSH хост | `<SERVER_SSH_HOST>` |
| Целевая директория | `/home/pak/projects/llm_qa_service` |
| GitHub репозиторий | `git@github.com:mikiminimouse/llm_qa_service.git` |
| Порт сервиса | `8001` |

---

### Предусловия
- **Python 3.11+** уже установлен на сервере
- **MongoDB** уже установлен и доступен на `localhost:27018`
- Доступ к серверу по SSH настроен

---

### Шаг 1: Подключение к серверу

```bash
ssh <SERVER_SSH_HOST>
```

---

### Шаг 2: Создание директории проекта

```bash
mkdir -p /home/pak/projects
cd /home/pak/projects
```

---

### Шаг 3: Клонирование репозитория

```bash
git clone git@github.com:mikiminimouse/llm_qa_service.git
cd llm_qa_service
```

---

### Шаг 4: Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
```

Проверь версию Python (должна быть 3.11+):
```bash
python --version
```

---

### Шаг 5: Установка зависимостей

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Основные зависимости:**
- `fastapi` — веб-фреймворк
- `uvicorn` — ASGI сервер
- `motor` — async MongoDB драйвер
- `httpx` — HTTP клиент для LLM API
- `pydantic` — валидация данных
- `python-dotenv` — загрузка переменных окружения

---

### Шаг 6: Создание .env файла

Создай файл `.env` в корне проекта:

```bash
cat > .env << 'EOF'
# ============================================
# MongoDB Configuration
# ============================================
MONGO_URI=mongodb://admin:<MONGO_PASSWORD>@localhost:27018/?authSource=admin
MONGO_DATABASE=docling_metadata
MONGO_PROTOCOLS_COLLECTION=docling_results
MONGO_QA_COLLECTION=qa_results

# ============================================
# GLM-4.7 API (via Z.ai)
# ============================================
GLM_API_KEY=<GLM_API_KEY>
GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
GLM_MODEL=GLM-4.7
GLM_TIMEOUT=120.0
GLM_MAX_RETRIES=5
GLM_RETRY_DELAY=2.0
GLM_MAX_TOKENS=4096
GLM_TEMPERATURE=0.1

# ============================================
# Server Configuration
# ============================================
HOST=0.0.0.0
PORT=8001
DEBUG=false

# ============================================
# Processing Configuration
# ============================================
BATCH_SIZE=10
SKIP_PROCESSED=true
SAVE_TO_UNIT_DIR=false
UNIT_BASE_PATHS=[]
EOF
```

**Важно:** Замени плейсхолдеры:
- `<MONGO_PASSWORD>` — пароль пользователя admin в MongoDB
- `<GLM_API_KEY>` — API ключ от Z.ai

---

### Шаг 7: Запуск сервиса

Запусти сервис в фоновом режиме с логированием:

```bash
nohup python main.py > llm_qa.log 2>&1 &
```

Сохрани PID процесса для последующего управления:
```bash
echo $! > llm_qa_service.pid
```

---

### Шаг 8: Верификация развертывания

Подожди 3-5 секунд для запуска сервиса, затем выполни проверки:

#### 8.1. Health Check
```bash
curl http://localhost:8001/api/v1/qa/health
```
**Ожидаемый ответ:**
```json
{"status":"ok","mongodb":true,"llm":true,"version":"1.0.0"}
```

#### 8.2. Статистика
```bash
curl http://localhost:8001/api/v1/qa/stats
```
**Ожидаемый ответ:** JSON с полями `total_documents`, `processed_documents`, `failed_documents`

#### 8.3. Список документов
```bash
curl "http://localhost:8001/api/v1/qa/documents?limit=5"
```
**Ожидаемый ответ:** Массив `unit_id` или пустой массив `[]`

#### 8.4. Swagger UI
Открой в браузере: `http://<SERVER_IP>:8001/docs`

---

### Управление сервисом

**Проверить статус:**
```bash
ps aux | grep "python main.py"
cat llm_qa.log | tail -50
```

**Остановить сервис:**
```bash
pkill -f "python main.py"
# или используя PID:
kill $(cat llm_qa_service.pid)
```

**Перезапустить сервис:**
```bash
cd /home/pak/projects/llm_qa_service
source venv/bin/activate
nohup python main.py > llm_qa.log 2>&1 &
echo $! > llm_qa_service.pid
```

**Посмотреть логи в реальном времени:**
```bash
tail -f llm_qa.log
```

---

### API Endpoints справка

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/` | GET | Информация о сервисе |
| `/api/v1/qa/health` | GET | Проверка состояния |
| `/api/v1/qa/stats` | GET | Статистика обработки |
| `/api/v1/qa/documents` | GET | Список документов |
| `/api/v1/qa/result/{unit_id}` | GET | Получить результат |
| `/api/v1/qa/process` | POST | Обработать документ |
| `/api/v1/qa/process/batch` | POST | Пакетная обработка |
| `/api/v1/qa/process/batch-parallel` | POST | Параллельная обработка |
| `/docs` | GET | Swagger UI |

---

### Поиск проблем

**Сервис не запускается:**
```bash
# Проверь логи
cat llm_qa.log

# Проверь, что порт не занят
netstat -tlnp | grep 8001

# Пробный запуск (без nohup)
python main.py
```

**MongoDB не доступна:**
```bash
# Проверь соединение
mongosh "mongodb://admin:<PASSWORD>@localhost:27018/?authSource=admin"
```

**Проблемы с зависимостями:**
```bash
# Переустанови зависимости
pip install --upgrade -r requirements.txt
```

---

**Примечание:** LLM health check отключен для экономии средств — поле `llm` всегда возвращает `true`.

---

**Замени плейсхолдеры:**
- `<SERVER_SSH_HOST>` → например `192.168.1.100` или `server.example.com`
- `<MONGO_PASSWORD>` → пароль MongoDB
- `<GLM_API_KEY>` → API ключ от Z.ai
- `<SERVER_IP>` → IP адрес сервера
