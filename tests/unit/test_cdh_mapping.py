"""Unit tests for completed-download path mapping."""

import pathlib
from types import SimpleNamespace

import comicarr
from comicarr.cdh_mapping import CDH_MAP
from comicarr.nzbget import NZBGet


def test_nzbget_windows_completed_path_maps_without_duplicate_completed_dir():
    mapper = object.__new__(CDH_MAP)
    mapper.storage = pathlib.PureWindowsPath(
        r"D:\downloads\completed\Spawn.371.[2025].[3.covers].[Digital-Empire]"
    )
    mapper.sab_dir = pathlib.PurePosixPath("/downloads/completed")

    remote_base = mapper._path_like_storage(r"D:\downloads\completed")
    relative_path = mapper.storage.relative_to(remote_base)
    final_path = mapper._join_destination(relative_path)

    assert str(final_path) == "/downloads/completed/Spawn.371.[2025].[3.covers].[Digital-Empire]"


def test_nzbget_success_with_rounded_size_still_maps_to_container_path(monkeypatch):
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

    class FakeCDHMap:
        def __init__(self, filepath, **_kwargs):
            self.filepath = pathlib.PureWindowsPath(filepath)

        def the_sequence(self):
            return pathlib.PurePosixPath("/downloads/completed") / self.filepath.name

    class FakeServer:
        def history(self, _include_hidden):
            return [
                {
                    "NZBID": 8854,
                    "Name": "Spawn.094.Digital.2000.TLK-EMPIRE-HD",
                    "NZBName": "Spawn.094.Digital.2000.TLK-EMPIRE-HD",
                    "Status": "SUCCESS/UNPACK",
                    "FileSizeMB": 39,
                    "DownloadedSizeMB": 41,
                    "DestDir": r"D:\downloads\completed\Spawn.094.Digital.2000.TLK-EMPIRE-HD",
                    "ScriptStatuses": [],
                    "Parameters": [],
                }
            ]

        def config(self):
            return [
                {"Name": "DestDir", "Value": r"D:\downloads\completed"},
                {"Name": "AppendCategoryDir", "Value": "no"},
            ]

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            NZBGET_DIRECTORY="/downloads/completed",
            NZBGET_CATEGORY=None,
        ),
    )
    monkeypatch.setattr("comicarr.nzbget.cdh_mapping.CDH_MAP", FakeCDHMap)
    client = object.__new__(NZBGet)
    client.server = FakeServer()

    result = client.historycheck(
        {
            "NZBID": 8854,
            "issueid": "83174",
            "comicid": "4937",
            "download_info": {"provider": "test", "id": "download"},
        }
    )

    assert result["status"] is True
    assert str(result["location"]) == "/downloads/completed/Spawn.094.Digital.2000.TLK-EMPIRE-HD"
