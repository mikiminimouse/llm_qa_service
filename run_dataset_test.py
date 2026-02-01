#!/usr/bin/env python3
"""Обработка всех документов из датасета."""

import asyncio
import time
from datetime import datetime

from infrastructure.loaders import MongoContextLoader
from application.orchestrator import QAOrchestrator
from infrastructure.llm import create_llm_client
from infrastructure.repositories import MongoQARepository
from infrastructure.prompt_manager import PromptManager
from config import get_settings


async def run_test():
    """Полный тест датасета."""

    print("=" * 60)
    print(f"ТЕТ ДАТАСЕТА 2025-12-23")
    print(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Промпты: v4 (оптимизированные)")
    print("=" * 60)

    settings = get_settings()

    # Создадим компоненты
    print("\n=== Инициализация ===")
    llm_client = create_llm_client(
        provider="zhipu",
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_BASE_URL,
        model=settings.GLM_MODEL,
        timeout=settings.GLM_TIMEOUT,
        max_retries=settings.GLM_MAX_RETRIES,
        retry_delay=settings.GLM_RETRY_DELAY,
    )

    context_loader = MongoContextLoader(
        mongo_uri=settings.MONGO_URI,
        database=settings.MONGO_DATABASE,
        collection=settings.MONGO_PROTOCOLS_COLLECTION,
    )

    repository = MongoQARepository(
        mongo_uri=settings.MONGO_URI,
        database=settings.MONGO_DATABASE,
        collection=settings.MONGO_QA_COLLECTION,
    )

    prompt_manager = PromptManager(prompts_dir=settings.PROMPTS_DIR)

    orchestrator = QAOrchestrator(
        llm_client=llm_client,
        context_loader=context_loader,
        repository=repository,
        prompt_manager=prompt_manager,
        skip_processed=False,  # Обрабатывать все
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
    )

    # Получим все unit_id
    print("\n=== Получение списка документов ===")
    unit_ids = await context_loader.list_unit_ids(limit=10000, skip=0)
    print(f"Найдено документов: {len(unit_ids)}")

    if not unit_ids:
        print("Нет документов для обработки!")
        return

    # Обработка с прогрессом
    print(f"\n=== Обработка {len(unit_ids)} документов ===")
    print("Параметры: max_concurrent=3, retry_enabled=true\n")

    start_time = time.time()

    results = await orchestrator.process_batch_parallel_with_retry(
        unit_ids=unit_ids,
        max_concurrent=3,
        retry_failed=True,
        retry_delay_seconds=30,
    )

    total_time = time.time() - start_time

    # Статистика
    print(f"\n=== Финальная статистика ===")

    stats = await orchestrator.get_stats()

    print(f"Всего документов: {stats.get('total', 0)}")
    print(f"Победителей найдено: {stats.get('winner_found', 0)}")
    print(f"Без победителя: {stats.get('winner_not_found', 0)}")
    print(f"Сервисные файлы: {stats.get('service_files', 0)}")

    # Подсчёт с ИНН
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_QA_COLLECTION]

    # Посчитаем с ИНН среди победителей
    winners_with_inn = await collection.count_documents({
        "winner_found": True,
        "result.winners.0.inn": {"$ne": None, "$ne": ""}
    })

    print(f"С ИНН: {winners_with_inn}")

    if stats.get('winner_found', 0) > 0:
        inn_rate = (winners_with_inn / stats.get('winner_found', 1)) * 100
        success_rate = (stats.get('winner_found', 0) / stats.get('total', 1)) * 100
        print(f"\nУспешность извлечения: {success_rate:.1f}%")
        print(f"Извлечение ИНН: {inn_rate:.1f}% от победителей")

    print(f"\nОбщее время: {total_time:.1f} сек ({total_time/60:.1f} мин)")
    print(f"Среднее время на документ: {total_time/len(unit_ids):.1f} сек")

    # Cleanup
    await llm_client.close()
    await context_loader.close()
    await repository.close()
    await client.close()

    print("\n" + "=" * 60)
    print("ТЕТ ЗАВЕРШЁН")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_test())
