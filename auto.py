"""Auto-merge node.

Classifies the PR/MR change set and, when it contains only whitespace /
alignment changes, merges it automatically. Real code changes are left for
human review.

Runs as a separate, guaranteed step (see ``run_auto_merge``) rather than a
core pipeline node, so the merge decision is made even if earlier stages had
non-fatal issues. Gated by ``settings.auto_merge_enabled`` (off by default).
"""
from __future__ import annotations
from app.change_classify import WHITESPACE_ONLY, classify_change
from app.config import settings
from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.pr_pipeline.state import PRAgentState

_MERGED_NOTE = (
    "## 🤖 PR Agent — auto-merged\n\n"
    "This change contained only whitespace / alignment differences (no semantic "
    "code change), so it was merged automatically."
)


class AutoMergeNode:
    """Decides whether a PR/MR is whitespace-only and merges it when it is."""

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Classify the change; auto-merge whitespace-only PRs when enabled,
        otherwise flag for human review."""
        state.emit("stage", stage="auto_merge", status="running")
        if state.status in {"ignored", "rejected"} or not state.metadata:
            state.emit("stage", stage="auto_merge", status="skipped")
            return state

        classification = classify_change(state.files)
        state.change_class = classification

        if classification != WHITESPACE_ONLY:
            # Code change (or nothing to inspect) -> leave for human review.
            # No note is posted here: the review-comments step already posts
            # feedback for code changes, so a separate "please review" note
            # would just be duplicate noise on every push.
            state.emit(
                "stage",
                stage="auto_merge",
                status="human_review",
                reason=classification,
            )
            return state

        if not state.checks_passed:
            # Whitespace-only, but a configured PR check failed. Leave it for
            # humans instead of auto-merging.
            state.emit(
                "stage",
                stage="auto_merge",
                status="human_review",
                reason="checks_failed",
            )
            return state

        if not settings.auto_merge_enabled:
            # Whitespace-only but auto-merge disabled -> report what would happen.
            state.emit(
                "stage",
                stage="auto_merge",
                status="dry_run",
                would_merge=True,
                reason=WHITESPACE_ONLY,
            )
            return state

        # Whitespace-only and enabled -> merge.
        try:
            if state.envelope.provider == "github":
                await self._merge_github(state)
            elif state.envelope.provider == "gitlab":
                await self._merge_gitlab(state)
            else:
                state.emit("stage", stage="auto_merge", status="done", merged=False, reason="unsupported_provider")
                return state
            state.merged = True
            if settings.auto_merge_comment_enabled:
                await self._post_note(state, _MERGED_NOTE)
            state.emit("stage", stage="auto_merge", status="done", merged=True)
        except Exception as exc:
            state.emit("warning", stage="auto_merge", message=f"auto-merge failed: {exc}")
            state.emit("stage", stage="auto_merge", status="done", merged=False)
        return state

    async def _merge_github(self, state: PRAgentState) -> None:
        metadata = state.metadata
        assert metadata is not None
        await GitHubClient().merge_pull_request(
            metadata.owner,
            metadata.repo,
            metadata.pr_number,
            sha=metadata.head_sha,
            merge_method=settings.auto_merge_method,
        )

    async def _merge_gitlab(self, state: PRAgentState) -> None:
        metadata = state.metadata
        assert metadata is not None
        project_id = (state.envelope.payload.get("project") or {}).get("id")
        if not project_id:
            raise ValueError("missing gitlab project id")
        await GitLabClient().merge_merge_request(project_id, metadata.pr_number)

    async def _post_note(self, state: PRAgentState, body: str) -> None:
        """Best-effort informational comment; never raises."""
        metadata = state.metadata
        if not metadata or metadata.pr_number <= 0:
            return
        try:
            if state.envelope.provider == "github":
                await GitHubClient().create_issue_comment(
                    metadata.owner, metadata.repo, metadata.pr_number, body
                )
            elif state.envelope.provider == "gitlab":
                project_id = (state.envelope.payload.get("project") or {}).get("id")
                if project_id:
                    await GitLabClient().create_merge_request_note(
                        project_id, metadata.pr_number, body
                    )
        except Exception as exc:
            state.emit("warning", stage="auto_merge", message=f"note failed: {exc}")
