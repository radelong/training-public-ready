import time
import uuid
from sqlalchemy import (create_engine, String, Integer, Text, Boolean, Float, ForeignKey,
                        Index, text, UniqueConstraint, inspect)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="learner")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Login(Base):
    __tablename__ = "logins"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class LoginFailure(Base):
    __tablename__ = "login_failures"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    until: Mapped[float] = mapped_column(Float, default=0)


class ConsoleGrant(Base):
    __tablename__ = "console_grants"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    login_hash: Mapped[str] = mapped_column(ForeignKey("logins.token_hash", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(ForeignKey("lab_sessions.id"))
    generation: Mapped[int] = mapped_column(Integer)
    expires: Mapped[float] = mapped_column(Float)


class HttpTunnel(Base):
    __tablename__ = "http_tunnels"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_hash: Mapped[str] = mapped_column(ForeignKey("console_grants.token_hash", ondelete="CASCADE"))


class Lab(Base):
    __tablename__ = "labs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24))
    template_id: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cores: Mapped[int] = mapped_column(Integer, default=2)
    memory: Mapped[int] = mapped_column(Integer, default=2048)
    drills_json: Mapped[str] = mapped_column(Text, default="[]")


class LabSession(Base):
    __tablename__ = "lab_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    lab_id: Mapped[str] = mapped_column(ForeignKey("labs.id"))
    state: Mapped[str] = mapped_column(String(24), default="queued")
    vmid: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    key_cipher: Mapped[str] = mapped_column(Text, default="")
    public_key: Mapped[str] = mapped_column(Text, default="")
    host_key: Mapped[str] = mapped_column(Text, default="")
    active_drill: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text, default="Waiting for a worker")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        Index("one_live_lab", "user_id", "lab_id", unique=True,
              postgresql_where=text("state != 'ended'"), sqlite_where=text("state != 'ended'")),
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("lab_sessions.id"))
    action: Mapped[str] = mapped_column(String(24))
    argument: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(24), default="queued")
    message: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (
        Index("one_pending_job", "session_id", unique=True,
              postgresql_where=text("state IN ('queued','running')"),
              sqlite_where=text("state IN ('queued','running')")),
    )


class Result(Base):
    __tablename__ = "results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    lab_id: Mapped[str] = mapped_column(ForeignKey("labs.id"))
    drill_id: Mapped[str] = mapped_column(String(128))
    passed: Mapped[bool] = mapped_column(Boolean)
    output: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class VideoProgress(Base):
    __tablename__ = "video_progress"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    author: Mapped[str] = mapped_column(String(180))
    topic: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(255))
    duration: Mapped[float] = mapped_column(Float)
    watched_json: Mapped[str] = mapped_column(Text, default="[]")
    last_position: Mapped[float] = mapped_column(Float, default=0)
    last_seen: Mapped[float] = mapped_column(Float, default=0)
    last_playing: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[float | None] = mapped_column(Float, nullable=True)


class VideoCatalogOrder(Base):
    __tablename__ = "video_catalog_order"
    relative_path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    author: Mapped[str | None] = mapped_column(String(180), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(180), nullable=True)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)


class BugReport(Base):
    __tablename__ = "bug_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    read_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    read_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (Index("bug_reports_created", "created"),)


class LearningGame(Base):
    __tablename__ = "learning_games"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(24), default="General")
    filename: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class LearningGameProgress(Base):
    __tablename__ = "learning_game_progress"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("learning_games.id"), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class Heartbeat(Base):
    __tablename__ = "heartbeat"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    updated: Mapped[float] = mapped_column(Float)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    draft_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class CourseVersion(Base):
    __tablename__ = "course_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    number: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint("course_id", "number"),)


class ContentAsset(Base):
    __tablename__ = "content_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class CourseProgress(Base):
    __tablename__ = "course_progress"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    completed_json: Mapped[str] = mapped_column(Text, default="[]")
    current_module: Mapped[str] = mapped_column(String(64), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint("version_id", "user_id"),)


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    marks_json: Mapped[str] = mapped_column(Text, default="{}")
    question_order_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    feedback: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    submitted: Mapped[float | None] = mapped_column(Float, nullable=True)


def database(url):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            # 742610 protects allocations; 742611 elects the long-running worker.
            connection.execute(text('SELECT pg_advisory_xact_lock(742612)'))
        Base.metadata.create_all(connection)
        migrations = {'video_catalog_order': {'author': 'VARCHAR(180)', 'topic': 'VARCHAR(180)'}}
        for table, columns in migrations.items():
            existing = {c['name'] for c in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        if 'question_order_json' not in {c['name'] for c in inspect(connection).get_columns('exam_attempts')}:
            connection.execute(text("ALTER TABLE exam_attempts ADD COLUMN question_order_json TEXT NOT NULL DEFAULT '[]'"))
    return engine, sessionmaker(engine, expire_on_commit=False)


def allocation_lock(db):
    # All API allocation/mutation decisions share one transaction-scoped lock.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(742610)"))
    elif db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
