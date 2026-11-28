"""
Host side of the stage B sandbox (proposal, stage B item 2: "The code it writes runs
only in sandbox containers: no network, no keys, read-only data, time and memory limits").

Each run gets a fresh container with:
  --network none                 no internet, no LAN, no broker
  --read-only, tmpfs /tmp        nothing persists; the image can't be changed
  --cap-drop ALL, no-new-privileges, non-root user
  --memory/--cpus/--pids-limit   resource caps; `timeout` inside + a host-side kill
  mounts (all read-only)         /app  = a fresh copy of only the code it needs
                                         (no keys, no .env, no gate log, no raw data)
                                 /data = one price snapshot (holdout only for gate 1)
                                 /job  = job.json + the strategy file
No environment variables from the host are passed in.

On Windows, Docker runs inside WSL2 (`wsl --exec docker ...`); on Linux, directly.

Usage:
    python -m research.agent.sandbox build      # build the image once (needs network)
    python -m research.agent.sandbox check      # run a known strategy end to end
"""

from __future__ import annotations

import json
import platform
import secrets
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JOBS_DIR = REPO / "research" / "agent" / "jobs"
IMAGE = "quant-sandbox:1"
LOOKAHEAD_DATES = ("2010-06-30", "2014-03-31", "2018-09-28", "2021-09-30")


@dataclass(frozen=True)
class Limits:
    timeout_s: int = 900
    memory: str = "2g"
    cpus: str = "2"
    pids: int = 128


# Code the runner needs, copied fresh into each job. Data files, logs and secrets never are.
CODE_GLOBS = ("shared/*.py", "research/__init__.py", "research/engine/*.py", "research/strategies/*.py",
              "research/gates/*.py", "research/data/__init__.py", "research/data/splits.py",
              "research/data/loader.py", "research/trials/__init__.py", "research/trials/log.py",
              "research/agent/__init__.py", "research/agent/sandbox_runner.py")


def _docker_cmd() -> list[str]:
    return ["wsl", "--exec", "docker"] if platform.system() == "Windows" else ["docker"]


def host_path(p: Path) -> str:
    """Path as Docker sees it (WSL form on Windows: E:\\x -> /mnt/e/x)."""
    p = p.resolve()
    if platform.system() == "Windows":
        drive, rest = p.drive.rstrip(":").lower(), p.as_posix()[2:]
        return f"/mnt/{drive}{rest}"
    return str(p)


def docker_available() -> bool:
    try:
        r = subprocess.run(_docker_cmd() + ["image", "inspect", IMAGE], capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build_image() -> None:
    ctx = host_path(REPO / "research" / "agent" / "sandbox")
    subprocess.run(_docker_cmd() + ["build", "-t", IMAGE, ctx], check=True)


def _stage(job_dir: Path) -> None:
    app = job_dir / "app"
    for pattern in CODE_GLOBS:
        for f in REPO.glob(pattern):
            dest = app / f.relative_to(REPO)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)


def run_job(mode: str, strategy_src: str, data_dir: Path, extra: dict | None = None,
            limits: Limits = Limits(), keep: bool = False) -> dict:
    """Run one job; returns the runner's result dict, or {"ok": False, "stage": ..., "error": ...}."""
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    nonce = secrets.token_hex(16)
    try:
        _stage(job_dir)
        (job_dir / "strategy.py").write_text(strategy_src, encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({"mode": mode, "nonce": nonce,
                                                      "lookahead_dates": list(LOOKAHEAD_DATES), **(extra or {})}))
        name = f"sbx-{job_id}"
        cmd = _docker_cmd() + [
            "run", "--rm", "--name", name,
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", limits.memory, "--memory-swap", limits.memory, "--cpus", limits.cpus,
            "--pids-limit", str(limits.pids),
            "-v", f"{host_path(job_dir / 'app')}:/app:ro",
            "-v", f"{host_path(job_dir)}:/job:ro",
            "-v", f"{host_path(data_dir)}:/data:ro",
            "-w", "/app", IMAGE,
            "timeout", "--kill-after=10", str(limits.timeout_s), "python", "-m", "research.agent.sandbox_runner",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=limits.timeout_s + 60)
        except subprocess.TimeoutExpired:
            subprocess.run(_docker_cmd() + ["kill", name], capture_output=True)
            return {"ok": False, "stage": "timeout", "error": f"no result within {limits.timeout_s}s"}
        out = proc.stdout.decode("utf-8", "replace")
        marker = f"@@RESULT-{nonce}@@ "
        lines = [l for l in out.splitlines() if l.startswith(marker)]
        if len(lines) != 1:
            err = proc.stderr.decode("utf-8", "replace")[-3000:]
            stage = "killed" if proc.returncode in (124, 137) else "no_result"
            return {"ok": False, "stage": stage,
                    "error": f"exit code {proc.returncode}; {len(lines)} result lines; stderr: {err}"}
        return json.loads(lines[0][len(marker):])
    finally:
        if not keep:
            shutil.rmtree(job_dir, ignore_errors=True)


def main(argv=None) -> None:
    import inspect

    args = argv if argv is not None else sys.argv[1:]
    if args[:1] == ["build"]:
        build_image()
        print(f"built {IMAGE}")
    elif args[:1] == ["check"]:
        from research.gates.sandbox_export import research_snapshot
        import research.strategies.vol_target as m

        r = run_job("research", inspect.getsource(m), research_snapshot())
        print(json.dumps({k: v for k, v in r.items() if k != "results"}, indent=1))
        for p, mm in (r.get("results") or {}).items():
            print(p, f"CAGR {mm['cagr']:.2%}  worst fall {mm['max_drawdown']:.1%}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
