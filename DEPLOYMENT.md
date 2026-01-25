# Deployment Guide: LLM QA Service

Инструкция по развёртыванию на сервере pak64x16x100hdd.

## Информация о сервере

| Параметр | Значение |
|----------|----------|
| SSH | `pak64x16x100hdd` |
| User | `pak` |
| Python | 3.11.2 |
| Docker | 20.10.24 |
| RAM | 15GB (13GB свободно) |
| Диск | /cloud - 140GB свободно |

## Шаги развёртывания

### 1. Подключение к серверу

```bash
ssh pak64x16x100hdd
```

### 2. Клонирование репозитория

```bash
cd ~
git clone git@github.com:mikiminimouse/llm_qa_service.git
cd llm_qa_service
```

### 3. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Установка зависимостей

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Конфигурация

```bash
cp .env.example .env
nano .env
```

Заполнить `.env`:

```env
# MongoDB (docling_multitender использует ту же БД)
MONGO_URI=mongodb://admin:password@localhost:27017/?authSource=admin
MONGO_DATABASE=docling_metadata
MONGO_PROTOCOLS_COLLECTION=docling_results
MONGO_QA_COLLECTION=qa_results

# GLM API (скопировать из текущего .env)
GLM_API_KEY=<your_api_key>
GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
GLM_MODEL=GLM-4.7
GLM_TIMEOUT=120.0
GLM_MAX_RETRIES=5
GLM_RETRY_DELAY=2.0

# Server
HOST=0.0.0.0
PORT=8001
DEBUG=false

# Processing
BATCH_SIZE=10
SKIP_PROCESSED=true
SAVE_TO_UNIT_DIR=false
```

### 6. Запуск сервиса

```bash
# Прямой запуск
python main.py

# Или через uvicorn
uvicorn main:app --host 0.0.0.0 --port 8001

# Фоновый запуск с nohup
nohup python main.py > llm_qa.log 2>&1 &
```

### 7. Проверка работоспособности

```bash
# Health check
curl http://localhost:8001/api/v1/qa/health
# Ожидаемый ответ: {"status":"ok","mongodb":true,"llm":true,"version":"1.0.0"}

# Статистика
curl http://localhost:8001/api/v1/qa/stats

# Список документов
curl "http://localhost:8001/api/v1/qa/documents?limit=5"
```

### 8. Тестирование

```bash
cd ~/llm_qa_service
source venv/bin/activate
pytest tests/ -v
```

## Интеграция с docling_multitender

На сервере pak уже есть `~/docling_multitender/`.

### Вариант A: Символическая ссылка

```bash
cd ~/docling_multitender
ln -s ~/llm_qa_service llm_qa_service
```

### Вариант B: Git подмодуль

```bash
cd ~/docling_multitender
git submodule add git@github.com:mikiminimouse/llm_qa_service.git
```

## Управление сервисом

### Проверка статуса

```bash
# Найти процесс
ps aux | grep llm_qa

# Проверить логи
tail -f llm_qa.log
```

### Остановка

```bash
# Найти PID
ps aux | grep "python main.py" | grep -v grep

# Остановить
kill <PID>
```

### Перезапуск

```bash
# Остановить старый процесс
pkill -f "llm_qa_service/main.py"

# Запустить новый
cd ~/llm_qa_service
source venv/bin/activate
nohup python main.py > llm_qa.log 2>&1 &
```

## Обновление

```bash
cd ~/llm_qa_service
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
# Перезапустить сервис
```

## Troubleshooting

### MongoDB не подключается

```bash
# Проверить статус MongoDB
sudo systemctl status mongod

# Проверить подключение
mongosh "mongodb://admin:password@localhost:27017/?authSource=admin"
```

### Порт занят

```bash
# Найти процесс на порту
lsof -i :8001

# Использовать другой порт
PORT=8002 python main.py
```

### Ошибки GLM API

- Проверить API ключ в `.env`
- Проверить баланс на Z.ai
- Увеличить `GLM_TIMEOUT` при таймаутах

## Мониторинг

### Логи

```bash
# Реальное время
tail -f llm_qa.log

# Последние ошибки
grep -i error llm_qa.log | tail -20
```

### API метрики

```bash
# Статистика обработки
curl http://localhost:8001/api/v1/qa/stats | jq
```

## Systemd (опционально)

Создать `/etc/systemd/system/llm-qa.service`:

```ini
[Unit]
Description=LLM QA Service
After=network.target mongod.service

[Service]
Type=simple
User=pak
WorkingDirectory=/home/pak/llm_qa_service
Environment=PATH=/home/pak/llm_qa_service/venv/bin
ExecStart=/home/pak/llm_qa_service/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активация:

```bash
sudo systemctl daemon-reload
sudo systemctl enable llm-qa
sudo systemctl start llm-qa
sudo systemctl status llm-qa
```
