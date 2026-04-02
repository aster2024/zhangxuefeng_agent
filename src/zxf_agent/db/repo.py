from __future__ import annotations

import uuid
from datetime import datetime

from zxf_agent.db.models import Session
from zxf_agent.db.session import SessionLocal


class SessionRepo:
    @staticmethod
    def get(session_id: str) -> Session | None:
        with SessionLocal() as db:
            return db.get(Session, session_id)

    @staticmethod
    def create(session_id: str | None = None) -> Session:
        row = Session(id=session_id or str(uuid.uuid4()))
        with SessionLocal() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    @staticmethod
    def update(session_id: str, **kwargs) -> None:
        with SessionLocal() as db:
            row = db.get(Session, session_id)
            if row is None:
                return
            for k, v in kwargs.items():
                setattr(row, k, v)
            row.updated_at = datetime.utcnow()
            db.commit()
