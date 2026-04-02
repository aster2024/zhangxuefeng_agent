from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from zxf_agent.config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
