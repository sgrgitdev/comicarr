#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Durable search jobs for the legacy search worker.

The provider matching and download dispatch still live in search.py.  This
module gives that legacy worker a persistent job/item layer so Activity can
explain what is happening and queued searches can survive a restart.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import desc, func, insert, or_, select, update

import comicarr
from comicarr import db, logger
from comicarr.tables import annuals, comics, issues, search_job_items, search_jobs, storyarcs

ACTIVE_ITEM_STATUSES = {"queued", "running"}
TERMINAL_JOB_STATUSES = {"completed", "completed_with_errors", "cancelled", "empty", "error"}
PROTECTED_ISSUE_STATUSES = {"Downloaded", "Snatched", "Archived"}
DEFAULT_STALE_RUNNING_SECONDS = 30 * 60


def _now() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _stale_running_seconds() -> int:
    try:
        return max(60, int(os.environ.get("COMICARR_SEARCH_STALE_SECONDS", DEFAULT_STALE_RUNNING_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_STALE_RUNNING_SECONDS


def _cutoff_iso(seconds: int) -> str:
    return (
        datetime.datetime.utcnow() - datetime.timedelta(seconds=seconds)
    ).replace(microsecond=0).isoformat() + "Z"


def _is_stale_running_item(item: dict[str, Any], seconds: int | None = None) -> bool:
    if item.get("status") != "running":
        return False
    seconds = _stale_running_seconds() if seconds is None else int(seconds)
    started_at = item.get("started_at")
    if not started_at:
        return True
    return str(started_at) <= _cutoff_iso(seconds)


def _timeout_reason(seconds: int) -> str:
    minutes = max(1, (int(seconds) + 59) // 60)
    return "Search timed out after %s minute(s); retry when the provider is responsive" % minutes


def _row_get(row: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not row:
        return default
    return row.get(key, default)


def _queue_booktype(content_type: str | None, booktype: str | None) -> str | None:
    if str(content_type or "").lower() == "manga" or str(booktype or "").lower() == "manga":
        return "manga"
    return booktype


def _item_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "comicname": item.get("comicname"),
        "seriesyear": item.get("seriesyear"),
        "issuenumber": item.get("issuenumber"),
        "issueid": item.get("issueid"),
        "comicid": item.get("comicid"),
        "booktype": item.get("booktype"),
        "content_type": item.get("content_type"),
        "chapter_number": item.get("chapter_number"),
        "volume_number": item.get("volume_number"),
        "manga_pack": item.get("manga_pack"),
        "manual": item.get("manual", False),
        "search_job_id": item.get("search_job_id"),
        "search_job_item_id": item.get("search_job_item_id"),
    }


def _enqueue_payload(payload: dict[str, Any], priority: bool = False) -> None:
    queue_obj = comicarr.SEARCH_QUEUE
    if priority and hasattr(queue_obj, "not_full") and hasattr(queue_obj, "queue"):
        with queue_obj.not_full:
            queue_obj.queue.appendleft(payload)
            queue_obj.unfinished_tasks += 1
            queue_obj.not_empty.notify()
        return
    queue_obj.put(payload)


def _job_counts(conn, job_id: int) -> Counter:
    rows = conn.execute(
        select(search_job_items.c.status, func.count().label("count"))
        .where(search_job_items.c.job_id == job_id)
        .group_by(search_job_items.c.status)
    )
    return Counter({row.status: row.count for row in rows})


def _refresh_job_status(conn, job_id: int) -> None:
    counts = _job_counts(conn, job_id)
    total = sum(counts.values())
    now = _now()

    if total == 0:
        status = "empty"
        message = "No matching wanted issues were found"
        finished_at = now
    elif counts.get("cancelled", 0) == total:
        status = "cancelled"
        message = "Search job cancelled"
        finished_at = now
    elif counts.get("queued", 0) or counts.get("running", 0):
        status = "running"
        message = "Search job is running"
        finished_at = None
    elif counts.get("error", 0):
        status = "completed_with_errors"
        message = "Search job completed with errors"
        finished_at = now
    else:
        status = "completed"
        message = "Search job completed"
        finished_at = now

    values = {"status": status, "message": message}
    if status not in {"queued", "running"}:
        values["finished_at"] = finished_at
    conn.execute(update(search_jobs).where(search_jobs.c.id == job_id).values(**values))


def _mark_stale_running_items(conn, older_than_seconds: int | None = None, limit: int = 500) -> int:
    seconds = _stale_running_seconds() if older_than_seconds is None else max(60, int(older_than_seconds))
    cutoff = _cutoff_iso(seconds)
    now = _now()
    reason = _timeout_reason(seconds)

    rows = conn.execute(
        select(search_job_items.c.id, search_job_items.c.job_id)
        .where(
            search_job_items.c.status == "running",
            or_(search_job_items.c.started_at.is_(None), search_job_items.c.started_at <= cutoff),
        )
        .limit(limit)
    ).all()
    if not rows:
        return 0

    job_ids = sorted({int(row.job_id) for row in rows})
    item_ids = [int(row.id) for row in rows]
    conn.execute(
        update(search_job_items)
        .where(search_job_items.c.id.in_(item_ids))
        .values(status="error", finished_at=now, result="error", reason=reason, error=reason)
    )
    for job_id in job_ids:
        _refresh_job_status(conn, job_id)

    logger.warn("[SEARCH-JOB] Marked %s stale running search item(s) as timed out", len(item_ids))
    return len(item_ids)


def mark_stale_running_items(older_than_seconds: int | None = None) -> dict[str, Any]:
    with db.get_engine().begin() as conn:
        stale = _mark_stale_running_items(conn, older_than_seconds=older_than_seconds)
    return {"stale": stale}


def _create_job(kind: str, source: str, title: str, total_items: int) -> int:
    now = _now()
    with db.get_engine().begin() as conn:
        result = conn.execute(
            insert(search_jobs).values(
                job_key=str(uuid.uuid4()),
                kind=kind,
                source=source,
                title=title,
                status="queued" if total_items else "empty",
                created_at=now,
                total_items=total_items,
                message="Queued %s item(s)" % total_items if total_items else "No matching items",
                cancel_requested=0,
            )
        )
        return int(result.inserted_primary_key[0])


def _create_job_items(job_id: int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    now = _now()
    with db.get_engine().begin() as conn:
        for position, item in enumerate(items, start=1):
            payload = _item_payload(item)
            result = conn.execute(
                insert(search_job_items).values(
                    job_id=job_id,
                    position=position,
                    issueid=payload.get("issueid"),
                    comicid=payload.get("comicid"),
                    comicname=payload.get("comicname"),
                    seriesyear=payload.get("seriesyear"),
                    issuenumber=payload.get("issuenumber"),
                    booktype=payload.get("booktype"),
                    content_type=payload.get("content_type"),
                    chapter_number=payload.get("chapter_number"),
                    volume_number=payload.get("volume_number"),
                    status="queued",
                    attempts=0,
                    created_at=now,
                    payload_json=json.dumps(payload, sort_keys=True),
                )
            )
            item_id = int(result.inserted_primary_key[0])
            payload["search_job_id"] = job_id
            payload["search_job_item_id"] = item_id
            created.append(payload)

        conn.execute(update(search_jobs).where(search_jobs.c.id == job_id).values(total_items=len(created)))
        _refresh_job_status(conn, job_id)
    return created


def _issue_rows(
    issue_ids: list[str] | None = None,
    wanted_only: bool = False,
    comic_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    status_values = ["Wanted"]
    if getattr(comicarr.CONFIG, "FAILED_DOWNLOAD_HANDLING", False) and getattr(comicarr.CONFIG, "FAILED_AUTO", False):
        status_values.append("Failed")

    stmt = (
        select(
            issues.c.IssueID,
            issues.c.Issue_Number,
            issues.c.IssueName,
            issues.c.IssueDate,
            issues.c.ReleaseDate,
            issues.c.DigitalDate,
            issues.c.DateAdded,
            issues.c.Status,
            issues.c.ComicID,
            issues.c.ChapterNumber,
            issues.c.VolumeNumber,
            comics.c.ComicName,
            comics.c.ComicYear,
            comics.c.Type.label("BookType"),
            comics.c.Corrected_Type,
            comics.c.ContentType,
        )
        .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID))
        .order_by(desc(issues.c.DateAdded), desc(issues.c.IssueDate), desc(issues.c.Issue_Number))
    )

    if issue_ids is not None:
        stmt = stmt.where(issues.c.IssueID.in_([str(i) for i in issue_ids]))
    if comic_id is not None:
        stmt = stmt.where(issues.c.ComicID == str(comic_id))
    if wanted_only:
        stmt = stmt.where(issues.c.Status.in_(status_values))
    if limit is not None:
        stmt = stmt.limit(int(limit))

    return db.select_all(stmt)


def _annual_rows(
    wanted_only: bool = False,
    comic_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not getattr(comicarr.CONFIG, "ANNUALS_ON", False):
        return []
    stmt = (
        select(
            annuals.c.IssueID,
            annuals.c.Issue_Number,
            annuals.c.IssueName,
            annuals.c.IssueDate,
            annuals.c.ReleaseDate,
            annuals.c.DigitalDate,
            annuals.c.DateAdded,
            annuals.c.Status,
            annuals.c.ComicID,
            comics.c.ComicName,
            comics.c.ComicYear,
            comics.c.Type.label("BookType"),
            comics.c.Corrected_Type,
            comics.c.ContentType,
        )
        .select_from(comics.join(annuals, comics.c.ComicID == annuals.c.ComicID))
        .where(annuals.c.Deleted != 1)
        .order_by(desc(annuals.c.DateAdded), desc(annuals.c.IssueDate), desc(annuals.c.Issue_Number))
    )
    if comic_id is not None:
        stmt = stmt.where(annuals.c.ComicID == str(comic_id))
    if wanted_only:
        stmt = stmt.where(annuals.c.Status == "Wanted")
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return db.select_all(stmt)


def _story_arc_rows(wanted_only: bool = False) -> list[dict[str, Any]]:
    if not getattr(comicarr.CONFIG, "SEARCH_STORYARCS", False):
        return []
    stmt = select(
        storyarcs.c.IssueArcID.label("IssueID"),
        storyarcs.c.IssueNumber.label("Issue_Number"),
        storyarcs.c.IssueName,
        storyarcs.c.IssueDate,
        storyarcs.c.ReleaseDate,
        storyarcs.c.DigitalDate,
        storyarcs.c.DateAdded,
        storyarcs.c.Status,
        storyarcs.c.ComicID,
        storyarcs.c.ComicName,
        storyarcs.c.SeriesYear.label("ComicYear"),
        storyarcs.c.Type.label("BookType"),
    ).order_by(desc(storyarcs.c.DateAdded), desc(storyarcs.c.IssueDate), desc(storyarcs.c.IssueNumber))
    if wanted_only:
        stmt = stmt.where(storyarcs.c.Status == "Wanted")
    return db.select_all(stmt)


def _rows_to_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_manga_volumes: set[tuple[str, str]] = set()
    for row in rows:
        issueid = str(row.get("IssueID") or "")
        if not issueid or issueid in seen:
            continue

        booktype = row.get("Corrected_Type") or row.get("BookType")
        content_type = row.get("ContentType") or "comic"
        volume_number = _row_get(row, "VolumeNumber")
        chapter_number = _row_get(row, "ChapterNumber")
        is_manga = str(content_type or "").lower() == "manga" or str(booktype or "").lower() == "manga"

        manga_pack = None
        if is_manga and volume_number not in (None, "", "None"):
            volume_key = (str(row.get("ComicID") or ""), str(volume_number))
            if volume_key in seen_manga_volumes:
                seen.add(issueid)
                continue
            seen_manga_volumes.add(volume_key)
            manga_pack = "volume"
            chapter_number = None

        seen.add(issueid)
        items.append(
            {
                "comicname": row.get("ComicName"),
                "seriesyear": row.get("ComicYear"),
                "issuenumber": str(volume_number) if manga_pack == "volume" else row.get("Issue_Number"),
                "issueid": issueid,
                "comicid": row.get("ComicID"),
                "booktype": _queue_booktype(content_type, booktype),
                "content_type": content_type,
                "chapter_number": chapter_number,
                "volume_number": volume_number,
                "manga_pack": manga_pack,
            }
        )
    return items


def start_force_search_job(ctx=None) -> dict[str, Any]:
    """Create and enqueue a durable search job for all wanted items."""
    rows = _issue_rows(wanted_only=True)
    rows.extend(_annual_rows(wanted_only=True))
    rows.extend(_story_arc_rows(wanted_only=True))
    items = _rows_to_items(rows)
    return start_search_job(items, kind="force", source="wanted", title="Search all wanted")


def start_issue_search_job(
    issue_ids: list[str],
    title: str = "Search selected issues",
    priority: bool = True,
) -> dict[str, Any]:
    """Create and enqueue a durable search job for explicit issue IDs."""
    rows = _issue_rows(issue_ids=issue_ids, wanted_only=False)
    items = _rows_to_items(rows)
    found_ids = {item["issueid"] for item in items}
    missing = [str(issue_id) for issue_id in issue_ids if str(issue_id) not in found_ids]
    result = start_search_job(items, kind="manual", source="selected", title=title, priority=priority)
    result["missing_issue_ids"] = missing
    return result


def mark_comic_items_wanted(comic_id: str, include_annuals: bool = True) -> dict[str, int]:
    """Mark searchable missing items in a series as Wanted."""
    now = _now()
    comic_id = str(comic_id)
    wanted_issues = 0
    wanted_annuals = 0

    with db.get_engine().begin() as conn:
        result = conn.execute(
            update(issues)
            .where(issues.c.ComicID == comic_id, issues.c.Status.notin_(PROTECTED_ISSUE_STATUSES))
            .values(Status="Wanted", DateAdded=now)
        )
        wanted_issues = int(result.rowcount or 0)

        if include_annuals and getattr(comicarr.CONFIG, "ANNUALS_ON", False):
            result = conn.execute(
                update(annuals)
                .where(
                    annuals.c.ComicID == comic_id,
                    annuals.c.Deleted != 1,
                    annuals.c.Status.notin_(PROTECTED_ISSUE_STATUSES),
                )
                .values(Status="Wanted", DateAdded=now)
            )
            wanted_annuals = int(result.rowcount or 0)

    return {"issues": wanted_issues, "annuals": wanted_annuals}


def start_comic_search_job(
    comic_id: str,
    title: str | None = None,
    mark_wanted: bool = False,
    include_annuals: bool = True,
    limit: int | None = None,
    priority: bool = True,
) -> dict[str, Any]:
    """Create and enqueue a durable search job for one series."""
    marked = {"issues": 0, "annuals": 0}
    if mark_wanted:
        marked = mark_comic_items_wanted(comic_id, include_annuals=include_annuals)

    rows = _issue_rows(wanted_only=True, comic_id=str(comic_id), limit=limit)
    if include_annuals:
        rows.extend(_annual_rows(wanted_only=True, comic_id=str(comic_id), limit=limit))

    items = _rows_to_items(rows)
    if title is None:
        title = "Search wanted for %s" % comic_id

    result = start_search_job(items, kind="series", source="wanted", title=title, priority=priority)
    result["comic_id"] = str(comic_id)
    result["marked_wanted"] = marked
    return result


def start_search_job(
    items: list[dict[str, Any]],
    kind: str,
    source: str,
    title: str,
    priority: bool = False,
) -> dict[str, Any]:
    job_id = _create_job(kind=kind, source=source, title=title, total_items=len(items))
    queued_items = _create_job_items(job_id, items)
    payloads = reversed(queued_items) if priority else queued_items
    for payload in payloads:
        _enqueue_payload(payload, priority=priority)

    logger.info("[SEARCH-JOB] Created %s job %s with %s item(s)", kind, job_id, len(queued_items))
    return {
        "success": True,
        "job_id": job_id,
        "status": "queued" if queued_items else "empty",
        "total_items": len(queued_items),
        "message": "Queued %s item(s)" % len(queued_items) if queued_items else "No matching items to search",
    }


def mark_item_running(item_id: int | None) -> bool:
    if not item_id:
        return True
    now = _now()
    with db.get_engine().begin() as conn:
        item = conn.execute(select(search_job_items).where(search_job_items.c.id == int(item_id))).mappings().first()
        if item is None:
            return True
        if item["status"] == "cancelled":
            return False
        conn.execute(
            update(search_job_items)
            .where(search_job_items.c.id == int(item_id))
            .values(
                status="running",
                started_at=now,
                finished_at=None,
                attempts=int(item.get("attempts") or 0) + 1,
                error=None,
                reason=None,
            )
        )
        conn.execute(
            update(search_jobs)
            .where(search_jobs.c.id == int(item["job_id"]))
            .values(status="running", started_at=now, finished_at=None, message="Search job is running")
        )
    return True


def mark_item_finished(item_id: int | None, result: Any = None, error: Exception | None = None) -> None:
    if not item_id:
        return

    status = "not_found"
    reason = "No matching release found"
    provider = None
    download_id = None

    if error is not None:
        status = "error"
        reason = str(error)
    elif result == "local":
        status = "local"
        reason = "Local file found and sent to post-processing"
    elif result == "skipped":
        status = "skipped"
        reason = "Skipped by search queue"
    elif isinstance(result, dict):
        if result.get("status") is True:
            status = "found"
            reason = "Release sent to download client"
            provider = result.get("provider") or result.get("prov")
            info = result.get("info") if isinstance(result.get("info"), dict) else {}
            download_id = info.get("id") or info.get("nzb_id") or info.get("download_id")
        elif result.get("status") == "IN PROGRESS":
            status = "queued"
            reason = "Search lock was busy; item requeued"
        else:
            reason = result.get("reason") or result.get("error") or reason

    values = {
        "status": status,
        "finished_at": _now(),
        "result": status,
        "reason": reason,
        "error": str(error) if error is not None else None,
        "provider": provider,
        "download_id": download_id,
    }
    if status == "queued":
        values["finished_at"] = None

    with db.get_engine().begin() as conn:
        item = conn.execute(
            select(search_job_items.c.job_id, search_job_items.c.status).where(search_job_items.c.id == int(item_id))
        ).first()
        if item is None:
            return
        if item.status == "cancelled":
            return
        conn.execute(update(search_job_items).where(search_job_items.c.id == int(item_id)).values(**values))
        _refresh_job_status(conn, int(item.job_id))


def retry_job_item(item_id: int) -> dict[str, Any]:
    with db.get_engine().begin() as conn:
        item = conn.execute(select(search_job_items).where(search_job_items.c.id == int(item_id))).mappings().first()
        if item is None:
            return {"success": False, "error": "Search job item not found"}
        if item["status"] == "running" and not _is_stale_running_item(item):
            return {"success": False, "error": "Search job item is already running"}
        conn.execute(
            update(search_job_items)
            .where(search_job_items.c.id == int(item_id))
            .values(status="queued", started_at=None, finished_at=None, result=None, reason="Retry queued", error=None)
        )
        conn.execute(
            update(search_jobs)
            .where(search_jobs.c.id == int(item["job_id"]))
            .values(status="running", finished_at=None, message="Retry queued")
        )

    payload = json.loads(item.get("payload_json") or "{}")
    payload["search_job_id"] = int(item["job_id"])
    payload["search_job_item_id"] = int(item_id)
    _enqueue_payload(payload, priority=True)
    return {"success": True, "job_id": int(item["job_id"]), "item_id": int(item_id), "status": "queued"}


def cancel_job(job_id: int) -> dict[str, Any]:
    now = _now()
    with db.get_engine().begin() as conn:
        job = conn.execute(select(search_jobs).where(search_jobs.c.id == int(job_id))).mappings().first()
        if job is None:
            return {"success": False, "error": "Search job not found"}
        conn.execute(
            update(search_jobs)
            .where(search_jobs.c.id == int(job_id))
            .values(status="cancelled", cancel_requested=1, finished_at=now, message="Search job cancelled")
        )
        conn.execute(
            update(search_job_items)
            .where(search_job_items.c.job_id == int(job_id), search_job_items.c.status.in_(ACTIVE_ITEM_STATUSES))
            .values(status="cancelled", finished_at=now, reason="Search job cancelled")
        )
    return {"success": True, "job_id": int(job_id), "status": "cancelled"}


def restore_pending_search_jobs(limit: int = 500) -> dict[str, Any]:
    """Requeue DB items that were queued/running before a restart."""
    queued = 0
    with db.get_engine().begin() as conn:
        _mark_stale_running_items(conn)
        running_items = conn.execute(
            select(search_job_items.c.id, search_job_items.c.job_id)
            .where(search_job_items.c.status == "running")
            .limit(limit)
        ).all()
        for item in running_items:
            conn.execute(
                update(search_job_items)
                .where(search_job_items.c.id == int(item.id))
                .values(status="queued", reason="Requeued after restart", started_at=None, finished_at=None)
            )

        rows = conn.execute(
            select(search_job_items)
            .where(search_job_items.c.status == "queued")
            .order_by(search_job_items.c.job_id.desc(), search_job_items.c.position.asc())
            .limit(limit)
        ).mappings().all()

        for row in rows:
            conn.execute(
                update(search_jobs)
                .where(search_jobs.c.id == int(row["job_id"]), search_jobs.c.status.notin_(TERMINAL_JOB_STATUSES))
                .values(status="running", finished_at=None, message="Restored queued search item(s)")
            )

    for row in rows:
        payload = json.loads(row.get("payload_json") or "{}")
        payload["search_job_id"] = int(row["job_id"])
        payload["search_job_item_id"] = int(row["id"])
        _enqueue_payload(payload)
        queued += 1

    if queued:
        logger.info("[SEARCH-JOB] Restored %s queued search item(s) after startup", queued)
    return {"restored": queued}


def get_jobs_snapshot(limit: int = 150) -> dict[str, Any]:
    limit = max(1, min(int(limit or 150), 500))
    with db.get_engine().begin() as conn:
        _mark_stale_running_items(conn)
        job_rows = conn.execute(select(search_jobs).order_by(desc(search_jobs.c.id)).limit(20)).mappings().all()
        item_rows = conn.execute(
            select(search_job_items)
            .where(
                or_(
                    search_job_items.c.status.in_(["queued", "running", "error", "not_found"]),
                    search_job_items.c.finished_at.isnot(None),
                )
            )
            .order_by(
                search_job_items.c.status == "running",
                desc(search_job_items.c.id),
            )
            .limit(limit)
        ).mappings().all()

        counts_by_job = {
            int(job["id"]): dict(_job_counts(conn, int(job["id"])))
            for job in job_rows
        }

    jobs = []
    for row in job_rows:
        job = dict(row)
        job["counts"] = counts_by_job.get(int(row["id"]), {})
        jobs.append(job)

    items = []
    for row in item_rows:
        item = dict(row)
        item["job_item_id"] = item["id"]
        item["search_job_item_id"] = item["id"]
        item["search_job_id"] = item["job_id"]
        item["updated_at"] = item.get("finished_at") or item.get("started_at") or item.get("created_at")
        items.append(item)

    return {"jobs": jobs, "job_items": items}
