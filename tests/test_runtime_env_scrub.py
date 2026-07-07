"""The single most important test: the agent subprocess env must never carry
credentials that force API billing. If this fails, you risk surprise charges.
"""
import os

from wayfarer.agents.runtime import subscription_env, _BILLING_ENV_VARS


def test_subscription_env_strips_billing_vars(monkeypatch):
    for v in _BILLING_ENV_VARS:
        monkeypatch.setenv(v, "should-be-removed")
    env = subscription_env()
    for v in _BILLING_ENV_VARS:
        assert v not in env, f"{v} leaked into the agent subprocess env"


def test_subscription_env_keeps_other_vars(monkeypatch):
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    monkeypatch.setenv("HOME", "/home/tester")
    env = subscription_env()
    assert env.get("HOME") == "/home/tester"
