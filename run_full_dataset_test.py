#!/usr/bin/env python3
"""Полный тест датасета 2025-12-23 с промптами v4."""

import asyncio
import httpx
import time
from datetime import datetime

API_URL = "http://localhost:8001"


async def run_full_test():
    """Полный тест датасета с промптами v4."""

    print("=" * 60)
    print(f"ТЕСТ ДАТАСЕТА 2025-12-23")
    print(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Промпты: v4 (оптимизированные)")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=7200.0) as client:
        # 1. Проверить здоровье API
        print("\n=== Шаг 1: Проверка API ===")
        resp = await client.get(f"{API_URL}/api/v1/qa/health")
        health = resp.json()
        print(f"API статус: {health.get('status')}")
        print(f"MongoDB: {health.get('mongodb')}")
        print(f"LLM: {health.get('llm')}")

        # 2. Получить все unit_id
        print("\n=== Шаг 2: Получение списка документов ===")
        resp = await client.get(f"{API_URL}/api/v1/qa/documents?limit=10000")
        unit_ids = resp.json()
        print(f"Найдено документов: {len(unit_ids)}")

        if not unit_ids:
            print("Нет документов для обработки!")
            return

        # 3. Запуск пакетной обработки
        print(f"\n=== Шаг 3: Обработка {len(unit_ids)} документов ===")
        print("Параметры:")
        print(f"  - max_concurrent: 3")
        print(f"  - retry_failed: true")
        print(f"  - retry_delay_seconds: 30")
        print(f"\nОбработка... (это займёт время)")

        start_time = time.time()

        # Разобьём на пачки для мониторинга прогресса
        batch_size = 50
        all_results = []

        for i in range(0, len(unit_ids), batch_size):
            batch = unit_ids[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(unit_ids) + batch_size - 1) // batch_size

            print(f"\n--- Пачка {batch_num}/{total_batches} ({len(batch)} документов) ---")

            resp = await client.post(
                f"{API_URL}/api/v1/qa/process/batch-parallel-retry",
                json={
                    "unit_ids": batch,
                    "max_concurrent": 3,
                    "retry_failed": True,
                    "retry_delay_seconds": 30
                },
                timeout=7200.0
            )
            result = resp.json()
            all_results.extend(result.get('results', []))

            print(f"  Успех: {result.get('success')}, Ошибок: {result.get('failed')}, "
                  f"Retry: {result.get('retried')}, Восстановлено: {result.get('recovered')}")

        total_time = time.time() - start_time

        # 4. Финальная статистика
        print(f"\n=== Шаг 4: Финальная статистика ===")

        resp = await client.get(f"{API_URL}/api/v1/qa/stats")
        stats = resp.json()

        print(f"Всего документов: {stats.get('total', 0)}")
        print(f"Победителей найдено: {stats.get('winner_found', 0)}")
        print(f"Без победителя: {stats.get('winner_not_found', 0)}")
        print(f"Сервисные файлы: {stats.get('service_files', 0)}")
        print(f"С ошибками: {stats.get('with_errors', 0)}")

        if stats.get('winner_found', 0) > 0:
            success_rate = (stats.get('winner_found', 0) / stats.get('total', 1)) * 100
            print(f"\nУспешность извлечения: {success_rate:.1f}%")

        print(f"\nОбщее время: {total_time:.1f} сек ({total_time/60:.1f} мин)")
        print(f"Среднее время на документ: {total_time/len(unit_ids):.1f} сек")

        print("\n" + "=" * 60)
        print("ТЕТ ЗАВЕРШЁН")
        print("=" * 60)

        # 5. Рекомендации
        print("\n=== Следующие шаги ===")
        print("1. Проверьте результаты в Gradio UI:")
        print("   http://localhost:7860")
        print("\n2. Сгенерируйте отчёт о качестве:")
        print("   python generate_quality_report.py")


if __name__ == "__main__":
    asyncio.run(run_full_test())
