from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(default=None, description="会话 ID，不传则自动创建")


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    status: Literal["collecting", "planned"]
    plan: Optional[Dict[str, Any]] = None
