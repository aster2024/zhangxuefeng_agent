from __future__ import annotations

from datetime import datetime, timedelta

from zxf_agent.config import settings


def get(key: str) -> dict | None:
    from zxf_agent.db.models import SearchCache
    from zxf_agent.db.session import SessionLocal

    with SessionLocal() as db:
        row = db.get(SearchCache, key)
        if row is None:
            return None
        cutoff = datetime.utcnow() - timedelta(days=settings.search_cache_ttl_days)
        if row.cached_at < cutoff:
            db.delete(row)
            db.commit()
            return None
        return row.result


def set(key: str, result: dict) -> None:
    from zxf_agent.db.models import SearchCache
    from zxf_agent.db.session import SessionLocal

    with SessionLocal() as db:
        row = db.get(SearchCache, key)
        if row:
            row.result = result
            row.cached_at = datetime.utcnow()
        else:
            db.add(SearchCache(key=key, result=result))
        db.commit()
