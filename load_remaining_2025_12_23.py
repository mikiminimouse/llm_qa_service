"""Загрузка оставшихся документов из датасета 2025-12-23 в MongoDB."""

import asyncio
import json
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

DATASET_PATH = Path("/home/pak/Processing data/2025-12-23/OutputDocling")
MONGO_URI = "mongodb://admin:password@localhost:27018/?authSource=admin"


async def load_remaining():
    """Загрузка документов, которых ещё нет в MongoDB."""
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['docling_metadata']
    collection = db['docling_results']

    loaded = 0
    skipped = 0
    errors = []
    total_files = 0

    # Подсчитаем общее количество JSON файлов
    json_files = list(DATASET_PATH.rglob("*.json"))
    total_files = len(json_files)
    print(f"Found {total_files} JSON files in dataset")

    for json_file in json_files:
        unit_dir = json_file.parent
        unit_id = unit_dir.name

        # Skip if already loaded
        existing = await collection.find_one({"unit_id": unit_id})
        if existing:
            skipped += 1
            continue

        try:
            with open(json_file) as f:
                docling_doc = json.load(f)

            doc = {
                'unit_id': unit_id,
                'content': docling_doc,
                'source_file': docling_doc.get('name', json_file.name),
                'loaded_at': '2026-01-26T10:00:00Z'
            }

            await collection.insert_one(doc)
            loaded += 1

            if loaded % 50 == 0:
                print(f"Progress: {loaded} loaded, {skipped} skipped...")

        except Exception as e:
            errors.append((unit_id, str(e)))
            print(f"Error loading {unit_id}: {e}")

    client.close()

    print(f"\n=== Summary ===")
    print(f"Total files in dataset: {total_files}")
    print(f"Already loaded (skipped): {skipped}")
    print(f"Newly loaded: {loaded}")
    print(f"Errors: {len(errors)}")

    if errors:
        print(f"\n=== Errors ===")
        for unit_id, error in errors[:10]:
            print(f"{unit_id}: {error[:100]}")

    return loaded, skipped, errors


if __name__ == "__main__":
    asyncio.run(load_remaining())
