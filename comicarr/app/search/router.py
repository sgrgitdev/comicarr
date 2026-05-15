#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain router — provider search, RSS monitoring.

Depends on series domain for cross-domain lookups (Phase 5).
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.search import service as search_service

router = APIRouter(prefix="/api/search", tags=["search"])


# ---------------------------------------------------------------------------
# Comic / manga search
# ---------------------------------------------------------------------------


@router.post("/comics", dependencies=[Depends(require_session)])
def search_comics(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Search for comics across ComicVine, Metron, or MangaDex."""
    if request_body is None:
        request_body = {}

    name = request_body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Missing search name"})

    result = search_service.find_comic(
        ctx,
        name=name,
        issue=request_body.get("issue"),
        type_=request_body.get("type", "comic"),
        mode=request_body.get("mode", "series"),
        limit=request_body.get("limit"),
        offset=request_body.get("offset"),
        sort=request_body.get("sort"),
        content_type=request_body.get("content_type"),
    )

    if isinstance(result, dict) and "error" in result:
        return JSONResponse(status_code=400, content={"detail": result["error"]})

    return result


@router.post("/manga", dependencies=[Depends(require_session)])
def search_manga(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Search for manga via MangaDex API."""
    if request_body is None:
        request_body = {}

    name = request_body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Missing search name"})

    result = search_service.find_manga(
        ctx,
        name=name,
        limit=request_body.get("limit"),
        offset=request_body.get("offset"),
        sort=request_body.get("sort"),
    )

    if isinstance(result, dict) and "error" in result:
        return JSONResponse(status_code=400, content={"detail": result["error"]})

    return result


# ---------------------------------------------------------------------------
# Add comic / manga to library
# ---------------------------------------------------------------------------


@router.post("/add", dependencies=[Depends(require_session)])
def add_comic(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add a comic to the watchlist."""
    if request_body is None:
        request_body = {}

    comic_id = request_body.get("id") or request_body.get("comic_id")
    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic id"})

    result = search_service.add_comic(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.post("/add-manga", dependencies=[Depends(require_session)])
def add_manga(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add a manga to the library by MangaDex ID."""
    if request_body is None:
        request_body = {}

    manga_id = request_body.get("id") or request_body.get("manga_id")
    if not manga_id:
        return JSONResponse(status_code=400, content={"detail": "Missing manga id"})

    result = search_service.add_manga(ctx, manga_id)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# Force search / RSS
# ---------------------------------------------------------------------------


@router.post("/force", dependencies=[Depends(require_session)])
def force_search(ctx: AppContext = Depends(get_context)):
    """Trigger a full search for all wanted issues."""
    return search_service.force_search(ctx)


@router.post("/issues", dependencies=[Depends(require_session)])
def search_issues(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Trigger a durable search for selected issue IDs."""
    if request_body is None:
        request_body = {}
    issue_ids = request_body.get("ids") or request_body.get("issue_ids") or []
    if not isinstance(issue_ids, list) or not issue_ids:
        return JSONResponse(status_code=400, content={"detail": "Missing issue ids"})
    result = search_service.search_issue_ids(ctx, issue_ids)
    if not result.get("success"):
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


@router.post("/jobs/items/{item_id}/retry", dependencies=[Depends(require_session)])
def retry_search_job_item(item_id: int, ctx: AppContext = Depends(get_context)):
    """Retry a failed/not-found search job item."""
    result = search_service.retry_search_job_item(ctx, item_id)
    if not result.get("success"):
        return JSONResponse(status_code=404, content={"detail": result.get("error")})
    return result


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_session)])
def cancel_search_job(job_id: int, ctx: AppContext = Depends(get_context)):
    """Cancel queued items in a durable search job."""
    result = search_service.cancel_search_job(ctx, job_id)
    if not result.get("success"):
        return JSONResponse(status_code=404, content={"detail": result.get("error")})
    return result


@router.post("/rss/force", dependencies=[Depends(require_session)])
def force_rss(ctx: AppContext = Depends(get_context)):
    """Trigger an RSS feed check."""
    result = search_service.force_rss(ctx)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.get("/queue", dependencies=[Depends(require_session)])
def get_search_queue(limit: int = Query(100, ge=1, le=500), ctx: AppContext = Depends(get_context)):
    """Get current search queue status."""
    return search_service.get_search_queue(ctx, limit=limit)


@router.get("/providers", dependencies=[Depends(require_session)])
def get_provider_stats(ctx: AppContext = Depends(get_context)):
    """Get provider search statistics."""
    return search_service.get_provider_stats(ctx)
