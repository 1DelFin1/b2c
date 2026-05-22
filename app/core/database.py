from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings


engine = create_async_engine(
    str(settings.pg_database.POSTGRES_URL_ASYNC),
    echo=settings.pg_database.ECHO,
)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass
