import json
from datetime import datetime, timedelta
from typing import List

from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import User, Task, TaskStatus, Checklist, Reminder, ReminderStatus
from bot.keyboards import main_menu_kb, confirm_task_kb, list_filters_kb
from services import AIService

ai_service = AIService()
router = Router()


class TaskStates(StatesGroup):
    waiting_input = State()
    waiting_confirm = State()
    waiting_clarification = State()


# --- Вспомогательные клавиатуры ---
def get_task_actions_kb(task_id: int, status: str) -> InlineKeyboardMarkup:
    kb = []
    if status == "pending":
        kb.append([InlineKeyboardButton(text="▶️ Начать", callback_data=f"action_start_{task_id}")])
    elif status == "in_progress":
        kb.append([InlineKeyboardButton(text="⏸️ Пауза", callback_data=f"action_pause_{task_id}")])
    elif status == "paused":
        kb.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"action_start_{task_id}")])
    if status != "completed":
        kb.append([InlineKeyboardButton(text="✅ Завершить", callback_data=f"action_finish_{task_id}")])
    kb.append([InlineKeyboardButton(text="🔙 В меню", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def checklist_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек-лист", callback_data="checklist_create")],
        [InlineKeyboardButton(text="📋 Все чек-листы", callback_data="checklist_view_all")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="to_main_menu")]
    ])


def checklist_item_kb(checklist_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Удалить чек-лист", callback_data=f"checklist_delete_{checklist_id}")],
        [InlineKeyboardButton(text="🔙 К списку чек-листов", callback_data="checklist_view_all")]
    ])


# --- UC-01: Старт и Добавление задачи ---
@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
    user = result.scalar_one_or_none()
    user_name = message.from_user.first_name or "друг"

    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username or f"user_{message.from_user.id}",
            settings={"timezone": "UTC"}
        )
        session.add(user)
        await session.commit()
        greeting = f"Привет, {user_name}! 👋\nЯ DailyMate — твой ИИ-ассистент для задач.\nПросто напиши задачу или выбери действие:"
    else:
        greeting = f"С возвращением, {user_name}! 👋\nЯ DailyMate. Что нужно сделать сегодня?"

    await message.answer(greeting, reply_markup=main_menu_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "add_task")
async def ask_task_text(cb: CallbackQuery):
    await cb.message.answer("📝 Напиши задачу в свободной форме.\nНапример: «Завтра до 18:00 купить молоко»")
    await cb.answer()


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def process_text_input(message: Message, state: FSMContext, session: AsyncSession):
    await message.bot.send_chat_action(message.chat.id, "typing")
    user_res = await session.execute(select(User.id).where(User.telegram_id == message.from_user.id))
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id:
        await message.answer("Сначала напишите /start")
        return

    try:
        parsed_tasks = await ai_service.parse_user_request(message.text, session, user_db_id)
    except Exception as e:
        print(f"AI Error: {e}")
        parsed_tasks = None

    if not parsed_tasks:
        await state.set_state(TaskStates.waiting_clarification)
        await message.answer("⚠️ Не удалось разобрать текст. Уточни детали или напиши проще.",
                             reply_markup=main_menu_kb())
        return

    await state.update_data(parsed_tasks=[t.model_dump() for t in parsed_tasks])
    await state.set_state(TaskStates.waiting_confirm)

    resp = "Я распознал:\n\n"
    for i, t in enumerate(parsed_tasks, 1):
        resp += f"📌 {i}. {t.title or 'Без названия'}\n🕒 {t.due_date or 'Без срока'}\n📂 {t.category or 'Общее'}\n\n"
    resp += "Сохранить?"

    await message.answer(resp, reply_markup=confirm_task_kb())


@router.callback_query(TaskStates.waiting_confirm, F.data == "task_confirm")
async def save_tasks(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    tasks_data = data.get("parsed_tasks", [])

    res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_id = res.scalar_one_or_none()
    if not user_id:
        await cb.answer("❌ Ошибка пользователя", show_alert=True)
        return

    for t in tasks_data:
        session.add(Task(
            user_id=user_id,
            title=t["title"],
            description=t.get("description", ""),
            due_data=datetime.fromisoformat(t["due_date"]) if t.get("due_date") else None,
            status=TaskStatus.pending,
            priority=t.get("priority", 2),
            original_text=cb.message.text,
            ai_extraction=t
        ))

    await session.commit()
    await cb.message.edit_text(f"✅ Сохранено задач: {len(tasks_data)}", reply_markup=main_menu_kb())
    await state.clear()
    await cb.answer()


@router.callback_query(TaskStates.waiting_confirm, F.data == "task_cancel")
async def cancel_task(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Отменено.", reply_markup=main_menu_kb())
    await cb.answer()


@router.message(TaskStates.waiting_clarification)
async def manual_task_input(message: Message, state: FSMContext):
    await state.update_data(parsed_tasks=[
        {"title": message.text[:100], "due_date": None, "category": "Общее", "priority": 2, "description": ""}
    ])
    await state.set_state(TaskStates.waiting_confirm)
    await message.answer("✅ Задача принята вручную. Сохранить?", reply_markup=confirm_task_kb())


# --- UC-02: Просмотр списка ---
@router.callback_query(F.data == "view_lists")
async def show_filters(cb: CallbackQuery):
    await cb.message.edit_text("📋 Выбери период:", reply_markup=list_filters_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("filter_"))
async def show_tasks(cb: CallbackQuery, session: AsyncSession):
    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()
    if not user_db_id:
        return await cb.answer("❌ Пользователь не найден", show_alert=True)

    f_type = cb.data.split("_", 1)[1]
    now = datetime.now()
    q = select(Task).where(
        Task.user_id == user_db_id,
        Task.status.in_([TaskStatus.pending, TaskStatus.in_progress, TaskStatus.paused])
    )

    if f_type == "today":
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.where(Task.due_data >= start_today, Task.due_data < start_today + timedelta(days=1))
        filter_name = "📅 Сегодня"
    elif f_type == "week":
        q = q.where(Task.due_data >= now, Task.due_data <= now + timedelta(days=7))
        filter_name = "📆 Эта неделя"
    elif f_type == "no_date":
        q = q.where(Task.due_data.is_(None))
        filter_name = "⏳ Без срока"
    else:
        filter_name = "📂 Все задачи"

    tasks = (await session.execute(q)).scalars().all()
    if not tasks:
        await cb.message.edit_text(f"{filter_name}\n\n📭 Задач на этот период нет. Создай первую!",
                                   reply_markup=list_filters_kb())
        await cb.answer()
        return

    text = f"{filter_name}\n\nТвои задачи:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for t in tasks:
        status_icon = {"pending": "⏳", "in_progress": "▶️", "paused": "⏸️"}.get(t.status.value, "")
        due_str = t.due_data.strftime("%d.%m %H:%M") if t.due_data else "Без срока"
        text += f"{status_icon} {t.title}\n🕒 {due_str}\n\n"
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text=f"📝 Управление: {t.title[:25]}", callback_data=f"view_task_{t.id}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В меню", callback_data="to_main_menu")])

    await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


# --- Управление задачей ---
@router.callback_query(F.data.startswith("view_task_"))
async def view_task_actions(cb: CallbackQuery, session: AsyncSession):
    try:
        task_id = int(cb.data.split("_")[2])
    except ValueError:
        return await cb.answer("❌ Ошибка", show_alert=True)

    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()
    if not user_db_id:
        return await cb.answer("❌ Пользователь не найден", show_alert=True)

    res = await session.execute(select(Task).where(Task.id == task_id, Task.user_id == user_db_id))
    task = res.scalar_one_or_none()
    if not task:
        return await cb.answer("Задача не найдена", show_alert=True)

    status_text = {
        "pending": "⏳ Ожидает", "in_progress": "▶️ В работе",
        "paused": "⏸️ На паузе", "completed": "✅ Завершена"
    }.get(task.status.value, task.status.value)

    due_str = task.due_data.strftime("%d.%m %H:%M") if task.due_data else "Не задан"
    priority_icon = "🔴" if task.priority == 1 else ("🟡" if task.priority == 2 else "🟢")

    text = f"📌 {task.title}\n📊 Статус: {status_text}\n📅 Срок: {due_str}\n⚡ Приоритет: {priority_icon}\n\nВыбери действие:"

    await cb.message.edit_text(text, reply_markup=get_task_actions_kb(task.id, task.status.value),
                               parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("action_"))
async def handle_task_action(cb: CallbackQuery, session: AsyncSession):
    try:
        action, task_id_str = cb.data.split("_")[1], cb.data.split("_")[2]
        task_id = int(task_id_str)
    except (IndexError, ValueError):
        return await cb.answer("❌ Ошибка данных", show_alert=True)

    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()
    if not user_db_id:
        return await cb.answer("❌ Пользователь не найден", show_alert=True)

    res = await session.execute(select(Task).where(Task.id == task_id, Task.user_id == user_db_id))
    task = res.scalar_one_or_none()
    if not task:
        return await cb.answer("Задача не найдена", show_alert=True)

    new_status, msg = task.status, ""
    if action == "start":
        new_status, msg = TaskStatus.in_progress, "▶️ Выполнение начато"
    elif action == "pause":
        new_status, msg = TaskStatus.paused, "⏸️ Задача на паузе"
    elif action == "finish":
        new_status, msg = TaskStatus.completed, "✅ Задача завершена!"
        task.completed_at = datetime.now()

    task.status = new_status
    await session.commit()
    await cb.answer(msg, show_alert=True)
    await cb.message.edit_text(f"{msg}\n\n📌 {task.title}", reply_markup=main_menu_kb(), parse_mode="Markdown")


# --- Напоминания ---
@router.callback_query(F.data.startswith("snooze_"))
async def snooze_reminder(cb: CallbackQuery, session: AsyncSession):
    try:
        task_id = int(cb.data.split("_")[1])
    except (IndexError, ValueError):
        return await cb.answer("❌ Ошибка", show_alert=True)

    res = await session.execute(
        select(Reminder).where(Reminder.task_id == task_id)
    )
    rem = res.scalar_one_or_none()

    if rem:
        rem.scheduled_at = datetime.now() + timedelta(hours=1)
        rem.status = ReminderStatus.scheduled
        rem.sent_at = None
        await session.commit()
        await cb.answer("⏰ Напоминание перенесено на 1 час", show_alert=True)
    else:
        await cb.answer("Напоминание не найдено", show_alert=True)



# --- FR-05: Генерация чек-листов ---
@router.callback_query(F.data == "checklists")
async def checklist_main_menu(cb: CallbackQuery):
    """Главное меню чек-листов."""
    await cb.message.edit_text(
        "📝 Чек-листы\n\nСоздавайте структурированные списки для рутинных дел.",
        reply_markup=checklist_main_kb(),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data == "checklist_create")
async def ask_checklist_topic(cb: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя тему для нового чек-листа."""
    await cb.message.answer("📝 Введите тему чек-листа (например: «Уборка», «Подготовка к экзамену»):")
    await state.set_state(TaskStates.waiting_input)
    await cb.answer()


@router.message(TaskStates.waiting_input)
async def create_checklist_from_topic(msg: Message, state: FSMContext, session: AsyncSession):
    """
    Основная логика FR-05:
    1. Принимает тему от пользователя.
    2. Генерирует через ИИ список шагов.
    3. Сохраняет его как объект Checklist в БД.
    4. НЕ создает отдельные задачи в таблице Task.
    """
    topic = msg.text.strip()

    steps = await ai_service.generate_checklist(topic)

    user_result = await session.execute(select(User.id).where(User.telegram_id == msg.from_user.id))
    user_id = user_result.scalar_one_or_none()
    if not user_id:
        await msg.answer("❌ Произошла ошибка. Пожалуйста, начните с команды /start.")
        await state.clear()
        return

    new_checklist = Checklist(
        user_id=user_id,
        title=topic,
        steps={"steps": steps},
        is_template=True
    )
    session.add(new_checklist)
    await session.commit()

    formatted_steps = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))
    response_text = (
        f"✅ Чек-лист «{topic}» успешно создан!\n\n"
        f"📋 Шаги:\n{formatted_steps}\n\n"
        f"Вы можете найти его в разделе «Все чек-листы»."
    )

    await msg.answer(response_text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    await state.clear()


@router.callback_query(F.data == "checklist_view_all")
async def view_all_checklists(cb: CallbackQuery, session: AsyncSession):
    """Показывает все чек-листы пользователя."""
    user_result = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_id = user_result.scalar_one_or_none()

    checklists_result = await session.execute(
        select(Checklist)
        .where(Checklist.user_id == user_id, Checklist.is_template == True)
        .order_by(Checklist.created_at.desc())
    )
    checklists = checklists_result.scalars().all()

    if not checklists:
        await cb.message.edit_text(
            "📭 У вас пока нет чек-листов.\n\nНажмите «➕ Создать чек-лист», чтобы начать!",
            reply_markup=checklist_main_kb(),
            parse_mode="Markdown"
        )
        await cb.answer()
        return

    response_lines = ["📋 Ваши чек-листы:\n"]
    keyboard_buttons = []

    for cl in checklists:
        step_count = len(cl.steps.get("steps", []))
        response_lines.append(f"• {cl.title}({step_count} шагов)")

        callback_data = f"view_checklist_{cl.id}"
        print(f"🔍 Создаю кнопку: text='📄 {cl.title}', callback_data='{callback_data}'")

        keyboard_buttons.append(
            [InlineKeyboardButton(text=f"📄 {cl.title}", callback_data=callback_data)]
        )

    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="checklists")])
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await cb.message.edit_text("\n".join(response_lines), reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("view_checklist_"))
async def view_single_checklist(cb: CallbackQuery, session: AsyncSession):
    """Показывает детали одного чек-листа со всеми его шагами."""
    try:
        checklist_id = int(cb.data.split("_")[2])
    except (ValueError, IndexError):
        return await cb.answer("❌ Неверный формат данных.", show_alert=True)

    checklist = await session.get(Checklist, checklist_id)
    if not checklist:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    user_res = await session.execute(
        select(User.id).where(User.telegram_id == cb.from_user.id)
    )
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id or checklist.user_id != user_db_id:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    steps = checklist.steps.get("steps", [])
    if not steps:
        detail_text = f"📋 {checklist.title}\n\n📭 Этот чек-лист пуст."
    else:
        steps_list = "\n".join(f"⬜ {i}. {step}" for i, step in enumerate(steps, start=1))
        detail_text = f"📋 {checklist.title}\n\n✅ Шаги:\n{steps_list}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К списку чек-листов", callback_data="checklist_view_all")],
        [InlineKeyboardButton(text="🗑️ Удалить чек-лист", callback_data=f"checklist_delete_{checklist_id}")]
    ])

    await cb.message.edit_text(detail_text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

# --- ОБРАБОТЧИКИ ЧЕК-ЛИСТОВ

@router.callback_query(F.data.startswith("checklist_delete_confirm_"))
async def delete_checklist_execute(cb: CallbackQuery, session: AsyncSession):
    """Удаляет чек-лист"""
    try:
        checklist_id = int(cb.data.split("_")[3])
    except (ValueError, IndexError):
        return await cb.answer("❌ Неверный формат данных.", show_alert=True)

    checklist = await session.get(Checklist, checklist_id)
    if not checklist:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id or checklist.user_id != user_db_id:
        return await cb.answer("❌ Доступ запрещён.", show_alert=True)

    await session.delete(checklist)
    await session.commit()

    await cb.message.edit_text(
        f"✅ Чек-лист **{checklist.title}** успешно удален.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все чек-листы", callback_data="checklist_view_all")]
        ]),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("checklist_delete_"))
async def delete_checklist_confirm(cb: CallbackQuery, session: AsyncSession):
    """Запрашивает подтверждение удаления"""
    try:
        checklist_id = int(cb.data.split("_")[2])
    except (ValueError, IndexError):
        return await cb.answer("❌ Неверный формат данных.", show_alert=True)

    checklist = await session.get(Checklist, checklist_id)
    if not checklist:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id or checklist.user_id != user_db_id:
        return await cb.answer("❌ Доступ запрещён.", show_alert=True)

    await cb.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить чек-лист?\n\n"
        f"📋 {checklist.title}\n"
        f"🗑️ Это действие нельзя отменить.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"view_checklist_{checklist_id}")],
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"checklist_delete_confirm_{checklist_id}")]
        ]),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("view_checklist_"))
async def view_single_checklist(cb: CallbackQuery, session: AsyncSession):
    """Показывает детали чек-листа"""
    try:
        checklist_id = int(cb.data.split("_")[2])
    except (ValueError, IndexError):
        return await cb.answer("❌ Неверный формат данных.", show_alert=True)

    checklist = await session.get(Checklist, checklist_id)
    if not checklist:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id or checklist.user_id != user_db_id:
        return await cb.answer("❌ Чек-лист не найден.", show_alert=True)

    steps = checklist.steps.get("steps", [])
    if not steps:
        detail_text = f"📋 {checklist.title}\n\n📭 Этот чек-лист пуст."
    else:
        steps_list = "\n".join(f"⬜ {i}. {step}" for i, step in enumerate(steps, start=1))
        detail_text = f"📋 {checklist.title}\n\n✅ Шаги:\n{steps_list}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К списку чек-листов", callback_data="checklist_view_all")],
        [InlineKeyboardButton(text="🗑️ Удалить чек-лист", callback_data=f"checklist_delete_{checklist_id}")]
    ])

    await cb.message.edit_text(detail_text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


# --- UC-06: Сводка ---
@router.callback_query(F.data == "daily_summary")
async def daily_summary(cb: CallbackQuery, session: AsyncSession):
    res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    u_id = res.scalar_one_or_none()
    if not u_id:
        return await cb.answer("❌ Ошибка", show_alert=True)

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    completed = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.completed,
                                   Task.completed_at >= today_start))).scalar() or 0
    in_progress = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.in_progress))).scalar() or 0
    paused = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.paused))).scalar() or 0
    pending = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.pending))).scalar() or 0
    overdue = (await session.execute(select(func.count()).where(Task.user_id == u_id, Task.status.in_(
        [TaskStatus.pending, TaskStatus.in_progress, TaskStatus.paused]), Task.due_data < now))).scalar() or 0

    text = (
        f"📊 Сводка за сегодня\n\n"
        f"✅ Завершено: {completed}\n"
        f"▶️ В работе: {in_progress}\n"
        f"⏸️ На паузе: {paused}\n"
        f"⏳ Ожидают: {pending}\n"
        f"⚠️ Просрочено: {overdue}"
    )
    await cb.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "to_main_menu")
async def back_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 Главное меню:", reply_markup=main_menu_kb(), parse_mode="Markdown")
    await cb.answer()