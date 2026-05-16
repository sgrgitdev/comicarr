import queue
from types import SimpleNamespace

import comicarr
from comicarr.app.search import service as search_service


def test_search_queue_does_not_refresh_local_folder_cache(monkeypatch):
    calls = []

    class FakeFileHandlers:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def walk_the_walk(self, allow_refresh=True):
            calls.append(allow_refresh)
            return {"status": False}

    monkeypatch.setattr(comicarr, "SEARCHLOCK", SimpleNamespace(locked=lambda: False))
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)
    monkeypatch.setattr(comicarr, "PACK_ISSUEIDS_DONT_QUEUE", {})
    monkeypatch.setattr(comicarr, "DDL_QUEUED", [])
    monkeypatch.setattr(comicarr, "filers", SimpleNamespace(FileHandlers=FakeFileHandlers))
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=lambda *args, **kwargs: {"status": False}))
    monkeypatch.setattr(search_service.time, "sleep", lambda _seconds: None)

    work_queue = queue.Queue()
    work_queue.put({"issueid": "issue-1", "comicid": "comic-1"})
    work_queue.put("exit")

    search_service.search_queue(work_queue)

    assert calls == [False]
