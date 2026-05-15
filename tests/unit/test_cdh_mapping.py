"""Unit tests for completed-download path mapping."""

import pathlib

from comicarr.cdh_mapping import CDH_MAP


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
