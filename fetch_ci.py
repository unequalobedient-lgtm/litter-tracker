#!/usr/bin/env python3
"""Standalone per-visit weight fetch for a PetSafe ScoopFree SmartSpin.

Loads the read-only cloud-history code from the ha-petsafe-smartspin repo
WITHOUT importing Home Assistant, logs in with your Pet Companion email/password
(from PETSAFE_EMAIL / PETSAFE_PASSWORD env vars), and writes visits.json.

Run non-interactively (e.g. GitHub Actions):
    python fetch_ci.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---- settings -------------------------------------------------------------
DEVICE_ID = "eb1819db8daf4c7071cmfe"   # your box's Virtual/Device ID
COUNTRY = "1"                           # US
REGION = "us"
LOCAL_TZ = ZoneInfo("America/New_York")

HERE = Path(__file__).resolve().parent
# The unzipped repo folder sits next to this script.
PKG_DIR = None
for name in ("ha-petsafe-smartspin-main", "ha-petsafe-smartspin"):
    candidate = HERE / name / "custom_components" / "petsafe_smartspin"
    if candidate.is_dir():
        PKG_DIR = candidate
        break
if PKG_DIR is None:
    sys.exit("Could not find the ha-petsafe-smartspin repo folder next to this script.")

PROFILE_PATH = HERE / "petsafe-app-profile.json"
if not PROFILE_PATH.is_file():
    sys.exit(f"App profile not found at {PROFILE_PATH}")
LOCAL_SAVE = HERE / "smartspin-local.json"
HISTORY_SAVE = HERE / "visits.json"

# ---- load the package modules without running its __init__ (no Home Assistant) ----
PKG = "petsafe_standalone"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PKG] = pkg

vpkg = types.ModuleType(PKG + ".vendor")
vpkg.__path__ = [str(PKG_DIR / "vendor")]
sys.modules[PKG + ".vendor"] = vpkg


def _load(mod_name: str, rel_path: str):
    full = f"{PKG}.{mod_name}"
    spec = importlib.util.spec_from_file_location(full, PKG_DIR / rel_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


for name in ("errors", "models", "signer", "client", "password_client", "profiles"):
    _load(f"vendor.{name}", f"vendor/{name}.py")
bootstrap = _load("cloud_bootstrap", "cloud_bootstrap.py")
cloud_history = _load("cloud_history", "cloud_history.py")

import aiohttp  # noqa: E402


async def main() -> int:
    profile_json = PROFILE_PATH.read_text()

    username = os.environ.get("PETSAFE_EMAIL", "").strip()
    password = os.environ.get("PETSAFE_PASSWORD", "")
    if not username or not password:
        sys.exit("Missing PETSAFE_EMAIL or PETSAFE_PASSWORD environment variable.")

    async with aiohttp.ClientSession() as session:
        print("\nLogging in and verifying the device...")
        creds = await cloud_history.async_create_cloud_credentials(
            session,
            username=username,
            password=password,
            country_code=COUNTRY,
            region=REGION,
            device_id=DEVICE_ID,
            profile_json=profile_json,
        )
        print("Login OK. Fetching visit history...")
        snapshot = await cloud_history.async_fetch_history(
            session, credentials=creds, device_id=DEVICE_ID,
        )

        rows = []
        print(f"\nLast {len(snapshot.visits)} visits (newest first):")
        print(f"{'When':<22}{'Weight (lb)':>12}{'Duration':>12}")
        for v in snapshot.visits:
            when = v.timestamp.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p")
            lbs = v.weight_kg * 2.2046226218
            print(f"{when:<22}{lbs:>12.2f}{v.duration_seconds:>10}s")
            rows.append({
                "timestamp": v.timestamp.isoformat(),
                "weight_kg": v.weight_kg,
                "weight_lb": round(lbs, 3),
                "duration_seconds": v.duration_seconds,
            })

        HISTORY_SAVE.write_text(json.dumps(rows, indent=2))
        print(f"\nSaved {len(rows)} visits to {HISTORY_SAVE.name}")

        # Additive, non-blocking probe for other DPs (waste-bin / tray weight).
        # Failures must never prevent the visit fetch or dashboard build.
        try:
            await _probe_dps(session, creds, DEVICE_ID)
        except Exception as exc:
            print(f"DP probe failed (non-fatal): {type(exc).__name__}")
            try:
                _write_probe({"ok": False, "error": type(exc).__name__, "notes": _PROBE_NOTES})
            except Exception:
                pass
    return 0


# Published SmartSpin (Tuya category "msp") property set, from a Tuya developer
# portal dump of the same model. There is no tray/waste-weight DP in that set.
# "Waste bin full" notifications most likely live in the DP21 notification
# bitmap and/or the DP22 fault bitmap — the probe reads those plus the rest.
_PROBE_NOTES = {
    "known_dp_map": {
        "4": "auto_clean (bool)",
        "5": "delay_clean_time (value, minutes)",
        "7": "excretion_times_day / visits today (value)",
        "10": "sleep (bool)",
        "11": "sleep_start_time (value, minutes)",
        "12": "sleep_end_time (value, minutes)",
        "16": "light (bool)",
        "21": "notification (bitmap) — most likely includes waste-bin-full alerts",
        "22": "fault (bitmap) — possible bin-full / sensor fault bits",
        "23": "factory_reset (bool)",
        "24": "status (enum: standby, cleaning, ...)",
        "101": "motor_current (value)",
        "102": "cat_duration_weight (raw) — the visit weight+duration channel already used",
        "103": "child_lock (bool)",
        "105": "beep (bool)",
        "106": "clean / clean_control_state (enum)",
        "107": "history_record (enum)",
        "109": "indicator (bool)",
        "110": "unit_switching (enum: Kg, ...)",
        "111": "deodorizer_box (bool)",
    },
    "bin_full_candidates": ["21", "22"],
    "tray_or_waste_weight_dp_in_published_schema": False,
    "probed_history_dpIds": "4,5,7,10,11,12,16,21,22,23,24,101,102,103,105,106,107,109,110,111",
}

_REDACT_SUBSTR = (
    "key", "secret", "token", "password", "passwd", "sid", "ecode",
    "email", "auth", "session", "cert", "sign", "cookie", "credential",
    "aes", "hmac", "private",
)


def _should_redact(key: str) -> bool:
    k = key.lower().replace("-", "").replace("_", "")
    if k in {"dpid", "dpids", "devid", "deviceid", "id"}:
        return False
    return any(s.replace("_", "") in k for s in _REDACT_SUBSTR)


def _sanitize(value, depth=0):
    if depth > 12:
        return "[truncated]"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            ks = str(k)
            if _should_redact(ks):
                out[ks] = "[redacted]"
            else:
                out[ks] = _sanitize(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize(v, depth + 1) for v in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 4000:
            return value[:4000] + "...[truncated]"
        return value
    return str(value)


def _write_probe(payload: dict) -> None:
    dest = HERE / "public" / "dp_probe.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote DP probe to {dest.relative_to(HERE)}")


async def _probe_dps(session, credentials, device_id: str) -> None:
    """Read-only extra queries. Never writes a DP or changes box settings."""
    from petsafe_standalone.vendor.client import TuyaMobileClient
    from petsafe_standalone.vendor.signer import PurePythonTuyaSigner

    report = {
        "ok": True,
        "probed_at": datetime.now(LOCAL_TZ).isoformat(),
        "notes": _PROBE_NOTES,
        "calls": {},
    }
    client = signer = profile = None
    try:
        region = credentials["region"]
        endpoint = bootstrap.REGION_ENDPOINTS[region]
        profile = bootstrap._parse_profile(json.dumps(credentials["profile"]), endpoint)
        saved = credentials["session"]
        installation_id = credentials["installation_id"]
        signer = PurePythonTuyaSigner(
            **{
                name: getattr(profile, name)
                for name in (
                    "app_id",
                    "app_secret",
                    "cert_sha256_hex",
                    "app_key",
                    "package",
                )
            }
        )
        client = TuyaMobileClient(
            signer,
            session,
            profile=profile,
            device_id=installation_id,
        )
        client.mobile_url = endpoint
        client.sid, client.ecode, client.uid = saved["sid"], saved["ecode"], saved["uid"]

        async def try_call(name, action, payload, version):
            try:
                raw = await client._call(action, payload, version=version)
                report["calls"][name] = {"ok": True, "action": action, "version": version, "response": _sanitize(raw)}
            except Exception as exc:
                # Keep error type/message but strip anything that looks sensitive.
                msg = str(exc)
                for token in ("sid=", "ecode=", "localKey", "local_key"):
                    if token.lower() in msg.lower():
                        msg = type(exc).__name__
                        break
                if len(msg) > 300:
                    msg = msg[:300]
                report["calls"][name] = {
                    "ok": False,
                    "action": action,
                    "version": version,
                    "error": type(exc).__name__,
                    "message": msg,
                }

        # Full device record (schema / current DPs often included). localKey is redacted.
        await try_call("device_get", "thing.m.device.get", {"devId": device_id}, "4.1")

        # History across the published SmartSpin DP set, including 21/22 bin-full candidates.
        # DP102 visit history is still fetched separately above and is unchanged.
        await try_call(
            "history_all_known_dps",
            "m.smart.operate.log",
            {
                "devId": device_id,
                "dpIds": _PROBE_NOTES["probed_history_dpIds"],
                "offset": 0,
                "limit": 50,
                "sortType": "DESC",
            },
            "2.0",
        )

        # Current DP values, if this mobile action exists for this app profile.
        for name, action, ver, payload in (
            ("device_status", "thing.m.device.status.get", "1.0", {"devId": device_id}),
            ("dp_get", "s.m.dev.dp.get", "2.0", {"devId": device_id}),
        ):
            await try_call(name, action, payload, ver)
    finally:
        # Same cleanup pattern as the vendor history client: drop signer/session material.
        if client is not None:
            if getattr(client, "signer", None) is not None:
                client.signer.__dict__.clear()
            client.__dict__.clear()
        if signer is not None:
            signer.__dict__.clear()

    _write_probe(report)
    print("DP probe finished.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
