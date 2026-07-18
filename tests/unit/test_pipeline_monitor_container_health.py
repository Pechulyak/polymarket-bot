# -*- coding: utf-8 -*-
"""Unit tests for scripts.pipeline_monitor.check_container_health (INFRA-042).

Edge-triggered docker healthcheck alert:
    - ok -> unhealthy  -> 1 alert (UNHEALTHY) + UPSERT
    - unhealthy -> ok  -> 1 alert (recovered)  + UPSERT
    - same state repeated -> silent
    - first run with healthy status -> silent (no spurious recovered)
    - inspect failure / unknown status -> continue, no alert

Tests narrow CONTAINERS via monkeypatch to one container to keep each
case focused. subprocess.run is mocked per-call so each test controls
what `docker inspect --format={{.State.Health.Status}}` returns.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts import pipeline_monitor


def _make_cursor_mock(fetchone_return, execute_log):
    """Build a cursor that:
      - works as a context manager (`with conn.cursor() as cur:`)
      - returns fetchone_return from fetchone()
      - records every execute() call (sql, params) into execute_log
    """
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.return_value = fetchone_return

    def _record(sql, params=None):
        execute_log.append((sql, params))

    cur.execute.side_effect = _record
    return cur


def _make_conn_mock(fetchone_return, execute_log, commit_log):
    """Build a DB-API style conn: cursor() returns our cursor mock,
    commit() appends to commit_log so we can assert UPSERT commits.
    """
    conn = MagicMock()
    cursor = _make_cursor_mock(fetchone_return, execute_log)
    conn.cursor.return_value = cursor

    def _commit():
        commit_log.append(True)

    conn.commit.side_effect = _commit
    conn.close = MagicMock()
    return conn


def _subprocess_completed(returncode, stdout=""):
    """Mimic subprocess.CompletedProcess — only .returncode and .stdout used."""
    return SimpleNamespace(returncode=returncode, stdout=stdout)


@pytest.fixture
def single_container(monkeypatch):
    """Narrow CONTAINERS to one container for focused single-container tests."""
    monkeypatch.setattr(pipeline_monitor, "CONTAINERS", ["polymarket_bot"])


def test_unhealthy_with_last_ok_alerts_and_upserts(
    monkeypatch, single_container
):
    """ok -> unhealthy transition: 1 UNHEALTHY alert + UPSERT(unhealthy)."""
    fetchone_return = ("ok",)  # last alert state was 'ok'
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)

    sent = []

    def _fake_docker_run(*args, **kwargs):
        # args[0] is the cmd list; ignore kwargs.
        return _subprocess_completed(0, "unhealthy\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    # One Telegram message, mentions UNHEALTHY.
    assert len(sent) == 1, f"expected 1 alert, got {len(sent)}: {sent}"
    assert "UNHEALTHY" in sent[0]
    assert "polymarket_bot" in sent[0]

    # UPSERT happened with status='unhealthy'.
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert len(upserts) == 1, f"expected 1 upsert, got {len(upserts)}: {upserts}"
    sql, params = upserts[0]
    assert params == (
        "container_health_alert_state_polymarket_bot",
        "unhealthy",
    )
    # And it was committed.
    assert commit_log == [True]


def test_unhealthy_with_last_unhealthy_silent(monkeypatch, single_container):
    """Same state repeated (still unhealthy): no alert, no upsert."""
    fetchone_return = ("unhealthy",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "unhealthy\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"expected silence, got: {sent}"
    # No UPSERT, no commit.
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []
    assert commit_log == []


def test_healthy_with_last_unhealthy_alerts_recovered(monkeypatch, single_container):
    """unhealthy -> ok transition: 1 recovered alert + UPSERT(ok)."""
    fetchone_return = ("unhealthy",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "healthy\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert len(sent) == 1, f"expected 1 alert, got {len(sent)}: {sent}"
    assert "recovered" in sent[0].lower()
    assert "polymarket_bot" in sent[0]

    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert len(upserts) == 1
    sql, params = upserts[0]
    assert params == (
        "container_health_alert_state_polymarket_bot",
        "ok",
    )
    assert commit_log == [True]


def test_healthy_with_last_ok_silent(monkeypatch, single_container):
    """No transition (ok -> ok): no alert, no upsert."""
    fetchone_return = ("ok",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "healthy\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"expected silence, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []
    assert commit_log == []


def test_first_run_with_healthy_status_no_spurious_recovered(
    monkeypatch, single_container
):
    """First run: fetchone() -> None. With healthy docker status, current=ok,
    last_alerted defaults to 'ok', no transition -> silent.
    Guards against false 'recovered' alerts on first execution."""
    fetchone_return = None
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "healthy\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"expected silence on first run, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []
    assert commit_log == []


def test_inspect_failure_continues_without_alert(monkeypatch, single_container):
    """If docker inspect raises, the per-container try/except swallows it
    and the function exits cleanly without sending an alert."""
    fetchone_return = ("ok",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        raise RuntimeError("docker daemon unreachable")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        # Must not raise.
        pipeline_monitor.check_container_health()

    assert sent == [], f"inspect failure must not alert, got: {sent}"
    # Connection still closed cleanly via finally.
    conn.close.assert_called_once()


def test_unknown_status_continues_without_alert(monkeypatch, single_container):
    """If docker returns an unexpected status string, treat as continue
    (no alert). Container may legitimately lack healthcheck or be
    in a transient state not handled by the mapping."""
    fetchone_return = ("ok",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "nonexistent-status\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"unexpected status must not alert, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []


def test_empty_stdout_no_healthcheck_treated_as_ok(monkeypatch, single_container):
    """Container without healthcheck returns empty stdout -> mapped to ok."""
    fetchone_return = ("ok",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"empty=no-healthcheck must not alert, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []


def test_starting_status_skips_no_premature_recovered(monkeypatch, single_container):
    """'starting' is transient during a restart. Even if last state was
    'unhealthy', a 'starting' status must NOT emit a premature 'recovered' —
    state is left untouched until the container reaches 'healthy'."""
    fetchone_return = ("unhealthy",)  # was unhealthy, container now restarting
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(0, "starting\n")

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"'starting' must not emit recovered, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []
    assert commit_log == []


def test_nonzero_rc_skips_no_spurious_recovered(monkeypatch, single_container):
    """docker inspect rc!=0 (container missing / inspect error) must be skipped,
    not read as empty->ok. Previously unhealthy container must NOT flip to
    a spurious 'recovered' just because it was removed."""
    fetchone_return = ("unhealthy",)
    execute_log = []
    commit_log = []
    conn = _make_conn_mock(fetchone_return, execute_log, commit_log)
    sent = []

    def _fake_docker_run(*args, **kwargs):
        return _subprocess_completed(1, "")  # non-zero rc, no output

    with patch.object(pipeline_monitor, "get_db_connection", return_value=conn), \
         patch.object(pipeline_monitor, "subprocess", wraps=MagicMock(
             run=_fake_docker_run)), \
         patch.object(pipeline_monitor, "send_telegram_message",
                      side_effect=lambda m: sent.append(m)):
        pipeline_monitor.check_container_health()

    assert sent == [], f"rc!=0 must not alert, got: {sent}"
    upserts = [c for c in execute_log
               if c[0].lstrip().upper().startswith("INSERT INTO SYSTEM_STATE")]
    assert upserts == []
    assert commit_log == []
    conn.close.assert_called_once()
