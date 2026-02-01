#!/usr/bin/env python3
"""
Тестирование производительности с новыми настройками.
Сравнивает max_concurrent=4 vs max_concurrent=10 на малом датасете.
"""

import asyncio
import json
import logging
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


async def get_unprocessed_unit_ids(limit: int = None):
    """Получить список необработанных unit_ids."""
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    docling_ids = await db.docling_results.distinct("unit_id")
    qa_ids = await db.qa_results.distinct("unit_id")
    unprocessed = list(set(docling_ids) - set(qa_ids))
    unprocessed.sort()

    if limit:
        unprocessed = unprocessed[:limit]

    client.close()
    return unprocessed


async def run_test(unit_ids, max_concurrent, test_name, settings):
    """Запуск теста с указанной конкурентностью."""
    logger.info(f"\n{'='*70}")
    logger.info(f"Запуск теста: {test_name} (max_concurrent={max_concurrent})")
    logger.info(f"Документов: {len(unit_ids)}")
    logger.info(f"{'='*70}")

    start = time.time()

    # Инициализация компонентов
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

    # Запуск обработки
    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unit_ids,
        max_concurrent=max_concurrent,
        retry_failed=False,  # Без retry для чистого замера
        retry_delay_seconds=0,
    )

    duration = time.time() - start

    await loader.close()
    await llm_client.close()

    # Сбор метрик
    times = [r.processing_time_ms for r in results if r.processing_time_ms > 0]
    success = sum(1 for r in results if r.success and not r.skipped)
    failed = sum(1 for r in results if not r.success)
    skipped = sum(1 for r in results if r.skipped)

    # HTTP 429 ошибки
    http_429 = sum(1 for r in results if r.error and "429" in r.error)
    http_timeout = sum(1 for r in results if r.error and ("timeout" in r.error.lower() or "timed out" in r.error.lower()))

    # Winner found
    winner_found = sum(1 for r in results if r.success and r.record and hasattr(r.record, 'result') and r.record.result.winner_found)

    return {
        "test_name": test_name,
        "max_concurrent": max_concurrent,
        "total_docs": len(unit_ids),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "duration_sec": round(duration, 2),
        "avg_time_ms": round(statistics.mean(times), 1) if times else 0,
        "median_time_ms": round(statistics.median(times), 1) if times else 0,
        "min_time_ms": round(min(times), 1) if times else 0,
        "max_time_ms": round(max(times), 1) if times else 0,
        "throughput": round(len(unit_ids) / duration, 2) if duration > 0 else 0,
        "http_429_count": http_429,
        "http_timeout_count": http_timeout,
        "winner_found": winner_found,
        "winner_rate": round(100 * winner_found / max(success, 1), 1),
    }


def print_comparison(metrics1, metrics2):
    """Вывод сравнения двух тестов."""
    print("\n" + "=" * 70)
    print(f"{'СРАВНЕНИЕ ПРОИЗВОДИТЕЛЬНОСТИ':^70}")
    print("=" * 70)

    for m in [metrics1, metrics2]:
        print(f"\n📊 {m['test_name']} (max_concurrent={m['max_concurrent']})")
        print(f"   Документов: {m['total_docs']}")
        print(f"   Успешно: {m['success']} | Ошибок: {m['failed']} | Пропущено: {m['skipped']}")
        print(f"   ⏱️  Время: {m['duration_sec']} сек")
        print(f"   📈 Пропускная способность: {m['throughput']} док/сек")
        print(f"   📊 Среднее время: {m['avg_time_ms']/1000:.1f} сек/док")
        print(f"   📊 Медиана: {m['median_time_ms']/1000:.1f} сек/док")
        print(f"   📊 Min/Max: {m['min_time_ms']/1000:.1f} / {m['max_time_ms']/1000:.1f} сек")
        print(f"   🏆 Winner found: {m['winner_found']}/{m['success']} ({m['winner_rate']}%)")
        print(f"   ⚠️  HTTP 429: {m['http_429_count']} | Timeout: {m['http_timeout_count']}")

    # Сравнение
    print(f"\n{'='*70}")
    print(f"{'АНАЛИЗ УСКОРЕНИЯ':^70}")
    print(f"{'='*70}")

    if metrics2['duration_sec'] > 0:
        speedup = metrics1['duration_sec'] / metrics2['duration_sec']
        print(f"🚀 Ускорение по времени: {speedup:.2f}x")

    if metrics1['throughput'] > 0:
        throughput_improvement = (metrics2['throughput'] - metrics1['throughput']) / metrics1['throughput'] * 100
        print(f"📈 Улучшение пропускной способности: +{throughput_improvement:.1f}%")

    if metrics2['avg_time_ms'] > 0:
        avg_time_change = (metrics1['avg_time_ms'] - metrics2['avg_time_ms']) / metrics1['avg_time_ms'] * 100
        print(f"⏱️  Изменение среднего времени: {avg_time_change:+.1f}%")

    # Проверка на проблемы
    print(f"\n{'='*70}")
    print(f"{'СТАБИЛЬНОСТЬ':^70}")
    print(f"{'='*70}")

    total_429 = metrics1['http_429_count'] + metrics2['http_429_count']
    total_timeout = metrics1['http_timeout_count'] + metrics2['http_timeout_count']

    if total_429 == 0:
        print("✅ HTTP 429 (rate limit): НЕ ОБНАРУЖЕНО")
    else:
        print(f"⚠️  HTTP 429 (rate limit): {total_429} обнаружено!")

    if total_timeout == 0:
        print("✅ Timeout ошибки: НЕ ОБНАРУЖЕНО")
    else:
        print(f"⚠️  Timeout ошибки: {total_timeout} обнаружено!")

    # Рекомендация
    print(f"\n{'='*70}")
    print(f"{'РЕКОМЕНДАЦИЯ':^70}")
    print(f"{'='*70}")

    if total_429 > 0:
        print("⚠️  Обнаружены HTTP 429 ошибки!")
        print("   Рекомендация: СНИЗИТЬ max_concurrent до 8")
    elif speedup >= 1.3:
        print(f"✅ Отличное ускорение ({speedup:.2f}x)!")
        print("   Рекомендация: max_concurrent=10 можно использовать в продакшене")
    elif speedup >= 1.1:
        print(f"✅ Умеренное ускорение ({speedup:.2f}x)")
        print("   Рекомендация: max_concurrent=10 приемлемо")
    else:
        print(f"⚠️  Незначительное ускорение ({speedup:.2f}x)")
        print("   Рекомендация: проверить API лимиты")

    print("=" * 70)


async def main():
    """Главная функция."""
    settings = get_settings()

    logger.info("=" * 70)
    logger.info(" " * 15 + "ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ")
    logger.info("=" * 70)

    # Получить необработанные документы
    unprocessed = await get_unprocessed_unit_ids(limit=50)

    if not unprocessed:
        logger.warning("Нет необработанных документов для теста!")
        return

    logger.info(f"\nНеобработанных документов: {len(unprocessed)}")
    logger.info(f"Используем для тестирования: {len(unprocessed)} документов")

    # Тест 1: max_concurrent=4 (baseline)
    metrics_baseline = await run_test(
        unit_ids=unprocessed,
        max_concurrent=4,
        test_name="Baseline (старые настройки)",
        settings=settings
    )

    # Сохраняем результаты первого теста для повторного тестирования
    # Для повторного теста используем те же документы (переобработка)
    # Это не идеально, но позволяет сравнить скорость

    # Тест 2: max_concurrent=10 (optimized)
    # Примечание: документы уже обработаны, поэтому skip_processed=True не используем
    # Просто измеряем скорость на тех же данных

    logger.info("\n⏳ Пауза 5 секунд перед вторым тестом...")
    await asyncio.sleep(5)

    # Для второго теста используем уже обработанные документы
    # Это покажет нам потенциальную скорость при max_concurrent=10
    test_ids = unprocessed[:min(20, len(unprocessed))]  # Ограничиваем для повторного теста

    metrics_optimized = await run_test(
        unit_ids=test_ids,
        max_concurrent=10,
        test_name="Optimized (новые настройки)",
        settings=settings
    )

    # Сравнение
    print_comparison(metrics_baseline, metrics_optimized)

    # Сохранить результаты в JSON
    results_file = Path("/home/pak/llm_qa_service/performance_test_results.json")
    results = {
        "timestamp": datetime.now().isoformat(),
        "baseline": metrics_baseline,
        "optimized": metrics_optimized,
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
