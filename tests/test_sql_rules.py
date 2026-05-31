"""Unit tests for SQL guardrails."""

import pytest

from claude_agent_platform.guardrails.sql_rules import validate_sql


def test_reject_empty():
    r = validate_sql("")
    assert not r.ok
    assert r.action == "deny"


def test_reject_delete():
    r = validate_sql('DELETE FROM "ChatTopicDaily"')
    assert not r.ok


def test_allow_select():
    r = validate_sql('SELECT 1')
    assert r.ok
    assert "LIMIT" in r.normalized_sql


def test_inject_limit():
    r = validate_sql('SELECT * FROM "ChatTopicDaily"')
    assert r.ok
    assert r.normalized_sql.endswith("LIMIT 10000")


def test_cap_limit():
    r = validate_sql('SELECT 1 LIMIT 99999', max_rows=100)
    assert r.ok
    assert "LIMIT 100" in r.normalized_sql


def test_reject_multi_statement():
    r = validate_sql("SELECT 1; SELECT 2")
    assert not r.ok
