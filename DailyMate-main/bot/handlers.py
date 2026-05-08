from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.models import User, Task, TaskStatus, Checklist, Reminder, ReminderStatus
from bot.keyboards import main_menu_kb, confirm_task_kb, list_filters_kb
from services import AIService
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
from typing import List

ai_service = AIService()
router = Router()


class TaskStates(StatesGroup):
    waiting_input = State()
    waiting_confirm = State()
    waiting_clarification = State()


# --- Вспомогательная функция: клавиатура действий для задачи ---
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


# --- UC-01: Добавление задачи (FR-01, FR-02, FR-03, FR-04, FR-05, FR-20) ---
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
        greeting = f"Привет, {user_name}! 👋\nЯ **DailyMate** — твой ИИ-ассистент для задач.\nПросто напиши задачу или выбери действие:"
    else:
        greeting = f"С возвращением, {user_name}! 👋\nЯ **DailyMate**. Что нужно сделать сегодня?"

    await message.answer(greeting, reply_markup=main_menu_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "add_task")
async def ask_task_text(cb: CallbackQuery):
    await cb.message.answer("📝 Напиши задачу в свободной форме.\nНапример: «Завтра до 18:00 купить молоко»")
    await cb.answer()


@router.message(F.text & ~F.text.startswith("/"))
async def process_text_input(message: Message, state: FSMContext, session: AsyncSession):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        parsed_tasks = await ai_service.parse_user_request(message.text)
    except Exception as e:
        print(f"AI Error: {e}")
        parsed_tasks = None

    if not parsed_tasks:
        await state.set_state(TaskStates.waiting_clarification)
        await message.answer("️ Не удалось разобрать текст. Уточни детали или напиши проще.",
                             reply_markup=main_menu_kb())
        return

    # Сохраняем как словари для FSM
    await state.update_data(parsed_tasks=[t.model_dump() for t in parsed_tasks])
    await state.set_state(TaskStates.waiting_confirm)

    # Безопасный доступ к полям Pydantic-модели
    resp = "**Я распознал:**\n\n"
    for i, t in enumerate(parsed_tasks, 1):
        resp += f"📌 {i}. {t.title or 'Без названия'}\n📅 {t.due_date or 'Без срока'}\n📂 {t.category or 'Общее'}\n\n"
    resp += "Сохранить?"
    await message.answer(resp, reply_markup=confirm_task_kb())


@router.callback_query(TaskStates.waiting_confirm, F.data == "task_confirm")
async def save_tasks(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    tasks_data = data.get("parsed_tasks", [])

    res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_id = res.scalar()

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


# --- UC-02: Просмотр списка (FR-07, FR-08, FR-19) ---
@router.callback_query(F.data == "view_lists")
async def show_filters(cb: CallbackQuery):
    await cb.message.edit_text(" Выбери период:", reply_markup=list_filters_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("filter_"))
async def show_tasks(cb: CallbackQuery, session: AsyncSession):
    user_res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    user_db_id = user_res.scalar_one_or_none()
    if not user_db_id:
        await cb.answer("❌ Пользователь не найден", show_alert=True)
        return

    f_type = cb.data.split("_", 1)[1]
    now = datetime.now()  # Naive datetime для совместимости с TIMESTAMP WITHOUT TIME ZONE

    # Показываем все активные задачи (pending, in_progress, paused)
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
        filter_name = "📋 Все задачи"

    tasks = (await session.execute(q)).scalars().all()

    if not tasks:
        await cb.message.edit_text(f"{filter_name}\n\n📭 Задач на этот период нет. Создай первую!",
                                   reply_markup=list_filters_kb())
        await cb.answer()
        return

    text = f"{filter_name}\n\n**Твои задачи:**\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])

    for t in tasks:
        status_icon = "⏳" if t.status == TaskStatus.pending else ("▶️" if t.status == TaskStatus.in_progress else "⏸️")
        text += f"{status_icon} **{t.title}**\n"
        text += f" {t.due_data.strftime('%d.%m %H:%M') if t.due_data else 'Без срока'}\n\n"
        # Кнопка для открытия меню действий
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"📝 Управление: {t.title[:25]}", callback_data=f"view_task_{t.id}")
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В меню", callback_data="to_main_menu")])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


# --- Управление задачей: Начать / Пауза / Завершить ---
@router.callback_query(F.data.startswith("view_task_"))
async def view_task_actions(cb: CallbackQuery, session: AsyncSession):
    try:
        task_id = int(cb.data.split("_")[2])
    except:
        return await cb.answer("❌ Ошибка", show_alert=True)

    # ✅ Сначала находим user_id по telegram_id
    user_res = await session.execute(
        select(User.id).where(User.telegram_id == cb.from_user.id)
    )
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id:
        return await cb.answer("❌ Пользователь не найден", show_alert=True)

    # ✅ Ищем задачу по correct user_id
    res = await session.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_db_id)
    )
    task = res.scalar_one_or_none()

    if not task:
        return await cb.answer("Задача не найдена", show_alert=True)

    status_text = {
        "pending": "⏳ Ожидает",
        "in_progress": "▶️ В работе",
        "paused": "⏸️ На паузе",
        "completed": "✅ Завершена"
    }.get(task.status.value, task.status.value)

    text = (
        f"📌 **{task.title}**\n"
        f"📊 Статус: {status_text}\n"
        f"📅 Срок: {task.due_data.strftime('%d.%m %H:%M') if task.due_data else 'Не задан'}\n"
        f"⚡ Приоритет: {'🔴' if task.priority == 1 else '🟡' if task.priority == 2 else '🟢'}\n\n"
        f"Выбери действие:"
    )
    await cb.message.edit_text(text, reply_markup=get_task_actions_kb(task.id, task.status.value),
                               parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("action_"))
async def handle_task_action(cb: CallbackQuery, session: AsyncSession):
    try:
        action, task_id_str = cb.data.split("_")[1], cb.data.split("_")[2]
        task_id = int(task_id_str)
    except:
        return await cb.answer("❌ Ошибка данных", show_alert=True)

    # ✅ Сначала находим user_id
    user_res = await session.execute(
        select(User.id).where(User.telegram_id == cb.from_user.id)
    )
    user_db_id = user_res.scalar_one_or_none()

    if not user_db_id:
        return await cb.answer("❌ Пользователь не найден", show_alert=True)

    # ✅ Ищем задачу по correct user_id
    res = await session.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_db_id)
    )
    task = res.scalar_one_or_none()

    if not task:
        return await cb.answer("Задача не найдена", show_alert=True)

    new_status = task.status
    msg = ""

    if action == "start":
        new_status = TaskStatus.in_progress
        msg = "▶️ Выполнение начато"
    elif action == "pause":
        new_status = TaskStatus.paused
        msg = "⏸️ Задача на паузе"
    elif action == "finish":
        new_status = TaskStatus.completed
        task.completed_at = datetime.now()
        msg = "✅ Задача завершена!"

    task.status = new_status
    await session.commit()

    await cb.answer(msg, show_alert=True)
    await cb.message.edit_text(f"{msg}\n\n📌 **{task.title}**", reply_markup=main_menu_kb(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("action_"))
async def handle_task_action(cb: CallbackQuery, session: AsyncSession):
    try:
        action, task_id_str = cb.data.split("_")[1], cb.data.split("_")[2]
        task_id = int(task_id_str)
    except:
        return await cb.answer("❌ Ошибка данных", show_alert=True)

    res = await session.execute(
        select(Task).where(Task.id == task_id, Task.user_id == cb.from_user.id)
    )
    task = res.scalar_one_or_none()
    if not task:
        return await cb.answer("Задача не найдена", show_alert=True)

    new_status = task.status
    msg = ""

    if action == "start":
        new_status = TaskStatus.in_progress
        msg = "▶️ Выполнение начато"
    elif action == "pause":
        new_status = TaskStatus.paused
        msg = "⏸️ Задача на паузе"
    elif action == "finish":
        new_status = TaskStatus.completed
        task.completed_at = datetime.now()  # Фиксация времени завершения (FR-10)
        msg = "✅ Задача завершена!"

    task.status = new_status
    await session.commit()

    await cb.answer(msg, show_alert=True)
    # Возвращаем в меню или обновляем текущий экран
    await cb.message.edit_text(f"{msg}\n\n📌 **{task.title}**", reply_markup=main_menu_kb(), parse_mode="Markdown")


# --- FR-13: Отложить напоминание ---
@router.callback_query(F.data.startswith("snooze_"))
async def snooze_reminder(cb: CallbackQuery, session: AsyncSession):
    try:
        task_id = int(cb.data.split("_")[1])
    except:
        return await cb.answer(" Ошибка", show_alert=True)

    res = await session.execute(
        select(Reminder).where(Reminder.task_id == task_id, Reminder.status == ReminderStatus.sent)
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


# --- UC-05: Чек-листы (FR-14, FR-15, FR-16) ---
@router.callback_query(F.data == "checklists")
async def checklist_menu(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("📝 Введи тему для чек-листа (например: 'Уборка'):")
    await state.set_state(TaskStates.waiting_input)
    await cb.answer()


@router.message(TaskStates.waiting_input)
async def generate_checklist(msg: Message, state: FSMContext, session: AsyncSession):
    steps = await ai_service.generate_checklist(msg.text)
    res = await session.execute(select(User.id).where(User.telegram_id == msg.from_user.id))
    u_id = res.scalar()

    cl = Checklist(user_id=u_id, title=msg.text, steps={"steps": steps}, is_template=True)
    session.add(cl)
    await session.commit()

    text = "📋 **Готовый чек-лист:**\n\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    await msg.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    await state.clear()


# --- UC-06: Ежедневная сводка (FR-17, FR-18) ---
@router.callback_query(F.data == "daily_summary")
async def daily_summary(cb: CallbackQuery, session: AsyncSession):
    res = await session.execute(select(User.id).where(User.telegram_id == cb.from_user.id))
    u_id = res.scalar()

    now = datetime.now()  # Naive datetime
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    completed = (await session.execute(
        select(func.count()).where(
            Task.user_id == u_id,
            Task.status == TaskStatus.completed,
            Task.completed_at >= today_start
        )
    )).scalar() or 0

    in_progress = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.in_progress)
    )).scalar() or 0

    paused = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.paused)
    )).scalar() or 0

    pending = (await session.execute(
        select(func.count()).where(Task.user_id == u_id, Task.status == TaskStatus.pending)
    )).scalar() or 0

    # Просроченные: активные задачи, срок которых уже прошёл
    overdue = (await session.execute(
        select(func.count()).where(
            Task.user_id == u_id,
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress, TaskStatus.paused]),
            Task.due_data < now
        )
    )).scalar() or 0

    await cb.message.edit_text(
        f"📊 **Сводка за сегодня**\n\n"
        f"✅ **Завершено:** {completed}\n"
        f"▶️ **В работе:** {in_progress}\n"
        f"⏸️ **На паузе:** {paused}\n"
        f" **Ожидают:** {pending}\n"
        f"⚠️ **Просрочено:** {overdue}",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data == "to_main_menu")
async def back_menu(cb: CallbackQuery):
    await cb.message.edit_text("🏠 Главное меню:", reply_markup=main_menu_kb())
    await cb.answer()