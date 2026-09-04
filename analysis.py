"""PR analysis query router.
Exposes read-only endpoints for retrieving stored analysis results:
- ``GET /pr-analysis/{owner}/{repo}/{pr_number}``        -- latest analysis for a PR.
- ``GET /pr-analysis/{owner}/{repo}/{pr_number}/events`` -- pipeline stage trail for a PR.
- ``GET /pr-analysis/events/{delivery_id}``              -- pipeline stage trail by delivery.
- ``GET /pr-analysis/{analysis_id}``                     -- analysis by primary key.
"""
from __future__ import
from datetime import 
from uuid import 

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.database import (
    get_analysis_by_id,
    get_analysis_diffs,
    get_findings,
    get_latest_analysis,
    get_merge_readiness,
    get_pipeline_events,
    get_pipeline_events_by_delivery,
    get_recent_runs,
)
from app.config import 
from app.schemas import (
    AnalysisFindingResponse,
    AnalysisResponse,
    MergeReadinessResponse,
    PipelineEventResponse,
    PipelineEventsResponse,
    PostCommentsResponse,
    RunSummaryResponse,
)

router = APIRouter(prefix="/pr-analysis", tags=["analysis"])


def _require_api_key(x_api_key: str = Header(default="")) -> None:
    """Reject requests that don't carry the configured API key.

    When ``settings.api_key`` is empty the check is skipped so the service
    works out-of-the-box in local/dev mode without any config.
    """
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _to_events_response(rows: list[dict]) -> PipelineEventsResponse:
    """Build a :class:`PipelineEventsResponse` from raw pipeline-event rows."""
    first = rows[0]
    return PipelineEventsResponse(
        provider=first.get("provider") or "github",
        delivery_id=first["delivery_id"],
        owner=first.get("owner") or "",
        repo=first.get("repo") or "",
        pr_number=int(first.get("pr_number") or 0),
        final_status=first.get("final_status") or "",
        events=[
            PipelineEventResponse(
                seq=int(r["seq"]),
                event_type=r.get("event_type") or "",
                stage=r.get("stage"),
                status=r.get("status"),
                detail=r.get("detail") or {},
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ],
    )


def _to_response(row: dict) -> AnalysisResponse:
    """Convert a raw database row dict into an :class:`AnalysisResponse`.

    Also fetches and attaches the associated findings rows.
    """
    analysis_id = int(row["id"])
    findings = [AnalysisFindingResponse(**f) for f in get_findings(analysis_id)]
    mr = get_merge_readiness(analysis_id)
    merge_readiness = MergeReadinessResponse(**mr) if mr else None
    created_at_value = row.get("created_at")
    if isinstance(created_at_value, datetime):
        created_at = created_at_value
    else:
        created_at = datetime.fromisoformat(str(created_at_value))
    return AnalysisResponse(
        id=analysis_id,
        provider=row.get("provider") or "github",
        owner=row["owner"],
        repo=row["repo"],
        pr_number=int(row["pr_number"]),
        head_sha=row.get("head_sha") or "",
        base_sha=row.get("base_sha") or "",
        files_changed=int(row.get("files_changed") or 0),
        additions=int(row.get("additions") or 0),
        deletions=int(row.get("deletions") or 0),
        risk_score=int(row.get("risk_score") or 0),
        risk_level=row.get("risk_level") or "low",
        summary=row.get("summary") or "",
        created_at=created_at,
        findings=findings,
        merge_readiness=merge_readiness,
    )


@router.get("/recent", response_model=list[RunSummaryResponse], dependencies=[Depends(_require_api_key)])
async def get_recent(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RunSummaryResponse]:
    """Return a summary of the most recent pipeline runs for the dashboard."""
    return [RunSummaryResponse(**run) for run in get_recent_runs(limit, offset)]


@router.get("/events/{delivery_id}", response_model=PipelineEventsResponse, dependencies=[Depends(_require_api_key)])
async def get_events_by_delivery(delivery_id: str) -> PipelineEventsResponse:
    """Return the pipeline stage trail for a specific webhook delivery id."""
    rows = get_pipeline_events_by_delivery(delivery_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No pipeline events found for this delivery.")
    return _to_events_response(rows)


@router.get("/{owner}/{repo}/{pr_number}/events", response_model=PipelineEventsResponse, dependencies=[Depends(_require_api_key)])
async def get_events_for_pr(
    owner: str,
    repo: str,
    pr_number: int,
    provider: str | None = Query(default=None, description="Optional provider filter: github or gitlab"),
) -> PipelineEventsResponse:
    """Return the pipeline stage trail for the most recent delivery of a PR/MR."""
    rows = get_pipeline_events(owner, repo, pr_number, provider)
    if not rows:
        raise HTTPException(status_code=404, detail="No pipeline events found for this PR/MR.")
    return _to_events_response(rows)


@router.get("/{owner}/{repo}/{pr_number}", response_model=AnalysisResponse, dependencies=[Depends(_require_api_key)])
async def get_latest(
    owner: str,
    repo: str,
    pr_number: int,
    provider: str | None = Query(default=None, description="Optional provider filter: github or gitlab"),
) -> AnalysisResponse:
    """Returns the most recent analysis for the given PR, raising 404 if none exists."""
    row = get_latest_analysis(owner, repo, pr_number, provider)
    if not row:
        raise HTTPException(status_code=404, detail="No analysis found for this PR/MR.")
    return _to_response(row)


@router.get("/{analysis_id}", response_model=AnalysisResponse, dependencies=[Depends(_require_api_key)])
async def get_by_id(analysis_id: int) -> AnalysisResponse:
    """Return a specific analysis by its database primary key.

    Raises:
        HTTPException(404): When no analysis with that ID exists.
    """
    row = get_analysis_by_id(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return _to_response(row)


@router.post(
    "/{analysis_id}/post-comments",
    response_model=PostCommentsResponse,
    dependencies=[Depends(_require_api_key)],
)
async def post_comments(analysis_id: int) -> PostCommentsResponse:
    """Re-trigger comment posting for an existing analysis.

    Reconstructs the pipeline state from stored DB records and runs the
    review-comments node, posting inline and summary comments back to the
    PR/MR on the originating provider.  Useful for retrying after a
    transient network failure or when ``post_comments_enabled`` was
    toggled on after the analysis was first run.

    Raises:
        HTTPException(404): When no analysis with the given ID exists.
        HTTPException(503): When comment posting fails entirely.
    """
    from app.pr_pipeline.graph import run_review_comments
    from app.pr_pipeline.state import (
        PRAgentState,
        PRFileDiff,
        PRMetadata,
        PRWebhookEnvelope,
        RuleFinding,
        RiskScore,
    )

    row = get_analysis_by_id(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    provider = str(row.get("provider") or "github")
    owner = str(row["owner"])
    repo = str(row["repo"])
    pr_number = int(row["pr_number"])

    # Reconstruct lightweight pipeline state from stored records.
    envelope = PRWebhookEnvelope(
        provider=provider,
        delivery_id=str(uuid4()),
        event="pull_request",
        action="post_comments_retry",
        signature_valid=True,
        received_at=datetime.now(timezone.utc),
        payload={},
    )
    metadata = PRMetadata(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        title=str(row.get("pr_title") or ""),
        author=str(row.get("pr_author") or ""),
        head_sha=str(row.get("head_sha") or ""),
        base_sha=str(row.get("base_sha") or ""),
        changed_files=int(row.get("files_changed") or 0),
        additions=int(row.get("additions") or 0),
        deletions=int(row.get("deletions") or 0),
    )
    diff_rows = get_analysis_diffs(analysis_id)
    files = [PRFileDiff(**d) for d in diff_rows]

    finding_rows = get_findings(analysis_id)
    findings = [
        RuleFinding(
            rule_id=f["rule_id"],
            severity=f["severity"],
            message=f["message"],
            file_path=f.get("file_path") or "",
            line_start=int(f.get("line_start") or 0),
            line_end=int(f.get("line_end") or 0),
            evidence=f.get("evidence") or {},
        )
        for f in finding_rows
    ]
    risk = RiskScore(
        score=int(row.get("risk_score") or 0),
        level=str(row.get("risk_level") or "low"),
    )

    state = PRAgentState(
        envelope=envelope,
        metadata=metadata,
        files=files,
        findings=findings,
        risk=risk,
        status="completed",
    )

    try:
        state = await run_review_comments(state)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Comment posting failed: {exc}")

    rule_count = sum(1 for c in state.review_comments if c.source == "rule")
    llm_count = sum(1 for c in state.review_comments if c.source == "llm")
    posted_any = any(c.posted for c in state.review_comments)

    return PostCommentsResponse(
        analysis_id=analysis_id,
        provider=provider,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        posted=posted_any,
        rule_comments=rule_count,
        llm_comments=llm_count,
        detail=f"{rule_count + llm_count} comment(s) generated, posted={posted_any}",
    )
