# Пример использования промпта для развертывания llm_qa_service

Этот файл показывает пример уже заполненного промпта, готового к отправке в Claude Code.
Замени значения на свои реальные данные.

---

## Пример 1: Короткий промпт (заполненный)

Разверни llm_qa_service на сервере.

**Параметры:**
- **SSH хост**: `192.168.1.100`
- **Целевая директория**: `/home/pak/projects/llm_qa_service`
- **Репозиторий**: `git@github.com:mikiminimouse/llm_qa_service.git`

**Конфигурация:**
- **MongoDB**: `mongodb://admin:MySecretPass123@localhost:27018/?authSource=admin`
- **GLM API Key**: `sk-zai-abc123def456...`
- **Порт сервиса**: `8001`

**Шаги:**
1. Подключись по SSH к серверу
2. Создай директорию `/home/pak/projects` если не существует
3. Клонируй репозиторий в `/home/pak/projects/llm_qa_service`
4. Создай виртуальное окружение: `python3 -m venv venv`
5. Активируй и установи зависимости: `source venv/bin/activate && pip install -r requirements.txt`
6. Создай `.env` файл (смотри конфигурацию ниже)
7. Запусти сервис в фоне: `nohup python main.py > llm_qa.log 2>&1 &`

**.env конфигурация:**
```env
MONGO_URI=mongodb://admin:MySecretPass123@localhost:27018/?authSource=admin
MONGO_DATABASE=docling_metadata
MONGO_PROTOCOLS_COLLECTION=docling_results
MONGO_QA_COLLECTION=qa_results

GLM_API_KEY=sk-zai-abc123def456...
GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
GLM_MODEL=GLM-4.7
GLM_TIMEOUT=120.0
GLM_MAX_RETRIES=5
GLM_RETRY_DELAY=2.0
GLM_MAX_TOKENS=4096
GLM_TEMPERATURE=0.1

HOST=0.0.0.0
PORT=8001
DEBUG=false

BATCH_SIZE=10
SKIP_PROCESSED=true
SAVE_TO_UNIT_DIR=false
UNIT_BASE_PATHS=[]
```

**Верификация:**
```bash
curl http://localhost:8001/api/v1/qa/health
# Ожидается: {"status":"ok","mongodb":true,"llm":true,"version":"1.0.0"}

curl http://localhost:8001/api/v1/qa/stats

curl "http://localhost:8001/api/v1/qa/documents?limit=5"
```

---

## Пример 2: Развертывание с существующей директорией

Если директория `/home/pak/projects/llm_qa_service` уже существует (например, при обновлении):

```
Обнови llm_qa_service на сервере 192.168.1.100.

SSH: ssh root@192.168.1.100
Директория: /home/pak/projects/llm_qa_service

Действия:
1. Останови текущий процесс: pkill -f "python main.py"
2. Сделай git pull в директории проекта
3. Активируй venv и обнови зависимости: pip install -r requirements.txt
4. Перезапусти сервис: nohup python main.py > llm_qa.log 2>&1 &
5. Проверь health endpoint

Конфигурация .env не менять (сохранить существующую).
```

---

## Пример 3: Однострочная команда для быстрого использования

```
Разверни llm_qa_service из git@github.com:mikiminimouse/llm_qa_service.git на сервере 192.168.1.100 в /home/pak/projects/llm_qa_service. MongoDB: mongodb://admin:Pass123@localhost:27018/?authSource=admin, GLM API Key: sk-zai-xxx, Порт: 8001. После установки запусти сервис и проверь health endpoint.
```

---

## Таблица замены плейсхолдеров

| Плейсхолдер | Пример значения | Описание |
|-------------|-----------------|----------|
| `<SERVER_SSH_HOST>` | `192.168.1.100` или `server.example.com` | IP адрес или hostname сервера |
| `<MONGO_PASSWORD>` | `MySecretPass123` | Пароль пользователя admin MongoDB |
| `<GLM_API_KEY>` | `sk-zai-abc123def456...` | API ключ от Z.ai |
| `<SERVER_IP>` | `192.168.1.100` | IP адрес для доступа к API из браузера |

---

## Проверка успешного развертывания

После выполнения Claude Code всех шагов, убедись что:

1. ✅ Health endpoint возвращает `{"status":"ok","mongodb":true,"llm":true,"version":"1.0.0"}`
2. ✅ Сервис запущен как фоновый процесс
3. ✅ Логи пишутся в `llm_qa.log`
4. ✅ Swagger UI доступен по адресу `http://<SERVER_IP>:8001/docs`

---

**Важно:** Не используй эти примеры с реальными данными — замени все пароли и API ключи на свои!
