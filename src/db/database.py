import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

Base = declarative_base()

engine = None
SessionLocal = None
Session = None

def init_db(database_url: str):
    global engine, SessionLocal, Session
    
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_path = database_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
    engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # Use scoped_session to provide thread-local sessions for multi-threaded access
    Session = scoped_session(SessionLocal)

def get_db():
    global Session
    if Session is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    db = Session()
    try:
        yield db
    finally:
        db.close()
