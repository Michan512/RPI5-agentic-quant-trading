"""
Versioned model store. Replaces legacy/training/retrain.py's "retrain and overwrite".

- Every training run saves a NEW version folder; nothing is ever overwritten.
- A new version is only ever a "candidate". Nothing loads a candidate for
  trading automatically.
- `load_approved()` returns a model only if a person has explicitly approved
  that version with `approve()`. In Stage E nothing is approved, and approval
  belongs to the promotion gates (research/gates), which come later.

Layout:
    research/trials/models/<model_name>/v0001/model.json   (gitignored)
    research/trials/models/<model_name>/v0001/meta.json
    research/trials/models/<model_name>/APPROVED.json      (only after approve())
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models"


def _dir(name: str) -> Path:
    return MODELS_DIR / name


def list_versions(name: str) -> list[dict]:
    d = _dir(name)
    if not d.exists():
        return []
    return [json.loads((v / "meta.json").read_text()) for v in sorted(d.glob("v*")) if (v / "meta.json").exists()]


def save_candidate(name: str, model, meta: dict) -> str:
    """Save a new version as a candidate. Returns the version id, e.g. 'v0003'."""
    d = _dir(name)
    d.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(v.name[1:]) for v in d.glob("v*") if v.name[1:].isdigit()] or [0])
    version = f"v{n:04d}"
    vdir = d / version
    vdir.mkdir()                       # fails if it somehow exists: never overwrite
    model_path = vdir / "model.json"
    model.save_model(str(model_path))
    record = {
        "model": name,
        "version": version,
        "status": "candidate",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        **meta,
    }
    (vdir / "meta.json").write_text(json.dumps(record, indent=2, default=str))
    return version


def approve(name: str, version: str, approved_by: str, reason: str) -> None:
    """Manual step only: mark one version as approved. Never call this from automated code."""
    vdir = _dir(name) / version
    if not (vdir / "meta.json").exists():
        raise FileNotFoundError(f"{name} {version} does not exist")
    (_dir(name) / "APPROVED.json").write_text(json.dumps({
        "version": version, "approved_by": approved_by, "reason": reason,
        "approved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))


def load_approved(name: str):
    """Load the approved version, checking its hash. Raises if none is approved."""
    from xgboost import XGBClassifier

    marker = _dir(name) / "APPROVED.json"
    if not marker.exists():
        raise LookupError(f"no approved version of {name!r}; candidates are never used automatically")
    version = json.loads(marker.read_text())["version"]
    vdir = _dir(name) / version
    meta = json.loads((vdir / "meta.json").read_text())
    data = (vdir / "model.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != meta["model_sha256"]:
        raise ValueError(f"{name} {version}: model file hash mismatch")
    model = XGBClassifier()
    model.load_model(str(vdir / "model.json"))
    return model, meta
