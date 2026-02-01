#!/usr/bin/env python3
"""
Script to analyze QA processing results and generate detailed metrics report.
"""

import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings


async def get_detailed_stats() -> dict:
    """Get detailed statistics from MongoDB."""
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_QA_COLLECTION]

    # Basic stats
    total = await collection.count_documents({})
    winner_found = await collection.count_documents({"winner_found": True})
    winner_not_found = await collection.count_documents({"winner_found": False, "result.flags.is_service_file": False})
    service_files = await collection.count_documents({"result.flags.is_service_file": True})
    with_errors = await collection.count_documents({"error": {"$ne": None}})

    # INN statistics
    with_inn = await collection.count_documents({
        "winner_found": True,
        "winner_inn": {"$ne": None, "$regex": r"^\d{10,12}$"}
    })

    # Customer confusion
    customer_confused = await collection.count_documents({
        "result.flags.customer_confused_with_winner": True
    })

    # Anonymized data
    anonymized = await collection.count_documents({
        "result.flags.data_anonymized": True
    })

    # Multi-lot
    multi_lot = await collection.count_documents({
        "result.flags.is_multi_lot": True
    })

    # Processing time stats
    pipeline = [
        {"$match": {"processing_time_ms": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": None,
            "avg_time": {"$avg": "$processing_time_ms"},
            "min_time": {"$min": "$processing_time_ms"},
            "max_time": {"$max": "$processing_time_ms"},
        }}
    ]
    time_stats = await collection.aggregate(pipeline).to_list(1)
    time_stats = time_stats[0] if time_stats else {"avg_time": 0, "min_time": 0, "max_time": 0}

    # Document types distribution
    type_pipeline = [
        {"$group": {
            "_id": "$result.document.document_type",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    doc_types = await collection.aggregate(type_pipeline).to_list(100)

    # Sample records for manual review
    sample_with_winner = await collection.find(
        {"winner_found": True}
    ).limit(10).to_list(10)

    sample_without_winner = await collection.find(
        {"winner_found": False, "result.flags.is_service_file": False}
    ).limit(10).to_list(10)

    sample_service = await collection.find(
        {"result.flags.is_service_file": True}
    ).limit(5).to_list(5)

    client.close()

    return {
        "basic": {
            "total": total,
            "winner_found": winner_found,
            "winner_not_found": winner_not_found,
            "service_files": service_files,
            "with_errors": with_errors,
        },
        "quality": {
            "with_valid_inn": with_inn,
            "with_inn_percent": round(with_inn / max(winner_found, 1) * 100, 1),
            "customer_confused": customer_confused,
            "anonymized": anonymized,
            "multi_lot": multi_lot,
        },
        "timing": {
            "avg_ms": round(time_stats.get("avg_time", 0), 0),
            "min_ms": time_stats.get("min_time", 0),
            "max_ms": time_stats.get("max_time", 0),
        },
        "document_types": {str(t["_id"]): t["count"] for t in doc_types},
        "samples": {
            "with_winner": [
                {
                    "unit_id": r["unit_id"],
                    "winner_name": r.get("winner_name", "N/A"),
                    "winner_inn": r.get("winner_inn", "N/A"),
                }
                for r in sample_with_winner
            ],
            "without_winner": [
                {
                    "unit_id": r["unit_id"],
                    "reasoning": r.get("result", {}).get("reasoning", "N/A")[:200],
                }
                for r in sample_without_winner
            ],
            "service_files": [
                {
                    "unit_id": r["unit_id"],
                    "source_file": r.get("source_file", "N/A"),
                }
                for r in sample_service
            ],
        }
    }


def print_report(stats: dict):
    """Print formatted report."""
    print("=" * 60)
    print("       ОТЧЁТ О ТЕСТИРОВАНИИ QA SERVICE")
    print("=" * 60)
    print(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    basic = stats["basic"]
    quality = stats["quality"]
    timing = stats["timing"]

    print("ОСНОВНЫЕ МЕТРИКИ:")
    print("-" * 40)
    print(f"Обработано документов: {basic['total']}")
    print(f"├── С победителем:     {basic['winner_found']} ({round(basic['winner_found']/max(basic['total'],1)*100, 1)}%)")
    print(f"├── Без победителя:    {basic['winner_not_found']} ({round(basic['winner_not_found']/max(basic['total'],1)*100, 1)}%)")
    print(f"├── Служебные файлы:   {basic['service_files']} ({round(basic['service_files']/max(basic['total'],1)*100, 1)}%)")
    print(f"└── С ошибками:        {basic['with_errors']} ({round(basic['with_errors']/max(basic['total'],1)*100, 1)}%)")
    print()

    print("КАЧЕСТВО ДАННЫХ:")
    print("-" * 40)
    print(f"С валидным ИНН:        {quality['with_valid_inn']} ({quality['with_inn_percent']}% от найденных)")
    print(f"Путаница заказчик/победитель: {quality['customer_confused']}")
    print(f"Анонимизированные:     {quality['anonymized']}")
    print(f"Многолотовые:          {quality['multi_lot']}")
    print()

    print("ВРЕМЯ ОБРАБОТКИ:")
    print("-" * 40)
    print(f"Среднее:  {timing['avg_ms']} мс")
    print(f"Минимум:  {timing['min_ms']} мс")
    print(f"Максимум: {timing['max_ms']} мс")
    print()

    print("ТИПЫ ДОКУМЕНТОВ:")
    print("-" * 40)
    for doc_type, count in stats.get("document_types", {}).items():
        print(f"  {doc_type}: {count}")
    print()

    print("ПРИМЕРЫ С ПОБЕДИТЕЛЕМ (для проверки):")
    print("-" * 40)
    for sample in stats["samples"]["with_winner"][:5]:
        print(f"  {sample['unit_id']}")
        print(f"    Победитель: {sample['winner_name'][:50]}...")
        print(f"    ИНН: {sample['winner_inn']}")
        print()

    print("ПРИМЕРЫ БЕЗ ПОБЕДИТЕЛЯ (для проверки):")
    print("-" * 40)
    for sample in stats["samples"]["without_winner"][:5]:
        print(f"  {sample['unit_id']}")
        print(f"    Причина: {sample['reasoning'][:100]}...")
        print()

    print("=" * 60)


async def export_to_json(output_path: str):
    """Export results to JSON file."""
    stats = await get_detailed_stats()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"Результаты сохранены в {output_path}")


async def main():
    """Main entry point."""
    stats = await get_detailed_stats()
    print_report(stats)

    # Export to JSON
    await export_to_json("/tmp/qa_analysis_report.json")


if __name__ == "__main__":
    asyncio.run(main())
