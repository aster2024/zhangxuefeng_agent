import httpx
from fastapi import APIRouter, HTTPException

from zxf_agent.api.schemas import ChatRequest, ChatResponse
from zxf_agent.orchestrator.workflow import handle

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = await handle(message=req.message, session_id=req.session_id)
        return ChatResponse(**result)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 402:
            raise HTTPException(status_code=502, detail="LLM API 余额不足（402），请充值或更换 API Key")
        if status == 401:
            raise HTTPException(status_code=502, detail="LLM API Key 无效（401），请检查 .env 配置")
        if status == 429:
            raise HTTPException(status_code=502, detail="LLM API 限速（429），请稍后重试")
        raise HTTPException(status_code=502, detail=f"LLM API 错误：{status}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM API 超时，请稍后重试")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="无法连接 LLM API（网络不通），请检查网络或代理设置")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
