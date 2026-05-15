import queue
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db
from comicarr.app.search import jobs
from comicarr.tables import comics, issues, metadata, search_job_items, search_jobs


@pytest.fixture
def durable_search_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///%s" % (tmp_path / "comicarr.db"))
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)

    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queue.Queue())
    monkeypatch.setattr(comicarr, "SEARCHLOCK", threading.Lock())
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            FAILED_DOWNLOAD_HANDLING=False,
            FAILED_AUTO=False,
            ANNUALS_ON=False,
            SEARCH_STORYARCS=False,
        ),
    )

    yield engine
    db.shutdown_engine()


def _insert_wanted_manga(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="manga-1",
                ComicName="Demon Slayer",
                ComicYear="2016",
                Type="manga",
                ContentType="manga",
            )
        )
        conn.execute(
            insert(issues).values(
                IssueID="chapter-1",
                ComicID="manga-1",
                ComicName="Demon Slayer",
                Issue_Number="1",
                Status="Wanted",
                ChapterNumber="1",
                VolumeNumber="1",
            )
        )


def test_force_search_job_is_durable_and_enqueued(durable_search_db):
    _insert_wanted_manga(durable_search_db)

    result = jobs.start_force_search_job()

    assert result["success"] is True
    assert result["total_items"] == 1
    assert comicarr.SEARCH_QUEUE.qsize() == 1

    queued = comicarr.SEARCH_QUEUE.get_nowait()
    assert queued["issueid"] == "chapter-1"
    assert queued["booktype"] == "manga"
    assert queued["search_job_id"] == result["job_id"]
    assert queued["search_job_item_id"]

    with durable_search_db.connect() as conn:
        job = conn.execute(select(search_jobs)).mappings().one()
        item = conn.execute(select(search_job_items)).mappings().one()

    assert job["status"] == "running"
    assert job["total_items"] == 1
    assert item["status"] == "queued"
    assert item["issueid"] == "chapter-1"


def test_job_item_running_and_finished_updates_job(durable_search_db):
    _insert_wanted_manga(durable_search_db)
    jobs.start_force_search_job()
    item = comicarr.SEARCH_QUEUE.get_nowait()

    assert jobs.mark_item_running(item["search_job_item_id"]) is True
    jobs.mark_item_finished(item["search_job_item_id"], result={"status": True, "provider": "Prowlarr"})

    with durable_search_db.connect() as conn:
        job = conn.execute(select(search_jobs)).mappings().one()
        job_item = conn.execute(select(search_job_items)).mappings().one()

    assert job["status"] == "completed"
    assert job_item["status"] == "found"
    assert job_item["provider"] == "Prowlarr"


def test_restore_pending_search_jobs_requeues_running_items(durable_search_db):
    _insert_wanted_manga(durable_search_db)
    result = jobs.start_force_search_job()
    item = comicarr.SEARCH_QUEUE.get_nowait()
    assert jobs.mark_item_running(item["search_job_item_id"]) is True

    restored = jobs.restore_pending_search_jobs()

    assert restored == {"restored": 1}
    assert comicarr.SEARCH_QUEUE.qsize() == 1
    restored_item = comicarr.SEARCH_QUEUE.get_nowait()
    assert restored_item["search_job_id"] == result["job_id"]
    assert restored_item["search_job_item_id"] == item["search_job_item_id"]

    with durable_search_db.connect() as conn:
        job_item = conn.execute(select(search_job_items)).mappings().one()
    assert job_item["status"] == "queued"
    assert job_item["reason"] == "Requeued after restart"
