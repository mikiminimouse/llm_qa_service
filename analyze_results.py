#!/usr/bin/env python3
"""
Анализ результатов тестирования и генерация отчётов.

Считывает сохранённые метрики и генерирует детальные отчёты:
- Сводная статистика
- Анализ ошибок
- Производительность
- Качество по типам документов
- Текстовый отчёт в Markdown
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from metrics_collector import print_comparison


def load_latest_metrics(metrics_dir: Path = Path("/home/pak/llm_qa_service/metrics")) -> Dict[str, Any]:
    """Загрузить последние метрики из файлов _latest.json."""
    files = {
        "summary": metrics_dir / "summary_latest.json",
        "by_type": metrics_dir / "by_type_latest.json",
        "by_size": metrics_dir / "by_size_latest.json",
        "errors": metrics_dir / "errors_latest.json",
        "percentiles": metrics_dir / "percentiles_latest.json",
        "raw": metrics_dir / "raw_latest.json",
    }

    metrics = {}
    for name, path in files.items():
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                metrics[name] = json.load(f)

    return metrics


def load_baseline() -> Dict[str, Any]:
    """Загрузить базовые метрики для сравнения (из предыдущего теста)."""
    baseline_path = Path("/home/pak/llm_qa_service/test_concurrent_6_results.json")
    if baseline_path.exists():
        with open(baseline_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def calculate_performance_metrics(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Рассчитать дополнительные метрики производительности."""
    total = summary.get("total_documents", 0)
    duration = summary.get("duration_seconds", 0)
    success = summary.get("success", 0)

    if total == 0 or duration == 0:
        return {}

    return {
        "docs_per_minute": round(total / (duration / 60), 2),
        "minutes_per_doc": round(duration / total / 60, 2),
        "estimated_hours_for_1000": round(1000 / (total / duration) / 3600, 2),
        "success_rate": summary.get("success_rate", 0),
        "winner_rate": summary.get("winner_rate", 0),
    }


def generate_markdown_report(metrics: Dict[str, Any], output_path: Path) -> None:
    """Сгенерировать Markdown отчёт."""
    summary = metrics.get("summary", {})
    by_type = metrics.get("by_type", {})
    by_size = metrics.get("by_size", {})
    errors = metrics.get("errors", {})
    percentiles = metrics.get("percentiles", {})

    perf = calculate_performance_metrics(summary)

    report = []
    report.append("# LLM_qaenrich: Отчёт о тестировании")
    report.append(f"\n**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\n## 📊 Сводная статистика\n")

    if summary:
        report.append(f"| Метрика | Значение |")
        report.append(f"|---------|----------|")
        report.append(f"| Всего документов | {summary.get('total_documents', 0)} |")
        report.append(f"| Успешно обработано | {summary.get('success', 0)} |")
        report.append(f"| С ошибками | {summary.get('failed', 0)} |")
        report.append(f"| Пропущено | {summary.get('skipped', 0)} |")
        report.append(f"| Успешность | {summary.get('success_rate', 0)}% |")
        report.append(f"| Время выполнения | {summary.get('duration_seconds', 0)/60:.1f} мин |")
        report.append(f"| Пропускная способность | {summary.get('throughput_per_sec', 0)} док/сек |")
        report.append(f"| Среднее время | {summary.get('avg_time_ms', 0)/1000:.1f} сек/док |")
        report.append(f"| Медиана времени | {summary.get('median_time_ms', 0)/1000:.1f} сек/док |")
        report.append(f"| Winner найден | {summary.get('winner_found', 0)}/{summary.get('success', 1)} ({summary.get('winner_rate', 0)}%) |")

        if perf:
            report.append(f"\n### Производительность\n")
            report.append(f"| Метрика | Значение |")
            report.append(f"|---------|----------|")
            report.append(f"| Док/минута | {perf.get('docs_per_minute', 0)} |")
            report.append(f"| Мин/документ | {perf.get('minutes_per_doc', 0)} |")
            report.append(f"| Оценка для 1000 док | {perf.get('estimated_hours_for_1000', 0)} часов |")

    if percentiles:
        report.append(f"\n### Процентили времени обработки\n")
        report.append(f"| Процентиль | Время (мс) | Время (сек) |")
        report.append(f"|------------|------------|-------------|")
        report.append(f"| p50 | {percentiles.get('p50', 0)} | {percentiles.get('p50', 0)/1000:.1f} |")
        report.append(f"| p75 | {percentiles.get('p75', 0)} | {percentiles.get('p75', 0)/1000:.1f} |")
        report.append(f"| p90 | {percentiles.get('p90', 0)} | {percentiles.get('p90', 0)/1000:.1f} |")
        report.append(f"| p95 | {percentiles.get('p95', 0)} | {percentiles.get('p95', 0)/1000:.1f} |")
        report.append(f"| p99 | {percentiles.get('p99', 0)} | {percentiles.get('p99', 0)/1000:.1f} |")
        report.append(f"| min | {percentiles.get('min', 0)} | {percentiles.get('min', 0)/1000:.1f} |")
        report.append(f"| max | {percentiles.get('max', 0)} | {percentiles.get('max', 0)/1000:.1f} |")

    if by_type:
        report.append(f"\n## 📄 По типам документов\n")
        report.append(f"| Тип | Кол-во | Успех | Winner | Winner Rate | Сред. время |")
        report.append(f"|-----|--------|-------|--------|-------------|-------------|")
        for doc_type, stats in sorted(by_type.items()):
            report.append(
                f"| {doc_type} | {stats['count']} | {stats['success']} | "
                f"{stats['winner_found']}/{stats['success']} | {stats['winner_rate']}% | "
                f"{stats['avg_time_ms']/1000:.1f} сек |"
            )

    if by_size:
        report.append(f"\n## 📏 По размеру документов\n")
        report.append(f"| Размер | Кол-во | Успех | Winner | Winner Rate | Сред. время |")
        report.append(f"|--------|--------|-------|--------|-------------|-------------|")
        size_order = ["empty", "small", "medium", "large", "xlarge"]
        for size in size_order:
            if size in by_size:
                stats = by_size[size]
                report.append(
                    f"| {size} | {stats['count']} | {stats['success']} | "
                    f"{stats['winner_found']}/{stats['success']} | {stats['winner_rate']}% | "
                    f"{stats['avg_time_ms']/1000:.1f} сек |"
                )

    if errors and errors.get("total_errors", 0) > 0:
        report.append(f"\n## ⚠️ Ошибки\n")
        report.append(f"| Тип ошибки | Количество |")
        report.append(f"|------------|------------|")
        for err_type, count in errors.get("by_type", {}).items():
            report.append(f"| {err_type} | {count} |")

        most_common = errors.get("most_common", [])
        if most_common:
            report.append(f"\n### Частые ошибки\n")
            for err in most_common[:10]:
                report.append(f"- `{err['error']}`: {err['count']} раз")

    report.append(f"\n## 📁 Файлы метрик\n")
    report.append(f"- `/home/pak/llm_qa_service/metrics/` - все метрики")
    report.append(f"- `/home/pak/llm_qa_service/full_test_report.json` - финальный отчёт")

    report.append(f"\n---\n")
    report.append(f"*Отчёт сгенерирован автоматически LLM_qaenrich*")

    output_path.write_text("\n".join(report), encoding='utf-8')
    print(f"📁 Markdown отчёт: {output_path}")


def generate_recommendations(metrics: Dict[str, Any]) -> None:
    """Генерация рекомендаций на основе метрик."""
    summary = metrics.get("summary", {})
    by_type = metrics.get("by_type", {})
    errors = metrics.get("errors", {})

    print("\n" + "=" * 70)
    print("💡 РЕКОМЕНДАЦИИ")
    print("=" * 70)

    # По успешности
    success_rate = summary.get("success_rate", 0)
    if success_rate < 90:
        print(f"\n⚠️  Низкая успешность ({success_rate}%):")
        print("   - Проверьте логи ошибок")
        print("   - Увеличьте timeout для больших документов")
        print("   - Рассмотрите увеличение retry_delay")
    elif success_rate > 98:
        print(f"\n✅ Отличная успешность ({success_rate}%)!")

    # По winner rate
    winner_rate = summary.get("winner_rate", 0)
    if winner_rate < 50:
        print(f"\n⚠️  Низкий winner rate ({winner_rate}%):")
        print("   - Проверьте качество промптов")
        print("   - Проверьте полноту извлечения таблиц")
    elif winner_rate > 70:
        print(f"\n✅ Хороший winner rate ({winner_rate}%)!")

    # По типам документов
    print(f"\n📄 По типам документов:")
    for doc_type, stats in by_type.items():
        if stats['winner_rate'] < 50:
            print(f"   - {doc_type}: низкий winner rate ({stats['winner_rate']}%) — проверьте парсер")
        elif stats['winner_rate'] > 80:
            print(f"   - {doc_type}: отличный winner rate ({stats['winner_rate']}%)")

    # По ошибкам
    if errors.get("total_errors", 0) > 0:
        by_type_errors = errors.get("by_type", {})
        if "http_429" in by_type_errors or "rate_limited" in by_type_errors:
            print(f"\n⚠️  Обнаружены Rate Limit ошибки:")
            print("   - Уменьшите max_concurrent")
            print("   - Увеличьте retry_delay")

        if "timeout" in by_type_errors:
            print(f"\n⚠️  Обнаружены Timeout ошибки:")
            print("   - Увеличьте GLM_TIMEOUT")
            print("   - Разбивайте большие документы на части")

    print("=" * 70)


def main():
    """Главная функция."""
    print("=" * 70)
    print(f"{'АНАЛИЗ РЕЗУЛЬТАТОВ ТЕСТИРОВАНИЯ':^70}")
    print("=" * 70)

    # Загрузка метрик
    print("\n📊 Загрузка метрик...")
    metrics = load_latest_metrics()

    if not metrics:
        print("❌ Метрики не найдены! Сначала запустите тестирование.")
        return

    print(f"✅ Загружено: {', '.join(metrics.keys())}")

    # Сводка
    summary = metrics.get("summary", {})
    if summary:
        print(f"\n📊 Сводка:")
        print(f"   Документов: {summary.get('total_documents', 0)}")
        print(f"   Успешность: {summary.get('success_rate', 0)}%")
        print(f"   Winner rate: {summary.get('winner_rate', 0)}%")
        print(f"   Время: {summary.get('duration_seconds', 0)/60:.1f} мин")

    # Генерация Markdown отчёта
    report_path = Path("/home/pak/llm_qa_service/test_report.md")
    generate_markdown_report(metrics, report_path)

    # Рекомендации
    generate_recommendations(metrics)

    # Сравнение с baseline
    baseline = load_baseline()
    if baseline and "metrics" in baseline:
        baseline_metrics = baseline["metrics"]
        # Преобразуем baseline формат
        baseline_summary = {
            "throughput_per_sec": baseline_metrics.get("throughput", 0),
            "avg_time_ms": baseline_metrics.get("avg_time_ms", 0),
            "median_time_ms": baseline_metrics.get("median_time_ms", 0),
            "winner_rate": baseline_metrics.get("winner_rate", 0),
            "success_rate": 100 * (1 - baseline_metrics.get("failed", 0) / max(baseline_metrics.get("total_docs", 1), 1)),
        }
        print_comparison(baseline_summary, summary)

    # Сохранение комбинированного отчёта
    combined = {
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "by_type": metrics.get("by_type", {}),
        "by_size": metrics.get("by_size", {}),
        "errors": metrics.get("errors", {}),
        "percentiles": metrics.get("percentiles", {}),
        "performance": calculate_performance_metrics(summary),
    }

    output_path = Path("/home/pak/llm_qa_service/analysis_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
    print(f"\n📁 Комбинированный отчёт: {output_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
