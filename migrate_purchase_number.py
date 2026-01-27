#!/usr/bin/env python3
"""Миграция номеров закупок в qa_results.

Добавляет поле purchase_notice_number с нормализованными номерами госзакупок.
"""

import asyncio
import logging
import re
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

# Настройки MongoDB
MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"
DB_NAME = "docling_metadata"
COLLECTION_NAME = "qa_results"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_purchase_number(raw_number: str) -> str | None:
    """
    Нормализовать номер закупки к формату purchaseNoticeNumber (223-ФЗ).

    Правила:
    - 11 цифр -> стандартный формат 223-ФЗ
    - 8+ цифр -> сокращённый формат
    - Меньше 8 цифр или не цифры -> None
    """
    if not raw_number:
        return None

    # Приводим к строке и убираем пробелы
    number_str = str(raw_number).strip()

    # Убираем распространённые префиксы
    for prefix in ["№", "No", "номер", "Number", "/", "КЗ", "Кз", "кз"]:
        number_str = number_str.replace(prefix, "")

    number_str = number_str.strip()

    # Извлекаем только цифры
    digits_only = re.sub(r"\D", "", number_str)

    # Проверяем длину (223-ФЗ обычно 11 цифр, но бывают и 8)
    if len(digits_only) >= 8:
        return digits_only

    # Слишком короткий или пустой
    return None


async def migrate_purchase_numbers():
    """Миграция номеров закупок в qa_results."""
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    logger.info(f"Подключение к {DB_NAME}.{COLLECTION_NAME}")

    # Получаем все документы
    total = await collection.count_documents({})
    logger.info(f"Всего документов: {total}")

    # Статистика
    stats = {
        "already_has_notice_number": 0,
        "migrated_successfully": 0,
        "no_purchase_number": 0,
        "could_not_normalize": 0,
    }

    # Обрабатываем пачками
    batch_size = 100
    processed = 0

    while processed < total:
        # Получаем пачку документов
        cursor = collection.find({}).skip(processed).limit(batch_size)
        docs = await cursor.to_list(length=batch_size)

        bulk_ops = []

        for doc in docs:
            unit_id = doc.get("unit_id", "unknown")

            # Получаем текущий purchase_number и purchase_notice_number
            current_number = doc.get("result", {}).get("procurement", {}).get("purchase_number")
            existing_notice = doc.get("result", {}).get("procurement", {}).get("purchase_notice_number")

            if not current_number:
                stats["no_purchase_number"] += 1
                continue

            # Нормализуем номер
            normalized = normalize_purchase_number(current_number)

            # Добавляем в bulk_ops если:
            # 1. Нет purchase_notice_number
            # 2. Есть purchase_notice_number, но он невалидный (не 8+ цифр)
            should_update = False
            if not existing_notice:
                should_update = True
            elif existing_notice and not re.match(r"^\d{8,}$", str(existing_notice)):
                # Перезаписываем невалидное значение
                should_update = True
                stats["already_has_notice_number"] -= 1  # Корректируем статистику

            if should_update and normalized:
                bulk_ops.append(UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"result.procurement.purchase_notice_number": normalized}}
                ))
                stats["migrated_successfully"] += 1
            elif existing_notice and re.match(r"^\d{8,}$", str(existing_notice)):
                stats["already_has_notice_number"] += 1
            else:
                stats["could_not_normalize"] += 1

        # Выполняем bulk update
        if bulk_ops:
            await collection.bulk_write(bulk_ops)
            logger.info(f"Обновлено {len(bulk_ops)} документов")

        processed += len(docs)
        logger.info(f"Обработано {processed}/{total} документов")

    # Вывод статистики
    logger.info("=" * 50)
    logger.info("СТАТИСТИКА МИГРАЦИИ:")
    logger.info(f"  Уже имели purchase_notice_number: {stats['already_has_notice_number']}")
    logger.info(f"  Успешно мигрировано: {stats['migrated_successfully']}")
    logger.info(f"  Не имели purchase_number: {stats['no_purchase_number']}")
    logger.info(f"  Не удалось нормализовать: {stats['could_not_normalize']}")
    logger.info("=" * 50)

    # Проверка результата
    logger.info("\nПроверка результата...")
    pipeline = [
        {"$project": {
            "pn": "$result.procurement.purchase_notice_number"
        }},
        {"$group": {
            "_id": None,
            "valid": {"$sum": {"$cond": [{"$regexMatch": {"input": "$pn", "regex": "^\\d{8,}$"}}, 1, 0]}},
            "none": {"$sum": {"$cond": [{"$eq": ["$pn", None]}, 1, 0]}},
        }}
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)
    if result:
        r = result[0]
        valid = r.get('valid', 0)
        none = r.get('none', 0)
        invalid = total - valid - none
        logger.info(f"  Валидные (8+ цифр): {valid}")
        logger.info(f"  Пустые (None): {none}")
        logger.info(f"  Невалидные: {invalid}")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate_purchase_numbers())
