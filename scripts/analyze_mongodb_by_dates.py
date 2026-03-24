#!/usr/bin/env python3
"""
Анализ количества записей в MongoDB по дням/неделям/месяцам.

Использование:
    python scripts/analyze_mongodb_by_dates.py
    python scripts/analyze_mongodb_by_dates.py --collection docling_results
    python scripts/analyze_mongodb_by_dates.py --date-field loaded_at
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from pymongo import MongoClient, ASCENDING
from dateutil.parser import parse as parse_date

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Возможные поля с датами для группировки
DATE_FIELDS = [
    "loadDate",        # protocols коллекция - дата загрузки из источника
    "loaded_at",       # docling_results - дата загрузки в MongoDB
    "created_at",      # общее поле создания
    "processed_at",    # дата обработки
    "protocol_date",   # дата протокола
    "publishDate",     # дата публикации
    "createDateTime",  # protocols - datetime создания
]


def find_date_field(collection):
    """Определяет, какое поле с датой существует в коллекции."""
    for field in DATE_FIELDS:
        sample = collection.find_one({field: {"$exists": True}}, {field: 1})
        if sample and sample.get(field):
            logger.info(f"   Найдено поле даты: {field}")
            return field
    return None


def parse_document_date(doc, date_field):
    """Пытается извлечь и распарсить дату из документа."""
    date_value = doc.get(date_field)

    if not date_value:
        return None

    # Если уже datetime объект
    if isinstance(date_value, datetime):
        return date_value

    # Если строка - парсим
    if isinstance(date_value, str):
        try:
            return parse_date(date_value)
        except Exception:
            pass

    return None


def get_date_range(collection, date_field=None):
    """Определяет минимальную и максимальную дату в коллекции."""
    if not date_field:
        date_field = find_date_field(collection)
        if not date_field:
            logger.warning("   Не найдено поле с датой, используем _id")
            return None, None

    # Сортируем по дате и берём первый/последний
    earliest = collection.find_one(
        {date_field: {"$exists": True, "$ne": None}},
        {date_field: 1},
        sort=[(date_field, ASCENDING)]
    )

    latest = collection.find_one(
        {date_field: {"$exists": True, "$ne": None}},
        {date_field: 1},
        sort=[(date_field, ASCENDING)]  # 注意：这里应该是DESCENDING
    )

    if earliest and latest:
        min_date = parse_document_date(earliest, date_field)
        # Для берем последний документ через сортировку
        max_date = parse_document_date(latest, date_field)

        return min_date, max_date

    return None, None


def analyze_by_dates(db, collection_name, date_field=None):
    """Анализирует количество записей по дням/неделям/месяцам."""
    collection = db[collection_name]

    logger.info(f"\n{'='*60}")
    logger.info(f"Анализ коллекции: {collection_name}")
    logger.info(f"{'='*60}")

    # Общее количество
    total = collection.count_documents({})
    logger.info(f"Всего записей: {total:,}")

    if total == 0:
        return {
            "collection": collection_name,
            "total": 0,
            "by_day": {},
            "by_week": {},
            "by_month": {},
            "date_field": None,
        }

    # Определяем поле даты
    if not date_field:
        date_field = find_date_field(collection)

    if not date_field:
        logger.warning(f"   Не найдено поле с датой, анализ по датам невозможен")
        return {
            "collection": collection_name,
            "total": total,
            "by_day": {},
            "by_week": {},
            "by_month": {},
            "date_field": None,
        }

    # Получаем диапазон дат
    min_date, max_date = get_date_range(collection, date_field)

    if min_date and max_date:
        logger.info(f"Диапазон дат: {min_date.strftime('%Y-%m-%d')} → {max_date.strftime('%Y-%m-%d')}")
    else:
        logger.warning("   Не удалось определить диапазон дат")

    # Агрегация по датам (через aggregation pipeline)
    by_day = defaultdict(int)
    by_week = defaultdict(int)
    by_month = defaultdict(int)

    # Используем aggregation для группировки по датам (datetime объекты)
    # Используем $dateToString для форматирования datetime в строку группировки
    pipeline = [
        {"$match": {date_field: {"$exists": True, "$ne": None, "$type": "date"}}},
        {
            "$group": {
                "_id": {
                    "date_str": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": f"${date_field}"
                        }
                    }
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id.date_str": 1}}
    ]

    try:
        results = list(collection.aggregate(pipeline, allowDiskUse=True))

        for r in results:
            date_str = r["_id"]["date_str"]  # YYYY-MM-DD
            count = r["count"]

            # Парсим дату для вычисления недели и месяца
            try:
                doc_date = datetime.strptime(date_str, "%Y-%m-%d")
                week_number = (doc_date.day - 1) // 7 + 1
                week_key = f"{doc_date.year}-W{week_number:02d}"
                month_key = doc_date.strftime("%Y-%m")

                by_day[date_str] = count
                by_week[week_key] += count
                by_month[month_key] += count
            except ValueError:
                by_day[date_str] = count

    except Exception as e:
        logger.warning(f"   Aggregation failed: {e}")
        # Fallback: сканируем документы (медленнее, но надежнее)
        logger.info("   Используем fallback метод сканирования...")

        for doc in collection.find({date_field: {"$exists": True}}, {date_field: 1}):
            doc_date = parse_document_date(doc, date_field)
            if doc_date:
                date_key = doc_date.strftime("%Y-%m-%d")
                week_number = (doc_date.day - 1) // 7 + 1
                week_key = f"{doc_date.year}-W{week_number:02d}"
                month_key = doc_date.strftime("%Y-%m")

                by_day[date_key] += 1
                by_week[week_key] += 1
                by_month[month_key] += 1

    # Вывод статистики
    logger.info(f"\nПо дням (последние 20):")
    for date_key in sorted(by_day.keys())[-20:]:
        logger.info(f"   {date_key}: {by_day[date_key]:,}")

    logger.info(f"\n по неделям:")
    for week_key in sorted(by_week.keys()):
        logger.info(f"   {week_key}: {by_week[week_key]:,}")

    logger.info(f"\nПо месяцам:")
    for month_key in sorted(by_month.keys()):
        logger.info(f"   {month_key}: {by_month[month_key]:,}")

    return {
        "collection": collection_name,
        "total": total,
        "by_day": dict(sorted(by_day.items())),
        "by_week": dict(sorted(by_week.items())),
        "by_month": dict(sorted(by_month.items())),
        "date_field": date_field,
        "min_date": min_date.isoformat() if min_date else None,
        "max_date": max_date.isoformat() if max_date else None,
    }


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Анализ MongoDB по датам")
    parser.add_argument(
        "--collection", "-c",
        default=None,
        help="Имя коллекции для анализа (по умолчанию: все коллекции)"
    )
    parser.add_argument(
        "--date-field", "-d",
        default=None,
        choices=DATE_FIELDS + ["auto"],
        help="Поле с датой для группировки"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Файл для сохранения результатов (JSON)"
    )
    args = parser.parse_args()

    print("\n" + "="*70)
    print("АНАЛИЗ MONGODB ПО ДАТАМ")
    print("="*70)

    # Подключение к MongoDB
    settings = get_settings()
    logger.info(f"Подключение к: {settings.MONGO_URI}")
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    date_field = args.date_field if args.date_field != "auto" else None

    # Определяем коллекции для анализа
    if args.collection:
        collections = [args.collection]
    else:
        collections = [
            settings.MONGO_PROTOCOLS_COLLECTION,
            settings.MONGO_QA_COLLECTION,
            "protocols",  # Дополнительная коллекция с метаданными
        ]

    # Анализируем каждую коллекцию
    results = []
    for coll_name in collections:
        # Проверяем существование коллекции
        if coll_name not in db.list_collection_names():
            logger.warning(f"Коллекция '{coll_name}' не найдена, пропускаем")
            continue

        result = analyze_by_dates(db, coll_name, date_field)
        results.append(result)

    client.close()

    # Сохранение результатов
    output_file = Path(args.output) if args.output else Path("reports/mongodb_dates_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "collections": results,
        "summary": {
            "total_collections": len(results),
            "total_records": sum(r["total"] for r in results),
        }
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*70}")
    print(f"Отчёт сохранён: {output_file}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
