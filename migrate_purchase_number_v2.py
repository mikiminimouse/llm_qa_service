#!/usr/bin/env python3
"""
Миграция purchase_notice_number к формату 223-ФЗ (только исходные номера).

После изменения логики ResponseParser:
- Только исходные номера из protocols223 (11 цифр) — валидны
- Все номера, извлечённые из текста документа — невалидны

Скрипт устанавливает None для всех невалидных номеров.
"""

import re
from pymongo import MongoClient
from pymongo import UpdateOne

# MongoDB connection
MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"
DATABASE = "docling_metadata"
COLLECTION = "qa_results"


def is_valid_purchase_number(value: str) -> bool:
    """Проверка: ровно 11 цифр (формат 223-ФЗ)."""
    if not value:
        return False
    return bool(re.match(r"^\d{11}$", str(value).strip()))


def migrate():
    """Выполнить миграцию."""
    client = MongoClient(MONGO_URI)
    db = client[DATABASE]
    collection = db[COLLECTION]

    print("=== Миграция purchase_notice_number ===\n")

    # Шаг 1: Анализ текущего состояния
    print("Шаг 1: Анализ текущего состояния...")
    pipeline = [
        {"$project": {
            "pn": "$result.procurement.purchase_notice_number"
        }},
        {"$group": {
            "_id": None,
            "valid_11": {"$sum": {"$cond": [
                {"$regexMatch": {"input": "$pn", "regex": "^\\d{11}$"}},
                1, 0
            ]}},
            "none_or_empty": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": ["$pn", None]},
                    {"$eq": ["$pn", ""]}
                ]},
                1, 0
            ]}},
            "invalid": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$pn", None]},
                    {"$ne": ["$pn", ""]},
                    {"$not": {"$regexMatch": {"input": "$pn", "regex": "^\\d{11}$"}}}
                ]},
                1, 0
            ]}},
            "total": {"$sum": 1}
        }}
    ]

    stats = list(collection.aggregate(pipeline))[0]
    print(f"  Всего записей: {stats['total']}")
    print(f"  Валидные (11 цифр): {stats['valid_11']}")
    print(f"  None/пустые: {stats['none_or_empty']}")
    print(f"  Невалидные: {stats['invalid']}")

    # Шаг 2: Собрать невалидные номера для примера
    print("\nШаг 2: Примеры невалидных номеров...")
    invalid_examples = collection.find(
        {"result.procurement.purchase_notice_number": {"$exists": True, "$ne": None, "$ne": ""}},
        {"result.procurement.purchase_notice_number": 1, "unit_id": 1}
    ).limit(20)

    invalid_samples = []
    for doc in invalid_examples:
        pn = doc.get("result", {}).get("procurement", {}).get("purchase_notice_number")
        if pn and not is_valid_purchase_number(pn):
            invalid_samples.append((doc.get("unit_id"), pn))
            if len(invalid_samples) >= 10:
                break

    for unit_id, pn in invalid_samples[:5]:
        print(f"  {unit_id}: '{pn}'")

    # Шаг 3: Миграция — очистить невалидные номера
    print(f"\nШаг 3: Очистка невалидных номеров...")

    # Найти все документы с невалидными номерами
    invalid_docs = collection.find(
        {
            "result.procurement.purchase_notice_number": {"$exists": True, "$ne": None, "$ne": ""}
        },
        {"unit_id": 1, "result.procurement.purchase_notice_number": 1}
    )

    bulk_operations = []
    for doc in invalid_docs:
        pn = doc.get("result", {}).get("procurement", {}).get("purchase_notice_number")
        if pn and not is_valid_purchase_number(pn):
            unit_id = doc.get("unit_id")
            bulk_operations.append(
                UpdateOne(
                    {"unit_id": unit_id},
                    {"$set": {"result.procurement.purchase_notice_number": None}}
                )
            )

    # Выполнить bulk update
    if bulk_operations:
        result = collection.bulk_write(bulk_operations)
        print(f"  Обновлено записей: {result.modified_count}")
    else:
        print("  Нет записей для обновления")

    # Шаг 4: Верификация
    print("\nШаг 4: Верификация...")
    stats_after = list(collection.aggregate(pipeline))[0]
    print(f"  Всего записей: {stats_after['total']}")
    print(f"  Валидные (11 цифр): {stats_after['valid_11']}")
    print(f"  None/пустые: {stats_after['none_or_empty']}")
    print(f"  Невалидные: {stats_after['invalid']}")

    if stats_after['invalid'] == 0:
        print("\n✅ Миграция завершена успешно!")
    else:
        print(f"\n⚠️ Осталось {stats_after['invalid']} невалидных записей")

    client.close()


if __name__ == "__main__":
    migrate()
