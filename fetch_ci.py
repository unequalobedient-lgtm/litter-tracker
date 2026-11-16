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
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
