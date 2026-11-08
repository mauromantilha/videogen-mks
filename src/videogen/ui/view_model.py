"""Monta o contexto de template da página do job (apresentação; regras vêm do domínio)."""

from collections import defaultdict
from typing import Any

from videogen.api.dto.jobs import JobView
from videogen.domain.job import JobState
from videogen.domain.script_rules import RuleViolation, validate_rules
from videogen.domain.status import JobStatus

LIVE = frozenset({JobStatus.SCRIPTING, JobStatus.APPROVED, JobStatus.RENDERING,
                  JobStatus.FINALIZING})  # fmt: skip
PANELS = {
    JobStatus.SCRIPTING: "_scripting.html", JobStatus.AWAITING_APPROVAL: "_script_editor.html",
    JobStatus.APPROVED: "_progress.html", JobStatus.RENDERING: "_progress.html",
    JobStatus.FINALIZING: "_progress.html", JobStatus.COMPLETED: "_result.html",
    JobStatus.FAILED: "_result.html", JobStatus.CANCELED: "_result.html",
}  # fmt: skip


def job_context(job: JobState) -> dict[str, Any]:
    by_scene: dict[int | None, list[RuleViolation]] = defaultdict(list)
    limits = job.request.script_limits()
    if job.script is not None:
        for violation in validate_rules(job.script, limits):
            by_scene[violation.scene_index].append(violation)
    return {
        "job": JobView.of(job),
        "panel": PANELS[job.status],
        "live": job.status in LIVE,
        "violations": by_scene,
        "max_words": limits.max_words,
        "budget": job.approval.max_budget_usd if job.approval else job.request.max_budget_usd,
    }


def scene_status_context(job: JobState, index: int) -> dict[str, Any]:
    script = job.require_script()
    limits = job.request.script_limits()
    violations = [v for v in validate_rules(script, limits) if v.scene_index == index]
    return {"job": JobView.of(job), "scene": script.cenas[index], "max_words": limits.max_words,
            "scene_violations": violations, "oob": True}  # fmt: skip
