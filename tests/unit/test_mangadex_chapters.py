from types import SimpleNamespace

import comicarr
from comicarr import mangadex


def test_get_all_chapters_uses_aggregate_for_missing_volumes(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(MANGADEX_LANGUAGES="en"))
    mangadex._CHAPTER_CACHE.clear()

    def fake_make_request(endpoint, params=None, method="GET"):
        assert endpoint == "/manga/manga-1/aggregate"
        return {
            "result": "ok",
            "volumes": {
                "1": {
                    "volume": "1",
                    "chapters": {
                        "1": {"chapter": "1"},
                        "2": {"chapter": "2"},
                    },
                }
            },
        }

    monkeypatch.setattr(mangadex, "_make_request", fake_make_request)
    monkeypatch.setattr(
        mangadex,
        "get_manga_chapters",
        lambda *args, **kwargs: {
            "chapters": [
                {
                    "id": "chapter-1",
                    "chapter": "1",
                    "volume": None,
                    "title": "Chapter 1",
                }
            ],
            "pagination": {"total": 1, "limit": 100, "offset": 0, "returned": 1},
        },
    )

    chapters = mangadex.get_all_chapters("md-manga-1")

    assert chapters == [
        {
            "id": "chapter-1",
            "chapter": "1",
            "volume": "1",
            "title": "Chapter 1",
        },
        {
            "id": "unavailable-manga-1-2",
            "chapter": "2",
            "volume": "1",
            "title": None,
            "language": "en",
            "pages": 0,
            "publish_at": None,
            "created_at": None,
            "updated_at": None,
            "scanlation_group": None,
            "external_url": None,
            "unavailable": True,
        },
    ]
