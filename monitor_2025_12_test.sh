#!/bin/bash
# Мониторинг обработки датасета 2025-12-03 ... 2025-12-09

echo "=================================================="
echo " Мониторинг обработки датасета 2025-12-03 ... 2025-12-09"
echo " Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo

# Статистика MongoDB
python3 -c "
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

async def stats():
    client = AsyncIOMotorClient('mongodb://admin:password@localhost:27018/?authSource=admin', serverSelectionTimeoutMS=5000)
    db = client['docling_metadata']

    # Всего документов в docling_results
    total = await db.docling_results.count_documents({})

    # Всего в qa_results
    qa = await db.qa_results.count_documents({})

    # Документы за период 2025-12-03 ... 2025-12-09
    pipeline = [
        {'\$match': {'protocol_date': {'\$exists': True, '\$ne': None}}},
        {'\$addFields': {'parsed_date': {'\$dateFromString': {'dateString': '\$protocol_date'}}}},
        {'\$match': {'parsed_date': {'\$gte': datetime(2025, 12, 3), '\$lt': datetime(2025, 12, 10)}}},
        {'\$count': 'total'}
    ]
    result = await db.docling_results.aggregate(pipeline).to_list(1)
    period_total = result[0]['total'] if result else 0

    # Статистика по qa_results
    winner_found = await db.qa_results.count_documents({'winner_found': True})
    service_files = await db.qa_results.count_documents({'is_service_file': True})
    with_errors = await db.qa_results.count_documents({'error': {'\$exists': True, '\$ne': None}})

    # Статистика по трейсингу
    with_reg = await db.qa_results.count_documents({'registration_number': {'\$exists': True, '\$ne': None}})
    with_trace = await db.qa_results.count_documents({'trace': {'\$exists': True}})
    with_history = await db.qa_results.count_documents({'history': {'\$exists': True, '\$ne': []}})

    # С ИНН
    with_inn = await db.qa_results.count_documents({
        'winner_found': True,
        'winner_inn': {'\$exists': True, '\$ne': None}
    })

    print('Данные:')
    print(f'  Документов за период:   %4d' % period_total)
    print(f'  qa_results всего:        %4d' % qa)
    print()
    print('Результаты обработки:')
    print(f'  Победителей найдено:    %4d' % winner_found)
    print(f'  Служебные файлы:        %4d' % service_files)
    print(f'  С ошибками:              %4d' % with_errors)
    print(f'  С ИНН:                   %4d' % with_inn)
    print()
    print('Трейсинг:')
    print(f'  С registration_number:   %4d' % with_reg)
    print(f'  С trace:                 %4d' % with_trace)
    print(f'  С history:               %4d' % with_history)
    print()
    if period_total > 0:
        progress = (qa / period_total) * 100
        bar_len = 40
        filled = int(bar_len * progress / 100)
        bar = '=' * filled + ' ' * (bar_len - filled)
        print('Прогресс: [%s] %.1f%%' % (bar, progress))
        print(f'Осталось: {period_total - qa}')

    await client.close()

asyncio.run(stats())
" 2>/dev/null

echo
echo "=================================================="
