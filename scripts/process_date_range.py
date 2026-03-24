#!/usr/bin/env python3
"""
Последовательная обработка диапазона дат.

Использование:
    python scripts/process_date_range.py --start 2025-12-01 --end 2025-12-31
    python scripts/process_date_range.py --start 2025-12-20 --end 2025-12-25 --dry-run
    python scripts/process_date_range.py --dates 2025-12-20,2025-12-21,2025-12-22

Для каждой даты:
1. Проверка существования директории
2. Загрузка датасета через load_dataset_by_date.py
3. Сохранение результатов
4. Логирование успехов/ошибок
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


DEFAULT_BASE_PATH = Path("/home/pak/Processing data")
LOAD_SCRIPT = Path(__file__).parent / "load_dataset_by_date.py"


def parse_dates(date_list: str) -> List[str]:
    """Парсит список дат через запятую."""
    return [d.strip() for d in date_list.split(",") if d.strip()]


def get_date_range(start_date: str, end_date: str) -> List[str]:
    """Генерирует список дат в диапазоне."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return dates


def check_directory_exists(date: str, base_path: Path) -> bool:
    """Проверяет существование директории для указанной даты."""
    data_path = base_path / date / "OutputDocling"
    return data_path.exists()


def process_date(
    date: str,
    base_path: Path,
    dry_run: bool = False,
    batch_size: int = 100
) -> dict:
    """Обрабатывает одну дату."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Обработка даты: {date}")
    logger.info(f"{'='*60}")

    # Проверка директории
    if not check_directory_exists(date, base_path):
        logger.warning(f"Директория не найдена: {base_path / date / 'OutputDocling'}")
        return {
            "date": date,
            "status": "skipped",
            "reason": "directory_not_found",
        }

    # Запуск скрипта загрузки
    cmd = [
        sys.executable,
        str(LOAD_SCRIPT),
        "--date", date,
        "--base-path", str(base_path),
        "--batch-size", str(batch_size),
    ]

    if dry_run:
        cmd.append("--dry-run")

    logger.info(f"Запуск: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 минут на дату
        )

        if result.returncode == 0:
            logger.info(f"Успешно обработано: {date}")

            # Пытаемся прочитать отчёт
            report_path = Path(f"reports/load_{date}_report.json")
            if report_path.exists():
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                load_result = report.get("load_result", {})
                return {
                    "date": date,
                    "status": "success",
                    "total": load_result.get("total", 0),
                    "new": load_result.get("new", 0),
                    "updated": load_result.get("updated", 0),
                }
            else:
                return {
                    "date": date,
                    "status": "success",
                    "reason": "report_not_found",
                }
        else:
            logger.error(f"Ошибка обработки: {date}")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            return {
                "date": date,
                "status": "error",
                "returncode": result.returncode,
                "stderr": result.stderr,
            }

    except subprocess.TimeoutExpired:
        logger.error(f"Таймаут при обработке: {date}")
        return {
            "date": date,
            "status": "timeout",
        }
    except Exception as e:
        logger.error(f"Исключение при обработке {date}: {e}")
        return {
            "date": date,
            "status": "exception",
            "error": str(e),
        }


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Последовательная обработка диапазона дат")
    parser.add_argument("--start", help="Начальная дата (YYYY-MM-DD)")
    parser.add_argument("--end", help="Конечная дата (YYYY-MM-DD)")
    parser.add_argument("--dates", help="Список дат через запятую")
    parser.add_argument("--base-path", default=str(DEFAULT_BASE_PATH), help="Базовый путь к данным")
    parser.add_argument("--dry-run", action="store_true", help="Анализ без фактической загрузки")
    parser.add_argument("--batch-size", type=int, default=100, help="Размер пачки для bulk operations")
    parser.add_argument("--stop-on-error", action="store_true", help="Остановиться при первой ошибке")
    args = parser.parse_args()

    # Определяем список дат
    dates = []
    if args.dates:
        dates = parse_dates(args.dates)
    elif args.start and args.end:
        dates = get_date_range(args.start, args.end)
    else:
        logger.error("Укажите либо --dates, либо --start и --end")
        return 1

    base_path = Path(args.base_path)

    print("\n" + "="*70)
    print(f"ПОСЛЕДОВАТЕЛЬНАЯ ОБРАБОТКА ДАТ")
    print(f"Всего дат: {len(dates)}")
    print(f"Диапазон: {dates[0]} → {dates[-1]}")
    if args.dry_run:
        print("[DRY-RUN] Анализ без фактической загрузки")
    print("="*70 + "\n")

    results = []
    success_count = 0
    error_count = 0
    skipped_count = 0

    for date in dates:
        result = process_date(date, base_path, args.dry_run, args.batch_size)
        results.append(result)

        if result["status"] == "success":
            success_count += 1
        elif result["status"] == "skipped":
            skipped_count += 1
        else:
            error_count += 1
            if args.stop_on_error:
                logger.error("Остановка из-за ошибки (--stop-on-error)")
                break

    # Итоговая статистика
    print("\n" + "="*70)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("="*70)
    print(f"Всего дат: {len(dates)}")
    print(f"Успешно: {success_count}")
    print(f"Пропущено: {skipped_count}")
    print(f"Ошибок: {error_count}")

    # Сводка по количеству
    total_new = sum(r.get("new", 0) for r in results if r["status"] == "success")
    total_updated = sum(r.get("updated", 0) for r in results if r["status"] == "success")
    print(f"\nВсего загружено: {total_new:,} новых, {total_updated:,} обновлено")

    # Сохранение отчёта
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(f"reports/process_range_{timestamp}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "base_path": str(base_path),
        "dry_run": args.dry_run,
        "date_range": {
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
            "count": len(dates),
        },
        "results": results,
        "summary": {
            "total": len(dates),
            "success": success_count,
            "skipped": skipped_count,
            "error": error_count,
            "total_new": total_new,
            "total_updated": total_updated,
        },
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nОтчёт сохранён: {report_path}")
    print("="*70 + "\n")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
