#!/usr/bin/env python3
"""Execute a cohortdefinition payload file against WebAPI and save artifacts."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_WEBAPI = "http://127.0.0.1/WebAPI"
DEFAULT_SOURCE_KEY = "SYNTHEA_CDM_BENCHMARK"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def api_request(
    base_url: str,
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(url=url, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {body}") from exc


def resolve_source(base_url: str, source_key: str) -> Dict[str, Any]:
    sources = api_request(base_url, "GET", "source/sources")
    for source in sources:
        if source.get("sourceKey") == source_key:
            return source
    raise RuntimeError(f"Source not found: {source_key}")


def poll_info(
    base_url: str,
    cohort_id: int,
    source_id: int,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> Dict[str, Any]:
    started = time.time()
    while time.time() - started < timeout_seconds:
        infos = api_request(base_url, "GET", f"cohortdefinition/{cohort_id}/info")
        for info in infos:
            info_id = info.get("id", {})
            if isinstance(info_id, dict) and info_id.get("sourceId") == source_id:
                if info.get("status") in {"COMPLETE", "FAILED"}:
                    return info
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"Timed out waiting for cohort_definition_id={cohort_id}, source_id={source_id}"
    )


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--webapi-url", default=DEFAULT_WEBAPI)
    parser.add_argument("--source-key", default=DEFAULT_SOURCE_KEY)
    parser.add_argument("--name-suffix", default=utc_now())
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval-seconds", type=int, default=5)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    payload = read_json(args.payload)
    source = resolve_source(args.webapi_url, args.source_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base_name = payload.get("name", "payload")
    payload["name"] = f"{base_name} {args.name_suffix}"

    write_json(args.output_dir / "payload.executed.json", payload)
    created = api_request(args.webapi_url, "POST", "cohortdefinition", payload)
    cohort_id = created["id"]
    write_json(args.output_dir / "created.json", created)

    trigger = api_request(
        args.webapi_url,
        "GET",
        f"cohortdefinition/{cohort_id}/generate/{args.source_key}",
    )
    write_json(args.output_dir / "trigger.json", trigger)

    info = poll_info(
        base_url=args.webapi_url,
        cohort_id=cohort_id,
        source_id=source["sourceId"],
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    write_json(args.output_dir / "info.json", info)
    print(json.dumps({
        "cohort_definition_id": cohort_id,
        "name": payload["name"],
        "status": info.get("status"),
        "person_count": info.get("personCount"),
        "record_count": info.get("recordCount"),
        "execution_duration": info.get("executionDuration"),
        "fail_message": info.get("failMessage"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
