"""Run only after exact dependency review/install; no upstream import/network."""
from __future__ import annotations
import json
from pathlib import Path
import secrets
import tempfile


def main():
    from sqlcipher3 import dbapi2 as sqlcipher
    import sqlite3
    with tempfile.TemporaryDirectory(prefix="deepdesk-sqlcipher-fixture-") as temporary:
        path = Path(temporary) / "fixture.db"
        key, wrong = secrets.token_hex(32), secrets.token_hex(32)
        connection = sqlcipher.connect(str(path))
        try:
            connection.execute("PRAGMA key='" + key + "'")
            version = connection.execute("PRAGMA cipher_version").fetchone()
            if not version or not version[0]:
                raise RuntimeError("Missing SQLCipher encryption")
            connection.execute("CREATE TABLE fixture (value TEXT NOT NULL)")
            connection.execute("INSERT INTO fixture VALUES (?)", ("synthetic proof",))
            connection.commit()
        finally:
            connection.close()
        if path.read_bytes().startswith(b"SQLite format 3"):
            raise RuntimeError("Plaintext database header")
        for driver, candidate in ((sqlcipher, wrong), (sqlite3, None)):
            connection = driver.connect(str(path))
            try:
                if candidate:
                    connection.execute("PRAGMA key='" + candidate + "'")
                try:
                    connection.execute("SELECT * FROM fixture").fetchall()
                except driver.DatabaseError:
                    pass
                else:
                    raise RuntimeError("Database unexpectedly readable without correct key")
            finally:
                connection.close()
        connection = sqlcipher.connect(str(path))
        try:
            connection.execute("PRAGMA key='" + key + "'")
            if connection.execute("SELECT value FROM fixture").fetchone() != ("synthetic proof",):
                raise RuntimeError("Correct-key reopen failed")
        finally:
            connection.close()
    print(json.dumps({"status": "passed", "sqlcipher": version[0], "checks": [
        "encrypted-header", "correct-key-reopen", "wrong-key-refused", "ordinary-sqlite-refused"]}))


if __name__ == "__main__":
    main()
