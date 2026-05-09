import json
import time
from datetime import datetime
from typing import List
from groq import AsyncGroq
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import settings
from database.models import AIInteraction, AIInteractionType
from .schemas import TaskCreateSchema

client = AsyncGroq(api_key=settings.GROQ_API_KEY)


class AIService:

    async def parse_user_request(self, text: str, session: AsyncSession, user_id: int) -> List[TaskCreateSchema]:
        start_time = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        prompt = f"""
Ты ИИ-ассистент DailyMate. Текущее системное время: {now_str}.
Вытащи из текста задачи. Категорию подбери по смыслу (Работа, Здоровье, Покупки и т.д.).
Приоритет: 1 - высокий (срочно), 2 - средний, 3 - низкий.
Если дата/время непонятны, ставь null.

Верни ответ СТРОГО в формате JSON:
{{"tasks": [{{"title": "...", "due_date": "YYYY-MM-DDTHH:MM:SS", "category": "...", "priority": 2, "description": "..."}}]}}
"""
        try:
            response = await client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "Отвечай только валидным JSON."},
                    {"role": "user", "content": prompt + "\n\nТекст пользователя: " + text}
                ],
                temperature=0.3,
                max_tokens=500
            )
            raw_content = response.choices[0].message.content

            if raw_content.startswith("```"):
                raw_content = raw_content.replace("```json", "").replace("```", "").strip()

            data = json.loads(raw_content)

            latency = (time.time() - start_time) * 1000
            session.add(AIInteraction(
                user_id=user_id,
                action_type=AIInteractionType.parse_task,
                request_payload=text,
                response_payload=raw_content,
                success=True,
                latency_ms=latency
            ))
            await session.commit()

            tasks = []
            for t in data.get("tasks", []):
                tasks.append(TaskCreateSchema(**t))
            return tasks

        except Exception as e:
            print(f"AI Parse Error: {e}")
            latency = (time.time() - start_time) * 1000
            session.add(AIInteraction(
                user_id=user_id,
                action_type=AIInteractionType.parse_task,
                request_payload=text,
                response_payload=str(e),
                success=False,
                latency_ms=latency
            ))
            await session.commit()
            return []

    async def generate_checklist(self, routine: str) -> List[str]:
        try:
            response = await client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system",
                     "content": "Ты помощник, который создаёт чек-листы. Отвечай списком конкретных шагов, каждый с новой строки. Без нумерации и лишних слов."},
                    {"role": "user", "content": f"Создай подробный чек-лист из 4-6 конкретных шагов для: {routine}"}
                ],
                temperature=0.5,
                max_tokens=300
            )
            content = response.choices[0].message.content

            steps = []
            for line in content.split("\n"):
                clean = line.strip().lstrip("0123456789.-•* ").strip()
                if len(clean) > 3:
                    steps.append(clean)

            return steps[:6] if steps else [f"Шаг 1: {routine}", "Шаг 2: Выполнить", "Шаг 3: Завершить"]

        except Exception as e:
            print(f"Checklist Error: {e}")
            return [f"Подготовиться к: {routine}", "Выполнить основные действия", "Проверить результат"]