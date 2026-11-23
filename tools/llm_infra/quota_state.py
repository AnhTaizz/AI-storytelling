"""Small transactional quota ledger. All timestamps are Unix seconds."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time

from tools.llm_infra.quota_policy import REASONS
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


class QuotaStateError(GeminiConfigError):
    """An unusable state file; a config error so the CLI reports it without a traceback."""


def validate_scope(*fields):
    if any(not isinstance(v, str) or not v.strip() or len(v) > 128 or not v.isprintable()
           for v in fields):
        raise ValueError("Invalid quota scope")


class QuotaStateStore:
    def __init__(self, path: str | Path | None, *, clock=time.time):
        self.path = None if path is None or str(path) == ":memory:" else Path(path)
        self._lock = threading.RLock()
        self._memory = None if self.path else sqlite3.connect(":memory:", check_same_thread=False)
        if self._memory or self.path.exists():
            self.purge_expired(clock())

    @contextmanager
    def _connection(self, *, create=False):
        with self._lock:
            db = self._memory
            try:
                if db is None:
                    if not create and not self.path.exists():
                        yield None
                        return
                    if create:
                        self.path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(self.path, timeout=5)
                db.row_factory = sqlite3.Row
                with db:
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                    if version == 0:
                        db.execute("""CREATE TABLE IF NOT EXISTS quota (
                            provider TEXT, model TEXT, project_alias TEXT, blocked_until REAL,
                            reason TEXT, unknown_streak INTEGER, recorded_at REAL, updated_at REAL,
                            PRIMARY KEY(provider, model, project_alias))""")
                        db.execute("PRAGMA user_version = 1")
                    elif version != 1:
                        raise sqlite3.DatabaseError()
                    yield db
            except (OSError, sqlite3.Error):
                raise QuotaStateError(f"Cannot use quota state at {self.path}. "
                                      "The file can be deleted to clear quota history.") from None
            finally:
                if db is not None and self._memory is None:
                    db.close()

    def block(self, provider, model, project_alias, until, reason, now):
        validate_scope(provider, model, project_alias)
        if reason not in REASONS:
            raise ValueError("Invalid quota reason")
        with self._connection(create=True) as db:
            db.execute("""INSERT INTO quota VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider,model,project_alias) DO UPDATE SET
                blocked_until=max(blocked_until,excluded.blocked_until),
                reason=CASE WHEN excluded.blocked_until >= blocked_until
                            THEN excluded.reason ELSE reason END,
                unknown_streak=CASE WHEN excluded.unknown_streak=1 THEN unknown_streak+1 ELSE 0 END,
                updated_at=excluded.updated_at""",
                       (provider, model, project_alias, until, reason, int(reason == "UNKNOWN_429"), now, now))

    def _row(self, provider, model, alias):
        validate_scope(provider, model, alias)
        with self._connection() as db:
            if db:
                return db.execute("""SELECT blocked_until, unknown_streak FROM quota
                    WHERE provider=? AND model=? AND project_alias=?""", (provider, model, alias)).fetchone()

    def blocked_until(self, provider, model, alias, now):
        row = self._row(provider, model, alias)
        return row[0] if row and row[0] > now else None

    def unknown_streak(self, provider, model, alias):
        row = self._row(provider, model, alias)
        return row[1] if row else 0

    def record_success(self, provider, model, alias, now):
        validate_scope(provider, model, alias)
        with self._connection() as db:
            if db:
                scope = (provider, model, alias)
                db.execute("""DELETE FROM quota WHERE provider=? AND model=? AND project_alias=?
                    AND blocked_until<=?""", (*scope, now))
                db.execute("""UPDATE quota SET unknown_streak=0, updated_at=?
                    WHERE provider=? AND model=? AND project_alias=?""", (now, *scope))

    def active_blocks(self, now):
        with self._connection() as db:
            return [dict(r) for r in db.execute("""SELECT * FROM quota WHERE blocked_until>?
                    ORDER BY provider,model,project_alias""", (now,))] if db else []

    def purge_expired(self, now):
        with self._connection() as db:
            if db:
                db.execute("DELETE FROM quota WHERE blocked_until<=?", (now,))
