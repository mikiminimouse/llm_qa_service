#!/usr/bin/env python3
"""
Генерация обогащённого отчёта с полной информацией о победителях и закупках.

Связывает данные из qa_results с protocols коллекцией для получения:
- purchase_notice_number (номер закупки)
- purchase_name (название закупки)
- registration_number (номер протокола)

Использует unit.meta.json файлы для связи по purchase_notice_number.
"""

import asyncio
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Путь к файлам метаданных
INPUT_BASE = Path("/home/pak/Processing data/2026-01-23/Input")


def load_unit_metadata(unit_id: str) -> Optional[dict]:
    """
    Загрузить метаданные из unit.meta.json.

    Args:
        unit_id: Идентификатор документа (UNIT_xxx)

    Returns:
        Словарь с метаданными или None
    """
    meta_path = INPUT_BASE / unit_id / "unit.meta.json"
    if not meta_path.exists():
        return None

    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Ошибка чтения {meta_path}: {e}")
        return None


async def find_protocol_by_purchase_number(
    collection,
    purchase_number: str
) -> Optional[dict]:
    """
    Найти протокол по номеру закупки.

    Args:
        collection: Коллекция protocols
        purchase_number: Номер закупки (purchaseNoticeNumber)

    Returns:
        Документ протокола или None
    """
    return await collection.find_one({
        "purchaseInfo.purchaseNoticeNumber": purchase_number
    })


async def enrich_winner_data(
    qa_result: dict,
    protocols_collection,
    unit_metadata_cache: dict
) -> dict:
    """
    Обогатить данные победителя информацией из protocols.

    Args:
        qa_result: Документ из qa_results
        protocols_collection: Коллекция protocols
        unit_metadata_cache: Кэш метаданных из unit.meta.json

    Returns:
        Обогащённый словарь с данными
    """
    unit_id = qa_result.get("unit_id")

    # 1. Пытаемся получить purchase_notice_number из кэша
    unit_meta = unit_metadata_cache.get(unit_id, {})
    purchase_number = unit_meta.get("purchase_notice_number")

    # 2. Если нет в кэше, пробуем загрузить из файла
    if not purchase_number:
        meta = load_unit_metadata(unit_id)
        if meta:
            purchase_number = meta.get("purchase_notice_number")
            unit_metadata_cache[unit_id] = meta

    # 3. Ищем протокол по purchase_number
    protocol_data = None
    if purchase_number:
        protocol = await find_protocol_by_purchase_number(
            protocols_collection,
            purchase_number
        )
        if protocol:
            purchase_info = protocol.get("purchaseInfo", {})
            protocol_data = {
                "purchase_notice_number": purchase_info.get("purchaseNoticeNumber"),
                "purchase_name": purchase_info.get("name"),
                "purchase_method_code": purchase_info.get("purchaseMethodCode"),
                "purchase_method_name": purchase_info.get("purchaseCodeName"),
                "registration_number": protocol.get("registrationNumber"),
                "protocol_guid": protocol.get("guid"),
                "protocol_unit_id": protocol.get("unit_id"),
            }

    # 4. Получаем данные из winners массива
    result_data = qa_result.get("result", {})
    winners_list = result_data.get("winners", [])
    winner_data = winners_list[0] if winners_list else {}
    procurement_data = result_data.get("procurement", {})
    customer_data = result_data.get("customer", {})
    flags = result_data.get("flags", {})

    # 5. Собираем enriched данные
    enriched = {
        "unit_id": unit_id,
        "winner_found": qa_result.get("winner_found", False),
        # Данные из qa_results.result.winners[0]
        "winner_name": winner_data.get("name") if winner_data else None,
        "winner_inn": winner_data.get("inn") if winner_data else None,
        "contract_price": winner_data.get("contract_price") if winner_data else None,
        "winner_status": winner_data.get("status") if winner_data else None,
        "winner_confidence": winner_data.get("confidence") if winner_data else None,
        "data_anonymized": winner_data.get("data_anonymized", False) if winner_data else False,
        # Данные о закупке из результата
        "procurement_number": procurement_data.get("purchase_number") if procurement_data else None,
        "procurement_purchase_name": procurement_data.get("purchase_name") if procurement_data else None,
        # Данные о заказчике
        "customer_name": customer_data.get("name") if customer_data else None,
        "customer_inn": customer_data.get("inn") if customer_data else None,
        # Флаги
        "is_service_file": flags.get("is_service_file", False),
        "single_participant": flags.get("single_participant", False),
        "all_rejected": flags.get("all_rejected", False),
        # Данные из protocols
        "protocol_purchase_notice_number": protocol_data.get("purchase_notice_number") if protocol_data else None,
        "protocol_purchase_name": protocol_data.get("purchase_name") if protocol_data else None,
        "protocol_registration_number": protocol_data.get("registration_number") if protocol_data else None,
        "protocol_method_name": protocol_data.get("purchase_method_name") if protocol_data else None,
        "protocol_method_code": protocol_data.get("purchase_method_code") if protocol_data else None,
        # Meta информация
        "source_purchase_number": purchase_number,
        "has_protocol_match": protocol_data is not None,
        "reasoning": result_data.get("reasoning", "")[:500] if result_data else "",  # Первые 500 символов
    }

    return enriched


async def main():
    """Главная функция."""
    print("=" * 80)
    print(f"{'ГЕНЕРАЦИЯ ОБОГАЩЁННОГО ОТЧЁТА О ПОБЕДИТЕЛЯХ':^80}")
    print("=" * 80)

    settings = get_settings()

    # Подключение к MongoDB
    logger.info(f"Подключение к MongoDB: {settings.MONGO_URI}")
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    qa_results = db[settings.MONGO_QA_COLLECTION]
    protocols = db["protocols"]

    # 1. Загружаем все qa_results
    total_qa = await qa_results.count_documents({})
    winners_count = await qa_results.count_documents({"winner_found": True})

    print(f"\n📊 Статистика qa_results:")
    print(f"   Всего документов: {total_qa}")
    print(f"   С найденными победителями: {winners_count}")

    # 2. Загружаем все winners
    cursor = qa_results.find({"winner_found": True})
    winners = []
    async for doc in cursor:
        winners.append(doc)

    print(f"   Загружено для обработки: {len(winners)}")

    # 3. Кэш метаданных из unit.meta.json
    unit_metadata_cache = {}

    # 4. Обогащаем данные
    print(f"\n🔍 Обогащение данных...")
    enriched_data = []

    for i, winner in enumerate(winners, 1):
        enriched = await enrich_winner_data(winner, protocols, unit_metadata_cache)
        enriched_data.append(enriched)

        if i % 100 == 0:
            print(f"   Обработано: {i}/{len(winners)}")

    # 5. Статистика по связям
    has_protocol = sum(1 for d in enriched_data if d["has_protocol_match"])
    has_purchase_number = sum(1 for d in enriched_data if d["protocol_purchase_notice_number"])
    has_inn = sum(1 for d in enriched_data if d["winner_inn"])

    print(f"\n📊 Результаты обогащения:")
    print(f"   Найдено соответствий в protocols: {has_protocol}/{len(enriched_data)} ({100*has_protocol/len(enriched_data):.1f}%)")
    print(f"   С номером закупки: {has_purchase_number}/{len(enriched_data)} ({100*has_purchase_number/len(enriched_data):.1f}%)")
    print(f"   С ИНН победителя: {has_inn}/{len(enriched_data)} ({100*has_inn/len(enriched_data):.1f}%)")

    # 6. Сохраняем CSV
    output_dir = Path("/home/pak/llm_qa_service")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_file = output_dir / "winners_enriched_full.csv"
    json_file = output_dir / "winners_enriched_full.json"

    # CSV с основными полями
    csv_fields = [
        "unit_id",
        "winner_found",
        "winner_name",
        "winner_inn",
        "contract_price",
        "winner_status",
        "data_anonymized",
        "customer_name",
        "customer_inn",
        "protocol_purchase_notice_number",
        "protocol_purchase_name",
        "protocol_registration_number",
        "protocol_method_name",
        "procurement_purchase_name",
    ]

    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()

        for data in enriched_data:
            row = {
                "unit_id": data["unit_id"],
                "winner_found": data["winner_found"],
                "winner_name": data["winner_name"] or "N/A",
                "winner_inn": data["winner_inn"] or "N/A",
                "contract_price": data["contract_price"] or "N/A",
                "winner_status": data.get("winner_status") or "N/A",
                "data_anonymized": data.get("data_anonymized", False),
                "customer_name": data.get("customer_name") or "N/A",
                "customer_inn": data.get("customer_inn") or "N/A",
                "protocol_purchase_notice_number": data["protocol_purchase_notice_number"] or "N/A",
                "protocol_purchase_name": data["protocol_purchase_name"] or "N/A",
                "protocol_registration_number": data["protocol_registration_number"] or "N/A",
                "protocol_method_name": data["protocol_method_name"] or "N/A",
                "procurement_purchase_name": data.get("procurement_purchase_name") or "N/A",
            }
            writer.writerow(row)

    print(f"\n📁 CSV сохранён: {csv_file}")

    # JSON с полными данными
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_winners": len(enriched_data),
            "with_protocol_match": has_protocol,
            "with_purchase_number": has_purchase_number,
            "with_inn": has_inn,
            "winners": enriched_data
        }, f, indent=2, ensure_ascii=False)

    print(f"📁 JSON сохранён: {json_file}")

    # 7. Статистика без совпадений
    no_match = [d for d in enriched_data if not d["has_protocol_match"]]
    print(f"\n⚠️ Документы без совпадений в protocols: {len(no_match)}")

    if no_match:
        print("   Примеры (первые 10):")
        for d in no_match[:10]:
            print(f"     - {d['unit_id']}: source_pn={d['source_purchase_number']}")

    # 8. Статистика ИНН и анонимизации
    anonymized_count = sum(1 for d in enriched_data if d.get("data_anonymized", False))
    print(f"\n🔍 Анализ данных:")
    print(f"   Анонимизировано данных (data_anonymized=true): {anonymized_count}/{len(enriched_data)} ({100*anonymized_count/len(enriched_data):.1f}%)")

    inn_values = [d["winner_inn"] for d in enriched_data if d["winner_inn"]]
    print(f"   Всего с ИНН победителя: {len(inn_values)} ({100*len(inn_values)/len(enriched_data):.1f}%)")

    # Проверка формата ИНН
    inn_10 = [inn for inn in inn_values if inn and len(str(inn).replace(" ", "")) == 10]
    inn_12 = [inn for inn in inn_values if inn and len(str(inn).replace(" ", "")) == 12]
    inn_other = [inn for inn in inn_values if inn and len(str(inn).replace(" ", "")) not in (10, 12)]

    print(f"   ИНН длиной 10 (юридические лица): {len(inn_10)}")
    print(f"   ИНН длиной 12 (ИП): {len(inn_12)}")
    print(f"   ИНН неправильного формата: {len(inn_other)}")

    if inn_other:
        print(f"   Примеры неправильных ИНН: {inn_other[:5]}")

    # 9. Примеры без ИНН
    no_inn = [d for d in enriched_data if not d["winner_inn"]]
    print(f"\n⚠️ Документы без ИНН: {len(no_inn)}")
    if no_inn:
        print("   Причины:")
        anonymized_no_inn = [d for d in no_inn if d.get("data_anonymized", False)]
        print(f"     - Анонимизация: {len(anonymized_no_inn)}")
        print("   Примеры (первые 5):")
        for d in no_inn[:5]:
            reason = "аноннимизировано" if d.get("data_anonymized") else "не найдено"
            print(f"     {d['unit_id']}: {d['winner_name']} ({reason})")

    client.close()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
