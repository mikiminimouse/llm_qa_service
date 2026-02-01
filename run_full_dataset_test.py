#!/usr/bin/env python3
"""
Полноценное тестирование LLM_qaenrich на новом датасете.

Обрабатывает все документы из /home/pak/Processing data/2026-01-23/OutputDocling/
с использованием max_concurrent=6 и собирает детальную аналитику.

Особенности:
- max_concurrent=6 (оптимизировано для GLM Coding Max-Quarterly)
- Timeout 45 секунд на документ
- Автоматический retry для failed
- Детальная статистика по всем срезам
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from application.orchestrator import QAOrchestrator
from config import get_settings
from infrastructure.llm.factory import create_llm_client
from infrastructure.repositories.mongo_qa_repository import MongoQARepository
from infrastructure.loaders.mongo_loader import MongoContextLoader
from infrastructure.prompt_manager import PromptManager
from metrics_collector import MetricsCollector, DocumentType, DocumentSize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def get_all_unit_ids_with_metadata() -> List[tuple]:
    """
    Получить все unit_ids с метаданными для тестирования.

    Returns:
        List of (unit_id, metadata) tuples
    """
    settings = get_settings()
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_PROTOCOLS_COLLECTION]

    # Получаем все документы с метаданными
    cursor = collection.find({}, {"unit_id": 1, "file_type": 1, "combined": 1, "total_chars": 1})

    results = []
    for doc in cursor:
        unit_id = doc.get("unit_id")
        if unit_id:
            metadata = {
                "file_type": doc.get("file_type", "unknown"),
                "content_length": doc.get("total_chars", 0),
            }
            results.append((unit_id, metadata))

    client.close()
    logger.info(f"📄 Найдено документов: {len(results)}")
    return results


async def get_unprocessed_unit_ids() -> List[str]:
    """
    Получить список unit_ids, которые не обработаны.

    Returns:
        List of unprocessed unit_ids
    """
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    # Все unit_ids из protocols
    all_ids = await db.protocols.distinct("unit_id")

    # Все обработанные из qa_results
    qa_ids = await db.qa_results.distinct("unit_id")

    # Необработанные
    unprocessed = [uid for uid in all_ids if uid not in qa_ids]

    await client.close()

    logger.info(f"Всего в protocols: {len(all_ids)}")
    logger.info(f"Обработано (qa_results): {len(qa_ids)}")
    logger.info(f"Необработано: {len(unprocessed)}")

    return unprocessed


async def run_full_test(
    max_concurrent: int = 6,
    sample_size: int = 0,
    skip_processed: bool = False,
):
    """
    Запуск полноценного тестирования.

    Args:
        max_concurrent: Максимальное количество параллельных запросов
        sample_size: Размер выборки (0 = все документы)
        skip_processed: Пропускать уже обработанные документы
    """
    logger.info("=" * 70)
    logger.info("     ПОЛНОЦЕННОЕ ТЕСТИРОВАНИЕ LLM_QAENRICH")
    logger.info("=" * 70)

    start_time = time.time()

    # Настройки
    settings = get_settings()
    logger.info(f"\n⚙️ Конфигурация:")
    logger.info(f"  GLM Model: {settings.GLM_MODEL}")
    logger.info(f"  GLM Timeout: {settings.GLM_TIMEOUT} сек")
    logger.info(f"  GLM Max Retries: {settings.GLM_MAX_RETRIES}")
    logger.info(f"  Max Concurrent: {max_concurrent}")
    logger.info(f"  Sample Size: {sample_size if sample_size > 0 else 'все'}")
    logger.info(f"  Skip Processed: {skip_processed}")

    # Инициализация компонентов
    logger.info(f"\n🔧 Инициализация компонентов...")

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
        skip_processed=skip_processed,
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
    )

    # Метрики
    metrics = MetricsCollector()
    metrics.start()

    # Получение документов для обработки
    logger.info(f"\n📄 Получение списка документов...")

    # Получаем все unit_ids с метаданными
    unit_ids_with_meta = await get_all_unit_ids_with_metadata()
    unit_ids = [uid for uid, _ in unit_ids_with_meta]
    metadata_map = {uid: meta for uid, meta in unit_ids_with_meta}

    if sample_size > 0 and sample_size < len(unit_ids):
        import random
        random.shuffle(unit_ids)
        unit_ids = unit_ids[:sample_size]
        logger.info(f"   Выборка: {len(unit_ids)} документов")

    # Обработка
    logger.info(f"\n🚀 Начало обработки {len(unit_ids)} документов...")
    logger.info(f"   Конкурентность: {max_concurrent} параллельных запросов")
    logger.info(f"   Retry для failed: включён")

    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unit_ids,
        max_concurrent=max_concurrent,
        retry_failed=True,
        retry_delay_seconds=15,
    )

    # Сбор метрик
    logger.info(f"\n📊 Сбор метрик...")

    for result in results:
        metadata = metadata_map.get(result.unit_id, {})
        metrics.add_from_result(
            unit_id=result.unit_id,
            processing_time_ms=result.processing_time_ms,
            success=result.success,
            skipped=result.skipped,
            error=result.error,
            record=result.record,
            metadata=metadata,
        )

    metrics.finish()

    # Вывод результатов
    duration = time.time() - start_time

    logger.info("\n" + "=" * 70)
    logger.info("     ИТОГОВАЯ СТАТИСТИКА")
    logger.info("=" * 70)
    logger.info(f"⏱️  Время выполнения: {duration:.1f} сек ({duration/60:.1f} мин)")

    metrics.print_summary()

    # Детализация по типам
    logger.info("\n📊 По типам документов:")
    by_type = metrics.get_by_type()
    for doc_type, stats in sorted(by_type.items()):
        logger.info(
            f"   {doc_type}: {stats['count']} док, "
            f"success={stats['success']}, "
            f"winner={stats['winner_found']}/{stats['success']} ({stats['winner_rate']}%), "
            f"time={stats['avg_time_ms']}мс"
        )

    # Детализация по размеру
    logger.info("\n📊 По размеру документов:")
    by_size = metrics.get_by_size()
    for size, stats in sorted(by_size.items()):
        logger.info(
            f"   {size}: {stats['count']} док, "
            f"success={stats['success']}, "
            f"winner={stats['winner_found']}/{stats['success']} ({stats['winner_rate']}%), "
            f"time={stats['avg_time_ms']}мс"
        )

    # Процентили
    percentiles = metrics.get_percentiles()
    if percentiles:
        logger.info("\n📊 Процентили времени обработки:")
        logger.info(f"   p50: {percentiles['p50']}мс")
        logger.info(f"   p75: {percentiles['p75']}мс")
        logger.info(f"   p90: {percentiles['p90']}мс")
        logger.info(f"   p95: {percentiles['p95']}мс")
        logger.info(f"   p99: {percentiles['p99']}мс")

    # Ошибки
    errors = metrics.get_errors()
    if errors["total_errors"] > 0:
        logger.info("\n⚠️  Ошибки:")
        logger.info(f"   Всего: {errors['total_errors']}")
        logger.info(f"   По типам: {errors['by_type']}")
        logger.info(f"   Частые:")
        for err in errors['most_common'][:5]:
            logger.info(f"      - {err['error']}: {err['count']}")

    # Сохранение метрик
    logger.info("\n💾 Сохранение метрик...")
    metrics_files = metrics.save_all()

    # Дополнительная статистика
    summary = metrics.get_summary()
    summary["settings"] = {
        "max_concurrent": max_concurrent,
        "sample_size": sample_size,
        "skip_processed": skip_processed,
        "glm_timeout": settings.GLM_TIMEOUT,
        "glm_max_retries": settings.GLM_MAX_RETRIES,
        "glm_retry_delay": settings.GLM_RETRY_DELAY,
    }

    # Сохранение финального отчёта
    report_path = Path("/home/pak/llm_qa_service/full_test_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info(f"📁 Финальный отчёт: {report_path}")

    # Закрытие соединений
    await loader.close()
    await llm_client.close()

    logger.info("=" * 70)
    logger.info("✅ Тестирование завершено!")
    logger.info("=" * 70)

    return summary


async def run_quick_test(sample_size: int = 30):
    """
    Быстрый тест на выборке документов.

    Args:
        sample_size: Размер выборки
    """
    logger.info(f"\n🔬 БЫСТРЫЙ ТЕСТ (выборка: {sample_size} документов)")
    return await run_full_test(
        max_concurrent=6,
        sample_size=sample_size,
        skip_processed=False,
    )


async def main():
    """Главная функция."""
    import argparse

    parser = argparse.ArgumentParser(description="Полноценное тестирование LLM_qaenrich")
    parser.add_argument("--quick", action="store_true", help="Быстрый тест на 30 документах")
    parser.add_argument("--sample", type=int, default=0, help="Размер выборки (0 = все)")
    parser.add_argument("--concurrent", type=int, default=6, help="Макс. параллельных запросов")
    parser.add_argument("--skip-processed", action="store_true", help="Пропускать обработанные")

    args = parser.parse_args()

    if args.quick:
        await run_quick_test(sample_size=30)
    else:
        await run_full_test(
            max_concurrent=args.concurrent,
            sample_size=args.sample,
            skip_processed=args.skip_processed,
        )


if __name__ == "__main__":
    asyncio.run(main())
