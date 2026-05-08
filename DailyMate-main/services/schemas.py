from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class TaskCreateSchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    title: str = Field(..., min_length=1, max_length=128, description="Название задачи")
    description: Optional[str] = Field(None, max_length=512, description="Описание")
    due_date: Optional[str] = Field(None, description="Дата дедлайна в ISO формате (YYYY-MM-DDTHH:MM:SS)")
    category: str = Field(default="Общее", max_length=64, description="Категория задачи")
    priority: int = Field(default=2, ge=1, le=3, description="Приоритет: 1=высокий, 2=средний, 3=низкий")