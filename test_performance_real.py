#!/usr/bin/env python3
"""
Тестирование производительности на РЕАЛЬНЫХ документах с содержанием.
Берет случайную выборку из уже обработанных документов и переобрабатывает их.
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


async def get_sample_with_content(sample_size: int = 20):
    """Получить случайную выборку документов с содержанием."""
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    # Простая выборка — берем случайные документы
    pipeline = [
        {"$sample": {"size": sample_size * 3}},
        {"$project": {"unit_id": 1, "_id": 0}}
    ]

    cursor = db.docling_results.aggregate(pipeline)
    docs = await cursor.to_list(length=sample_size * 3)
    all_ids = [d["unit_id"] for d in docs]

    # Проверим наличие содержимого для первых N
    valid_ids = []
    for unit_id in all_ids[:sample_size * 2]:
        doc = await db.docling_results.find_one({"unit_id": unit_id}, {"content": 1})
        if doc and doc.get("content"):
            content = doc["content"]
            # content может быть объектом с полями texts/tables или строкой
            if isinstance(content, dict):
                texts = content.get("texts", "")
                tables = content.get("tables", "")
                combined = str(texts) + str(tables)
                if len(combined) > 500:  # Минимальная длина содержимого
                    valid_ids.append(unit_id)
            elif isinstance(content, str) and len(content) > 500:
                valid_ids.append(unit_id)

        if len(valid_ids) >= sample_size:
            break

    client.close()
    return valid_ids[:sample_size]


async def run_test(unit_ids, max_concurrent, test_name, settings):
    """Запуск теста с указанной конкурентностью."""
    logger.info(f"\n{'='*70}")
    logger.info(f"🚀 {test_name} (max_concurrent={max_concurrent})")
    logger.info(f"📄 Документов: {len(unit_ids)}")
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
        skip_processed=False,  # Переобрабатываем
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
    )

    # Запуск обработки
    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unit_ids,
        max_concurrent=max_concurrent,
        retry_failed=False,
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

    # Ошибки
    http_429 = sum(1 for r in results if r.error and "429" in r.error)
    http_timeout = sum(1 for r in results if r.error and ("timeout" in r.error.lower() or "timed out" in r.error.lower()))
    other_errors = sum(1 for r in results if r.error and "429" not in r.error and "timeout" not in r.error.lower())

    # Winner found
    winner_found = sum(1 for r in results if r.success and r.record and hasattr(r.record, 'result') and r.record.result.winner_found)

    # Детализация ошибок
    error_summary = {}
    for r in results:
        if r.error:
            err_key = r.error.split('(')[0].strip() if '(' in r.error else r.error[:50]
            error_summary[err_key] = error_summary.get(err_key, 0) + 1

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
        "p95_time_ms": round(sorted(times)[int(len(times) * 0.95)] if len(times) > 0 else 0, 1) if times else 0,
        "min_time_ms": round(min(times), 1) if times else 0,
        "max_time_ms": round(max(times), 1) if times else 0,
        "throughput": round(len(unit_ids) / duration, 2) if duration > 0 else 0,
        "http_429_count": http_429,
        "http_timeout_count": http_timeout,
        "other_errors": other_errors,
        "error_summary": error_summary,
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
        print(f"   Документов: {m['total_docs']} | ✅ {m['success']} | ❌ {m['failed']} | ⏭️ {m['skipped']}")
        print(f"   ⏱️  Общее время: {m['duration_sec']} сек")
        print(f"   📈 Пропускная способность: {m['throughput']} док/сек")
        print(f"   📊 Среднее время: {m['avg_time_ms']/1000:.1f} сек/док")
        print(f"   📊 Медиана: {m['median_time_ms']/1000:.1f} сек/док")
        print(f"   📊 P95: {m['p95_time_ms']/1000:.1f} сек/док")
        print(f"   📊 Min/Max: {m['min_time_ms']/1000:.1f} / {m['max_time_ms']/1000:.1f} сек")
        print(f"   🏆 Winner found: {m['winner_found']}/{m['success']} ({m['winner_rate']}%)")
        print(f"   ⚠️  HTTP 429: {m['http_429_count']} | Timeout: {m['http_timeout_count']} | Other: {m['other_errors']}")

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
    elif speedup >= 1.5:
        print(f"✅ ОТЛИЧНОЕ ускорение ({speedup:.2f}x)!")
        print("   Рекомендация: max_concurrent=10 — ИСПОЛЬЗОВАТЬ В ПРОДАКШЕНЕ")
    elif speedup >= 1.2:
        print(f"✅ Хорошее ускорение ({speedup:.2f}x)")
        print("   Рекомендация: max_concurrent=10 приемлемо для продакшена")
    elif speedup >= 1.1:
        print(f"✅ Умеренное ускорение ({speedup:.2f}x)")
        print("   Рекомендация: max_concurrent=10 можно использовать")
    else:
        print(f"⚠️  Незначительное ускорение ({speedup:.2f}x)")
        print("   Рекомендация: возможно API уже работает на пределе")

    print("=" * 70)


async def main():
    """Главная функция."""
    settings = get_settings()

    print("=" * 70)
    print(f"{'ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ НА РЕАЛЬНЫХ ДОКУМЕНТАХ':^70}")
    print("=" * 70)

    # Получить документы с содержанием
    sample_size = 20
    unit_ids = await get_sample_with_content(sample_size)

    if not unit_ids:
        logger.error("Не удалось найти документы с содержанием!")
        return

    logger.info(f"\nВыбрано документов для теста: {len(unit_ids)}")

    # Перемешиваем для случайности
    random.shuffle(unit_ids)

    # Тест 1: max_concurrent=4 (baseline)
    print("\n" + "="*70)
    print("ТЕСТ 1: Baseline (max_concurrent=4)")
    print("="*70)

    metrics_baseline = await run_test(
        unit_ids=unit_ids,
        max_concurrent=4,
        test_name="Baseline",
        settings=settings
    )

    # Пауза перед вторым тестом
    print("\n⏳ Пауза 5 секунд перед вторым тестом...")
    await asyncio.sleep(5)

    # Тест 2: max_concurrent=10 (optimized)
    print("\n" + "="*70)
    print("ТЕСТ 2: Optimized (max_concurrent=10)")
    print("="*70)

    metrics_optimized = await run_test(
        unit_ids=unit_ids,
        max_concurrent=10,
        test_name="Optimized",
        settings=settings
    )

    # Сравнение
    print_comparison(metrics_baseline, metrics_optimized)

    # Сохранить результаты
    results_file = Path("/home/pak/llm_qa_service/performance_test_results.json")
    results = {
        "timestamp": datetime.now().isoformat(),
        "sample_size": len(unit_ids),
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
