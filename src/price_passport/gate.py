"""The promotion gate: moves `@champion` to a model version only if it clearly beats the current champion (decisions 8).

A challenger is compared on the MAE its training run logged on the fixed holdout. It becomes champion only if that MAE
is at least 2 percent lower than the champion's, measured on the same holdout; a tie keeps the champion, and a run on
another holdout is refused rather than compared. Without a champion, the first version that reaches the gate becomes
one. Every decision is written onto the challenger as tags, so the registry shows why a version did or did not serve.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from price_passport.training import model_name

CHAMPION = "champion"
REQUIRED_IMPROVEMENT = 0.02
LATEST = "latest"


@dataclass(frozen=True)
class Candidate:
    version: str
    mae: float
    holdout_id: str


class Outcome(StrEnum):
    PROMOTED = "promoted"
    KEPT = "kept"
    REFUSED = "refused"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str


def decide(champion: Candidate | None, challenger: Candidate) -> Decision:
    if champion is None:
        return Decision(Outcome.PROMOTED, "no champion yet")
    if champion.version == challenger.version:
        return Decision(Outcome.KEPT, f"version {challenger.version} is already the champion")
    if champion.holdout_id != challenger.holdout_id:
        return Decision(
            Outcome.REFUSED,
            f"holdout {challenger.holdout_id} differs from the champion's {champion.holdout_id}",
        )
    threshold = champion.mae * (1 - REQUIRED_IMPROVEMENT)
    comparison = f"MAE {challenger.mae:.3f} against champion v{champion.version} at {champion.mae:.3f}"
    if challenger.mae <= threshold:
        return Decision(Outcome.PROMOTED, f"{comparison}, at least 2 percent lower")
    return Decision(Outcome.KEPT, f"{comparison}, less than 2 percent lower")


def candidate(client: Any, name: str, version: str) -> Candidate:
    model_version = client.get_model_version(name, version)
    run = client.get_run(model_version.run_id)
    return Candidate(
        version=str(model_version.version),
        mae=float(run.data.metrics["mae"]),
        holdout_id=run.data.tags["holdout_id"],
    )


def current_champion(client: Any, name: str) -> Candidate | None:
    from mlflow.exceptions import MlflowException

    try:
        model_version = client.get_model_version_by_alias(name, CHAMPION)
    except MlflowException as error:
        if error.error_code == "RESOURCE_DOES_NOT_EXIST":
            return None
        raise
    return candidate(client, name, str(model_version.version))


def latest_version(client: Any, name: str) -> str:
    versions = client.search_model_versions(f"name='{name}'")
    if not versions:
        raise ValueError(f"{name} has no versions")
    return str(max(int(model_version.version) for model_version in versions))


def run_gate(client: Any, name: str, version: str) -> Decision:
    if version == LATEST:
        version = latest_version(client, name)
    champion = current_champion(client, name)
    decision = decide(champion, candidate(client, name, version))
    if champion is not None and champion.version == version:
        # The champion's tags say why it was promoted; judging it again must not overwrite them.
        return decision
    if decision.outcome is Outcome.PROMOTED:
        client.set_registered_model_alias(name, CHAMPION, version)
    client.set_model_version_tag(name, version, "gate_outcome", decision.outcome.value)
    client.set_model_version_tag(name, version, "gate_reason", decision.reason)
    client.set_model_version_tag(name, version, "gate_champion_before", champion.version if champion else "none")
    return decision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--version", default=LATEST, help="model version to judge, or 'latest'")
    arguments = parser.parse_args(argv)

    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_registry_uri("databricks-uc")
    name = model_name(arguments.catalog, arguments.schema)
    decision = run_gate(MlflowClient(), name, arguments.version)
    print(f"{name}: {decision.outcome.value}, {decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
