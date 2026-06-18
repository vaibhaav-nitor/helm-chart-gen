#!/usr/bin/env python
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

if "CREWAI_STORAGE_DIR" not in os.environ:
    os.environ["CREWAI_STORAGE_DIR"] = str(Path(".crewai_storage").resolve())

from helm_chart_gen.crew import HelmChartGen

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


DEFAULT_INPUTS: dict[str, Any] = {
    "repository_url": "https://github.com/crewAIInc/crewAI-examples.git",
    "git_ref": "main",
    "app_subdirectory": "",
    "chart_name": "generated-app",
    "release_name": "generated-app",
    "namespace": "default",
    "image_repository": "example.azurecr.io/generated-app",
    "image_tag": "0.1.0",
    "container_port": "",
    "ingress_enabled": False,
    "ingress_host": "",
    "aks_cluster_name": "",
    "azure_tenant_id": "",
    "keyvault_name": "",
    "user_assigned_identity_client_id": "",
    "secret_mappings_json": "[]",
    "config_values_json": "{}",
    "enable_hpa": False,
    "min_replicas": 2,
    "max_replicas": 5,
}


def run():
    """Run the crew locally with environment-variable inputs."""
    inputs = _inputs_from_env()
    return _kickoff(inputs)


def train():
    """Train the crew for a given number of iterations."""
    inputs = _inputs_from_env()
    try:
        HelmChartGen().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}") from e


def replay():
    """Replay the crew execution from a specific task."""
    try:
        HelmChartGen().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}") from e


def test():
    """Test the crew execution."""
    inputs = _inputs_from_env()
    try:
        HelmChartGen().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}") from e


def run_with_trigger():
    """Run the crew with a CrewAI Studio trigger payload."""
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        raise Exception("Invalid JSON payload provided as argument") from exc

    inputs = _normalize_inputs(trigger_payload)
    return _kickoff(inputs)


def _kickoff(inputs: dict[str, Any]):
    _prepare_local_storage()
    try:
        return HelmChartGen().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the Helm chart generator crew: {e}") from e


def _inputs_from_env() -> dict[str, Any]:
    env_inputs = {
        key: os.getenv(f"HELM_GEN_{key.upper()}")
        for key in DEFAULT_INPUTS
        if os.getenv(f"HELM_GEN_{key.upper()}") is not None
    }
    return _normalize_inputs(env_inputs)


def _normalize_inputs(raw_inputs: dict[str, Any]) -> dict[str, Any]:
    payload = raw_inputs.get("crewai_trigger_payload", raw_inputs)
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        payload = {}

    normalized = {**DEFAULT_INPUTS, **payload}
    normalized["ingress_enabled"] = _to_bool(normalized["ingress_enabled"])
    normalized["enable_hpa"] = _to_bool(normalized["enable_hpa"])
    normalized["min_replicas"] = int(normalized["min_replicas"] or 2)
    normalized["max_replicas"] = int(normalized["max_replicas"] or 5)
    normalized["secret_mappings_json"] = _safe_json_string(normalized["secret_mappings_json"], default="[]")
    normalized["config_values_json"] = _safe_json_string(normalized["config_values_json"], default="{}")
    _reject_secret_values(normalized)
    return normalized


def _safe_json_string(value: Any, default: str) -> str:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        json.loads(value)
        return value
    return json.dumps(value)


def _reject_secret_values(inputs: dict[str, Any]) -> None:
    secret_mappings = json.loads(inputs["secret_mappings_json"])
    if not isinstance(secret_mappings, list):
        raise ValueError("secret_mappings_json must be a JSON list.")

    forbidden_keys = {"value", "secret_value", "password", "token", "api_key", "apikey"}
    for item in secret_mappings:
        if isinstance(item, dict) and forbidden_keys.intersection({str(key).lower() for key in item}):
            raise ValueError("secret_mappings_json must contain Key Vault references only, not secret values.")


def _prepare_local_storage() -> None:
    if "CREWAI_STORAGE_DIR" not in os.environ:
        storage_dir = Path(".crewai_storage").resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CREWAI_STORAGE_DIR"] = str(storage_dir)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


if __name__ == "__main__":
    run()
