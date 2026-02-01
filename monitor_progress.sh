#!/bin/bash
# Мониторинг прогресса обработки LLM

echo "=== Мониторинг обработки LLM ==="
echo "Последние 30 строк лога:"
tail -30 /tmp/llm_processing.log
echo ""
echo "=== Статистика MongoDB ==="
source venv/bin/activate && python -c "
from pymongo import MongoClient
client = MongoClient('mongodb://admin:password@localhost:27018/?authSource=admin')
db = client['docling_metadata']
qa_count = db.qa_results.count_documents({})
docling_count = db.docling_results.count_documents({})
with_pn = db.docling_results.count_documents({'purchase_notice_number': {'\$exists': True}})
print(f'qa_results: {qa_count}')
print(f'docling_results: {with_pn} с purchase_notice_number / {docling_count} всего')
print(f'Обработано: {qa_count - 447} новых (старый датасет: 447)')
print(f'Осталось: {docling_count - qa_count}')
"
