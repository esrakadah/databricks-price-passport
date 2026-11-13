from types import SimpleNamespace

import pytest
from mlflow.exceptions import MlflowException, RestException

from price_passport.gate import CHAMPION, Candidate, Outcome, decide, run_gate

HOLDOUT = "2026-08-01_2026-10-28"
NAME = "workspace.price_passport.price_model"


def test_the_first_version_through_the_gate_becomes_champion():
    assert decide(None, Candidate("1", 52.6, HOLDOUT)).outcome is Outcome.PROMOTED


def test_a_challenger_two_percent_better_is_promoted():
    assert decide(Candidate("1", 50.0, HOLDOUT), Candidate("2", 49.0, HOLDOUT)).outcome is Outcome.PROMOTED


def test_a_challenger_less_than_two_percent_better_is_not():
    decision = decide(Candidate("1", 50.0, HOLDOUT), Candidate("2", 49.01, HOLDOUT))

    assert decision.outcome is Outcome.KEPT
    assert "less than 2 percent" in decision.reason


def test_a_tie_keeps_the_champion():
    assert decide(Candidate("1", 50.0, HOLDOUT), Candidate("2", 50.0, HOLDOUT)).outcome is Outcome.KEPT


def test_a_run_on_another_holdout_is_refused_not_compared():
    decision = decide(Candidate("1", 50.0, HOLDOUT), Candidate("2", 10.0, "2026-09-01_2026-11-28"))

    assert decision.outcome is Outcome.REFUSED


def test_the_champion_judged_again_stays():
    assert decide(Candidate("2", 36.5, HOLDOUT), Candidate("2", 36.5, HOLDOUT)).outcome is Outcome.KEPT


class FakeRegistry:
    """The part of MlflowClient the gate uses, over versions given as {version: (mae, holdout_id)}."""

    def __init__(self, versions, champion=None):
        self.versions = versions
        self.aliases = {CHAMPION: champion} if champion else {}
        self.tags = {}

    def get_model_version(self, name, version):
        return SimpleNamespace(version=version, run_id=f"run-{version}")

    def get_run(self, run_id):
        mae, holdout_id = self.versions[run_id.removeprefix("run-")]
        return SimpleNamespace(data=SimpleNamespace(metrics={"mae": mae}, tags={"holdout_id": holdout_id}))

    def get_model_version_by_alias(self, name, alias):
        if alias not in self.aliases:
            raise RestException({"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "alias does not exist"})
        return self.get_model_version(name, self.aliases[alias])

    def search_model_versions(self, filter_string):
        return [SimpleNamespace(version=version) for version in self.versions]

    def set_registered_model_alias(self, name, alias, version):
        self.aliases[alias] = version

    def set_model_version_tag(self, name, version, key, value):
        self.tags[(version, key)] = value


def test_the_latest_version_is_judged_and_the_alias_moves_on_promotion():
    registry = FakeRegistry({"1": (52.6, HOLDOUT), "2": (36.5, HOLDOUT)}, champion="1")

    decision = run_gate(registry, NAME, "latest")

    assert decision.outcome is Outcome.PROMOTED
    assert registry.aliases[CHAMPION] == "2"
    assert registry.tags[("2", "gate_outcome")] == "promoted"
    assert registry.tags[("2", "gate_champion_before")] == "1"


def test_a_kept_champion_keeps_its_alias_and_the_challenger_records_why():
    registry = FakeRegistry({"1": (50.0, HOLDOUT), "2": (49.5, HOLDOUT)}, champion="1")

    run_gate(registry, NAME, "2")

    assert registry.aliases[CHAMPION] == "1"
    assert registry.tags[("2", "gate_outcome")] == "kept"
    assert "less than 2 percent" in registry.tags[("2", "gate_reason")]


def test_without_a_champion_the_judged_version_becomes_one():
    registry = FakeRegistry({"1": (52.6, HOLDOUT)})

    run_gate(registry, NAME, "1")

    assert registry.aliases[CHAMPION] == "1"
    assert registry.tags[("1", "gate_champion_before")] == "none"


def test_registry_errors_other_than_a_missing_alias_are_not_swallowed():
    registry = FakeRegistry({"1": (52.6, HOLDOUT)})

    def unavailable(name, alias):
        raise RestException({"error_code": "TEMPORARILY_UNAVAILABLE", "message": "registry unavailable"})

    registry.get_model_version_by_alias = unavailable

    with pytest.raises(MlflowException, match="unavailable"):
        run_gate(registry, NAME, "1")


def test_judging_the_champion_again_leaves_its_promotion_record_alone():
    registry = FakeRegistry({"1": (52.6, HOLDOUT), "2": (36.5, HOLDOUT)}, champion="1")
    run_gate(registry, NAME, "2")

    run_gate(registry, NAME, "2")

    assert registry.tags[("2", "gate_outcome")] == "promoted"
    assert registry.tags[("2", "gate_champion_before")] == "1"
