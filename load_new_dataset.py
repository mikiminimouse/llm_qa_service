"""Script to load new dataset into MongoDB for testing."""

import asyncio
import json
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient
from tqdm import tqdm


async def load_dataset(
    source_path: str,
    mongo_uri: str,
    database: str,
    collection: str,
    clear_existing: bool = False,
):
    """Load dataset from filesystem to MongoDB."""
    client = AsyncIOMotorClient(mongo_uri)
    db = client[database]
    coll = db[collection]

    # Clear existing if requested
    if clear_existing:
        print(f"Clearing collection {collection}...")
        await coll.delete_many({})

    # Find all JSON files
    source = Path(source_path)
    json_files = list(source.rglob("*.json"))
    print(f"Found {len(json_files)} JSON files")

    # Load each file
    loaded = 0
    errors = 0

    for json_file in tqdm(json_files, desc="Loading"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Extract unit_id from filename or data
            unit_id = data.get('unit_id') or json_file.stem

            # Create document
            doc = {
                'unit_id': unit_id,
                'content': data,
                'source_file': str(json_file),
                'dataset': '2025-12-23',
                'loaded_at': asyncio.get_event_loop().time(),
            }

            # Upsert
            await coll.update_one(
                {'unit_id': unit_id},
                {'$set': doc},
                upsert=True
            )
            loaded += 1

        except Exception as e:
            errors += 1
            tqdm.write(f"Error loading {json_file}: {e}")

    print(f"\nLoaded: {loaded}, Errors: {errors}")

    # Verify count
    count = await coll.count_documents({'dataset': '2025-12-23'})
    print(f"Documents in collection with dataset=2025-12-23: {count}")

    await client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='/home/pak/Processing data/2025-12-23/OutputDocling')
    parser.add_argument('--mongo-uri', default='mongodb://admin:password@localhost:27018/?authSource=admin')
    parser.add_argument('--database', default='docling_metadata')
    parser.add_argument('--collection', default='docling_results')
    parser.add_argument('--clear', action='store_true')
    args = parser.parse_args()

    asyncio.run(load_dataset(
        args.source,
        args.mongo_uri,
        args.database,
        args.collection,
        args.clear,
    ))
