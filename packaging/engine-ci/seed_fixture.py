"""CI-only offline fixture writer, never bundled into the production app.

Run only in the reviewed engine environment while its server is stopped.
Credentials are generated synthetic values passed via stdin, never arguments.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import re
import uuid
from contextlib import redirect_stdout


def main():
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise RuntimeError("Oversized fixture input")
    config = json.loads(raw)
    if set(config) != {"fixture_marker", "username", "password", "research_id"}:
        raise RuntimeError("Unexpected fixture input fields")
    if not re.fullmatch(r"[a-f0-9]{64}",config["fixture_marker"]):
        raise RuntimeError("Invalid fixture marker")
    if not re.fullmatch(r"deepdesk_fixture_[a-f0-9]{12}",config["username"]):
        raise RuntimeError("Invalid fixture account")
    if not re.fullmatch(r"fixture1-&\+=%[a-f0-9]{64}",config["password"]):
        raise RuntimeError("Invalid synthetic password shape")
    if str(uuid.UUID(config["research_id"],version=4)) != config["research_id"]:
        raise RuntimeError("Invalid fixture research identifier")
    root = Path(os.environ["LDR_DATA_DIR"])
    marker = root.parent / "deepdesk-ci-fixture-only"
    if not root.is_absolute() or not marker.is_file() or marker.read_text() != config["fixture_marker"]:
        raise RuntimeError("Refusing a non-fixture data directory")
    if not config["username"].startswith("deepdesk_fixture_"):
        raise RuntimeError("Refusing a non-fixture account")
    os.environ["LDR_BOOTSTRAP_ALLOW_UNENCRYPTED"] = "false"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from local_deep_research.database.encrypted_db import db_manager
    from local_deep_research.database.session_context import get_user_db_session
    from local_deep_research.database.models.research import ResearchHistory, ResearchResource
    from local_deep_research.database.models.queued_research import QueuedResearch
    if not db_manager.has_encryption:
        raise RuntimeError("SQLCipher is required")
    if db_manager.open_user_database(config["username"], config["password"]) is None:
        raise RuntimeError("Could not unlock the synthetic fixture database")
    try:
        with get_user_db_session(config["username"], password=config["password"]) as session:
            if (session.query(ResearchHistory).count() != 0 or session.query(ResearchResource).count() != 0
                    or session.query(QueuedResearch).count() != 0):
                raise RuntimeError("Fixture account is not empty")
            session.add(ResearchHistory(
                id=config["research_id"], query="Synthetic CI persistence fixture; no model or search ran",
                mode="quick", status="completed", progress=100,
                created_at="2026-10-10T00:00:00+00:00", completed_at="2026-10-10T00:00:01+00:00",
                duration_seconds=1, title="Synthetic CI fixture",
                report_content="Synthetic CI evidence [1](https://fixture.invalid/evidence).",
                research_meta={"ci_synthetic_fixture": True, "iterations": 0}, progress_log=[],
            ))
            session.flush()
            session.add(ResearchResource(
                research_id=config["research_id"], title="Synthetic source, never fetched",
                url="https://fixture.invalid/evidence", source_type="ci_fixture",
                created_at="2026-10-10T00:00:00+00:00",
                resource_metadata={"original_data": {"index": "1", "title": "Synthetic source, never fetched"}},
            ))
            session.commit()
    finally:
        from local_deep_research.database.thread_local_session import cleanup_current_thread
        cleanup_current_thread()
        db_manager.close_all_databases()


if __name__ == "__main__":
    with redirect_stdout(sys.stderr):
        main()
    print(json.dumps({"status": "seeded", "synthetic": True, "model_executed": False, "provider_queried": False}))
