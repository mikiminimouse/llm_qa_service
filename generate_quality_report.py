"""Генерация отчёта о качестве извлечения ИНН и производительности."""

import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"


async def generate_quality_report():
    """Генерация отчёта о качестве извлечения."""
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['docling_metadata']

    # Общее количество документов в docling_results
    total_in_db = await db.docling_results.count_documents({})

    # Обработанные документы
    total_processed = await db.qa_results.count_documents({})

    # Победители найдены
    winners_found = await db.qa_results.count_documents({'winner_found': True})

    # С ИНН
    with_inn = await db.qa_results.count_documents({
        'winner_found': True,
        'winner_inn': {'$ne': None, '$ne': ''}
    })

    # Без ИНН
    without_inn = winners_found - with_inn

    # Сервисные файлы
    service_files = await db.qa_results.count_documents({'is_service_file': True})

    # Ошибки
    errors = await db.qa_results.count_documents({'error': {'$ne': None, '$ne': ''}})

    print("=" * 60)
    print(f"ОТЧЁТ О КАЧЕСТВЕ ИЗВЛЕЧЕНИЯ ИНН")
    print(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    print(f"=== Данные ===")
    print(f"Документов в базе (docling_results): {total_in_db}")
    print(f"Обработано (qa_results): {total_processed}")
    print()
    print(f"=== Результаты извлечения ===")
    print(f"Победителей найдено: {winners_found} ({winners_found/total_processed*100:.1f}% от обработанных)")
    print(f"С ИНН: {with_inn} ({with_inn/winners_found*100:.1f}% от победителей)")
    print(f"Без ИНН: {without_inn} ({without_inn/winners_found*100:.1f}% от победителей)")
    print()
    print(f"=== Статусы ===")
    print(f"Сервисные файлы: {service_files}")
    print(f"С ошибками: {errors}")
    print()

    client.close()


async def generate_performance_report():
    """Генерация отчёта о производительности."""
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['docling_metadata']

    # Get processing times
    pipeline = [
        {"$match": {"processing_time_ms": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "avg_time": {"$avg": "$processing_time_ms"},
            "min_time": {"$min": "$processing_time_ms"},
            "max_time": {"$max": "$processing_time_ms"},
            "count": {"$sum": 1}
        }}
    ]

    result = await db.qa_results.aggregate(pipeline).to_list(None)

    print("=" * 60)
    print("ПРОИЗВОДИТЕЛЬНОСТЬ")
    print("=" * 60)
    print()

    if result:
        r = result[0]
        avg_sec = r['avg_time'] / 1000
        min_sec = r['min_time'] / 1000
        max_sec = r['max_time'] / 1000

        print(f"Обработано документов: {r['count']}")
        print(f"Среднее время: {avg_sec:.1f} сек")
        print(f"Мин: {min_sec:.1f} сек")
        print(f"Макс: {max_sec:.1f} сек")
        print()

        # Оценка времени для 100 документов
        print(f"=== Прогноз ===")
        print(f"Время для 100 документов: ~{avg_sec * 100 / 60:.1f} минут")
        print(f"Время для 843 документов: ~{avg_sec * 843 / 3600:.1f} часов")
    else:
        print("Нет данных о производительности")

    print()

    client.close()


async def main():
    """Главная функция."""
    await generate_quality_report()
    await generate_performance_report()

    print("=" * 60)
    print("Для просмотра результатов в Web UI:")
    print("http://localhost:7860")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
