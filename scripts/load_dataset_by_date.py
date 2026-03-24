#!/usr/bin/env python3
"""
Загрузка датасета за конкретную дату в MongoDB.

Использование:
    python scripts/load_dataset_by_date.py --date 2025-12-23
    python scripts/load_dataset_by_date.py --date 2025-12-23 --dry-run
    python scripts/load_dataset_by_date.py --date 2025-12-23 --base-path "/custom/path"

Структура ожидаемых директорий:
    /home/pak/Processing data/{date}/OutputDocling/
    ├── docx/
    │   ├── UNIT_001/
    │   │   ├── UNIT_001.json
    │   │   └── UNIT_001.md
    │   └── UNIT_002/
    │       └── ...
    ├── html/
    ├── xlsx/
    └── xml/
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pymongo import MongoClient, UpdateOne

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Базовый путь к директории с данными
DEFAULT_BASE_PATH = Path("/home/pak/Processing data")


def extract_text_content(docling_data: dict) -> dict:
    """
    Извлекает текстовое содержимое из Docling JSON.

    Returns:
        {
            "texts": "собранный текст",
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


def extract_metadata(json_path: Path, target_date: str) -> dict:
    """Извлекает метаданные из JSON файла."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    unit_id = json_path.parent.name  # Имя директории = UNIT_xxx
    file_type = json_path.parent.parent.name  # docx, html, xlsx, xml

    # Origin данные
    origin = data.get("origin", {})
    name = data.get("name", "")

    # Схема и версия
    schema_name = data.get("schema_name", "Unknown")
    version = data.get("version", "Unknown")

    # Извлечение текстового содержимого
    content = extract_text_content(data)

    # Trace chain данные (если есть)
    contract = data.get("contract", {})
    registration_number = contract.get("registration_number") or data.get("registrationNumber")

    return {
        "unit_id": unit_id,
        "file_type": file_type,
        "original_filename": origin.get("filename", name),
        "mimetype": origin.get("mimetype", "unknown"),
        "schema_name": schema_name,
        "schema_version": version,
        "json_path": str(json_path),
        "md_path": str(json_path.with_suffix(".md")),
        "target_date": target_date,
        "loaded_at": datetime.now().isoformat(),
        "registration_number": registration_number,
        # Trace chain инициализация
        "trace": ["load_dataset_by_date"],
        "history": [{
            "component": "load_dataset_by_date",
            "timestamp": datetime.now().isoformat(),
            "action": "loaded",
            "target_date": target_date
        }],
        **content
    }


def scan_dataset(target_date: str, base_path: Path) -> List[dict]:
    """Сканирует директорию и собирает метаданные для всех файлов."""
    data_path = base_path / target_date / "OutputDocling"

    if not data_path.exists():
        logger.error(f"Директория не найдена: {data_path}")
        return []

    logger.info(f"Сканирование директории: {data_path}")

    metadata_list = []
    type_dirs = [d for d in data_path.iterdir() if d.is_dir() and not d.name.startswith('.')]

    for type_dir in type_dirs:
        logger.info(f"   Обработка {type_dir.name}/...")
        unit_dirs = [d for d in type_dir.iterdir() if d.is_dir() and d.name.startswith("UNIT_")]

        for unit_dir in unit_dirs:
            json_file = unit_dir / f"{unit_dir.name}.json"
            if json_file.exists():
                try:
                    metadata = extract_metadata(json_file, target_date)
                    metadata_list.append(metadata)
                except Exception as e:
                    logger.warning(f"   Ошибка чтения {json_file}: {e}")

    logger.info(f"Найдено файлов: {len(metadata_list)}")
    return metadata_list


def check_existing_unit_ids(client, database: str, collection: str, unit_ids: List[str]) -> set:
    """Проверяет какие unit_id уже существуют в MongoDB."""
    db = client[database]
    coll = db[collection]

    existing = set()
    # Проверяем пачками по 1000
    batch_size = 1000
    for i in range(0, len(unit_ids), batch_size):
        batch = unit_ids[i:i + batch_size]
        cursor = coll.find({"unit_id": {"$in": batch}}, {"unit_id": 1})
        existing.update(doc["unit_id"] for doc in cursor)

    return existing


def load_to_mongodb(
    metadata_list: List[dict],
    settings,
    batch_size: int = 100,
    dry_run: bool = False
) -> dict:
    """Загружает метаданные в MongoDB."""

    result_stats = {
        "total": len(metadata_list),
        "new": 0,
        "skipped": 0,
        "updated": 0,
    }

    if dry_run:
        logger.info("[DRY-RUN] Пропускаем фактическую загрузку")
        result_stats["new"] = len(metadata_list)
        return result_stats

    logger.info(f"Подключение к MongoDB: {settings.MONGO_URI}")
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_PROTOCOLS_COLLECTION]

    # Проверяем существующие документы
    logger.info("Проверка существующих документов...")
    all_unit_ids = [m["unit_id"] for m in metadata_list]
    existing_ids = check_existing_unit_ids(client, settings.MONGO_DATABASE, settings.MONGO_PROTOCOLS_COLLECTION, all_unit_ids)

    logger.info(f"   Существует: {len(existing_ids)}")
    logger.info(f"   Новых: {len(all_unit_ids) - len(existing_ids)}")

    # Готовим bulk operations
    operations = []
    new_count = 0
    updated_count = 0

    for metadata in metadata_list:
        unit_id = metadata["unit_id"]
        is_new = unit_id not in existing_ids

        if is_new:
            new_count += 1
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
        else:
            # Существующий документ - обновляем trace и историю
            updated_count += 1
            operations.append(
                UpdateOne(
                    {"unit_id": unit_id},
                    {
                        "$push": {
                            "trace": "load_dataset_by_date",
                            "history": {
                                "$each": [{
                                    "component": "load_dataset_by_date",
                                    "timestamp": datetime.now().isoformat(),
                                    "action": "reloaded",
                                    "target_date": metadata["target_date"]
                                }]
                            }
                        },
                        "$set": {
                            "loaded_at": metadata["loaded_at"],
                            "total_chars": metadata["total_chars"],
                        }
                    }
                )
            )

        if len(operations) >= batch_size:
            bulk_result = collection.bulk_write(operations, ordered=False)
            logger.info(f"   Обработано: {bulk_result.upserted_count} upserted, {bulk_result.modified_count} modified")
            operations = []

    # Финальная пачка
    if operations:
        bulk_result = collection.bulk_write(operations, ordered=False)
        logger.info(f"   Финал: {bulk_result.upserted_count} upserted, {bulk_result.modified_count} modified")

    # Создаём индексы
    logger.info("Создание индексов...")
    collection.create_index("unit_id", unique=True)
    collection.create_index("file_type")
    collection.create_index("loaded_at")
    collection.create_index("target_date")

    final_count = collection.count_documents({})
    logger.info(f"Итоговое количество документов: {final_count:,}")

    client.close()

    result_stats["new"] = new_count
    result_stats["skipped"] = 0
    result_stats["updated"] = updated_count

    return result_stats


def generate_statistics(metadata_list: List[dict]) -> dict:
    """Генерирует статистику по датасету."""
    stats = {
        "total": len(metadata_list),
        "by_type": {},
        "content_stats": {
            "empty": 0,
            "small": 0,
            "medium": 0,
            "large": 0,
            "xlarge": 0,
        },
        "avg_text_count": 0,
        "avg_table_count": 0,
        "avg_total_chars": 0,
    }

    total_text_count = 0
    total_table_count = 0
    total_chars = 0

    for meta in metadata_list:
        file_type = meta["file_type"]
        stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

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
    parser = argparse.ArgumentParser(description="Загрузка датасета за конкретную дату")
    parser.add_argument("--date", required=True, help="Дата датасета в формате YYYY-MM-DD")
    parser.add_argument("--base-path", default=str(DEFAULT_BASE_PATH), help="Базовый путь к директории с данными")
    parser.add_argument("--dry-run", action="store_true", help="Анализ без фактической загрузки")
    parser.add_argument("--batch-size", type=int, default=100, help="Размер пачки для bulk operations")
    args = parser.parse_args()

    target_date = args.date
    base_path = Path(args.base_path)

    print("\n" + "="*70)
    print(f"ЗАГРУЗКА DATASET ЗА ДАТУ: {target_date}")
    print("="*70 + "\n")

    settings = get_settings()

    # Сканирование
    metadata_list = scan_dataset(target_date, base_path)

    if not metadata_list:
        logger.error("Не найдено файлов для загрузки!")
        return 1

    # Статистика
    stats = generate_statistics(metadata_list)
    print("Статистика датасета:")
    print(f"   Всего документов: {stats['total']:,}")
    print(f"   По типам:")
    for file_type, count in sorted(stats["by_type"].items()):
        print(f"      {file_type}: {count:,}")
    print(f"   По размеру (символы):")
    print(f"      пустые (< 1): {stats['content_stats']['empty']}")
    print(f"      малые (1-499): {stats['content_stats']['small']}")
    print(f"      средние (500-1999): {stats['content_stats']['medium']}")
    print(f"      большие (2000-4999): {stats['content_stats']['large']}")
    print(f"      очень большие (>=5000): {stats['content_stats']['xlarge']}")
    print(f"   Среднее текстовых блоков: {stats['avg_text_count']}")
    print(f"   Среднее таблиц: {stats['avg_table_count']}")
    print(f"   Среднее символов: {stats['avg_total_chars']}")

    # Загрузка
    print(f"\n{'='*70}")
    if args.dry_run:
        print("[DRY-RUN] Анализ без загрузки")
    else:
        print("Загрузка в MongoDB...")
    print(f"{'='*70}\n")

    load_result = load_to_mongodb(
        metadata_list,
        settings,
        batch_size=args.batch_size,
        dry_run=args.dry_run
    )

    # Сохранение отчёта
    report_path = Path(f"reports/load_{target_date}_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "target_date": target_date,
        "base_path": str(base_path),
        "dry_run": args.dry_run,
        "timestamp": datetime.now().isoformat(),
        "statistics": stats,
        "load_result": load_result,
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*70}")
    print(f"Отчёт сохранён: {report_path}")
    print(f"{'='*70}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
