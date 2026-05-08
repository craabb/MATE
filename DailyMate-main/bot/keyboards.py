from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить задачу", callback_data="add_task")
    builder.button(text="Мои задачи", callback_data="view_lists")
    builder.button(text="Чек-листы", callback_data="checklists")
    builder.button(text="Сводка", callback_data="daily_summary")
    builder.adjust(1)
    return builder.as_markup()

def confirm_task_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data="task_confirm")
    builder.button(text="Отмена", callback_data="task_cancel")
    return builder.as_markup()

def list_filters_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="filter_today")
    builder.button(text="На неделе", callback_data="filter_week")
    builder.button(text="Без срока", callback_data="filter_all")
    builder.button(text="В меню", callback_data="to_main_menu")
    builder.adjust(2)
    return builder.as_markup()


def task_actions_kb(task_id: int, current_status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if current_status == "pending":
        builder.button(text="▶️ Начать", callback_data=f"action_start_{task_id}")
    elif current_status == "in_progress":
        builder.button(text="⏸️ Пауза", callback_data=f"action_pause_{task_id}")
    elif current_status == "paused":
        builder.button(text="▶️ Продолжить", callback_data=f"action_start_{task_id}")

    if current_status != "completed":
        builder.button(text="Завершить", callback_data=f"action_finish_{task_id}")

    builder.button(text="В меню", callback_data="to_main_menu")
    builder.adjust(1)  # Кнопки в один столбик
    return builder.as_markup()