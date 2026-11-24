"""Short, read-only connections to Phase 5 SQLite stores."""

from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from urllib.parse import quote


class SourceUnavailable(Exception):
    pass


@contextmanager
def read_database(path):
    path = Path(path).resolve()
    # Opening a WAL database can update or create its shared-memory sidecar
    # even with mode=ro. The Phase 5 writers use rollback journals.
    with path.open("rb") as handle:
        header = handle.read(20)
    if (2 in header[18:20] or path.with_name(path.name + "-wal").exists()
            or path.with_name(path.name + "-shm").exists()):
        raise SourceUnavailable("wal_snapshot_required")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        yield connection
