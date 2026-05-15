import queue
from types import SimpleNamespace

import comicarr
from comicarr import db
from comicarr.app.downloads import service as downloads_service
from comicarr.tables import comics, issues, metadata, nzblog


def test_find_completed_download_path_strips_nzb_extension(tmp_path):
    completed = tmp_path / "completed"
    release = completed / "Spawn.094.Digital.2000.TLK-EMPIRE-HD"
    release.mkdir(parents=True)

    found = downloads_service._find_completed_download_path(
        "Spawn.094.Digital.2000.TLK-EMPIRE-HD.nzb",
        roots=[completed],
    )

    assert found == release


def test_restore_pending_completed_downloads_queues_visible_snatched_item(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///%s" % (tmp_path / "comicarr.db"))
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)

    completed = tmp_path / "completed"
    release = completed / "Spawn.094.Digital.2000.TLK-EMPIRE-HD"
    release.mkdir(parents=True)

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            POST_PROCESSING=True,
            NZBGET_DIRECTORY=str(completed),
            CHECK_FOLDER=None,
        ),
    )
    monkeypatch.setattr(comicarr, "USE_NZBGET", False)
    monkeypatch.setattr(comicarr, "PP_QUEUE", queue.Queue())

    with engine.begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="4937",
                ComicName="Spawn",
                ComicYear="1992",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="83174",
                ComicID="4937",
                ComicName="Spawn",
                Issue_Number="94",
                Status="Snatched",
            )
        )
        conn.execute(
            nzblog.insert().values(
                IssueID="83174",
                NZBName="Spawn.094.Digital.2000.TLK-EMPIRE-HD",
                PROVIDER="Prowlarr",
            )
        )

    restored = downloads_service.restore_pending_completed_downloads()

    assert restored == {"restored": 1, "failed": 0, "missing": 0, "skipped": 0}
    queued = comicarr.PP_QUEUE.get_nowait()
    assert queued["issueid"] == "83174"
    assert queued["comicid"] == "4937"
    assert queued["nzb_name"] == release.name
    assert queued["nzb_folder"] == str(release)

    db.shutdown_engine()


def test_restore_pending_completed_downloads_queues_failed_history_item(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///%s" % (tmp_path / "comicarr.db"))
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)

    completed = tmp_path / "completed"
    completed.mkdir(parents=True)

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            POST_PROCESSING=True,
            NZBGET_DIRECTORY=str(completed),
            CHECK_FOLDER=None,
        ),
    )
    monkeypatch.setattr(comicarr, "USE_NZBGET", True)
    monkeypatch.setattr(comicarr, "PP_QUEUE", queue.Queue())
    monkeypatch.setattr(
        downloads_service,
        "_nzbget_history_lookup",
        lambda _names: {
            "Spawn.319.2021.Digital-Empire": {
                "Name": "Spawn.319.2021.Digital-Empire",
                "Status": "FAILURE/HEALTH",
                "DestDir": r"D:\intermediate\Spawn.319.2021.Digital-Empire.#8747",
            }
        },
    )

    with engine.begin() as conn:
        conn.execute(comics.insert().values(ComicID="4937", ComicName="Spawn", ComicYear="1992"))
        conn.execute(
            issues.insert().values(
                IssueID="865937",
                ComicID="4937",
                ComicName="Spawn",
                Issue_Number="319",
                Status="Snatched",
            )
        )
        conn.execute(
            nzblog.insert().values(
                IssueID="865937",
                NZBName="Spawn.319.2021.Digital-Empire",
                PROVIDER="Prowlarr",
                ID="download",
            )
        )

    restored = downloads_service.restore_pending_completed_downloads()

    assert restored == {"restored": 1, "failed": 1, "missing": 0, "skipped": 0}
    queued = comicarr.PP_QUEUE.get_nowait()
    assert queued["issueid"] == "865937"
    assert queued["failed"] is True
    assert queued["download_info"] == {"provider": "Prowlarr", "id": "download"}

    db.shutdown_engine()
