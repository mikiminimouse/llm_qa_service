"""Gradio Web UI for LLM_qaenrich.

Provides a web interface for:
- Viewing processing results
- Filtering by status, INN presence
- Viewing document details
- Triggering INN enrichment
- Exporting data
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import gradio as gr
import pandas as pd
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


# Configuration from environment
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://admin:password@localhost:27018/?authSource=admin"
)
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "docling_metadata")
MONGO_QA_COLLECTION = os.getenv("MONGO_QA_COLLECTION", "qa_results")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001")


class QAResultsViewer:
    """Viewer for QA processing results."""

    def __init__(self, mongo_uri: str, database: str, collection: str):
        """Initialize the viewer."""
        self.mongo_uri = mongo_uri
        self.database = database
        self.collection = collection
        self._client: Optional[AsyncIOMotorClient] = None

    async def _get_client(self) -> AsyncIOMotorClient:
        """Get MongoDB client."""
        if self._client is None:
            self._client = AsyncIOMotorClient(self.mongo_uri)
        return self._client

    async def close(self):
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None

    async def get_all_results(self) -> list[dict]:
        """Get all QA results from MongoDB."""
        client = await self._get_client()
        db = client[self.database]
        collection = db[self.collection]

        cursor = collection.find({}, {
            "_id": 0,
            "unit_id": 1,
            "winner_found": 1,
            "result.winners": 1,
            "result.procurement": 1,  # Добавляем для номера закупки
            "result.flags": 1,
            "source_file": 1,
            "processed_at": 1,
            "processing_time_ms": 1,
            "model_used": 1,
            "error": 1,
        })
        results = await cursor.to_list(length=None)
        return results

    async def get_result(self, unit_id: str) -> Optional[dict]:
        """Get specific QA result by unit_id."""
        client = await self._get_client()
        db = client[self.database]
        collection = db[self.collection]

        result = await collection.find_one({"unit_id": unit_id}, {
            "_id": 0,
            "unit_id": 1,
            "winner_found": 1,
            "result.winners": 1,
            "result.procurement": 1,  # Добавляем для номера закупки
            "result.flags": 1,
            "result.customer": 1,
            "result.document": 1,
            "result.reasoning": 1,
            "source_file": 1,
            "processed_at": 1,
            "processing_time_ms": 1,
            "model_used": 1,
            "error": 1,
        })
        return result

    async def get_stats(self) -> dict:
        """Get processing statistics."""
        client = await self._get_client()
        db = client[self.database]
        collection = db[self.collection]

        total = await collection.count_documents({})
        winner_found = await collection.count_documents({"winner_found": True})
        not_found = await collection.count_documents({"winner_found": False})
        # Use $nin for proper "not in" logic
        errors = await collection.count_documents({"error": {"$nin": [None, ""]}})

        # Count with INN - check for string type (non-empty INN values)
        with_inn = await collection.count_documents({
            "winner_found": True,
            "result.winners.0.inn": {"$type": "string", "$ne": ""}
        })

        return {
            "total": total,
            "winner_found": winner_found,
            "not_found": not_found,
            "errors": errors,
            "with_inn": with_inn,
            "inn_percentage": round(with_inn / winner_found * 100, 1) if winner_found > 0 else 0,
        }


# Global viewer instance
_viewer: Optional[QAResultsViewer] = None


def get_viewer() -> QAResultsViewer:
    """Get or create viewer instance."""
    global _viewer
    if _viewer is None:
        _viewer = QAResultsViewer(MONGO_URI, MONGO_DATABASE, MONGO_QA_COLLECTION)
    return _viewer


def format_results_for_table(results: list[dict]) -> pd.DataFrame:
    """Format results for Gradio table display."""
    if not results:
        return pd.DataFrame(columns=[
            "№ Закупки", "Победитель", "ИНН", "Цена", "Статус"
        ])

    rows = []
    for r in results:
        winner_name = "Не найден"
        winner_inn = ""
        contract_price = ""
        status = "Не найден"

        # Получаем номер закупки — только валидные (11 цифр, формат 223-ФЗ)
        procurement = r.get("result", {}).get("procurement", {})
        purchase_number = "—"  # По умолчанию

        # Проверяем purchase_notice_number (приоритет)
        pn = procurement.get("purchase_notice_number")
        if pn and isinstance(pn, str) and len(pn) == 11 and pn.isdigit():
            purchase_number = pn
        else:
            # Fallback на purchase_number только если валидный
            raw = procurement.get("purchase_number")
            if raw and isinstance(raw, str) and len(raw) == 11 and raw.isdigit():
                purchase_number = raw

        if r.get("winner_found") and r.get("result", {}).get("winners"):
            winners = r["result"]["winners"]
            if winners:
                w = winners[0]
                winner_name = w.get("name", "Неизвестно")[:50]
                winner_inn = w.get("inn", "")
                contract_price = str(w.get("contract_price", "")) or ""
                status = "Найден"

        rows.append({
            "№ Закупки": purchase_number,
            "Победитель": winner_name,
            "ИНН": winner_inn or "—",
            "Цена": contract_price[:20] if contract_price else "—",
            "Статус": status,
        })

    return pd.DataFrame(rows)


def format_result_details(result: dict) -> str:
    """Format result details for display."""
    if not result:
        return "Результат не найден"

    lines = [
        f"## Unit ID: {result.get('unit_id', 'N/A')}",
        "",
        f"**Обработано:** {result.get('processed_at', 'N/A')}",
        f"**Модель:** {result.get('model_used', 'N/A')}",
        f"**Время обработки:** {result.get('processing_time_ms', 0)} мс",
        f"**Источник:** {result.get('source_file', 'N/A')}",
        "",
    ]

    if result.get("error"):
        lines.extend([
            "## ❌ Ошибка",
            f"``{result.get('error')}``",
            ""
        ])

    extraction = result.get("result", {})
    lines.extend([
        f"## Победитель найден: {'Да ✅' if result.get('winner_found') else 'Нет ❌'}",
        ""
    ])

    # Winners
    winners = extraction.get("winners", [])
    if winners:
        lines.append("### Победители:")
        for i, w in enumerate(winners, 1):
            lines.append(f"#### {i}. {w.get('name', 'Неизвестно')}")
            if w.get("inn"):
                lines.append(f"- **ИНН:** `{w.get('inn')}`")
            if w.get("kpp"):
                lines.append(f"- **КПП:** `{w.get('kpp')}`")
            if w.get("ogrn"):
                lines.append(f"- **ОГРН:** `{w.get('ogrn')}`")
            if w.get("address"):
                lines.append(f"- **Адрес:** {w.get('address')}")
            if w.get("contract_price"):
                lines.append(f"- **Цена контракта:** {w.get('contract_price')}")
            lines.append("")

    # Procurement info
    procurement = extraction.get("procurement", {})
    if procurement:
        lines.append("### Информация о закупке:")
        if procurement.get("number"):
            lines.append(f"- **Номер:** {procurement.get('number')}")
        if procurement.get("name"):
            lines.append(f"- **Наименование:** {procurement.get('name')}")
        if procurement.get("initial_price"):
            lines.append(f"- **Начальная цена:** {procurement.get('initial_price')}")
        if procurement.get("status"):
            lines.append(f"- **Статус:** {procurement.get('status')}")
        lines.append("")

    # Flags
    flags = extraction.get("flags", {})
    if flags:
        flag_items = [f"- **{k}:** {v}" for k, v in flags.items() if v]
        if flag_items:
            lines.append("### Флаги:")
            lines.extend(flag_items)
            lines.append("")

    # Reasoning
    if extraction.get("reasoning"):
        lines.extend([
            "### Анализ LLM:",
            extraction.get("reasoning"),
            ""
        ])

    return "\n".join(lines)


# Gradio interface functions

async def load_data(refresh: bool = False) -> tuple[pd.DataFrame, str]:
    """Load all results for display."""
    viewer = get_viewer()
    results = await viewer.get_all_results()
    stats = await viewer.get_stats()

    df = format_results_for_table(results)

    stats_text = f"""## 📊 Статистика

| Метрика | Значение |
|---------|----------|
| Всего документов | {stats['total']} |
| Победителей найдено | {stats['winner_found']} ({round(stats['winner_found']/stats['total']*100) if stats['total'] else 0}%) |
| Не найдено | {stats['not_found']} |
| Ошибок | {stats['errors']} |
| С ИНН | {stats['with_inn']} ({stats['inn_percentage']}%) |
"""

    return df, stats_text


async def show_details(unit_id: str) -> str:
    """Show details for selected unit_id."""
    if not unit_id:
        return "Выберите документ из таблицы"

    viewer = get_viewer()
    result = await viewer.get_result(unit_id)
    return format_result_details(result)


async def filter_results(
    status_filter: str,
    search_query: str,
) -> tuple[pd.DataFrame, str]:
    """Filter results based on criteria."""
    viewer = get_viewer()
    all_results = await viewer.get_all_results()

    filtered = []
    for r in all_results:
        # Status filter
        if status_filter == "С ИНН":
            if not r.get("result", {}).get("winners"):
                continue
            has_inn = any(
                w.get("inn") for w in r["result"]["winners"]
            )
            if not has_inn:
                continue
        elif status_filter == "Без ИНН":
            if not r.get("result", {}).get("winners"):
                continue
            has_inn = any(
                w.get("inn") for w in r["result"]["winners"]
            )
            if has_inn:
                continue
        elif status_filter == "Победитель найден":
            if not r.get("winner_found"):
                continue
        elif status_filter == "Победитель не найден":
            if r.get("winner_found"):
                continue

        # Search query
        if search_query:
            search_lower = search_query.lower()
            # Search in winner names
            found = False
            for w in r.get("result", {}).get("winners", []):
                if search_lower in w.get("name", "").lower():
                    found = True
                    break
                if search_lower in w.get("inn", ""):
                    found = True
                    break
            if not found:
                continue

        filtered.append(r)

    df = format_results_for_table(filtered)
    stats = await viewer.get_stats()

    stats_text = f"""## 📊 Статистика (отфильтровано: {len(filtered)})

| Метрика | Значение |
|---------|----------|
| Всего документов | {stats['total']} |
| Победителей найдено | {stats['winner_found']} |
| С ИНН | {stats['with_inn']} ({stats['inn_percentage']}%) |
"""

    return df, stats_text


async def export_csv() -> str:
    """Export results to CSV."""
    viewer = get_viewer()
    results = await viewer.get_all_results()
    df = format_results_for_table(results)

    filename = f"/tmp/qa_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(filename, index=False)
    return filename


def create_ui() -> gr.Blocks:
    """Create Gradio UI."""

    with gr.Blocks(
        title="LLM QA Service - Результаты извлечения",
    ) as app:

        gr.Markdown("# 🔍 LLM QA Service - Результаты извлечения")
        gr.Markdown("Сервис для извлечения информации о победителях закупок")

        # Кнопки управления
        with gr.Row():
            refresh_btn = gr.Button("🔄 Обновить все", variant="primary")
            export_btn = gr.Button("📥 Экспорт в CSV")

        # Статистика
        stats_display = gr.Markdown("Загрузка...")

        # Вкладки для разных категорий
        with gr.Tabs() as tabs:
            # Все документы
            with gr.Tab("📋 Все документы"):
                all_table = gr.Dataframe(
                    label="Все обработанные документы",
                    interactive=False,
                    wrap=True,
                )
                all_selected = gr.Textbox(
                    label="Unit ID для деталей",
                    visible=False,
                )
                all_details_btn = gr.Button("📄 Показать детали", size="sm")
                all_details = gr.Markdown("Выберите документ для просмотра деталей")

            # С ИНН (успешное извлечение)
            with gr.Tab("✅ С ИНН"):
                inn_table = gr.Dataframe(
                    label="Документы с извлечённым ИНН",
                    interactive=False,
                    wrap=True,
                )
                inn_selected = gr.Textbox(
                    label="Unit ID для деталей",
                    visible=False,
                )
                inn_details_btn = gr.Button("📄 Показать детали", size="sm")
                inn_details = gr.Markdown("Выберите документ для просмотра деталей")

            # Без ИНН (требуют внимания)
            with gr.Tab("⚠️ Без ИНН"):
                no_inn_table = gr.Dataframe(
                    label="Документы без ИНН (требуют внимания)",
                    interactive=False,
                    wrap=True,
                )
                no_inn_selected = gr.Textbox(
                    label="Unit ID для деталей",
                    visible=False,
                )
                no_inn_details_btn = gr.Button("📄 Показать детали", size="sm")
                no_inn_details = gr.Markdown("Выберите документ для просмотра деталей")

            # Победитель не найден
            with gr.Tab("❌ Победитель не найден"):
                not_found_table = gr.Dataframe(
                    label="Документы где победитель не найден",
                    interactive=False,
                    wrap=True,
                )
                not_found_selected = gr.Textbox(
                    label="Unit ID для деталей",
                    visible=False,
                )
                not_found_details_btn = gr.Button("📄 Показать детали", size="sm")
                not_found_details = gr.Markdown("Выберите документ для просмотра деталей")

        # Поиск
        with gr.Row():
            search_query = gr.Textbox(
                label="🔍 Поиск по названию или ИНН",
                placeholder="Введите для поиска...",
                scale=3,
            )
            search_btn = gr.Button("Найти", variant="secondary", scale=1)

        search_results = gr.Dataframe(
            label="Результаты поиска",
            interactive=False,
            wrap=True,
            visible=False,
        )

        # Event handlers - обновление данных
        async def load_all_tabs():
            """Load data for all tabs."""
            viewer = get_viewer()
            all_results = await viewer.get_all_results()
            stats = await viewer.get_stats()

            # Подготовка данных для каждой вкладки
            all_df = format_results_for_table(all_results)

            # С ИНН
            with_inn = [r for r in all_results if r.get("winner_found")
                        and r.get("result", {}).get("winners")
                        and any(w.get("inn") for w in r["result"]["winners"])]
            inn_df = format_results_for_table(with_inn)

            # Без ИНН
            without_inn = [r for r in all_results if r.get("winner_found")
                           and r.get("result", {}).get("winners")
                           and not any(w.get("inn") for w in r["result"]["winners"])]
            no_inn_df = format_results_for_table(without_inn)

            # Победитель не найден
            not_found = [r for r in all_results if not r.get("winner_found")]
            not_found_df = format_results_for_table(not_found)

            stats_text = f"""## 📊 Общая статистика

| Метрика | Значение |
|---------|----------|
| Всего документов | {stats['total']} |
| Победителей найдено | {stats['winner_found']} ({stats['winner_found']/stats['total']*100:.1f}%) |
| ✅ С ИНН | {stats['with_inn']} ({stats['inn_percentage']}%) |
| ⚠️ Без ИНН | {len(without_inn)} |
| ❌ Победитель не найден | {stats['not_found']} |
| Ошибок | {stats['errors']} |
"""

            return (
                all_df, inn_df, no_inn_df, not_found_df,
                stats_text,
                gr.update(visible=False),  # hide search results
            )

        # Refresh button - Gradio 4+ supports async functions directly
        refresh_btn.click(
            fn=load_all_tabs,
            outputs=[
                all_table, inn_table, no_inn_table, not_found_table,
                stats_display, search_results
            ],
        )

        # Search function
        async def do_search(query: str):
            """Search by name or INN."""
            if not query:
                return None, gr.update(visible=False)

            viewer = get_viewer()
            all_results = await viewer.get_all_results()

            search_lower = query.lower()
            filtered = []
            for r in all_results:
                for w in r.get("result", {}).get("winners", []):
                    if search_lower in w.get("name", "").lower():
                        filtered.append(r)
                        break
                    if search_lower in w.get("inn", ""):
                        filtered.append(r)
                        break

            df = format_results_for_table(filtered)
            return df, gr.update(visible=True) if df is not None and len(df) > 0 else None, gr.update(visible=False)

        search_btn.click(
            fn=do_search,
            inputs=[search_query],
            outputs=[search_results, search_results, search_results],
        )

        # Details buttons helper
        async def show_details_for_tab(unit_id: str) -> str:
            """Show details for selected unit_id."""
            if not unit_id:
                return "Выберите документ из таблицы"
            viewer = get_viewer()
            result = await viewer.get_result(unit_id)
            return format_result_details(result)

        # Connect details buttons for each tab
        for tab_items in [
            (all_table, all_selected, all_details_btn, all_details),
            (inn_table, inn_selected, inn_details_btn, inn_details),
            (no_inn_table, no_inn_selected, no_inn_details_btn, no_inn_details),
            (not_found_table, not_found_selected, not_found_details_btn, not_found_details),
        ]:
            table, selected, btn, details = tab_items
            table.select(
                fn=lambda evt: evt[0] if evt and len(evt) > 0 else "",
                inputs=[gr.State()],
                outputs=[selected],
            )
            btn.click(
                fn=show_details_for_tab,
                inputs=[selected],
                outputs=[details],
            )

        # Export button
        export_btn.click(
            fn=export_csv,
            outputs=[gr.File()],
        )

        # Load initial data
        app.load(
            fn=load_all_tabs,
            outputs=[
                all_table, inn_table, no_inn_table, not_found_table,
                stats_display, search_results
            ],
        )

    return app


def main():
    """Run Gradio app."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Gradio UI...")

    app = create_ui()

    # Launch Gradio
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=gr.themes.Soft(),
        css="""
        .stat-card {background: #f8f9fa; padding: 1rem; border-radius: 8px;}
        .winner-found {color: #10b981;}
        .winner-not-found {color: #ef4444;}
        .inn-has {color: #059669;}
        .inn-missing {color: #d97706;}
        """,
    )


if __name__ == "__main__":
    main()
