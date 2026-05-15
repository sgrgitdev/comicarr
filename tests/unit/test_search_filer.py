from types import SimpleNamespace

import comicarr
from comicarr import search_filer


def _configure_search_filer(monkeypatch):
    comicarr.CONFIG = SimpleNamespace(
        IGNORE_SEARCH_WORDS=[],
        USE_MINSIZE=False,
        USE_MAXSIZE=False,
        MINSIZE="0",
        MAXSIZE="0",
        IGNORE_COVERS=False,
        ANNUALS_ON=True,
        READ2FILENAME=False,
        FOLDER_SCAN_LOG_VERBOSE=False,
    )
    comicarr.OS_DETECT = "Windows"
    comicarr.ISSUE_EXCEPTIONS = []
    comicarr.LOG_LEVEL = 0
    comicarr.COMICINFO = []
    monkeypatch.setattr(search_filer.search, "generate_id", lambda _provider, _link, _comic: "generated-id")


def _spawn_search_info():
    return {
        "ComicName": "Spawn",
        "nzbprov": "dognzb",
        "RSS": "no",
        "UseFuzzy": "1",
        "StoreDate": "2026-05-01",
        "IssueDate": "2026-05-01",
        "digitaldate": "0000-00-00",
        "booktype": "Print",
        "content_type": "comic",
        "ignore_booktype": False,
        "SeriesYear": "1992",
        "ComicVersion": "1",
        "IssDateFix": "no",
        "ComicYear": "2026",
        "IssueID": "issue-375",
        "ComicID": "spawn",
        "IssueNumber": "375",
        "manual": False,
        "newznab_host": None,
        "torznab_host": None,
        "oneoff": False,
        "tmpprov": "NZBFinder",
        "SARC": None,
        "IssueArcID": None,
        "cmloopit": 1,
        "findcomiciss": "375",
        "intIss": 375000,
        "chktpb": 0,
        "provider_stat": {"type": "newznab"},
        "smode": "series",
    }


def _comic_search_info(name, issue, issue_year, series_year=None):
    info = _spawn_search_info()
    info.update(
        {
            "ComicName": name,
            "ComicID": name.lower().replace(" ", "-"),
            "IssueID": "%s-%s" % (name.lower().replace(" ", "-"), issue),
            "IssueNumber": issue,
            "ComicYear": issue_year,
            "SeriesYear": series_year or issue_year,
            "StoreDate": "%s-01-01" % issue_year,
            "IssueDate": "%s-01-01" % issue_year,
            "findcomiciss": issue,
            "intIss": int(issue) * 1000,
            "tmpprov": "NZBgeek",
        }
    )
    return info


def test_normalize_title_for_parser_removes_release_prefix_and_no_marker():
    title = "Image.Comics.Spawn.No.375.2026.Retail.Comic.eBook-BitBook"

    assert search_filer.normalize_title_for_parser(title, "Spawn") == "Spawn #375 2026 Retail Comic eBook-BitBook"


def test_checker_matches_indexer_no_issue_format(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "Image.Comics.Spawn.No.375.2026.Retail.Comic.eBook-BitBook",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/123",
        "site": "NZBFinder",
    }

    matches = search_filer.search_check().checker([entry], _spawn_search_info())

    assert len(matches) == 1
    assert matches[0]["IssueID"] == "issue-375"
    assert matches[0]["downloadit"] is True


def test_checker_matches_exact_power_fantasy_release(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "The.Power.Fantasy.001.2024.Digital.Mephisto-Empire",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/pf-1",
        "site": "NZBgeek",
    }

    matches = search_filer.search_check().checker([entry], _comic_search_info("The Power Fantasy", "1", "2024"))

    assert len(matches) == 1
    assert matches[0]["IssueNumber"] == "1"
    assert matches[0]["downloadit"] is True


def test_checker_matches_original_series_issue_with_volume_marker(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "The Ultimates - Vol.1 06 (2002) (Digital) (TheHand-Empire)",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/ultimates-6",
        "site": "NZBgeek",
    }

    matches = search_filer.search_check().checker([entry], _comic_search_info("The Ultimates", "6", "2002"))

    assert len(matches) == 1
    assert matches[0]["IssueNumber"] == "6"
    assert matches[0]["downloadit"] is True


def test_checker_matches_original_series_issue_with_compact_volume_marker(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "The.Ultimates-Vol.1.06.2002.Digital.Thehand-EMPIRE",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/ultimates-6-compact",
        "site": "NZBgeek",
    }

    matches = search_filer.search_check().checker([entry], _comic_search_info("The Ultimates", "6", "2002"))

    assert len(matches) == 1
    assert matches[0]["IssueNumber"] == "6"
    assert matches[0]["downloadit"] is True


def test_normalize_title_for_parser_rewrites_collected_volume():
    title = "Image.Comics.-.The.Power.Fantasy.Vol.01.2025.Retail.Comic.eBook-BitBook"

    assert search_filer.normalize_title_for_parser(title, "The Power Fantasy") == "The Power Fantasy v01 (2025)"


def test_checker_matches_collected_volume_fallback(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "Image.Comics.-.The.Power.Fantasy.Vol.02.2025.Retail.Comic.eBook-BitBook",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/pf-vol-2",
        "site": "NZBFinder",
    }
    info = _comic_search_info("The Power Fantasy", "6", "2025")
    info["volume_pack_search"] = True
    info["expected_collected_volume"] = 2

    matches = search_filer.search_check().checker([entry], info)

    assert len(matches) == 1
    assert matches[0]["IssueNumber"] == "6"
    assert matches[0]["nzbtitle"] == entry["title"]
    assert matches[0]["downloadit"] is True


def test_checker_rejects_unexpected_collected_volume(monkeypatch):
    _configure_search_filer(monkeypatch)
    entry = {
        "title": "Image.Comics.-.The.Power.Fantasy.Vol.03.2026.Retail.Comic.eBook-BitBook",
        "updated": "Fri, 15 May 2026 00:00:00 +0000",
        "link": "http://example/nzb",
        "id": "details/pf-vol-3",
        "site": "NZBFinder",
    }
    info = _comic_search_info("The Power Fantasy", "6", "2025")
    info["volume_pack_search"] = True
    info["expected_collected_volume"] = 2

    matches = search_filer.search_check().checker([entry], info)

    assert matches == []
