# Отчёт: Обработка необработанных документов 2026-01-23

**Дата:** 2026-01-27
**Проект:** LLM_qaenrich
**Датасет:** 2026-01-23 (773 новых документа)

---

## Диагностика проблемы

### Анализ MongoDB до исправления

| Коллекция | Документов | Проблема |
|-----------|-----------|----------|
| `protocols` | 8 137 | ✅ Имеют `purchaseInfo.purchaseNoticeNumber` |
| `docling_results` | 1 223 | ❌ **Ни один** не имеет `purchase_notice_number` |
| `qa_results` | 447 | ✅ Старый датасет 2025-12-23 |

### Корневая причина

Скрипт `load_dataset_2026_01_23.py` не копировал поле `purchase_notice_number` из коллекции `protocols` при загрузке документов в `docling_results`.

### Связь между коллекциями

- `docling_results` ∩ `protocols` = **773 документа** (идеальное совпадение!)
- Все 773 имеют `purchaseNoticeNumber` в `protocols.purchaseInfo`
- Связь по полю `unit_id`

---

## Выполненные действия

### Шаг 1: Синхронизация purchase_notice_number ✅

**Создан файл:** `sync_purchase_number.py`

**Действие:** Скопировал `purchaseNoticeNumber` из `protocols` в `docling_results`

**Результат:**
```
✅ Обновлено: 773 документа
С purchase_notice_number: 773 (было 0)
```

**Примеры номеров:**
- `UNIT_05067646b4e74e5b`: 32615602579
- `UNIT_3f11f04c97b34d9e`: 32615602579
- `UNIT_578da109faf840fb`: 32515594378

Все номера валидны (11 цифр, формат 223-ФЗ).

---

### Шаг 2: Обработка через GLM-4.7 ✅

**Создан файл:** `process_unprocessed.py`

**Конфигурация:**
- Модель: **GLM-4.7**
- Timeout: 120 секунд
- Max retries: 5
- Параллельность: 3 запроса
- Автоматический retry для failed

**Запуск:**
```bash
cd /home/pak/projects/LLM_qaenrich
source venv/bin/activate
python process_unprocessed.py > /tmp/llm_processing.log 2>&1 &
```

---

## Текущий статус

### Прогресс обработки (на момент запуска)

```
[19/776] Processing: UNIT_041bc3f605fb4bb5
```

### Производительность

| Метрика | Значение |
|---------|----------|
| Скорость обработки | ~16-20 документов/минуту |
| Среднее время | 25-40 секунд/документ |
| winner_found rate | ~50% (10/20 в начале) |
| HTTP成功率 | 100% (все запросы 200 OK) |

### Оценка времени завершения

- 776 документов × 2.5 сек/док / 3 (parallel) ≈ **~10 минут**

---

## Мониторинг

### Проверка прогресса

```bash
# Посмотреть лог
tail -f /tmp/llm_processing.log

# Или использовать мониторинг-скрипт
bash /home/pak/projects/LLM_qaenrich/monitor_progress.sh
```

### Проверка MongoDB

```python
from pymongo import MongoClient
client = MongoClient('mongodb://admin:password@localhost:27018/?authSource=admin')
db = client['docling_metadata']

# Количество обработанных
qa_count = db.qa_results.count_documents({})
print(f"Обработано: {qa_count}")

# Необработанные
docling_ids = set(db.docling_results.distinct("unit_id"))
qa_ids = set(db.qa_results.distinct("unit_id"))
print(f"Осталось: {len(docling_ids - qa_ids)}")
```

---

## Созданные файлы

| Файл | Описание |
|------|----------|
| `sync_purchase_number.py` | Синхронизация purchase_notice_number |
| `process_unprocessed.py` | Обработка через GLM-4.7 |
| `monitor_progress.sh` | Мониторинг прогресса |

---

## Следующие шаги

1. **Дождаться завершения обработки** (~10 минут)
2. **Проверить результаты:**
   ```bash
   bash monitor_progress.sh
   ```
3. **Запустить WebUI для визуальной проверки:**
   ```bash
   python -m ui.gradio_app
   ```

4. **Анализ качества** (по завершении):
   - Процент найденных победителей
   - Процент извлечённых ИНН
   - Анализ ошибок

---

## Резюме

| Задача | Статус |
|--------|--------|
| Диагностика проблемы | ✅ Выполнено |
| Синхронизация purchase_notice_number | ✅ Выполнено (773 док.) |
| Создание скрипта обработки | ✅ Выполнено |
| Запуск обработки через GLM-4.7 | ✅ В процессе |
| Мониторинг прогресса | ✅ Настроено |

**Обработка запущена в фоновом режиме и продолжается автоматически.**
