"""_extract_log must resolve the FILE redirect, never the fd-duplication form
`2>&1`. A bare `>>?\\s*(\\S+)` matched the `>` inside `2>&1` first and captured
`&1` as the log path, silently defeating missed-run detection (review finding)."""

from loki.listeners import cron


def test_extract_log_stderr_dup_before_file():
    assert cron._extract_log("/usr/bin/job 2>&1 >> /var/log/job.log") == "/var/log/job.log"


def test_extract_log_stderr_dup_after_file():
    assert cron._extract_log("/usr/bin/job >> /var/log/job.log 2>&1") == "/var/log/job.log"


def test_extract_log_single_redirect():
    assert cron._extract_log("job > /var/log/out") == "/var/log/out"


def test_extract_log_dev_null_with_dup_is_not_a_log():
    assert cron._extract_log("job > /dev/null 2>&1") is None


def test_extract_log_no_redirect():
    assert cron._extract_log("job --flag value") is None


def test_extract_log_expands_user(monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    assert cron._extract_log("job >> ~/x.log 2>&1") == "/home/tester/x.log"


# --- unreadable source must never read as "nothing scheduled" -------------

def test_gather_sources_reports_an_unreadable_user_crontab(monkeypatch, tmp_path):
    """`crontab` is setgid; loki-daemon.service sets RestrictSUIDSGID=true, so
    `crontab -l` returns None inside the daemon. That must surface as an
    ERROR, not as an empty schedule — an empty schedule renders as a clean
    board (0 missed / 0 collisions) and hides 13 real jobs."""
    from loki.listeners import cron

    monkeypatch.setattr(cron, "_run", lambda *a, **k: None)
    monkeypatch.setattr(cron, "_CRON_D_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(cron, "_SNAPSHOT", tmp_path / "absent.snapshot")

    lines, errors = cron.CronListener()._gather_sources()

    assert lines == []
    assert errors, "an unreadable crontab must produce an error"
    assert any("crontab" in e for e in errors)


def test_gather_sources_reports_no_error_when_the_crontab_reads(monkeypatch, tmp_path):
    from loki.listeners import cron

    monkeypatch.setattr(cron, "_run", lambda *a, **k: "*/5 * * * * /bin/true\n")
    monkeypatch.setattr(cron, "_CRON_D_DIR", str(tmp_path / "nope"))

    lines, errors = cron.CronListener()._gather_sources()

    assert errors == []
    assert len(lines) == 1


def test_gather_sources_falls_back_to_the_snapshot(monkeypatch, tmp_path):
    """The snapshot is how the hardened daemon sees cron at all."""
    from loki.listeners import cron

    snap = tmp_path / "crontab.snapshot"
    snap.write_text("*/30 * * * * /home/operator/bin/news-ingest\n")
    monkeypatch.setattr(cron, "_run", lambda *a, **k: None)
    monkeypatch.setattr(cron, "_CRON_D_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(cron, "_SNAPSHOT", snap)

    lines, errors = cron.CronListener()._gather_sources()

    assert len(lines) == 1
    assert lines[0][1] == "crontab (snapshot)"
    assert errors == []


def test_poll_publishes_the_source_errors(monkeypatch, tmp_path):
    """The error has to reach state.schedule, or the card can't render it."""
    from loki.listeners import cron

    monkeypatch.setattr(cron, "_run", lambda *a, **k: None)
    monkeypatch.setattr(cron, "_CRON_D_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(cron, "_SNAPSHOT", tmp_path / "absent.snapshot")

    captured = {}

    class _Store:
        def apply(self, fn):
            class _S:
                schedule = type("X", (), {})()
            m = _S()
            fn(m)
            captured.update(vars(m.schedule))

    monkeypatch.setattr(cron.StateStore, "get", staticmethod(lambda: _Store()))
    listener = cron.CronListener()
    monkeypatch.setattr(listener, "_emit_transitions", lambda *a, **k: None)

    listener.poll()

    assert captured["cron_entries"] == []
    assert captured["cron_source_errors"], "poll must publish the read failure"


# --- env-prefixed cron lines ----------------------------------------------

def test_target_script_skips_leading_env_assignments():
    """`15 3 * * * XDG_RUNTIME_DIR=/run/user/1000 /path/doctrine_lint.py` — the
    target is the SCRIPT, not the env assignment. Taking toks[0] made the
    target 'XDG_RUNTIME_DIR=/run/user/1000', which fails the "must be an
    absolute path" scope check, so the doctrine-lint governance job was
    silently absent from the schedule."""
    from loki.listeners import cron

    cmd = "XDG_RUNTIME_DIR=/run/user/1000 /home/operator/monarch-stack/doctrine_lint.py"
    assert cron._target_script(cmd) == "/home/operator/monarch-stack/doctrine_lint.py"


def test_target_script_skips_several_env_assignments():
    from loki.listeners import cron

    assert cron._target_script("A=1 B=2 /bin/job --flag") == "/bin/job"


def test_target_script_unchanged_for_a_plain_command():
    from loki.listeners import cron

    assert cron._target_script("/home/operator/bin/news-ingest") == "/home/operator/bin/news-ingest"
    assert cron._target_script("/bin/job >> /var/log/x.log") == "/bin/job"


def test_target_script_does_not_mistake_a_flag_for_an_assignment():
    from loki.listeners import cron

    assert cron._target_script("/bin/job --opt=value") == "/bin/job"


def test_target_script_all_assignments_falls_back_to_the_first_token():
    from loki.listeners import cron

    assert cron._target_script("A=1 B=2") == "A=1"


# --- systemd timers -------------------------------------------------------
# Fixtures are VERBATIM `systemctl --user show ... --timestamp=unix` output,
# captured 2026-07-22. Calendar timers carry `next_elapse=@<epoch>`; monotonic
# ones (OnUnitActiveSec) have an EMPTY NextElapseUSecRealtime and no calendar
# at all, so a next run simply is not knowable from this call — we record the
# timer without one rather than fabricating a time.

_CALENDAR_BLOCK = """Unit=loki-drift-fast.service
TimersCalendar={ OnCalendar=*-*-* *:00:00 ; next_elapse=@1784754000 }
NextElapseUSecRealtime=Wed 2026-07-22 17:00:00 EDT
LastTriggerUSec=Wed 2026-07-22 16:00:03 EDT
Id=loki-drift-fast.timer
Description=Drift runner - unit suites, hourly"""

_MONOTONIC_BLOCK = """Unit=loki-metrics-sample.service
TimersMonotonic={ OnUnitActiveUSec=1min ; next_elapse=2w 6d 21h 27min 59.8s }
NextElapseUSecRealtime=
LastTriggerUSec=Wed 2026-07-22 16:17:23 EDT
Id=loki-metrics-sample.timer
Description=Sample Loki Core-vitals into loki_metrics every 60s"""


def test_parse_timer_show_builds_a_cron_job_from_a_calendar_timer():
    from loki.listeners import cron

    job = cron._parse_timer_show(_CALENDAR_BLOCK)

    assert job is not None
    assert job.name == "loki-drift-fast.timer"
    assert job.source == "systemd"
    assert job.schedule == "*-*-* *:00:00"
    assert job.command == "loki-drift-fast.service"
    assert job.log_path is None                  # journald, not a file
    assert job.next_run is not None
    assert job.next_run.tzinfo is not None       # stored UTC-aware, like cron jobs
    assert job.next_run.timestamp() == 1784754000


def test_parse_timer_show_keeps_a_monotonic_timer_but_without_a_next_run():
    """The 60s metrics sampler is monotonic: real, running, and with no
    knowable next_elapse here. It must still be VISIBLE — omitting it is the
    same silent-omission bug we are fixing — but next_run stays None rather
    than invented."""
    from loki.listeners import cron

    job = cron._parse_timer_show(_MONOTONIC_BLOCK)

    assert job is not None
    assert job.name == "loki-metrics-sample.timer"
    assert job.schedule == "OnUnitActiveUSec=1min"
    assert job.next_run is None


def test_parse_timer_show_returns_none_without_an_id():
    from loki.listeners import cron

    assert cron._parse_timer_show("Unit=x.service\nDescription=nope") is None


def test_systemd_timers_reports_an_error_when_systemctl_is_unavailable(monkeypatch):
    from loki.listeners import cron

    monkeypatch.setattr(cron, "_run", lambda *a, **k: None)
    jobs, errors = cron.CronListener()._systemd_timers()

    assert jobs == []
    assert errors                      # unavailable != "no timers"


def test_systemd_timers_off_switch(monkeypatch):
    """Env kill-switch, so a noisy or slow systemctl can be turned off without
    a code change (the listener runs every 60s)."""
    from loki.listeners import cron

    monkeypatch.setenv("LOKI_CRON_SYSTEMD_TIMERS", "0")
    jobs, errors = cron.CronListener()._systemd_timers()

    assert jobs == [] and errors == []


def test_systemd_timers_parses_a_two_unit_response(monkeypatch):
    from loki.listeners import cron

    def fake_run(cmd, *a, **k):
        if "list-units" in cmd:
            return ("loki-drift-fast.timer   loaded active waiting x y\n"
                    "loki-metrics-sample.timer loaded active waiting x y\n")
        return _CALENDAR_BLOCK + "\n\n" + _MONOTONIC_BLOCK + "\n"

    monkeypatch.setattr(cron, "_run", fake_run)
    jobs, errors = cron.CronListener()._systemd_timers()

    assert errors == []
    assert [j.name for j in jobs] == ["loki-drift-fast.timer",
                                      "loki-metrics-sample.timer"]
