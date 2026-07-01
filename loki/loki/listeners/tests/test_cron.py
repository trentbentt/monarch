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
