#!/usr/bin/env python3
"""Guarded reference orchestrator for Instagram Content Publishing API.

Safe defaults:
- `check` and `plan` never publish.
- `publish` requires an exact approval hash and IG_ENABLE_LIVE_PUBLISH=I_UNDERSTAND.
- tokens are read from environment only and never written to state or output.
- an uncertain publish response is reconciled before another publish is allowed.

This is a reference implementation, not a substitute for configuring a Meta app,
permissions, App Review, secret storage, temporary HTTPS hosting, and owner approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL = {"ERROR", "EXPIRED", "PUBLISHED"}
READY = "FINISHED"
LIVE_SENTINEL = "I_UNDERSTAND"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def redact_url(value: str | None) -> str | None:
    if not value:
        return value
    p = urllib.parse.urlsplit(value)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "[REDACTED]" if p.query else "", ""))


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("image must be JPEG")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in {0xD8, 0xD9}:
            continue
        if i + 2 > len(data):
            break
        length = int.from_bytes(data[i:i + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[i + 3:i + 5], "big")
            width = int.from_bytes(data[i + 5:i + 7], "big")
            return width, height
        i += max(length, 2)
    raise ValueError("could not read JPEG dimensions")


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=format_name,duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels,pix_fmt,bit_rate",
        "-of", "json", str(path),
    ]
    try:
        cp = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise RuntimeError("ffprobe is required for video preflight") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed: {e.stderr.strip()}") from e
    return json.loads(cp.stdout)


def fps_value(value: str | None) -> float:
    if not value:
        return 0.0
    numerator, _, denominator = value.partition("/")
    try:
        return float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def mp4_layout(path: Path) -> dict[str, Any]:
    """Read enough ISO-BMFF structure to catch two Meta hard failures.

    Meta requires the moov atom at the front and rejects edit lists. This is a
    deliberately small parser: it walks top-level boxes for ordering and scans
    box markers for `edts`. It never rewrites the media.
    """
    data = path.read_bytes()
    boxes: list[tuple[str, int]] = []
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8].decode("latin1")
        header = 8
        if size == 1 and offset + 16 <= len(data):
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data):
            break
        boxes.append((kind, offset))
        offset += size
    positions = {kind: pos for kind, pos in boxes}
    return {
        "top_level_boxes": [kind for kind, _ in boxes],
        "moov_before_mdat": "moov" in positions and "mdat" in positions and positions["moov"] < positions["mdat"],
        "has_edit_list": b"edts" in data,
    }


def preflight_media(path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"media file not found: {path}")
    size = path.stat().st_size
    result: dict[str, Any] = {"file": path.name, "sha256": sha256_file(path), "bytes": size, "kind": kind, "checks": []}
    if kind == "IMAGE":
        width, height = jpeg_dimensions(path)
        ratio = width / height
        checks = {
            "jpeg": path.read_bytes()[:2] == b"\xff\xd8",
            "max_8_mib": size <= 8 * 1024 * 1024,
            "width_320_1440": 320 <= width <= 1440,
            "ratio_4_5_to_1_91_1": 0.8 <= ratio <= 1.91,
        }
        result.update({"width": width, "height": height, "aspect_ratio": ratio, "checks": checks})
    else:
        probe = ffprobe(path)
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(probe.get("format", {}).get("duration") or 0)
        fmt = str(probe.get("format", {}).get("format_name", ""))
        fps = fps_value(video.get("r_frame_rate"))
        video_bitrate = int(video.get("bit_rate") or probe.get("format", {}).get("bit_rate") or 0)
        audio_bitrate = int(audio.get("bit_rate") or 0) if audio else 0
        layout = mp4_layout(path)
        checks = {
            "mov_or_mp4": any(x in fmt for x in ("mov", "mp4")),
            "video_codec_h264_or_hevc": video.get("codec_name") in {"h264", "hevc"},
            "audio_optional_or_aac": not audio or audio.get("codec_name") == "aac",
            "duration_3_to_900_seconds": 3 <= duration <= 900,
            "fps_23_to_60": 23 <= fps <= 60,
            "video_bitrate_max_25_mbps": video_bitrate == 0 or video_bitrate <= 25_000_000,
            "audio_bitrate_present": not audio or audio_bitrate > 0,
            "dimensions_present": bool(video.get("width") and video.get("height")),
            "moov_atom_at_front": layout["moov_before_mdat"],
            "no_edit_list": not layout["has_edit_list"],
        }
        warnings = []
        if audio and 0 < audio_bitrate < 128_000:
            warnings.append("measured audio bitrate is below Meta's documented 128 kbps target; verify the encoder setting")
        result.update({"duration_seconds": duration, "fps": fps, "mp4_layout": layout, "probe": probe, "warnings": warnings, "checks": checks})
    result["ok"] = all(result["checks"].values())
    return result


@dataclass
class PublishPlan:
    account_id: str
    expected_username: str
    api_host: str
    api_version: str
    media_kind: str
    media_sha256: str
    caption_sha256: str
    cover_sha256: str | None
    mode: str
    share_to_feed: bool
    is_ai_generated: bool
    trial_strategy: str | None
    approval_hash: str


def build_plan(config: dict[str, Any], media: dict[str, Any], caption: str, cover_sha: str | None) -> PublishPlan:
    base = {
        "account_id": str(config["account_id"]),
        "expected_username": config["expected_username"],
        "api_host": config["api_host"],
        "api_version": config["api_version"],
        "media_kind": config["media_kind"],
        "media_sha256": media["sha256"],
        "caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
        "cover_sha256": cover_sha,
        "mode": config.get("mode", "NORMAL"),
        "share_to_feed": bool(config.get("share_to_feed", True)),
        "is_ai_generated": bool(config.get("is_ai_generated", False)),
        "trial_strategy": config.get("trial_strategy"),
    }
    return PublishPlan(**base, approval_hash=stable_hash(base))


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"version": 1, "runs": {}}
        if path.exists():
            self.data = json.loads(path.read_text("utf-8"))

    def run(self, approval_hash: str) -> dict[str, Any]:
        return self.data["runs"].setdefault(approval_hash, {"state": "PLANNED", "created_at": utc_now(), "events": []})

    def event(self, approval_hash: str, state: str, **safe_fields: Any) -> None:
        run = self.run(approval_hash)
        run["state"] = state
        run["events"].append({"at": utc_now(), "state": state, **safe_fields})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)


class MetaAPI:
    def __init__(self, host: str, version: str, token: str):
        self.base = f"https://{host}/{version}"
        self.token = token

    def request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        clean["access_token"] = self.token
        data = urllib.parse.urlencode(clean).encode("utf-8")
        url = f"{self.base}/{path.lstrip('/')}"
        if method == "GET":
            url += "?" + data.decode("utf-8")
            data = None
        req = urllib.request.Request(url, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Meta API HTTP {e.code}: {body[:1000]}") from e


def load_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], Path, str, Path | None]:
    config = json.loads(Path(args.config).read_text("utf-8"))
    if config.get("media_kind") not in {"IMAGE", "REELS"}:
        raise ValueError("reference CLI implements IMAGE and REELS; use STATE-MACHINE.md for carousel assembly")
    media_path = Path(config["media_path"]).expanduser().resolve()
    caption = Path(config["caption_path"]).read_text("utf-8").strip()
    cover_path = Path(config["cover_path"]).expanduser().resolve() if config.get("cover_path") else None
    if len(caption) > 2200:
        raise ValueError("caption exceeds 2200 characters")
    if len(re.findall(r"(?<!\w)#\w+", caption)) > 30:
        raise ValueError("caption exceeds 30 hashtags")
    if len(re.findall(r"(?<!\w)@\w+", caption)) > 20:
        raise ValueError("caption exceeds 20 mentions")
    if config.get("mode") == "TRIAL" and config.get("trial_strategy") not in {"MANUAL", "SS_PERFORMANCE"}:
        raise ValueError("TRIAL mode requires trial_strategy MANUAL or SS_PERFORMANCE")
    if not str(config.get("asset_url", "")).startswith("https://"):
        raise ValueError("asset_url must use HTTPS")
    return config, media_path, caption, cover_path


def command_check(args: argparse.Namespace) -> int:
    config, media_path, caption, cover_path = load_inputs(args)
    media = preflight_media(media_path, config["media_kind"])
    cover = preflight_media(cover_path, "IMAGE") if cover_path else None
    plan = build_plan(config, media, caption, cover["sha256"] if cover else None)
    report = {"ok": media["ok"] and (cover is None or cover["ok"]), "media": media, "cover": cover, "plan": asdict(plan), "asset_url": redact_url(config["asset_url"]), "live_action": False}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def command_plan(args: argparse.Namespace) -> int:
    config, media_path, caption, cover_path = load_inputs(args)
    media = preflight_media(media_path, config["media_kind"])
    cover = preflight_media(cover_path, "IMAGE") if cover_path else None
    if not media["ok"] or (cover and not cover["ok"]):
        raise RuntimeError("preflight failed; publication plan not created")
    plan = build_plan(config, media, caption, cover["sha256"] if cover else None)
    Path(args.output).write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2), "utf-8")
    print(plan.approval_hash)
    return 0


def command_publish(args: argparse.Namespace) -> int:
    if os.getenv("IG_ENABLE_LIVE_PUBLISH") != LIVE_SENTINEL:
        raise RuntimeError("live publishing is locked; set IG_ENABLE_LIVE_PUBLISH=I_UNDERSTAND only after owner approval")
    token = os.getenv("IG_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("IG_ACCESS_TOKEN is missing")
    config, media_path, caption, cover_path = load_inputs(args)
    media = preflight_media(media_path, config["media_kind"])
    cover = preflight_media(cover_path, "IMAGE") if cover_path else None
    if not media["ok"] or (cover and not cover["ok"]):
        raise RuntimeError("preflight failed")
    plan = build_plan(config, media, caption, cover["sha256"] if cover else None)
    if args.confirm_hash != plan.approval_hash:
        raise RuntimeError("confirmation hash does not match frozen plan")

    journal = Journal(Path(args.journal))
    run = journal.run(plan.approval_hash)
    if run.get("state") in {"PUBLISHED", "PUBLISH_UNKNOWN", "RECONCILE_REQUIRED"}:
        raise RuntimeError(f"duplicate guard: existing state is {run.get('state')}; reconcile before any retry")

    api = MetaAPI(config["api_host"], config["api_version"], token)
    account = api.request("GET", config["account_id"], {"fields": "id,username"})
    if account.get("username") != config["expected_username"]:
        raise RuntimeError("connected username does not match expected_username")
    journal.event(plan.approval_hash, "ACCOUNT_VERIFIED", account_id=account.get("id"), username=account.get("username"))

    params: dict[str, Any] = {"caption": caption}
    if config["media_kind"] == "IMAGE":
        params["image_url"] = config["asset_url"]
    elif config["media_kind"] == "REELS":
        params.update({"media_type": "REELS", "video_url": config["asset_url"], "share_to_feed": str(bool(config.get("share_to_feed", True))).lower()})
        if config.get("cover_url"):
            params["cover_url"] = config["cover_url"]
        if config.get("mode") == "TRIAL":
            params["trial_params"] = json.dumps({"graduation_strategy": config["trial_strategy"]})
    else:
        raise RuntimeError("live reference currently implements IMAGE and REELS; use the documented state machine for carousel assembly")
    if config.get("is_ai_generated"):
        params["is_ai_generated"] = "true"

    created = api.request("POST", f"{config['account_id']}/media", params)
    container_id = str(created["id"])
    journal.event(plan.approval_hash, "CONTAINER_CREATED", container_id=container_id, asset_url=redact_url(config["asset_url"]))

    deadline = time.time() + int(config.get("poll_timeout_seconds", 300))
    while time.time() < deadline:
        status = api.request("GET", container_id, {"fields": "id,status,status_code"})
        code = status.get("status_code")
        journal.event(plan.approval_hash, f"CONTAINER_{code or 'UNKNOWN'}", container_id=container_id)
        if code == READY:
            break
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"container terminal status: {code}; {status.get('status', '')}")
        time.sleep(int(config.get("poll_interval_seconds", 60)))
    else:
        journal.event(plan.approval_hash, "RECONCILE_REQUIRED", container_id=container_id, reason="poll_timeout")
        raise RuntimeError("container did not become FINISHED before timeout")

    journal.event(plan.approval_hash, "PUBLISH_REQUEST_STARTED", container_id=container_id)
    try:
        published = api.request("POST", f"{config['account_id']}/media_publish", {"creation_id": container_id})
    except Exception:
        journal.event(plan.approval_hash, "PUBLISH_UNKNOWN", container_id=container_id)
        raise
    media_id = str(published["id"])
    journal.event(plan.approval_hash, "PUBLISH_RESPONSE_RECEIVED", container_id=container_id, media_id=media_id)
    readback = api.request("GET", media_id, {"fields": "id,permalink,username,caption,media_type,media_product_type,timestamp"})
    journal.event(plan.approval_hash, "PUBLISHED", container_id=container_id, media_id=media_id, permalink=readback.get("permalink"), username=readback.get("username"))
    print(json.dumps({"ok": True, "approval_hash": plan.approval_hash, "readback": readback, "revoke_temporary_asset_now": True}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "plan", "publish"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True)
        if name == "plan":
            s.add_argument("--output", default="approval-plan.json")
        if name == "publish":
            s.add_argument("--confirm-hash", required=True)
            s.add_argument("--journal", default="publish-journal.json")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return {"check": command_check, "plan": command_plan, "publish": command_publish}[args.command](args)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "live_action": args.command == "publish"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
