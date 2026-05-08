import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from database import session_factory
from database.models import Reminder, Task, ReminderStatus, TaskStatus
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def run_reminder_scheduler(bot: Bot):
    """
    Фоновая задача: проверяет напоминания каждую минуту.
    """
    print(" Scheduler started...")
    while True:
        try:
            async with session_factory() as session:
                now = datetime.now()

                res = await session.execute(
                    select(Reminder).where(
                        Reminder.status == ReminderStatus.scheduled,
                        Reminder.scheduled_at <= now
                    )
                )
                reminders = res.scalars().all()

                for rem in reminders:
                    task = await session.get(Task, rem.task_id)
                    if task and task.status == TaskStatus.pending:
                        # ✅ УБРАНО: types. → используем классы напрямую
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="Выполнено", callback_data=f"done_{task.id}")],
                            [InlineKeyboardButton(text="Отложить на 1ч", callback_data=f"snooze_{task.id}")]
                        ])

                        due_str = task.due_data.strftime('%H:%M') if task.due_data else 'Сегодня'

                        await bot.send_message(
                            chat_id=task.user_id,
                            text=f"Напоминание:\n\n{task.title}\nСрок: {due_str}",
                            parse_mode="Markdown",
                            reply_markup=kb
                        )
                        rem.status = ReminderStatus.sent
                        rem.sent_at = datetime.now(timezone.utc)
                        await session.commit()
        except Exception as e:
            print(f"Scheduler Error: {e}")
        await asyncio.sleep(60)