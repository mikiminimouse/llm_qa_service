# Развертывание llm_qa_service (короткая версия)

Скопируй и вставь этот промпт в Claude Code для быстрого развертывания сервиса:

---

Разверни llm_qa_service на сервере.

**Параметры:**
- **SSH хост**: `<SERVER_SSH_HOST>`
- **Целевая директория**: `/home/pak/projects/llm_qa_service`
- **Репозиторий**: `git@github.com:mikiminimouse/llm_qa_service.git`

**Конфигурация:**
- **MongoDB**: `mongodb://admin:<MONGO_PASSWORD>@localhost:27018/?authSource=admin`
- **GLM API Key**: `<GLM_API_KEY>`
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
MONGO_URI=mongodb://admin:<MONGO_PASSWORD>@localhost:27018/?authSource=admin
MONGO_DATABASE=docling_metadata
MONGO_PROTOCOLS_COLLECTION=docling_results
MONGO_QA_COLLECTION=qa_results

GLM_API_KEY=<GLM_API_KEY>
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

**Примечание:** Замени `<SERVER_SSH_HOST>`, `<MONGO_PASSWORD>` и `<GLM_API_KEY>` на реальные значения.
