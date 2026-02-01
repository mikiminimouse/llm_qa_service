#!/usr/bin/env python3
"""
Загрузка нового датасета из /home/pak/Processing data/2026-01-23/OutputDocling/
в MongoDB для последующей обработки LLM_qaenrich.

Структура датасета:
- docx/, html/, xlsx/, xml/ - директории по типам файлов
- Каждая директория содержит поддиректории UNIT_*/ с файлами .json и .md
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient, UpdateOne

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


BASE_PATH = Path("/home/pak/Processing data/2026-01-23/OutputDocling")


def count_files_by_type() -> Dict[str, int]:
    """Подсчёт файлов по типам."""
    counts = {}
    for type_dir in BASE_PATH.iterdir():
        if type_dir.is_dir() and not type_dir.name.startswith('.'):
            json_files = list(type_dir.glob("**/*.json"))
            counts[type_dir.name] = len(json_files)
    return counts


def extract_text_content(docling_data: dict) -> dict:
    """
    Извлекает текстовое содержимое из Docling JSON.

    Returns:
        {
            "texts": "собранный текст из текстовых блоков",
            "tables": "собранный текст из таблиц",
            "combined": "объединённый текст",
            "text_count": количество текстовых блоков,
            "table_count": количество таблиц,
            "total_chars": общее количество символов
        }
    """
    texts = []
    tables = []

    # Извлечение текстовых блоков
    texts_data = docling_data.get("texts", [])
    for text_item in texts_data:
        if isinstance(text_item, dict):
            text_content = text_item.get("text", "")
            if text_content:
                texts.append(text_content)

    # Извлечение таблиц
    tables_data = docling_data.get("tables", [])
    for table_item in tables_data:
        if isinstance(table_item, dict):
            # Извлекаем текст из ячеек таблицы
            table_texts = []
            for cell in table_item.get("texts", []):
                if isinstance(cell, dict):
                    cell_text = cell.get("text", "")
                    if cell_text:
                        table_texts.append(cell_text)
            if table_texts:
                tables.append(" | ".join(table_texts))

    combined_texts = "\n".join(texts)
    combined_tables = "\n".join(tables)
    combined = f"{combined_texts}\n{combined_tables}".strip()

    return {
        "texts": combined_texts,
        "tables": combined_tables,
        "combined": combined,
        "text_count": len(texts),
        "table_count": len(tables),
        "total_chars": len(combined),
    }


def extract_metadata(json_path: Path) -> dict:
    """Извлекает метаданные из JSON файла."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    unit_id = json_path.parent.name  # Имя директории = UNIT_xxx

    # Определение типа файла по директории
    file_type = json_path.parent.parent.name  # docx, html, xlsx, xml

    # Origin данные
    origin = data.get("origin", {})
    name = data.get("name", "")

    # Схема и версия
    schema_name = data.get("schema_name", "Unknown")
    version = data.get("version", "Unknown")

    # Извлечение текстового содержимого
    content = extract_text_content(data)

    return {
        "unit_id": unit_id,
        "file_type": file_type,
        "original_filename": origin.get("filename", name),
        "mimetype": origin.get("mimetype", "unknown"),
        "schema_name": schema_name,
        "schema_version": version,
        "json_path": str(json_path),
        "md_path": str(json_path.with_suffix(".md")),
        "loaded_at": datetime.now().isoformat(),
        **content
    }


def scan_dataset() -> List[dict]:
    """Сканирует директорию и собирает метаданные для всех файлов."""
    logger.info(f"🔍 Сканирование директории: {BASE_PATH}")

    metadata_list = []
    type_dirs = [d for d in BASE_PATH.iterdir() if d.is_dir() and not d.name.startswith('.')]

    for type_dir in type_dirs:
        logger.info(f"   Обработка {type_dir.name}/...")
        unit_dirs = [d for d in type_dir.iterdir() if d.is_dir() and d.name.startswith("UNIT_")]

        for unit_dir in unit_dirs:
            json_file = unit_dir / f"{unit_dir.name}.json"
            if json_file.exists():
                try:
                    metadata = extract_metadata(json_file)
                    metadata_list.append(metadata)
                except Exception as e:
                    logger.warning(f"   Ошибка чтения {json_file}: {e}")

    logger.info(f"✅ Найдено файлов: {len(metadata_list)}")
    return metadata_list


def load_to_mongodb(metadata_list: List[dict], batch_size: int = 100):
    """Загружает метаданные в MongoDB."""
    settings = get_settings()

    logger.info(f"📦 Подключение к MongoDB: {settings.MONGO_URI}")
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_PROTOCOLS_COLLECTION]

    # Проверяем текущее количество
    existing_count = collection.count_documents({})
    logger.info(f"   Текущее количество документов: {existing_count}")

    # Готовим bulk operations
    operations = []
    for metadata in metadata_list:
        unit_id = metadata["unit_id"]

        operations.append(
            UpdateOne(
                {"unit_id": unit_id},
                {
                    "$set": metadata,
                    "$setOnInsert": {"created_at": datetime.now().isoformat()}
                },
                upsert=True
            )
        )

        if len(operations) >= batch_size:
            result = collection.bulk_write(operations, ordered=False)
            logger.info(f"   Обработано: {result.upserted_count} upserted, {result.modified_count} modified")
            operations = []

    # Финальная пачка
    if operations:
        result = collection.bulk_write(operations, ordered=False)
        logger.info(f"   Финал: {result.upserted_count} upserted, {result.modified_count} modified")

    # Создаём индексы
    logger.info("📊 Создание индексов...")
    collection.create_index("unit_id", unique=True)
    collection.create_index("file_type")
    collection.create_index("content.total_chars")

    new_count = collection.count_documents({})
    logger.info(f"✅ Итоговое количество документов: {new_count} (+{new_count - existing_count} новых)")

    client.close()


def generate_statistics(metadata_list: List[dict]) -> dict:
    """Генерирует статистику по датасету."""
    stats = {
        "total": len(metadata_list),
        "by_type": {},
        "content_stats": {
            "empty": 0,
            "small": 0,  # < 500 chars
            "medium": 0,  # 500-2000
            "large": 0,   # 2000-5000
            "xlarge": 0,  # > 5000
        },
        "avg_text_count": 0,
        "avg_table_count": 0,
        "avg_total_chars": 0,
    }

    total_text_count = 0
    total_table_count = 0
    total_chars = 0

    for meta in metadata_list:
        # По типу
        file_type = meta["file_type"]
        stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

        # По размеру
        chars = meta["total_chars"]
        if chars == 0:
            stats["content_stats"]["empty"] += 1
        elif chars < 500:
            stats["content_stats"]["small"] += 1
        elif chars < 2000:
            stats["content_stats"]["medium"] += 1
        elif chars < 5000:
            stats["content_stats"]["large"] += 1
        else:
            stats["content_stats"]["xlarge"] += 1

        total_text_count += meta["text_count"]
        total_table_count += meta["table_count"]
        total_chars += chars

    if metadata_list:
        stats["avg_text_count"] = round(total_text_count / len(metadata_list), 1)
        stats["avg_table_count"] = round(total_table_count / len(metadata_list), 1)
        stats["avg_total_chars"] = round(total_chars / len(metadata_list), 1)

    return stats


def main():
    """Главная функция."""
    print("=" * 70)
    print(f"{'ЗАГРУЗКА НОВОГО DATASET В MONGODB':^70}")
    print("=" * 70)

    # Проверка существования директории
    if not BASE_PATH.exists():
        logger.error(f"❌ Директория не найдена: {BASE_PATH}")
        return

    # Подсчёт файлов по типам
    print("\n📊 Подсчёт файлов...")
    type_counts = count_files_by_type()
    for file_type, count in sorted(type_counts.items()):
        print(f"   {file_type}: {count}")
    print(f"   Итого: {sum(type_counts.values())}")

    # Сканирование
    print("\n🔍 Сканирование датасета...")
    metadata_list = scan_dataset()

    if not metadata_list:
        logger.error("❌ Не найдено файлов для загрузки!")
        return

    # Статистика
    print("\n📊 Статистика датасета:")
    stats = generate_statistics(metadata_list)
    print(f"   Всего документов: {stats['total']}")
    print(f"   По типам:")
    for file_type, count in sorted(stats["by_type"].items()):
        print(f"      {file_type}: {count}")
    print(f"   По размеру (символы):")
    print(f"      пустые (< 1): {stats['content_stats']['empty']}")
    print(f"      малые (1-499): {stats['content_stats']['small']}")
    print(f"      средние (500-1999): {stats['content_stats']['medium']}")
    print(f"      большие (2000-4999): {stats['content_stats']['large']}")
    print(f"      очень большие (>=5000): {stats['content_stats']['xlarge']}")
    print(f"   Среднее текстовых блоков: {stats['avg_text_count']}")
    print(f"   Среднее таблиц: {stats['avg_table_count']}")
    print(f"   Среднее символов: {stats['avg_total_chars']}")

    # Загрузка в MongoDB
    print("\n📦 Загрузка в MongoDB...")
    load_to_mongodb(metadata_list)

    # Сохранение статистики
    stats_file = Path("/home/pak/llm_qa_service/dataset_stats.json")
    stats["timestamp"] = datetime.now().isoformat()
    stats["source_path"] = str(BASE_PATH)

    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\n📁 Статистика сохранена: {stats_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
