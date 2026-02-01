#!/usr/bin/env python3
"""
Обработка всех необработанных документов через GLM-4.7.

Особенности:
- Параллельная обработка (max_concurrent=3)
- Timeout 120 секунд на документ
- Автоматический retry для failed с уменьшенным concurrency
- Детальная статистика по времени обработки
- Сохранение результатов в qa_results
"""

import asyncio
import logging
import sys
import time
from collections import Counter
from datetime import datetime

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


async def get_unprocessed_unit_ids():
    """Получить список unit_ids, которые есть в docling_results но нет в qa_results."""
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    # Все unit_ids из docling_results
    docling_ids = await db.docling_results.distinct("unit_id")

    # Все обработанные unit_ids из qa_results
    qa_ids = await db.qa_results.distinct("unit_id")

    # Необработанные
    unprocessed = list(set(docling_ids) - set(qa_ids))
    unprocessed.sort()

    logger.info(f"Всего в docling_results: {len(docling_ids)}")
    logger.info(f"Обработано (qa_results): {len(qa_ids)}")
    logger.info(f"Необработано: {len(unprocessed)}")

    client.close()
    return unprocessed


async def process_with_glm47():
    """Обработать все необработанные документы."""
    start_time = time.time()

    logger.info("=" * 70)
    logger.info("     ОБРАБОТКА НЕОБРАБОТАННЫХ ДОКУМЕНТОВ ЧЕРЕЗ GLM-4.7")
    logger.info("=" * 70)

    # Настройка
    settings = get_settings()
    logger.info(f"\n⚙️ Конфигурация:")
    logger.info(f"  GLM Model: {settings.GLM_MODEL}")
    logger.info(f"  GLM Timeout: {settings.GLM_TIMEOUT} сек")
    logger.info(f"  GLM Max Retries: {settings.GLM_MAX_RETRIES}")
    logger.info(f"  Max Tokens: {settings.GLM_MAX_TOKENS}")
    logger.info(f"  Temperature: {settings.GLM_TEMPERATURE}")

    # Инициализация компонентов
    logger.info(f"\n🔧 Инициализация компонентов...")
    try:
        llm_client = create_llm_client(
            provider="glm",
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_BASE_URL,
            model=settings.GLM_MODEL,
            timeout=settings.GLM_TIMEOUT,  # 120 сек
            max_retries=settings.GLM_MAX_RETRIES,  # 5
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
            skip_processed=False,  # Не пропускаем, обрабатываем все
            max_tokens=settings.GLM_MAX_TOKENS,
            temperature=settings.GLM_TEMPERATURE,
        )

        logger.info(f"✅ Компоненты инициализированы")

    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        return

    # Получить необработанные документы
    unprocessed_ids = await get_unprocessed_unit_ids()

    if not unprocessed_ids:
        logger.info("\n✅ Все документы уже обработаны!")
        await loader.close()
        await llm_client.close()
        return

    # Обработка с retry
    # Оптимизация параллельности:
    # - GLM Coding Max-Quarterly позволяет ~5-6 concurrent requests
    # - max_concurrent=6 — безопасный предел без HTTP 429
    # - При max_concurrent=10 наблюдаются множественные 429 ошибки
    # - Retry mechanism обрабатывает временные ошибки
    logger.info(f"\n🚀 Начало обработки {len(unprocessed_ids)} документов...")
    logger.info(f"   Конкурентность: 6 параллельных запросов (оптимизировано)")
    logger.info(f"   Retry для failed: включён")

    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unprocessed_ids,
        max_concurrent=6,  # Оптимизировано: 4 → 6 (без HTTP 429)
        retry_failed=True,
        retry_delay_seconds=15,  # Уменьшено: 30 → 15 сек
    )

    # Статистика
    duration = time.time() - start_time
    success = sum(1 for r in results if r.success and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.success)

    # Анализ времени обработки
    times = [r.processing_time_ms for r in results if r.processing_time_ms > 0]
    avg_time = sum(times) / len(times) if times else 0
    median_time = sorted(times)[len(times) // 2] if times else 0

    # Анализ winner_found
    winner_found = sum(1 for r in results if r.success and r.record and r.record.result.winner_found)

    logger.info("\n" + "=" * 70)
    logger.info("     ИТОГОВАЯ СТАТИСТИКА")
    logger.info("=" * 70)
    logger.info(f"⏱️  Время выполнения: {duration:.1f} сек ({duration/60:.1f} мин)")
    logger.info(f"📄 Всего документов: {len(results)}")
    logger.info(f"✅ Успешно обработано: {success}")
    logger.info(f"⏭️  Пропущено: {skipped}")
    logger.info(f"❌ С ошибками: {failed}")
    logger.info(f"\n📊 Производительность:")
    logger.info(f"   Среднее время: {avg_time/1000:.1f} сек/документ")
    logger.info(f"   Медианное время: {median_time/1000:.1f} сек/документ")
    logger.info(f"   Произв. с учётом параллельности: {duration/len(results):.1f} сек/документ")
    logger.info(f"\n🏆 Качество:")
    logger.info(f"   Победителей найдено: {winner_found}/{success} ({100*winner_found/max(success,1):.1f}%)")
    logger.info("=" * 70)

    # Детализация ошибок
    if failed > 0:
        logger.info("\n⚠️ Ошибки:")
        errors = Counter(r.error for r in results if r.error)
        for error, count in errors.most_common(5):
            logger.info(f"   {error}: {count}")

    await loader.close()
    await llm_client.close()


if __name__ == "__main__":
    asyncio.run(process_with_glm47())
