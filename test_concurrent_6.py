#!/usr/bin/env python3
"""
Тестирование производительности с max_concurrent=6
"""

import asyncio
import json
import logging
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from motor.motor_asyncio import AsyncIOMotorClient
from application.orchestrator import QAOrchestrator
from config import get_settings
from infrastructure.llm.factory import create_llm_client
from infrastructure.repositories.mongo_qa_repository import MongoQARepository
from infrastructure.loaders.mongo_loader import MongoContextLoader
from infrastructure.prompt_manager import PromptManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def get_sample_with_content(sample_size: int = 30):
    """Получить случайную выборку документов с содержанием."""
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    pipeline = [
        {"$sample": {"size": sample_size * 3}},
        {"$project": {"unit_id": 1, "_id": 0}}
    ]

    cursor = db.docling_results.aggregate(pipeline)
    docs = await cursor.to_list(length=sample_size * 3)
    all_ids = [d["unit_id"] for d in docs]

    valid_ids = []
    for unit_id in all_ids[:sample_size * 2]:
        doc = await db.docling_results.find_one({"unit_id": unit_id}, {"content": 1})
        if doc and doc.get("content"):
            content = doc["content"]
            if isinstance(content, dict):
                texts = content.get("texts", "")
                tables = content.get("tables", "")
                combined = str(texts) + str(tables)
                if len(combined) > 500:
                    valid_ids.append(unit_id)
            elif isinstance(content, str) and len(content) > 500:
                valid_ids.append(unit_id)

        if len(valid_ids) >= sample_size:
            break

    client.close()
    return valid_ids[:sample_size]


async def run_test(unit_ids, max_concurrent, settings):
    """Запуск теста."""
    logger.info(f"\n{'='*70}")
    logger.info(f"🚀 ТЕСТ: max_concurrent={max_concurrent}")
    logger.info(f"📄 Документов: {len(unit_ids)}")
    logger.info(f"{'='*70}")

    start = time.time()

    llm_client = create_llm_client(
        provider="glm",
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_BASE_URL,
        model=settings.GLM_MODEL,
        timeout=settings.GLM_TIMEOUT,
        max_retries=settings.GLM_MAX_RETRIES,
        retry_delay=settings.GLM_RETRY_DELAY,
    )

    loader = MongoContextLoader(
        settings.MONGO_URI,
        settings.MONGO_DATABASE,
        settings.MONGO_PROTOCOLS_COLLECTION
    )

    repository = MongoQARepository(
        settings.MONGO_URI,
        settings.MONGO_DATABASE,
        settings.MONGO_QA_COLLECTION
    )

    prompt_manager = PromptManager()

    orchestrator = QAOrchestrator(
        llm_client=llm_client,
        context_loader=loader,
        repository=repository,
        prompt_manager=prompt_manager,
        skip_processed=False,
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
    )

    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unit_ids,
        max_concurrent=max_concurrent,
        retry_failed=False,
        retry_delay_seconds=0,
    )

    duration = time.time() - start

    await loader.close()
    await llm_client.close()

    times = [r.processing_time_ms for r in results if r.processing_time_ms > 0]
    success = sum(1 for r in results if r.success and not r.skipped)
    failed = sum(1 for r in results if not r.success)

    http_429 = sum(1 for r in results if r.error and "429" in r.error)
    http_timeout = sum(1 for r in results if r.error and ("timeout" in r.error.lower() or "timed out" in r.error.lower()))
    rate_limited = sum(1 for r in results if r.error and "Rate limited" in r.error)

    winner_found = sum(1 for r in results if r.success and r.record and hasattr(r.record, 'result') and r.record.result.winner_found)

    return {
        "max_concurrent": max_concurrent,
        "total_docs": len(unit_ids),
        "success": success,
        "failed": failed,
        "duration_sec": round(duration, 2),
        "avg_time_ms": round(statistics.mean(times), 1) if times else 0,
        "median_time_ms": round(statistics.median(times), 1) if times else 0,
        "throughput": round(len(unit_ids) / duration, 2) if duration > 0 else 0,
        "http_429_count": http_429,
        "http_timeout_count": http_timeout,
        "rate_limited_count": rate_limited,
        "winner_found": winner_found,
        "winner_rate": round(100 * winner_found / max(success, 1), 1),
    }


def print_metrics(metrics):
    """Вывод метрик."""
    print("\n" + "=" * 70)
    print(f"{'РЕЗУЛЬТАТЫ ТЕСТА':^70}")
    print("=" * 70)
    print(f"🔧 max_concurrent: {metrics['max_concurrent']}")
    print(f"📄 Документов: {metrics['total_docs']}")
    print(f"✅ Успешно: {metrics['success']} | ❌ Ошибок: {metrics['failed']}")
    print(f"⏱️  Общее время: {metrics['duration_sec']} сек ({metrics['duration_sec']/60:.1f} мин)")
    print(f"📈 Пропускная способность: {metrics['throughput']} док/сек")
    print(f"📊 Среднее время: {metrics['avg_time_ms']/1000:.1f} сек/док")
    print(f"📊 Медиана: {metrics['median_time_ms']/1000:.1f} сек/док")
    print(f"🏆 Winner found: {metrics['winner_found']}/{metrics['success']} ({metrics['winner_rate']}%)")
    print(f"\n⚠️  Ошибки:")
    print(f"   HTTP 429 (Rate Limit): {metrics['http_429_count']}")
    print(f"   Rate Limited (backoff): {metrics['rate_limited_count']}")
    print(f"   Timeout: {metrics['http_timeout_count']}")

    if metrics['http_429_count'] == 0 and metrics['rate_limited_count'] == 0:
        print(f"\n✅ НЕТ HTTP 429 ОШИБОК!")
    else:
        total_429 = metrics['http_429_count'] + metrics['rate_limited_count']
        print(f"\n⚠️  ОБНАРУЖЕНО {total_429} RATE LIMIT ОШИБОК!")

    print("=" * 70)


async def main():
    settings = get_settings()

    print("=" * 70)
    print(f"{'ТЕСТИРОВАНИЕ max_concurrent=6':^70}")
    print("=" * 70)

    unit_ids = await get_sample_with_content(30)

    if not unit_ids:
        logger.error("Не удалось найти документы с содержанием!")
        return

    logger.info(f"Выбрано документов: {len(unit_ids)}")
    random.shuffle(unit_ids)

    # Тест с max_concurrent=6
    metrics = await run_test(unit_ids, max_concurrent=6, settings=settings)
    print_metrics(metrics)

    # Сохранить результаты
    results_file = Path("/home/pak/llm_qa_service/test_concurrent_6_results.json")
    results = {
        "timestamp": datetime.now().isoformat(),
        "sample_size": len(unit_ids),
        "metrics": metrics,
        "settings": {
            "GLM_TIMEOUT": settings.GLM_TIMEOUT,
            "GLM_MAX_RETRIES": settings.GLM_MAX_RETRIES,
            "GLM_RETRY_DELAY": settings.GLM_RETRY_DELAY,
        }
    }

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n📁 Результаты сохранены: {results_file}")


if __name__ == "__main__":
    asyncio.run(main())
