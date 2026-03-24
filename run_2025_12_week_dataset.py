#!/usr/bin/env python3
"""Обработка датасета за неделю 2025-12-03 ... 2025-12-09."""

import asyncio
import time
from datetime import datetime
from pathlib import Path

from infrastructure.loaders.mongo_loader import MongoContextLoader
from application.orchestrator import QAOrchestrator
from infrastructure.llm import create_llm_client
from infrastructure.repositories.mongo_qa_repository import MongoQARepository
from infrastructure.prompt_manager import PromptManager
from config.settings import get_settings


# Файл с предварительно подготовленным списком unit_ids
UNIT_IDS_FILE = "/home/pak/projects/LLM_qaenrich/unit_ids_2025_12_03_2025_12_09.txt"


def load_unit_ids(filepath: str) -> list[str]:
    """Загрузить unit_ids из файла."""
    with open(filepath) as f:
        return [line.strip() for line in f.readlines() if line.strip()]


async def print_progress(current: int, total: int, start_time: float):
    """Вывести прогресс обработки."""
    elapsed = time.time() - start_time
    eta = elapsed / current * (total - current) if current > 0 else 0

    print(f[
        "Прогресс: {current}/{total} ({current*100//total}%) | "
        f"Прошло: {elapsed//60:.0f} мин | "
        f"Осталось: ~{eta//60:.0f} мин"
    ], end='\r', flush=True)


async def run_test():
    """Полный тест датасета за неделю."""

    print("=" * 70)
    print(f" ТЕСТ ДАТАСЕТА: 2025-12-03 ... 2025-12-09")
    print(f" Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    settings = get_settings()

    # Загрузка unit_ids из файла
    print(f"\n[1/5] Загрузка списка документов...")
    print(f"      Файл: {UNIT_IDS_FILE}")

    try:
        unit_ids = load_unit_ids(UNIT_IDS_FILE)
    except FileNotFoundError:
        print(f"      ✗ Файл не найден!")
        return

    print(f"      ✓ Загружено {len(unit_ids)} unit_ids")

    # Создание компонентов
    print(f"\n[2/5] Инициализация компонентов...")

    llm_client = create_llm_client(
        provider="zhipu",
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_BASE_URL,
        model=settings.GLM_MODEL,
        timeout=settings.GLM_TIMEOUT,
        max_retries=settings.GLM_MAX_RETRIES,
        retry_delay=settings.GLM_RETRY_DELAY,
    )
    print(f"      ✓ LLM клиент: {settings.GLM_MODEL}")

    context_loader = MongoContextLoader(
        mongo_uri=settings.MONGO_URI,
        database=settings.MONGO_DATABASE,
        collection=settings.MONGO_PROTOCOLS_COLLECTION,
    )
    print(f"      ✓ Контекст лоадер: {settings.MONGO_DATABASE}.{settings.MONGO_PROTOCOLS_COLLECTION}")

    repository = MongoQARepository(
        mongo_uri=settings.MONGO_URI,
        database=settings.MONGO_DATABASE,
        collection=settings.MONGO_QA_COLLECTION,
    )
    print(f"      ✓ Репозиторий: {settings.MONGO_DATABASE}.{settings.MONGO_QA_COLLECTION}")

    prompt_manager = PromptManager(prompts_dir=settings.PROMPTS_DIR)
    print(f"      ✓ Промпт менеджер: {settings.PROMPTS_DIR}")

    # Проверка уже обработанных
    print(f"\n[3/5] Проверка уже обработанных документов...")
    already_processed = 0
    for uid in unit_ids:
        if await repository.exists(uid):
            already_processed += 1

    to_process = len(unit_ids) - already_processed
    print(f"      Всего: {len(unit_ids)}")
    print(f"      Уже обработано: {already_processed}")
    print(f"      К обработке: {to_process}")

    if to_process == 0:
        print(f"\n      Все документы уже обработаны!")
        await llm_client.close()
        await context_loader.close()
        await repository.close()
        return

    # Создание оркестратора
    orchestrator = QAOrchestrator(
        llm_client=llm_client,
        context_loader=context_loader,
        repository=repository,
        prompt_manager=prompt_manager,
        skip_processed=True,  # Пропускать уже обработанные
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
    )

    # Обработка
    print(f"\n[4/5] Обработка {to_process} документов...")
    print(f"      Параметры: max_concurrent=3, retry_enabled=true")
    print(f"      Промпты: {settings.PROMPT_VERSION}")
    print()

    start_time = time.time()
    last_progress_time = start_time

    # Обёртка для отслеживания прогресса
    async def process_with_progress():
        results = await orchestrator.process_batch_parallel_with_retry(
            unit_ids=unit_ids,
            max_concurrent=3,
            retry_failed=True,
            retry_delay_seconds=30,
        )
        return results

    # Запуск обработки
    results = await process_with_progress()

    total_time = time.time() - start_time

    # Статистика
    print(f"\n{'=' * 70}")
    print(f"[5/5] ФИНАЛЬНАЯ СТАТИСТИКА")
    print(f"{'=' * 70}")

    stats = await orchestrator.get_stats()

    print(f"\nОбщая статистика:")
    print(f"  Всего документов:       {stats.get('total', 0)}")
    print(f"  Победителей найдено:   {stats.get('winner_found', 0)}")
    print(f"  Без победителя:        {stats.get('winner_not_found', 0)}")
    print(f"  Служебные файлы:       {stats.get('service_files', 0)}")
    print(f"  С ошибками:            {stats.get('with_errors', 0)}")

    # Статистика по трейсингу
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    qa_collection = db[settings.MONGO_QA_COLLECTION]

    with_reg_number = await qa_collection.count_documents({
        "registration_number": {"$exists": True, "$ne": None}
    })
    with_trace = await qa_collection.count_documents({
        "trace": {"$exists": True}
    })
    with_history = await qa_collection.count_documents({
        "history": {"$exists": True, "$ne": []}
    })
    with_inn = await qa_collection.count_documents({
        "winner_found": True,
        "winner_inn": {"$exists": True, "$ne": None}
    })

    print(f"\nСтатистика трейсинга:")
    print(f"  С registration_number: {with_reg_number}")
    print(f"  С trace:                {with_trace}")
    print(f"  С history:              {with_history}")

    print(f"\nСтатистика по ИНН:")
    print(f"  С ИНН:                  {with_inn}")

    if stats.get('winner_found', 0) > 0:
        inn_rate = (with_inn / stats.get('winner_found', 1)) * 100
        success_rate = (stats.get('winner_found', 0) / stats.get('total', 1)) * 100
        print(f"  Успешность извлечения: {success_rate:.1f}%")
        print(f"  Извлечение ИНН:       {inn_rate:.1f}% от победителей")

    # Время
    print(f"\nПроизводительность:")
    print(f"  Общее время:           {total_time:.1f} сек ({total_time/60:.1f} мин)")
    print(f"  Среднее время/док:     {total_time/len(unit_ids):.1f} сек")

    # Детальная информация о нескольких документах
    print(f"\nПримеры записей с трейсингом:")
    sample = await qa_collection.find({"trace": {"$exists": True}}).to_list(3)
    for i, doc in enumerate(sample, 1):
        print(f"  [{i}] {doc.get('unit_id')}")
        print(f"      registration_number: {doc.get('registration_number')}")
        print(f"      trace.component: {doc.get('trace', {}).get('component')}")
        print(f"      history events: {len(doc.get('history', []))}")

    await client.close()

    # Cleanup
    await llm_client.close()
    await context_loader.close()
    await repository.close()

    print(f"\n{'=' * 70}")
    print(f" ТЕСТ ЗАВЕРШЁН")
    print(f" Время окончания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(run_test())
