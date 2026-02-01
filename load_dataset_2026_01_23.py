#!/usr/bin/env python3
"""
Загрузка документов из 2026-01-23/OutputDocling в MongoDB.

Скрипт сканирует директорию с JSON файлами от Docling
и загружает их в коллекцию docling_results.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

# Конфигурация
MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"
MONGO_DATABASE = "docling_metadata"
MONGO_COLLECTION = "docling_results"
DATASET_PATH = "/home/pak/Processing data/2026-01-23/OutputDocling"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def find_all_json_files(base_path: Path) -> List[Path]:
    """Найти все JSON файлы в директории."""
    json_files = list(base_path.rglob("*.json"))
    # Фильтруем только файлы с именем вида UNIT_*.json
    unit_files = [f for f in json_files if f.name.startswith("UNIT_") and f.parent.name.startswith("UNIT_")]
    return unit_files


def load_json_file(file_path: Path) -> dict:
    """Загрузить JSON файл с преобразованием больших int."""
    def clean_large_ints(obj):
        """Рекурсивно преобразовать большие int в строки."""
        if isinstance(obj, dict):
            return {k: clean_large_ints(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_large_ints(v) for v in obj]
        elif isinstance(obj, int) and abs(obj) > 2**63:
            return str(obj)  # Превращаем в строку
        return obj

    with open(file_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        return clean_large_ints(raw_data)


async def load_document_to_mongo(client, doc_data: dict, source_file: str, unit_id: str) -> bool:
    """Загрузить документ в MongoDB."""
    db = client[MONGO_DATABASE]
    collection = db[MONGO_COLLECTION]

    # Проверяем, существует ли документ
    existing = await collection.find_one({"unit_id": unit_id})
    if existing:
        logger.debug(f"Документ {unit_id} уже существует, пропускаем")
        return False

    # Формируем документ для загрузки
    document = {
        "unit_id": unit_id,
        "content": doc_data,
        "source_file": source_file,
        "processed_at": datetime.now().isoformat(),
    }

    await collection.insert_one(document)
    return True


async def main():
    """Главная функция."""
    logger.info("=== Загрузка датасета 2026-01-23 ===")

    # Подключение к MongoDB
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DATABASE]
    collection = db[MONGO_COLLECTION]

    # Поиск всех JSON файлов
    base_path = Path(DATASET_PATH)
    logger.info(f"Сканирование директории: {base_path}")

    json_files = find_all_json_files(base_path)
    logger.info(f"Найдено файлов: {len(json_files)}")

    if not json_files:
        logger.warning("JSON файлы не найдены!")
        return

    # Подсчет уже загруженных документов
    existing_count = await collection.count_documents({})
    logger.info(f"Уже загружено документов: {existing_count}")

    # Загрузка документов
    loaded = 0
    skipped = 0
    errors = 0

    for idx, file_path in enumerate(json_files, 1):
        try:
            # Извлекаем unit_id из пути
            unit_id = file_path.stem  # Имя файла без расширения

            # Проверяем, существует ли документ
            existing = await collection.find_one({"unit_id": unit_id})
            if existing:
                skipped += 1
                if idx % 100 == 0:
                    logger.info(f"Прогресс: {idx}/{len(json_files)} | Загружено: {loaded}, Пропущено: {skipped}")
                continue

            # Загружаем JSON
            doc_data = load_json_file(file_path)

            # Формируем документ
            document = {
                "unit_id": unit_id,
                "content": doc_data,
                "source_file": str(file_path),
                "processed_at": datetime.now().isoformat(),
            }

            await collection.insert_one(document)
            loaded += 1

            if idx % 100 == 0:
                logger.info(f"Прогресс: {idx}/{len(json_files)} | Загружено: {loaded}, Пропущено: {skipped}")

        except Exception as e:
            logger.error(f"Ошибка при обработке {file_path}: {e}")
            errors += 1

    # Итоговая статистика
    logger.info("=" * 50)
    logger.info("=== Результаты загрузки ===")
    logger.info(f"Всего файлов: {len(json_files)}")
    logger.info(f"Загружено: {loaded}")
    logger.info(f"Пропущено (уже существуют): {skipped}")
    logger.info(f"Ошибок: {errors}")

    # Финальное количество в коллекции
    final_count = await collection.count_documents({})
    logger.info(f"Итого документов в коллекции: {final_count}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
