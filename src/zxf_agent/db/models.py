from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from zxf_agent.db.base import Base


class Session(Base):
    """多轮对话会话状态"""
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)   # [{role, content}]
    profile: Mapped[dict] = mapped_column(JSON, default=dict)    # 提取到的考生信息
    status: Mapped[str] = mapped_column(String(32), default="collecting")  # collecting | planned
    plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SearchCache(Base):
    """搜索结果缓存，避免重复搜索相同院校数据"""
    __tablename__ = "search_cache"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)  # "苏州大学|山东|物理组"
    result: Mapped[dict] = mapped_column(JSON)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
