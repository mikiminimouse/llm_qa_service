"""Export winners from MongoDB qa_results to CSV format."""

import csv
import logging
from datetime import datetime
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def export_winners_to_csv(
    output_path: str = "winners_export.csv",
    mongo_uri: str = "mongodb://admin:password@localhost:27018/?authSource=admin",
    db_name: str = "docling_metadata",
    collection_name: str = "qa_results"
) -> int:
    """
    Export winners from MongoDB to CSV.

    Args:
        output_path: Path to output CSV file
        mongo_uri: MongoDB connection URI
        db_name: Database name
        collection_name: Collection name

    Returns:
        Number of exported records
    """
    client = MongoClient(mongo_uri)
    db = client[db_name]
    collection = db[collection_name]

    # Count total
    total = collection.count_documents({"result.winner_found": True})
    logger.info(f"Found {total} records with winners")

    if total == 0:
        logger.warning("No winners found to export")
        return 0

    # Get all records with winners, sorted by unit_id
    cursor = collection.find({"result.winner_found": True}).sort("unit_id", 1)

    # Headers
    headers = [
        'unit_id',
        'winner_name',
        'inn',
        'kpp',
        'ogrn',
        'address',
        'contract_price',
        'customer_name',
        'customer_inn',
        'purchase_number',
        'purchase_name',
        'confidence',
        'processing_time_ms',
        'model_used',
        'timestamp'
    ]

    exported = 0

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(headers)

        for doc in cursor:
            result = doc.get('result', {})
            winners = result.get('winners', [])

            if not winners:
                continue

            # Main winner (first in array)
            w = winners[0]
            procurement = result.get('procurement', {})
            customer = result.get('customer', {})

            # Format contract price
            price = w.get('contract_price')
            if price is None:
                price_str = ''
            elif isinstance(price, (int, float)):
                price_str = f"{price:.2f}"
            else:
                price_str = str(price)

            # Format timestamp
            timestamp = doc.get('timestamp')
            if timestamp:
                timestamp_str = str(timestamp)
            else:
                timestamp_str = ''

            writer.writerow([
                doc.get('unit_id', ''),
                w.get('name', ''),
                w.get('inn', ''),
                w.get('kpp', ''),
                w.get('ogrn', ''),
                w.get('address', ''),
                price_str,
                customer.get('name', ''),
                customer.get('inn', ''),
                procurement.get('purchase_notice_number', ''),
                procurement.get('purchase_name', ''),
                w.get('confidence', ''),
                doc.get('processing_time_ms', ''),
                doc.get('model_used', ''),
                timestamp_str
            ])

            exported += 1

            if exported % 100 == 0:
                logger.info(f"Exported {exported}/{total}")

    client.close()

    logger.info(f"Export complete: {exported} records -> {output_path}")
    return exported


def export_all_records(
    output_path: str = "qa_results_full.csv",
    mongo_uri: str = "mongodb://admin:password@localhost:27018/?authSource=admin",
    db_name: str = "docling_metadata",
    collection_name: str = "qa_results"
) -> int:
    """
    Export ALL records from qa_results (including ones without winners).

    Args:
        output_path: Path to output CSV file
        mongo_uri: MongoDB connection URI
        db_name: Database name
        collection_name: Collection name

    Returns:
        Number of exported records
    """
    client = MongoClient(mongo_uri)
    db = client[db_name]
    collection = db[collection_name]

    # Count total
    total = collection.count_documents({})
    logger.info(f"Found {total} total records")

    cursor = collection.find({}).sort("unit_id", 1)

    headers = [
        'unit_id',
        'winner_found',
        'winner_name',
        'inn',
        'customer_name',
        'customer_inn',
        'purchase_number',
        'purchase_name',
        'is_service_file',
        'data_anonymized',
        'confidence',
        'processing_time_ms',
        'model_used',
        'timestamp'
    ]

    exported = 0

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(headers)

        for doc in cursor:
            result = doc.get('result', {})
            winners = result.get('winners', [])
            procurement = result.get('procurement', {})
            customer = result.get('customer', {})
            flags = result.get('flags', {})

            w = winners[0] if winners else {}

            writer.writerow([
                doc.get('unit_id', ''),
                result.get('winner_found', ''),
                w.get('name', ''),
                w.get('inn', ''),
                customer.get('name', ''),
                customer.get('inn', ''),
                procurement.get('purchase_notice_number', ''),
                procurement.get('purchase_name', ''),
                flags.get('is_service_file', ''),
                flags.get('data_anonymized', ''),
                w.get('confidence', '') if w else '',
                doc.get('processing_time_ms', ''),
                doc.get('model_used', ''),
                doc.get('timestamp', '')
            ])

            exported += 1

            if exported % 100 == 0:
                logger.info(f"Exported {exported}/{total}")

    client.close()

    logger.info(f"Export complete: {exported} records -> {output_path}")
    return exported


if __name__ == "__main__":
    print("=== Экспорт победителей ===")
    count = export_winners_to_csv()
    print(f"\nЭкспортировано записей с победителями: {count}")

    print("\n=== Экспорт всех записей ===")
    count_all = export_all_records()
    print(f"\nЭкспортировано всех записей: {count_all}")
