import re
from datetime import datetime, timedelta
from typing import List, Optional
from .schemas import TaskCreateSchema


class AIService:
    """
    Улучшенный парсер задач для MVP.
    """

    async def parse_user_request(self, text: str) -> List[TaskCreateSchema]:
        """Парсит текст и возвращает список задач"""
        tasks = []
        text_lower = text.lower().strip()
        original_text = text

        # === 1. ОПРЕДЕЛЕНИЕ ВРЕМЕНИ/ДАТЫ ===
        due_date = None
        time_range = None

        # Паттерн: "с 10 до 19", "с 10:00 до 19:00"
        time_range_match = re.search(r'с\s+(\d{1,2})(?::(\d{2}))?\s+до\s+(\d{1,2})(?::(\d{2}))?', text_lower)
        if time_range_match:
            start_hour = int(time_range_match.group(1))
            end_hour = int(time_range_match.group(3))
            time_range = f"{start_hour:02d}:00 - {end_hour:02d}:00"
            # Устанавливаем дедлайн на конец временного диапазона
            due_date = (datetime.now() + timedelta(days=1)).replace(hour=end_hour, minute=0)

        # Паттерн: "завтра"
        elif "завтра" in text_lower:
            due_date = (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0)

        # Паттерн: "сегодня"
        elif "сегодня" in text_lower:
            due_date = datetime.now().replace(hour=18, minute=0)

        # Паттерн: "до пятницы", "до понедельника"
        day_match = re.search(r'до\s+(пятницы|понедельника|вторника|среды|четверга|субботы|воскресенья)', text_lower)
        if day_match:
            days_map = {
                'понедельника': 0, 'вторника': 1, 'среды': 2,
                'четверга': 3, 'пятницы': 4, 'субботы': 5, 'воскресенья': 6
            }
            target_day = days_map[day_match.group(1)]
            today = datetime.now()
            days_ahead = (target_day - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            due_date = (today + timedelta(days=days_ahead)).replace(hour=18, minute=0)

        # Паттерн: конкретное время "в 10:00", "в 18 часов"
        time_match = re.search(r'в\s+(\d{1,2})(?::(\d{2}))?\s*(?:часов|часа?)?', text_lower)
        if time_match and not time_range:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            if due_date is None:
                due_date = (datetime.now() + timedelta(days=1)).replace(hour=hour, minute=minute)
            else:
                due_date = due_date.replace(hour=hour, minute=minute)

        # === 2. ОПРЕДЕЛЕНИЕ ПРИОРИТЕТА ===
        priority = 2  # default: средний

        if any(w in text_lower for w in ["срочно", "важно", "быстро", "!!!", "горит"]):
            priority = 1  # высокий
        elif any(w in text_lower for w in ["потом", "когда будет время", "не горит", "когда-нибудь"]):
            priority = 3  # низкий

        # === 3. ОПРЕДЕЛЕНИЕ КАТЕГОРИИ ===
        category = "Общее"

        # Покупки (только явные маркеры)
        if any(w in text_lower for w in ["купить", "куплю", "покупка", "магазин", "продукты"]):
            if any(w in text_lower for w in ["молоко", "хлеб", "еда", "продукты", "вода"]):
                category = "Покупки"

        # Финансы
        elif any(w in text_lower for w in
                 ["оплатить", "оплата", "счет", "интернет", "квартплата", "коммуналка", "перевести деньги"]):
            category = "Финансы"

        # Здоровье
        elif any(w in text_lower for w in ["врач", "здоровье", "лекарство", "аптека", "больница", "запись к врачу"]):
            category = "Здоровье"

        # Учеба
        elif any(w in text_lower for w in
                 ["учеба", "экзамен", "домашка", "пара", "лекция", "семинар", "курсовая", "диплом"]):
            category = "Учеба"

        # Чтение/Саморазвитие
        elif any(w in text_lower for w in ["читать книгу", "книга", "чтение", "учить", "изучать"]):
            category = "Чтение"

        # Работа
        elif any(w in text_lower for w in ["работа", "отчет", "совещание", "встреча", "дедлайн", "проект"]):
            category = "Работа"

        # Спорт
        elif any(w in text_lower for w in ["спорт", "тренировка", "зарядка", "бег", "зал", "фитнес"]):
            category = "Спорт"

        # === 4. ОЧИСТКА ЗАГОЛОВКА ===
        # Удаляем служебные слова и паттерны
        title = original_text

        # Удаляем временные маркеры
        title = re.sub(
            r'(завтра|сегодня|срочно|важно|!!!)+',
            '',
            title,
            flags=re.IGNORECASE
        )

        # Удаляем временные диапазоны
        title = re.sub(
            r'с\s+\d{1,2}(?::\d{2})?\s+до\s+\d{1,2}(?::\d{2})?',
            '',
            title,
            flags=re.IGNORECASE
        )

        # Удаляем конкретное время
        title = re.sub(
            r'в\s+\d{1,2}(?::\d{2})?\s*(?:часов|часа?)?',
            '',
            title,
            flags=re.IGNORECASE
        )

        # Удаляем дни недели
        title = re.sub(
            r'до\s+(пятницы|понедельника|вторника|среды|четверга|субботы|воскресенья)',
            '',
            title,
            flags=re.IGNORECASE
        )

        # Очищаем лишние пробелы
        title = ' '.join(title.split()).strip()

        # Если заголовок пустой после очистки - берем оригинал
        if not title or len(title) < 3:
            title = original_text[:100]

        # === 5. СОЗДАНИЕ ЗАДАЧИ ===
        task_dict = {
            "title": title,
            "due_date": due_date.isoformat() if due_date else None,
            "category": category,
            "priority": priority,
            "description": f"Время: {time_range}" if time_range else ""
        }

        tasks.append(TaskCreateSchema(**task_dict))

        return tasks

    async def generate_checklist(self, routine: str) -> List[str]:
        """Заглушка генерации чек-листа"""
        return [
            "Шаг 1: Подготовьте необходимые материалы",
            "Шаг 2: Выделите время в расписании",
            "Шаг 3: Выполните основные действия",
            "Шаг 4: Проверьте результат",
            "Шаг 5: Зафиксируйте завершение"
        ]

    async def summarize_day(self, tasks: list) -> str:
        """Заглушка сводки"""
        completed = sum(1 for t in tasks if t.get('status') == 'completed')
        total = len(tasks)
        return f"За день выполнено: {completed}/{total} задач. {'Отличная работа! 🎉' if completed > 0 else 'Начните с малого 💪'}"