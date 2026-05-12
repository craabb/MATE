import asyncio
from datetime import datetime
from sqlalchemy import select
from database import session_factory
from database.models import Reminder, Task, ReminderStatus, TaskStatus, User
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


async def run_reminder_scheduler(bot: Bot):
    """Фоновая задача: проверяет дедлайны задач и отправляет уведомления."""
    print("🕐 Scheduler started...")
    while True:
        try:
            async with session_factory() as session:
                now = datetime.now()


                tasks_res = await session.execute(
                    select(Task, User)
                    .join(User, Task.user_id == User.id)
                    .where(
                        Task.status == TaskStatus.pending,
                        Task.due_data <= now
                    )
                )

                for task, user in tasks_res:

                    rem_res = await session.execute(
                        select(Reminder).where(Reminder.task_id == task.id)
                    )
                    rem = rem_res.scalar_one_or_none()


                    if rem and rem.status == ReminderStatus.sent:
                        print(f"⏭️ Пропущена задача {task.id} (уже отправлено)")
                        continue

                    print(f"📤 Отправляю напоминание: {task.title} (ID: {task.id})")


                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"action_finish_{task.id}")],
                        [InlineKeyboardButton(text="⏰ Отложить на 1ч", callback_data=f"snooze_{task.id}")]
                    ])

                    due_str = task.due_data.strftime('%d.%m %H:%M') if task.due_data else 'Без срока'


                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=f"⏰ *Напоминание:*\n\n*{task.title}*\n📅 Срок: {due_str}",
                        parse_mode="Markdown",
                        reply_markup=kb
                    )


                    if not rem:

                        rem = Reminder(
                            task_id=task.id,
                            scheduled_at=now,
                            status=ReminderStatus.sent,
                            sent_at=now
                        )
                        session.add(rem)
                        print(f"✅ Создано новое напоминание ID={rem.id if hasattr(rem, 'id') else 'new'}")
                    else:

                        rem.status = ReminderStatus.sent
                        rem.sent_at = now
                        rem.scheduled_at = None
                        print(f"✅ Обновлено напоминание ID={rem.id}")

                    await session.commit()
                    await session.refresh(rem)
                    print(f"💾 Reminder saved: task_id={task.id}, status={rem.status}, sent_at={rem.sent_at}")

        except Exception as e:
            print(f"❌ Scheduler Error: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(60)