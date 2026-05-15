#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.

import threading
import time

import requests

import comicarr
from comicarr import logger


_SCAN_LOCK = threading.Lock()
_LAST_SCAN_AT = 0


def _config_value(name, default=None):
    return getattr(comicarr.CONFIG, name, default)


def _configured_library_ids():
    configured_ids = _config_value("KAVITA_LIBRARY_IDS")
    if configured_ids and configured_ids != "None":
        ids = []
        for library_id in str(configured_ids).split(","):
            library_id = library_id.strip()
            if library_id:
                ids.append(library_id)
        return ids

    library_id = _config_value("KAVITA_LIBRARY_ID")
    if library_id:
        return [library_id]
    return []


def _library_ids_for_kind(library_kind=None):
    if library_kind == "comic":
        library_id = _config_value("KAVITA_COMICS_LIBRARY_ID") or _config_value("KAVITA_LIBRARY_ID")
        if library_id:
            return [library_id]
    elif library_kind == "manga":
        library_id = _config_value("KAVITA_MANGA_LIBRARY_ID")
        if library_id:
            return [library_id]

    return _configured_library_ids()


def trigger_library_scan(reason=None, library_kind=None):
    """Trigger a Kavita library scan in the background after a successful import."""
    if not _config_value("KAVITA_SCAN_ENABLED", False):
        return False

    host = (_config_value("KAVITA_HOST") or "").rstrip("/")
    username = _config_value("KAVITA_USERNAME")
    password = _config_value("KAVITA_PASSWORD")
    library_ids = _library_ids_for_kind(library_kind)
    min_interval = _config_value("KAVITA_SCAN_MIN_INTERVAL", 60) or 60

    if not host or not username or not password or not library_ids:
        logger.warn("[KAVITA] Scan trigger enabled, but host, username, password, or library ids are missing.")
        return False

    global _LAST_SCAN_AT
    now = time.time()
    with _SCAN_LOCK:
        if now - _LAST_SCAN_AT < min_interval:
            logger.fdebug("[KAVITA] Scan trigger skipped due to minimum interval.")
            return False
        _LAST_SCAN_AT = now

    thread = threading.Thread(
        target=_trigger_library_scan,
        args=(host, username, password, library_ids, reason),
        name="KavitaScanTrigger",
        daemon=True,
    )
    thread.start()
    return True


def _trigger_library_scan(host, username, password, library_ids, reason=None):
    session = requests.Session()
    try:
        login = session.post(
            "%s/api/account/login" % host,
            json={"username": username, "password": password},
            timeout=15,
        )
        login.raise_for_status()
        token = login.json().get("token")
        if not token:
            logger.warn("[KAVITA] Login succeeded but no token was returned.")
            return

        for library_id in library_ids:
            response = session.post(
                "%s/api/library/scan" % host,
                params={"libraryId": library_id},
                headers={"Authorization": "Bearer %s" % token},
                timeout=15,
            )
            response.raise_for_status()
            if reason:
                logger.info("[KAVITA] Triggered library scan for library id %s after %s." % (library_id, reason))
            else:
                logger.info("[KAVITA] Triggered library scan for library id %s." % library_id)
    except requests.exceptions.RequestException as e:
        logger.warn("[KAVITA] Unable to trigger library scan: %s" % e)
    except ValueError as e:
        logger.warn("[KAVITA] Unable to parse Kavita login response: %s" % e)
    except Exception as e:
        logger.warn("[KAVITA] Unexpected error while triggering library scan: %s" % e)
