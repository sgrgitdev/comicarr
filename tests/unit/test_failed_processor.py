import queue
from types import SimpleNamespace

import comicarr
from comicarr import db
from comicarr.failed import FailedProcessor
from comicarr.process import Process
from comicarr.tables import comics, failed, issues, metadata, nzblog


def test_failed_processor_reads_nzblog_provider_column(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///%s" % (tmp_path / "comicarr.db"))
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(FAILED_AUTO=False))
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)

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
                IssueID="409014",
                ComicID="4937",
                ComicName="Spawn",
                Issue_Number="232",
                Status="Snatched",
            )
        )
        conn.execute(
            nzblog.insert().values(
                IssueID="409014",
                NZBName="Spawn.232.2013.1920px.Darkness-Empire",
                PROVIDER="Prowlarr",
                ID="download",
            )
        )

    result_queue = queue.Queue()
    processor = FailedProcessor(
        nzb_name="Spawn.232.2013.1920px.Darkness-Empire",
        nzb_folder=r"D:\intermediate\Spawn.232.2013.1920px.Darkness-Empire.#8796",
        id="download",
        prov="Prowlarr",
        queue=result_queue,
    )

    processor.Process()

    assert result_queue.get_nowait()[0]["mode"] == "stop"
    with engine.connect() as conn:
        issue = conn.execute(issues.select().where(issues.c.IssueID == "409014")).mappings().one()
        failed_row = conn.execute(failed.select().where(failed.c.IssueID == "409014")).mappings().one()

    assert issue["Status"] == "Failed"
    assert failed_row["Provider"] == "Prowlarr"

    db.shutdown_engine()


def test_failed_process_requeues_with_durable_search_job(monkeypatch):
    captured = {}
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

    class FakeFailedProcessor:
        def __init__(self, **kwargs):
            self.queue = kwargs["queue"]

        def Process(self):
            self.queue.put(
                [
                    {
                        "mode": "retry",
                        "issueid": "409014",
                        "comicid": "4937",
                        "comicname": "Spawn",
                        "issuenumber": "232",
                        "annchk": "no",
                    }
                ]
            )

    def fake_start_search_job(items, **kwargs):
        captured["items"] = items
        captured["kwargs"] = kwargs
        return {"success": True, "job_id": 1}

    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(FAILED_DOWNLOAD_HANDLING=True))
    monkeypatch.setattr(comicarr, "failed", SimpleNamespace(FailedProcessor=FakeFailedProcessor))
    monkeypatch.setattr("comicarr.app.search.jobs.start_search_job", fake_start_search_job)

    Process(
        "Spawn.232.2013.1920px.Darkness-Empire",
        r"D:\intermediate\Spawn.232.2013.1920px.Darkness-Empire.#8796",
        failed=True,
        issueid="409014",
        comicid="4937",
        apicall=True,
        download_info={"provider": "Prowlarr", "id": "download"},
    ).post_process()

    assert captured["items"] == [
        {
            "issueid": "409014",
            "comicid": "4937",
            "comicname": "Spawn",
            "issuenumber": "232",
            "manual": True,
        }
    ]
    assert captured["kwargs"]["kind"] == "failed-retry"
    assert captured["kwargs"]["priority"] is True
