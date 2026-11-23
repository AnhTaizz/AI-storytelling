"""Persistent per-account estimates using a separate table in the quota state file."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from threading import Lock

from tools.llm_infra.cloudflare_free_models_v1 import NEURON_PRICES
from tools.llm_infra.quota_state import QuotaStateError, validate_scope


def utc_day(now):
    return datetime.fromtimestamp(now, timezone.utc).date().isoformat()


def estimate_neurons(model, prompt_tokens, completion_tokens):
    input_price, output_price = NEURON_PRICES[model]
    weighted = prompt_tokens * input_price + completion_tokens * output_price
    return (weighted + 999999) // 1000000


def estimate_prompt_neurons(model, text_chars):
    return estimate_neurons(model, (text_chars + 2) // 3, 0)


def estimate_response_neurons(model, prompt_chars, response):
    prompt, completion = response.prompt_tokens, response.completion_tokens
    if prompt is None:
        prompt = (prompt_chars + 2) // 3
    if completion is None:
        completion = (len(response.text) + 2) // 3
    return estimate_neurons(model, prompt, completion)


def _day_key(day):
    return date.fromisoformat(day).isoformat()


class NeuronLedger:
    def __init__(self, path=None):
        self._path = None if path is None or str(path) == ":memory:" else Path(path)
        self._lock = Lock()
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if self._path is None else None

    @contextmanager
    def _connection(self, *, create=False):
        with self._lock:
            db = self._memory
            try:
                if db is None:
                    if not create and not self._path.exists():
                        yield None
                        return
                    if create:
                        self._path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(self._path, timeout=5)
                with db:
                    db.execute("""CREATE TABLE IF NOT EXISTS estimated_neurons (
                        provider TEXT, scope TEXT, day TEXT, neurons INTEGER, updated_at REAL,
                        PRIMARY KEY(provider, scope, day))""")
                    yield db
            except (OSError, sqlite3.Error):
                raise QuotaStateError("Cannot use quota state for estimated Neurons.") from None
            finally:
                if db is not None and self._memory is None:
                    db.close()

    def add(self, provider, scope, day, neurons, now):
        """Add a non-negative estimate and return the new total atomically."""
        validate_scope(provider, scope)
        day = _day_key(day)
        if type(neurons) is not int or neurons < 0:
            raise ValueError("Estimated Neurons must be a non-negative integer")
        with self._connection(create=True) as db:
            return db.execute("""INSERT INTO estimated_neurons VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, scope, day) DO UPDATE SET
                neurons=neurons+excluded.neurons, updated_at=max(updated_at, excluded.updated_at)
                RETURNING neurons""", (provider, scope, day, neurons, now)).fetchone()[0]

    def used(self, provider, scope, day):
        validate_scope(provider, scope)
        day = _day_key(day)
        with self._connection() as db:
            row = db.execute("""SELECT neurons FROM estimated_neurons
                WHERE provider=? AND scope=? AND day=?""", (provider, scope, day)).fetchone() if db else None
            return row[0] if row else 0

    def purge_before(self, day):
        day = _day_key(day)
        with self._connection() as db:
            if db:
                db.execute("DELETE FROM estimated_neurons WHERE day < ?", (day,))
