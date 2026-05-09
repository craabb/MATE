from datetime import datetime
import enum

from sqlalchemy import Integer, BigInteger, String, DateTime, ForeignKey, Boolean, Enum, CheckConstraint, Text, Float, \
    JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
# from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func


class TaskStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    paused = "paused"
    completed = "completed"
    overdue = "overdue"
    postponed = "postponed"


class ReminderStatus(enum.Enum):
    scheduled = "scheduled"
    sent = "sent"
    skipped = "skipped"


class AIInteractionType(enum.Enum):
    parse_task = "parse_task"
    generate_checklist = "generate_checklist"
    summarize = "summarize"


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(128), default="#FFFFFF")


class Checklist(Base):
    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    steps: Mapped[dict] = mapped_column(JSON, default=lambda: {"steps": []})
    is_template: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(128), nullable=True)
    due_data: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=True)
    priority: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("priority >= 1 AND priority <= 3"),
        nullable=True
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_extraction: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class Reminder(Base):
    __tablename__ = "reminders"

    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[ReminderStatus] = mapped_column(Enum(ReminderStatus))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    action_type: Mapped[AIInteractionType] = mapped_column(Enum(AIInteractionType))
    request_payload: Mapped[str] = mapped_column(Text, nullable=False)
    response_payload: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

