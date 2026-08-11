"""
Cron Listener v0.2

Schedule reconciliation. Polls cron sources every 60s, computes upcoming runs,
and surfaces drift: missed runs, near-collisions, and stale entries (target
script gone). Observability-only — emits events, takes no action.

Spec: master_summary §12.4 ("cron.py — schedule reconciliation").

── Design notes (P2-3 design walk, 2026-05-29) ────────────────────────────────
- Log path is DERIVED from each crontab line's `>> <path>` redirect, not a
  hardcoded JOB_LOG_MAP — the crontab is self-describing, so this stays correct
  as jobs change.
- Cron runs in system-LOCAL tz (America/New_York here); Loki stores UTC.
  Next/prev runs are computed with croniter on a local-aware base, then
  converted to UTC.
- Missed-run signal: the most-recent scheduled occurrence is "missed" if it was
  due more than GRACE ago AND the job's log mtime predates it (log not touched
  at/after the scheduled time). Heuristic; jobs with no derivable log are
  skipped (can't tell).
- Scope: user crontab + /etc/cron.d. systemd timers (OS housekeeping) are out
  of scope. VRAM-collision forecasting is deferred (doctrine optional).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from croniter import croniter

from .base import BaseListener
from .util import run_cmd
from ..schema import Collision, CronJob, MissedRun, ScheduledRun
from ..state import StateStore

logger = logging.getLogger(__name__)

_GRACE = timedelta(minutes=15)          # time allowed for a due job to run + write its log
_UPCOMING_WINDOW = timedelta(minutes=60)
_COLLISION_GAP = timedelta(minutes=5)
_CRON_D_DIR = "/etc/cron.d"
# `crontab` is setgid (root:crontab) and loki-daemon.service sets
# RestrictSUIDSGID=true, so `crontab -l` is unreadable from inside the daemon
# (and /var/spool/cron/crontabs is 1730, so a direct read is out too). Cron
# writes this snapshot for us instead — see the operator-apply bundle;
# reading a plain file needs no privileges at all.
_SNAPSHOT = Path.home() / ".local/state/loki/crontab.snapshot"
_SNAPSHOT_MAX_AGE = timedelta(minutes=90)


def _run(cmd: List[str], timeout: float = 3.0) -> Optional[str]:
    # Cron line parsing needs raw (unstripped) stdout. Subprocess boilerplate
    # is shared in util.run_cmd (also catches OSError — strictly safer here).
    return run_cmd(cmd, timeout, strip=False)


def _local_now() -> datetime:
    """System-local timezone-aware now (the frame cron schedules run in)."""
    return datetime.now().astimezone()


def _extract_log(cmd: str) -> Optional[str]:
    # Match stdout/stderr redirects to a FILE, skipping fd-duplication forms
    # like `2>&1` whose target starts with `&`. A bare `>>?\s*(\S+)` regex
    # matches the `>` inside `2>&1` first and captures `&1` as the log path,
    # silently defeating missed-run detection for any job that merges stderr
    # before its file redirect. Take the LAST real file redirect, so both
    # `cmd >> a 2>&1` and `cmd 2>&1 >> a` resolve to `a`.
    path = None
    for target in re.findall(r">>?\s*(\S+)", cmd):
        if target.startswith("&"):
            continue
        path = target
    if path is None:
        return None
    path = os.path.expanduser(path)
    # /dev/null (and other /dev sinks) are not real logs — using their mtime
    # would yield false "missed run" flags.
    if path == "/dev/null" or path.startswith("/dev/"):
        return None
    return path


def _strip_redirects(cmd: str) -> str:
    # Drop everything from the first redirect operator onward.
    return re.split(r"\s*\d?>>?", cmd, maxsplit=1)[0].strip()


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _target_script(cmd: str) -> str:
    """The script a cron line actually runs.

    A line may prefix the command with env assignments —
    `XDG_RUNTIME_DIR=/run/user/1000 /path/doctrine_lint.py` — and taking
    toks[0] blindly made the "target" an assignment, which then failed the
    absolute-path scope check in poll(). The doctrine-lint governance job
    was silently missing from the schedule for exactly that reason. Skip
    leading NAME=VALUE tokens; a flag like `--opt=value` is not an
    assignment because it doesn't start with an identifier character."""
    toks = _strip_redirects(cmd).split()
    for tok in toks:
        if not _ENV_ASSIGN_RE.match(tok):
            return tok
    return toks[0] if toks else cmd


def _parse_line(line: str, has_user: bool) -> Optional[Tuple[str, str]]:
    """Return (schedule_expr, command) or None for blanks/comments/env-assigns."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):   # env assignment (SHELL=, PATH=, MAILTO=)
        return None
    if line.startswith("@"):
        parts = line.split(None, 2 if has_user else 1)
        if has_user and len(parts) >= 3:
            return parts[0], parts[2]
        if not has_user and len(parts) >= 2:
            return parts[0], parts[1]
        return None
    n = 6 if has_user else 5
    parts = line.split(None, n)
    if len(parts) < n + 1:
        return None
    schedule = " ".join(parts[:5])
    command = parts[n]
    return schedule, command


def _mtime_utc(path: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except (FileNotFoundError, PermissionError, OSError):
        return None


_TIMER_PROPS = ["Id", "Unit", "Description", "NextElapseUSecRealtime",
                "LastTriggerUSec", "TimersCalendar", "TimersMonotonic"]
# `TimersCalendar={ OnCalendar=<spec> ; next_elapse=@<epoch> }` under
# --timestamp=unix. NextElapseUSecRealtime stays HUMAN-formatted even with that
# flag (verified 2026-07-22), which is why the epoch is taken from here.
_ONCALENDAR_RE = re.compile(r"OnCalendar=([^;}]+)")
_NEXT_EPOCH_RE = re.compile(r"next_elapse=@(\d+)")
_MONOTONIC_SPEC_RE = re.compile(r"\{\s*(On\w+USec=[^;}]+?)\s*[;}]")


def _timers_enabled() -> bool:
    """Off-switch: this runs every 60s, so it must be disableable without a
    code change."""
    return os.environ.get("LOKI_CRON_SYSTEMD_TIMERS", "1") not in ("0", "false", "no")


def _parse_timer_show(block: str) -> Optional[CronJob]:
    """One `systemctl show` property block -> CronJob.

    Two timer shapes exist and both must survive:
      * calendar (OnCalendar) — carries `next_elapse=@<epoch>`, so next_run is
        exact;
      * monotonic (OnUnitActiveSec / OnBootSec, e.g. the 60s metrics sampler) —
        NextElapseUSecRealtime is EMPTY and there is no calendar, so the next
        run is not knowable from this call. The timer is still recorded, with
        next_run=None. Dropping it would repeat the silent-omission bug this
        whole change exists to fix; inventing a time would be worse.
    """
    props = {}
    monotonic_specs = []
    for line in block.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k == "TimersMonotonic":
            monotonic_specs.append(v)
        else:
            props[k] = v

    name = props.get("Id")
    if not name:
        return None

    cal = props.get("TimersCalendar", "") or ""
    next_run = None
    m = _NEXT_EPOCH_RE.search(cal)
    if m:
        try:
            next_run = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            next_run = None

    oncal = _ONCALENDAR_RE.search(cal)
    if oncal:
        schedule = oncal.group(1).strip()
    else:
        spec = next((s for s in (_MONOTONIC_SPEC_RE.search(x) for x in monotonic_specs) if s), None)
        schedule = spec.group(1).strip() if spec else "systemd-timer"

    return CronJob(
        name=name,
        schedule=schedule,
        command=props.get("Unit") or props.get("Description") or "",
        log_path=None,            # journald, not a file — no mtime heuristic
        source="systemd",
        next_run=next_run,
    )


class CronListener(BaseListener):
    name = "cron"
    interval_sec = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._last_missed: set[str] = set()
        self._last_stale: set[str] = set()
        self._last_collisions: set[frozenset] = set()

    def _read_snapshot(self) -> Tuple[Optional[str], Optional[str]]:
        """The snapshot, plus why it can't be trusted. A stale snapshot is a
        real signal — it means the cron job that writes it stopped running."""
        try:
            text = _SNAPSHOT.read_text()
        except FileNotFoundError:
            return None, (
                "user crontab unreadable (`crontab` is setgid; the daemon runs "
                f"with RestrictSUIDSGID) and no snapshot at {_SNAPSHOT}")
        except OSError as exc:
            return None, f"crontab snapshot unreadable ({exc.__class__.__name__})"

        mtime = _mtime_utc(str(_SNAPSHOT))
        if mtime is None:
            return text, "crontab snapshot mtime unreadable"
        age = datetime.now(timezone.utc) - mtime
        if age > _SNAPSHOT_MAX_AGE:
            return text, (
                f"crontab snapshot is {int(age.total_seconds() // 60)}m old "
                "— the snapshot cron job may have stopped")
        return text, None

    def _systemd_timers(self) -> Tuple[List[CronJob], List[str]]:
        """User systemd timers as schedule entries. In scope since the metrics
        and drift runners moved here: loki-metrics-sample, loki-metrics-gc,
        loki-drift-fast/nightly/weekly, loki-bench-heartbeat,
        loki-cloud-preflight. The listener's old "systemd timers are OS
        housekeeping" scope note predates that substrate entirely.

        `systemctl --user` needs no privileges, so unlike `crontab` it works
        inside the hardened daemon (verified under RestrictSUIDSGID=yes).

        Missed-run detection is deliberately NOT applied: systemd owns retry
        and journald owns the log, so the log-mtime heuristic doesn't carry."""
        if not _timers_enabled():
            return [], []

        listing = _run(["systemctl", "--user", "list-units", "--type=timer",
                        "--all", "--plain", "--no-legend"], timeout=5.0)
        if listing is None:
            return [], ["systemd timers unreadable (systemctl --user unavailable)"]

        units = [ln.split()[0] for ln in listing.splitlines()
                 if ln.strip() and ln.split()[0].endswith(".timer")]
        if not units:
            return [], []

        shown = _run(["systemctl", "--user", "show", *units, "--timestamp=unix",
                      *[f"-p{p}" for p in _TIMER_PROPS]], timeout=5.0)
        if shown is None:
            return [], ["systemd timer properties unreadable"]

        jobs = [j for j in (_parse_timer_show(b) for b in shown.split("\n\n")) if j]
        return jobs, []

    def _gather_sources(self) -> Tuple[List[Tuple[str, str, bool]], List[str]]:
        """Return (lines, errors). `errors` is the whole point: a source we
        could not read is NOT the same as a source with no jobs in it, and the
        difference has to survive all the way to the card."""
        out: List[Tuple[str, str, bool]] = []
        errors: List[str] = []

        crontab = _run(["crontab", "-l"])
        if crontab is not None:
            for ln in crontab.splitlines():
                out.append((ln, "crontab", False))
        else:
            # Fall back to the snapshot cron writes for us.
            snap, snap_err = self._read_snapshot()
            if snap is not None:
                for ln in snap.splitlines():
                    out.append((ln, "crontab (snapshot)", False))
            if snap_err:
                errors.append(snap_err)

        try:
            for fname in sorted(os.listdir(_CRON_D_DIR)):
                if fname.startswith(".") or fname == "placeholder":
                    continue
                fpath = os.path.join(_CRON_D_DIR, fname)
                try:
                    text = Path(fpath).read_text()
                except (PermissionError, OSError):
                    continue
                for ln in text.splitlines():
                    out.append((ln, f"/etc/cron.d/{fname}", True))
        except FileNotFoundError:
            pass
        except (PermissionError, OSError) as exc:
            errors.append(f"{_CRON_D_DIR} unreadable ({exc.__class__.__name__})")
        return out, errors

    def poll(self) -> None:
        now_local = _local_now()
        now_utc = now_local.astimezone(timezone.utc)

        jobs: List[CronJob] = []
        missed: List[MissedRun] = []
        upcoming: List[ScheduledRun] = []
        stale: List[str] = []

        sources, source_errors = self._gather_sources()
        for raw, source, has_user in sources:
            parsed = _parse_line(raw, has_user)
            if parsed is None:
                continue
            schedule, command = parsed
            if not croniter.is_valid(schedule):
                continue

            command = command.strip()
            target = _target_script(command)
            # Scope: monarch workload jobs target an absolute/home path. Shell
            # builtins and conditionals (test, [, command -v …) lead the system
            # /etc/cron.d housekeeping entries — same OS-housekeeping category as
            # systemd timers, which are out of scope. Skip non-path targets.
            if not (target.startswith("/") or target.startswith("~")):
                continue
            name = os.path.basename(target)
            log_path = _extract_log(command)
            clean_cmd = _strip_redirects(command)

            # next / prev run in local tz, stored as UTC. One croniter parse per
            # job (not two): take prev from the base cursor, reset to the base
            # via set_current, then take next — exactly equivalent to two fresh
            # croniter() instances (verified across schedules/boundaries) at half
            # the schedule-parse cost.
            try:
                it = croniter(schedule, now_local)
                prev_local = it.get_prev(datetime)
                it.set_current(now_local, force=True)
                nxt_local = it.get_next(datetime)
            except Exception:
                continue
            # croniter's tz propagation is version-dependent: some versions hand
            # back NAIVE datetimes even for an aware base. now_local is aware, so
            # an unguarded `now_local - prev_local` (below) would raise TypeError.
            # Anchor any naive result to the local zone here, at the source.
            if nxt_local.tzinfo is None:
                nxt_local = nxt_local.replace(tzinfo=now_local.tzinfo)
            if prev_local.tzinfo is None:
                prev_local = prev_local.replace(tzinfo=now_local.tzinfo)
            nxt_utc = nxt_local.astimezone(timezone.utc)

            jobs.append(CronJob(
                name=name, schedule=schedule, command=clean_cmd,
                log_path=log_path, source=source, next_run=nxt_utc,
            ))

            # upcoming within 60 min
            if nxt_utc - now_utc <= _UPCOMING_WINDOW:
                upcoming.append(ScheduledRun(name=name, next_run=nxt_utc))

            # stale: a path-like target that doesn't exist
            if (target.startswith("/") or target.startswith("~")) and not os.path.exists(target):
                stale.append(name)

            # missed: prev run due > GRACE ago and log not touched since
            if (now_local - prev_local) > _GRACE and log_path:
                lm = _mtime_utc(log_path)
                prev_utc = prev_local.astimezone(timezone.utc)
                if lm is not None and lm < prev_utc:
                    missed.append(MissedRun(
                        name=name, scheduled_for=prev_utc,
                        log_path=log_path, last_log_mtime=lm,
                    ))

        # systemd timers: already structured, so they join `jobs` directly
        # rather than going through cron-line parsing. A monotonic timer has no
        # knowable next_run and simply never enters the upcoming window.
        timer_jobs, timer_errors = self._systemd_timers()
        source_errors.extend(timer_errors)
        for tj in timer_jobs:
            jobs.append(tj)
            if tj.next_run is not None and tj.next_run - now_utc <= _UPCOMING_WINDOW:
                upcoming.append(ScheduledRun(name=tj.name, next_run=tj.next_run))

        # collisions: upcoming pairs within 5 min
        collisions: List[Collision] = []
        su = sorted(upcoming, key=lambda r: r.next_run)
        for i in range(len(su)):
            for j in range(i + 1, len(su)):
                gap = su[j].next_run - su[i].next_run
                if gap <= _COLLISION_GAP:
                    collisions.append(Collision(
                        job_a=su[i].name, job_b=su[j].name,
                        run_a=su[i].next_run, run_b=su[j].next_run,
                        gap_sec=int(gap.total_seconds()),
                    ))
                else:
                    break  # sorted — no closer pair past this point

        def update(model):
            s = model.schedule
            s.cron_entries = jobs
            s.missed_runs_24h = missed
            s.upcoming_60min = sorted(upcoming, key=lambda r: r.next_run)
            s.collisions = collisions
            s.stale_entries = sorted(set(stale))
            s.cron_updated_at = now_utc
            s.cron_source_errors = source_errors

        StateStore.get().apply(update)
        self._emit_transitions(missed, stale, collisions)

    def _emit_transitions(self, missed, stale, collisions) -> None:
        store = StateStore.get()

        missed_names = {m.name for m in missed}
        for m in missed:
            if m.name not in self._last_missed:
                store.emit(
                    type="cron_missed_run", severity="warning",
                    detail=f"{m.name} missed scheduled run at "
                           f"{m.scheduled_for.isoformat()} (log stale)",
                )
                logger.warning("[cron] missed run: %s", m.name)
        self._last_missed = missed_names

        stale_set = set(stale)
        for name in stale_set:
            if name not in self._last_stale:
                store.emit(
                    type="cron_stale_entry", severity="warning",
                    detail=f"{name}: cron target script does not exist",
                )
                logger.warning("[cron] stale entry: %s", name)
        self._last_stale = stale_set

        coll_set = {frozenset((c.job_a, c.job_b)) for c in collisions}
        for c in collisions:
            pair = frozenset((c.job_a, c.job_b))
            if pair not in self._last_collisions:
                store.emit(
                    type="cron_collision_warning", severity="info",
                    detail=f"{c.job_a} and {c.job_b} run within {c.gap_sec}s "
                           f"(next 60 min)",
                )
        self._last_collisions = coll_set
