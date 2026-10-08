from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./congestion.db"

# check_same_thread=False : FastAPI는 여러 스레드로 요청을 처리하는데
# SQLite는 기본적으로 만든 스레드에서만 쓸 수 있어서 이 제약을 풀어줌
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """요청마다 DB 세션을 열고, 끝나면 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()