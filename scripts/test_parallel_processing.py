#!/usr/bin/env python3
"""
Скрипт тестирования параллельной обработки документов.

Запускает тесты с разным количеством параллельных потоков
и сравнивает результаты с baseline (последовательной обработкой).
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import psutil

# Добавляем корневую директорию проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ParallelProcessingTester:
    """Класс для тестирования параллельной обработки."""

    def __init__(
        self,
        api_url: str = "http://localhost:8001",
        mongo_uri: str = "mongodb://admin:password@localhost:27018/?authSource=admin",
        mongo_db: str = "docling_metadata",
    ):
        self.api_url = api_url.rstrip("/")
        self.mongo_uri = mongo_uri
        self.mongo_db = mongo_db
        self.results_dir = PROJECT_ROOT / "test_results"
        self.results_dir.mkdir(exist_ok=True)

    async def get_unit_ids(self, limit: int = 100) -> list[str]:
        """Получить список unit_id для тестирования."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.api_url}/api/v1/qa/documents",
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()

    async def clear_qa_results(self) -> int:
        """Очистить коллекцию qa_results через MongoDB."""
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(self.mongo_uri)
        db = client[self.mongo_db]
        result = await db.qa_results.delete_many({})
        deleted_count = result.deleted_count
        client.close()
        return deleted_count

    async def run_parallel_test(
        self,
        unit_ids: list[str],
        max_concurrent: int,
        test_name: str,
    ) -> dict:
        """Запустить тест параллельной обработки."""
        print(f"\n{'='*60}")
        print(f"Запуск теста: {test_name} (max_concurrent={max_concurrent})")
        print(f"Документов: {len(unit_ids)}")
        print(f"{'='*60}")

        # Очищаем qa_results перед тестом
        deleted = await self.clear_qa_results()
        print(f"Очищено записей qa_results: {deleted}")

        # Мониторинг ресурсов
        cpu_samples = []
        memory_samples = []
        monitoring = True

        async def monitor_resources():
            while monitoring:
                cpu_samples.append(psutil.cpu_percent(interval=1))
                memory_samples.append(psutil.virtual_memory().percent)
                await asyncio.sleep(5)

        # Запускаем мониторинг в фоне
        monitor_task = asyncio.create_task(monitor_resources())

        start_time = time.time()

        async with httpx.AsyncClient(timeout=3600.0) as client:
            response = await client.post(
                f"{self.api_url}/api/v1/qa/process/batch-parallel",
                json={
                    "unit_ids": unit_ids,
                    "max_concurrent": max_concurrent,
                    "continue_on_error": True,
                },
            )
            response.raise_for_status()
            result = response.json()

        total_time = time.time() - start_time

        # Останавливаем мониторинг
        monitoring = False
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # Статистика ресурсов
        cpu_avg = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
        cpu_max = max(cpu_samples) if cpu_samples else 0
        mem_avg = sum(memory_samples) / len(memory_samples) if memory_samples else 0
        mem_max = max(memory_samples) if memory_samples else 0

        test_result = {
            "test_name": test_name,
            "max_concurrent": max_concurrent,
            "total_documents": len(unit_ids),
            "total_time_seconds": round(total_time, 2),
            "avg_time_per_doc_ms": round(total_time * 1000 / len(unit_ids), 0),
            "success": result.get("success", 0),
            "skipped": result.get("skipped", 0),
            "failed": result.get("failed", 0),
            "cpu_avg_percent": round(cpu_avg, 1),
            "cpu_max_percent": round(cpu_max, 1),
            "memory_avg_percent": round(mem_avg, 1),
            "memory_max_percent": round(mem_max, 1),
            "timestamp": datetime.now().isoformat(),
        }

        print(f"\nРезультаты теста {test_name}:")
        print(f"  Общее время: {test_result['total_time_seconds']} сек ({test_result['total_time_seconds']/60:.1f} мин)")
        print(f"  Среднее время/документ: {test_result['avg_time_per_doc_ms']} мс")
        print(f"  Успешных: {test_result['success']}")
        print(f"  Пропущено: {test_result['skipped']}")
        print(f"  Ошибок: {test_result['failed']}")
        print(f"  CPU avg/max: {test_result['cpu_avg_percent']}% / {test_result['cpu_max_percent']}%")
        print(f"  Memory avg/max: {test_result['memory_avg_percent']}% / {test_result['memory_max_percent']}%")

        return test_result

    def calculate_speedup(self, baseline_time: float, parallel_time: float, num_threads: int) -> dict:
        """Рассчитать ускорение и эффективность."""
        speedup = baseline_time / parallel_time if parallel_time > 0 else 0
        efficiency = (speedup / num_threads) * 100 if num_threads > 0 else 0

        return {
            "speedup": round(speedup, 2),
            "efficiency_percent": round(efficiency, 1),
        }

    def generate_report(self, results: list[dict], baseline_time: Optional[float] = None) -> str:
        """Сгенерировать сравнительный отчёт."""
        report_lines = [
            "",
            "=" * 70,
            "СРАВНИТЕЛЬНЫЙ АНАЛИЗ ПАРАЛЛЕЛЬНОЙ ОБРАБОТКИ",
            "=" * 70,
            "",
        ]

        # Если есть baseline в результатах
        baseline_result = next((r for r in results if r.get("max_concurrent") == 1), None)
        if baseline_result:
            baseline_time = baseline_result["total_time_seconds"]

        # Используем переданный baseline_time, если он есть
        if baseline_time is None and baseline_result:
            baseline_time = baseline_result["total_time_seconds"]

        # Если baseline_time всё ещё None, используем оценку из плана (~56 мин = 3360 сек)
        if baseline_time is None:
            baseline_time = 3360  # ~56 минут из baseline
            report_lines.append(f"BASELINE (из предварительного теста):")
            report_lines.append(f"├── Общее время: {baseline_time/60:.1f} мин ({baseline_time} сек)")
            report_lines.append(f"├── Среднее время/документ: ~33843 мс")
            report_lines.append(f"└── Документов обработано: 100")
            report_lines.append("")

        for result in results:
            concurrent = result["max_concurrent"]
            total_time = result["total_time_seconds"]
            metrics = self.calculate_speedup(baseline_time, total_time, concurrent)

            report_lines.append(f"{concurrent} ПОТОК{'А' if concurrent < 5 else 'ОВ'}:")
            report_lines.append(f"├── Общее время: {total_time/60:.1f} мин ({total_time} сек)")
            report_lines.append(f"├── Среднее время/документ: {result['avg_time_per_doc_ms']} мс")
            report_lines.append(f"├── Успешных: {result['success']}")
            report_lines.append(f"├── Ошибок: {result['failed']}")
            report_lines.append(f"├── Ускорение: {metrics['speedup']}x")
            report_lines.append(f"└── Эффективность: {metrics['efficiency_percent']}%")
            report_lines.append("")

        report_lines.append("НАГРУЗКА НА СЕРВЕР:")
        for result in results:
            concurrent = result["max_concurrent"]
            report_lines.append(f"├── CPU ({concurrent} поток{'а' if concurrent < 5 else 'ов'}): avg={result['cpu_avg_percent']}%, max={result['cpu_max_percent']}%")

        report_lines.append("")
        for result in results:
            concurrent = result["max_concurrent"]
            report_lines.append(f"├── Memory ({concurrent} поток{'а' if concurrent < 5 else 'ов'}): avg={result['memory_avg_percent']}%, max={result['memory_max_percent']}%")

        report_lines.append("")
        report_lines.append("=" * 70)

        # Рекомендации
        if len(results) >= 2:
            best_result = min(results, key=lambda x: x["total_time_seconds"])
            best_concurrent = best_result["max_concurrent"]

            report_lines.append("")
            report_lines.append("РЕКОМЕНДАЦИИ:")
            report_lines.append(f"├── Оптимальное количество потоков: {best_concurrent}")

            # Проверяем, не слишком ли высокая нагрузка
            if best_result["cpu_max_percent"] > 80:
                report_lines.append(f"└── Предупреждение: высокая нагрузка на CPU ({best_result['cpu_max_percent']}%)")
            else:
                report_lines.append(f"└── Можно увеличить до {best_concurrent + 2} потоков при необходимости")

        report_lines.append("=" * 70)

        return "\n".join(report_lines)

    async def run_full_test_suite(
        self,
        num_documents: int = 100,
        thread_configs: list[int] = None,
    ) -> dict:
        """Запустить полный набор тестов."""
        if thread_configs is None:
            thread_configs = [3, 5]

        print(f"Получение списка документов (limit={num_documents})...")
        unit_ids = await self.get_unit_ids(limit=num_documents)
        print(f"Получено {len(unit_ids)} документов")

        if len(unit_ids) < num_documents:
            print(f"Внимание: доступно только {len(unit_ids)} документов")

        results = []

        for max_concurrent in thread_configs:
            test_name = f"parallel_{max_concurrent}_threads"
            result = await self.run_parallel_test(
                unit_ids=unit_ids,
                max_concurrent=max_concurrent,
                test_name=test_name,
            )
            results.append(result)

            # Пауза между тестами для стабилизации системы
            if max_concurrent != thread_configs[-1]:
                print("\nПауза 30 секунд перед следующим тестом...")
                await asyncio.sleep(30)

        # Генерация отчёта
        # Baseline time из плана: ~56 минут = 3360 секунд
        report = self.generate_report(results, baseline_time=3360)
        print(report)

        # Сохранение результатов
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.results_dir / f"parallel_test_{timestamp}.json"
        report_file = self.results_dir / f"parallel_test_{timestamp}_report.txt"

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\nРезультаты сохранены:")
        print(f"  JSON: {results_file}")
        print(f"  Отчёт: {report_file}")

        return {
            "results": results,
            "report": report,
            "results_file": str(results_file),
            "report_file": str(report_file),
        }


async def main():
    parser = argparse.ArgumentParser(description="Тестирование параллельной обработки")
    parser.add_argument(
        "--documents", "-n",
        type=int,
        default=100,
        help="Количество документов для тестирования (default: 100)",
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        nargs="+",
        default=[3, 5],
        help="Количество потоков для тестирования (default: 3 5)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8001",
        help="URL API сервиса (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Только очистить qa_results",
    )

    args = parser.parse_args()

    tester = ParallelProcessingTester(api_url=args.api_url)

    if args.clear_only:
        deleted = await tester.clear_qa_results()
        print(f"Очищено записей qa_results: {deleted}")
        return

    await tester.run_full_test_suite(
        num_documents=args.documents,
        thread_configs=args.threads,
    )


if __name__ == "__main__":
    asyncio.run(main())
