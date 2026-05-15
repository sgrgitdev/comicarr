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


def _insert_wanted_manga_volume(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="manga-volume-1",
                ComicName="Demon Slayer",
                ComicYear="2016",
                Type="manga",
                ContentType="manga",
            )
        )
        conn.execute(
            insert(issues),
            [
                {
                    "IssueID": "chapter-1",
                    "ComicID": "manga-volume-1",
                    "ComicName": "Demon Slayer",
                    "Issue_Number": "1",
                    "Status": "Wanted",
                    "ChapterNumber": "1",
                    "VolumeNumber": "1",
                },
                {
                    "IssueID": "chapter-2",
                    "ComicID": "manga-volume-1",
                    "ComicName": "Demon Slayer",
                    "Issue_Number": "2",
                    "Status": "Wanted",
                    "ChapterNumber": "2",
                    "VolumeNumber": "1",
                },
            ],
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


def test_priority_search_job_goes_to_front_of_queue(durable_search_db):
    first = {
        "issueid": "bulk-1",
        "comicid": "comic-1",
        "comicname": "Bulk Comic",
        "issuenumber": "1",
    }
    priority = {
        "issueid": "priority-1",
        "comicid": "comic-2",
        "comicname": "New Comic",
        "issuenumber": "1",
    }

    jobs.start_search_job([first], kind="bulk", source="test", title="Bulk")
    jobs.start_search_job([priority], kind="series", source="test", title="Priority", priority=True)

    assert comicarr.SEARCH_QUEUE.get_nowait()["issueid"] == "priority-1"
    assert comicarr.SEARCH_QUEUE.get_nowait()["issueid"] == "bulk-1"


def test_manga_volume_chapters_are_grouped_into_one_volume_search(durable_search_db):
    _insert_wanted_manga_volume(durable_search_db)

    result = jobs.start_comic_search_job("manga-volume-1")

    assert result["success"] is True
    assert result["total_items"] == 1
    queued = comicarr.SEARCH_QUEUE.get_nowait()
    assert queued["issueid"] == "chapter-2"
    assert queued["issuenumber"] == "1"
    assert queued["chapter_number"] is None
    assert queued["volume_number"] == "1"
    assert queued["manga_pack"] == "volume"


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


def test_start_comic_search_job_can_mark_series_wanted(durable_search_db):
    with durable_search_db.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="comic-1",
                ComicName="Spawn",
                ComicYear="1992",
                Type="Print",
                ContentType="comic",
            )
        )
        conn.execute(
            insert(issues),
            [
                {
                    "IssueID": "issue-1",
                    "ComicID": "comic-1",
                    "ComicName": "Spawn",
                    "Issue_Number": "1",
                    "Status": "Skipped",
                },
                {
                    "IssueID": "issue-2",
                    "ComicID": "comic-1",
                    "ComicName": "Spawn",
                    "Issue_Number": "2",
                    "Status": "Downloaded",
                },
            ],
        )

    result = jobs.start_comic_search_job("comic-1", mark_wanted=True)

    assert result["success"] is True
    assert result["total_items"] == 1
    assert result["marked_wanted"]["issues"] == 1
    queued = comicarr.SEARCH_QUEUE.get_nowait()
    assert queued["issueid"] == "issue-1"

    with durable_search_db.connect() as conn:
        statuses = {
            row["IssueID"]: row["Status"]
            for row in conn.execute(select(issues.c.IssueID, issues.c.Status)).mappings().all()
        }

    assert statuses == {"issue-1": "Wanted", "issue-2": "Downloaded"}
