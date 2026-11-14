import json
import re
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RULESET_FILE = REPOSITORY_ROOT / ".github" / "rulesets" / "protect-main.json"
CI_WORKFLOW_FILE = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
# Jobs are the two-space-indented keys under the top-level `jobs:` block.
JOB_NAME = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def load_ruleset() -> dict[str, Any]:
    ruleset: dict[str, Any] = json.loads(RULESET_FILE.read_text(encoding="utf-8"))
    return ruleset


def rule(rule_type: str) -> dict[str, Any]:
    return next(entry for entry in load_ruleset()["rules"] if entry["type"] == rule_type)


def ci_job_names() -> set[str]:
    workflow = CI_WORKFLOW_FILE.read_text(encoding="utf-8")
    jobs_block = workflow.split("\njobs:\n", 1)[1]
    return set(JOB_NAME.findall(jobs_block))


def required_checks() -> list[str]:
    checks = rule("required_status_checks")["parameters"]["required_status_checks"]
    return [check["context"] for check in checks]


def test_every_required_check_is_a_job_in_the_ci_workflow() -> None:
    # GitHub names a workflow check after its job; a renamed job would block every merge.
    assert set(required_checks()) <= ci_job_names()


def test_both_ci_jobs_are_required() -> None:
    assert {"check", "docker"} <= set(required_checks())


def test_the_ruleset_targets_the_default_branch_with_no_bypass() -> None:
    ruleset = load_ruleset()

    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert (ruleset["enforcement"], ruleset["bypass_actors"]) == ("active", [])


def test_main_cannot_be_deleted_force_pushed_or_given_merge_commits() -> None:
    rule_types = {entry["type"] for entry in load_ruleset()["rules"]}

    assert {"deletion", "non_fast_forward", "required_linear_history"} <= rule_types


def test_pull_requests_are_squash_merged_with_threads_resolved_and_up_to_date() -> None:
    pull_request = rule("pull_request")["parameters"]
    status_checks = rule("required_status_checks")["parameters"]

    assert pull_request["allowed_merge_methods"] == ["squash"]
    assert pull_request["required_review_thread_resolution"] is True
    assert status_checks["strict_required_status_checks_policy"] is True
