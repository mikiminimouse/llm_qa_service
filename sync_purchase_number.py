#!/usr/bin/env python3
"""
Синхронизация purchase_notice_number из protocols в docling_results.

Для каждого документа в docling_results:
1. Найти соответствующий документ в protocols по unit_id
2. Скопировать purchaseNoticeNumber в purchase_notice_number
3. Сохранить в docling_results

Проблема: load_dataset_2026_01_23.py не копировал это поле при загрузке.
Решение: Синхронизировать из коллекции protocols.
"""

import logging
import sys
from pymongo import MongoClient, UpdateOne

# Конфигурация
MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"
DATABASE = "docling_metadata"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def sync_purchase_numbers():
    """Синхронизировать purchase_notice_number из protocols в docling_results."""
    logger.info("=== СИНХРОНИЗАЦИЯ PURCHASE_NOTICE_NUMBER ===\n")

    client = MongoClient(MONGO_URI)
    db = client[DATABASE]

    # Шаг 1: Анализ текущего состояния
    logger.info("Шаг 1: Анализ текущего состояния...")
    total_docling = db.docling_results.count_documents({})
    with_pn = db.docling_results.count_documents({"purchase_notice_number": {"$exists": True}})
    without_pn = db.docling_results.count_documents({"purchase_notice_number": {"$exists": False}})

    logger.info(f"  Всего в docling_results: {total_docling}")
    logger.info(f"  С purchase_notice_number: {with_pn}")
    logger.info(f"  Без purchase_notice_number: {without_pn}")

    # Шаг 2: Найти документы без purchase_notice_number
    if without_pn == 0:
        logger.info("\n✅ Все документы уже имеют purchase_notice_number!")
        client.close()
        return

    logger.info(f"\nШаг 2: Поиск purchaseNoticeNumber в protocols для {without_pn} документов...")

    # Получить все unit_ids без purchase_notice_number
    docling_results = db.docling_results.find(
        {"purchase_notice_number": {"$exists": False}},
        {"unit_id": 1}
    )

    bulk_operations = []
    not_found = []

    for doc in docling_results:
        unit_id = doc["unit_id"]

        # Найти соответствующий protocol
        protocol = db.protocols.find_one({
            "unit_id": unit_id,
            "purchaseInfo.purchaseNoticeNumber": {"$exists": True}
        }, {"purchaseInfo.purchaseNoticeNumber": 1})

        if protocol:
            pnn = protocol["purchaseInfo"]["purchaseNoticeNumber"]
            # Валидация: только 11 цифр (формат 223-ФЗ)
            if len(str(pnn)) == 11 and str(pnn).isdigit():
                bulk_operations.append(
                    UpdateOne(
                        {"unit_id": unit_id},
                        {"$set": {"purchase_notice_number": pnn}}
                    )
                )
            else:
                logger.warning(f"  Невалидный номер для {unit_id}: {pnn}")
        else:
            not_found.append(unit_id)

    logger.info(f"  Найдено в protocols: {len(bulk_operations)}")
    if not_found:
        logger.warning(f"  Не найдено в protocols: {len(not_found)}")

    # Шаг 3: Выполнить bulk update
    logger.info(f"\nШаг 3: Выполнение bulk update...")
    if bulk_operations:
        result = db.docling_results.bulk_write(bulk_operations)
        logger.info(f"  ✅ Обновлено: {result.modified_count} документов")
    else:
        logger.warning("  ⚠️ Нет документов для обновления")

    # Шаг 4: Верификация
    logger.info(f"\nШаг 4: Верификация...")
    with_pn_after = db.docling_results.count_documents({"purchase_notice_number": {"$exists": True}})
    without_pn_after = db.docling_results.count_documents({"purchase_notice_number": {"$exists": False}})

    logger.info(f"  С purchase_notice_number: {with_pn_after}")
    logger.info(f"  Без purchase_notice_number: {without_pn_after}")

    # Показать примеры
    if with_pn_after > with_pn:
        logger.info(f"\n  Новых записей: {with_pn_after - with_pn}")
        samples = list(db.docling_results.find({
            "purchase_notice_number": {"$exists": True}
        }).limit(3))
        logger.info(f"\n  Примеры:")
        for s in samples:
            logger.info(f"    {s['unit_id']}: {s.get('purchase_notice_number')}")

    logger.info("\n" + "=" * 60)
    if without_pn_after == 0:
        logger.info("✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
    else:
        logger.warning(f"⚠️ Осталось {without_pn_after} документов без purchase_notice_number")
    logger.info("=" * 60)

    client.close()


if __name__ == "__main__":
    sync_purchase_numbers()
