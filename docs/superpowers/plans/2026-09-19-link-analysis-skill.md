# 链接直达本地分析 Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a URL-triggered Codex workflow that imports exactly one supported social-media video, runs its local media pipeline, writes an Obsidian AI note, and makes the result visible in the existing workbench.

**Architecture:** A new authenticated backend ingress owns URL identity validation, idempotent `manual` work creation, and safe note completion. A project CLI processes one `work_id` by reusing the monitor pipeline without enabling the global queue; the user-level Codex skill then reads its local artifacts, writes the note, and calls the completion API.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/SQLite, pytest, existing monitor pipeline, Python CLI, Markdown-based Codex skill.

**Spec:** `docs/superpowers/specs/2026-09-19-link-analysis-skill-design.md`

## Global Constraints

- Target project remains `F:\媒体监测`; do not migrate, clear, or reinitialize it.
- Support only `douyin`, `bilibili`, `xhs`, and `twitter`; a platform must never be guessed from an ambiguous URL.
- Default a received link to `one_time`; only explicit monitoring language enables `monitor` mode.
- A link analysis affects exactly one `work_id`; it must not enable `MONITOR_RUN_PIPELINE` or consume other queued works.
- Codex replaces WorkBuddy only for the active, user-triggered link flow; existing monitored work keeps its WorkBuddy-pending behavior.
- Never print, copy into documentation, or return platform cookies, tokens, or `.env` secrets.
- Preserve the existing dirty working tree; every commit stages only files named in its task.

## Review Focus

- Short links that resolve to an unsupported host must produce a validation error, not silently become a supported platform.
- A duplicate manual link already owned by a monitored work must return that work unchanged, including `source_type` and existing artifacts.
- A runner invocation for a non-queued work must not overwrite a completed note or re-download media.
- A note path containing `..`, an absolute drive path, or a missing Markdown file must be rejected before any database update.
- A Twitter/X or Xiaohongshu non-video post must fail transparently without attempting an audio transcription.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/schemas/link_analysis.py` | Pydantic request/result schemas for the ingress endpoint and safe note completion. |
| `backend/app/services/link_analysis_service.py` | URL identity parsing, short-link resolution seam, idempotent manual work creation, and note-path completion transaction. |
| `backend/app/api/link_analyses.py` | Authenticated `POST /api/v1/link-analyses` route. |
| `backend/app/api/works.py` | Authenticated `POST /api/v1/works/{work_id}/complete-note` route. |
| `backend/app/main.py` | Registers the link-analyses router. |
| `backend/app/services/note_service.py` | Keeps the legacy pending-manifest route unchanged; receives no direct-note behavior. |
| `monitor/jobs.py` | Exposes a one-work pipeline function and preserves legacy monitor behavior via an explicit pending-manifest flag. |
| `tools/process_link_analysis.py` | Thin CLI that invokes exactly one-work processing and emits a concise result. |
| `backend/tests/test_link_analyses.py` | API and service contract tests for identity, idempotency, monitoring intent, and note safety. |
| `backend/tests/test_link_analysis_runner.py` | Single-work pipeline isolation and legacy monitor compatibility tests. |
| `docs/openapi-aggregator.yaml` | Public API contract for both new endpoints and schemas. |
| `frontend/src/types/api.d.ts` | Generated-by-hand type contract additions for the two API responses. |
| `C:\Users\Administrator\.codex\skills\local-media-link-analysis\SKILL.md` | Discoverable workflow telling Codex how to react after a user supplies a supported URL. |
| `README.md` | Concise local usage, capability boundary, and failure/retry guidance. |

## Task 1: Link identity and idempotent manual-ingress API

**Files:**
- Create: `backend/app/schemas/link_analysis.py`
- Create: `backend/app/services/link_analysis_service.py`
- Create: `backend/app/api/link_analyses.py`
- Modify: `backend/app/main.py`
- Modify: `docs/openapi-aggregator.yaml`
- Modify: `frontend/src/types/api.d.ts`
- Test: `backend/tests/test_link_analyses.py`

**Interfaces:**
- Consumes: `work_repo.upsert(db, platform, external_id, **fields)` and `task_repo.upsert(db, work_id, stage, status, ...)`.
- Produces: `parse_link_identity(url: str, resolve_redirect: Callable[[str], str] | None = None) -> LinkIdentity` and `LinkAnalysisService.ingest(db, request: LinkAnalysisCreate) -> LinkAnalysisResult`.

- [ ] **Step 1: Write failing identity and ingress tests**

```python
def test_create_bilibili_manual_work_is_idempotent(client, auth_headers):
    payload = {"url": "https://www.bilibili.com/video/BV1xx411c7mD", "platform": "bilibili", "external_id": "BV1xx411c7mD", "mode": "one_time"}
    first = client.post("/api/v1/link-analyses", json=payload, headers=auth_headers)
    second = client.post("/api/v1/link-analyses", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert first.json()["data"]["created"] is True
    assert second.json()["data"]["created"] is False
    assert second.json()["data"]["work"]["id"] == first.json()["data"]["work"]["id"]
    assert first.json()["data"]["work"]["source_type"] == "manual"

def test_rejects_platform_identity_mismatch(client, auth_headers):
    response = client.post("/api/v1/link-analyses", json={"url": "https://www.bilibili.com/video/BV1xx411c7mD", "platform": "xhs", "external_id": "abc", "mode": "one_time"}, headers=auth_headers)
    assert response.status_code == 422
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `python -m pytest backend/tests/test_link_analyses.py -q` from `F:\媒体监测\backend`.

Expected: FAIL because `/api/v1/link-analyses` and the request schema do not exist.

- [ ] **Step 3: Implement exact URL identity and ingest contracts**

```python
@dataclass(frozen=True)
class LinkIdentity:
    platform: Literal["douyin", "bilibili", "xhs", "twitter"]
    external_id: str
    canonical_url: str

class LinkAnalysisCreate(BaseModel):
    url: HttpUrl
    platform: Literal["douyin", "bilibili", "xhs", "twitter"]
    external_id: str = Field(min_length=1, max_length=200)
    mode: Literal["one_time", "monitor"] = "one_time"

class LinkAnalysisService:
    def ingest(self, db: Session, request: LinkAnalysisCreate) -> LinkAnalysisResult: ...
```

Implement parsers for Bilibili `BV...`, X/X-Twitter `/status/<digits>`, Xiaohongshu `/explore/<id>` or `/discovery/item/<id>`, and Douyin `/video/<digits>`. Keep redirect handling injectable through `resolve_redirect`; only permit it for known short-link hosts. Require the supplied identity to exactly match the parsed identity. On first creation write `source_type="manual"`, `status="QUEUED"`, a provisional `title`, and each stage as `pending`; on duplicate return the existing work without mutating it. Add the router and its registration, OpenAPI paths/schemas, and matching TypeScript interfaces.

- [ ] **Step 4: Run the targeted tests and verify GREEN**

Run: `python -m pytest backend/tests/test_link_analyses.py -q` from `F:\媒体监测\backend`.

Expected: PASS, including duplicate, host/ID mismatch, invalid mode, known short-link resolution, unsupported redirected host, and existing monitored-work preservation cases.

- [ ] **Step 5: Commit the isolated ingress change**

```bash
git add backend/app/schemas/link_analysis.py backend/app/services/link_analysis_service.py backend/app/api/link_analyses.py backend/app/main.py docs/openapi-aggregator.yaml frontend/src/types/api.d.ts backend/tests/test_link_analyses.py
git commit -m "feat: add idempotent manual link ingress"
```

## Task 2: Safe direct-note completion API

**Files:**
- Modify: `backend/app/services/link_analysis_service.py`
- Modify: `backend/app/api/works.py`
- Modify: `backend/app/schemas/link_analysis.py`
- Modify: `docs/openapi-aggregator.yaml`
- Modify: `frontend/src/types/api.d.ts`
- Test: `backend/tests/test_link_analyses.py`

**Interfaces:**
- Consumes: `settings.obsidian_root`, `work_repo.get`, `work_repo.update`, and `task_repo.upsert`.
- Produces: `LinkAnalysisService.complete_note(db, work_id: int, note_path: str) -> Work` and `POST /api/v1/works/{work_id}/complete-note`.

- [ ] **Step 1: Add failing path-safety and status-transition tests**

```python
def test_complete_note_marks_done_only_for_existing_relative_markdown(client, auth_headers):
    note = settings.obsidian_root / "未分组" / "示例.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# 示例", encoding="utf-8")
    response = client.post(f"/api/v1/works/{work_id}/complete-note", json={"note_path": "未分组/示例.md"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "DONE"

@pytest.mark.parametrize("note_path", ["../secret.md", "C:/outside.md", "未分组/missing.md"])
def test_complete_note_rejects_unsafe_or_missing_path(client, auth_headers, note_path):
    assert client.post(f"/api/v1/works/{work_id}/complete-note", json={"note_path": note_path}, headers=auth_headers).status_code == 422
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `python -m pytest backend/tests/test_link_analyses.py -q` from `F:\媒体监测\backend`.

Expected: FAIL because `complete-note` is not registered.

- [ ] **Step 3: Implement the validated completion transaction**

```python
class NoteCompletionRequest(BaseModel):
    note_path: str = Field(min_length=1, max_length=500)

def complete_note(self, db: Session, work_id: int, note_path: str) -> Work:
    candidate = (settings.obsidian_root / note_path).resolve()
    candidate.relative_to(settings.obsidian_root.resolve())
    if candidate.suffix.lower() != ".md" or not candidate.is_file():
        raise validation("NOTE_PATH_INVALID")
    work = work_repo.get(db, work_id)
    ...
```

Use `relative_to` to reject escapes, persist a slash-normalized path relative to `OBSIDIAN_ROOT`, set work status `DONE`, upsert note stage `succeeded` with no error, and commit once. Keep `note_service.analyze` exactly as the legacy WorkBuddy-pending route.

- [ ] **Step 4: Run the targeted tests and verify GREEN**

Run: `python -m pytest backend/tests/test_link_analyses.py -q` from `F:\媒体监测\backend`.

Expected: PASS for valid completion, repeat completion, escape rejection, non-Markdown rejection, missing file rejection, and unknown work ID.

- [ ] **Step 5: Commit the isolated completion API**

```bash
git add backend/app/services/link_analysis_service.py backend/app/api/works.py backend/app/schemas/link_analysis.py docs/openapi-aggregator.yaml frontend/src/types/api.d.ts backend/tests/test_link_analyses.py
git commit -m "feat: complete Codex-generated notes safely"
```

## Task 3: One-work pipeline runner without global queue activation

**Files:**
- Modify: `monitor/jobs.py`
- Create: `tools/process_link_analysis.py`
- Test: `backend/tests/test_link_analysis_runner.py`

**Interfaces:**
- Consumes: `monitor.jobs._process_work(db, work, write_pending: bool)` and the existing `SessionLocal`.
- Produces: `process_link_analysis(work_id: int) -> dict[str, str | int]`, callable as `python tools/process_link_analysis.py --work-id <id>`.

- [ ] **Step 1: Write failing isolation and legacy-compatibility tests**

```python
def test_manual_runner_processes_only_requested_queued_work(monkeypatch, db):
    called = []
    monkeypatch.setattr(jobs, "_process_work", lambda session, work, write_pending: called.append((work.id, write_pending)))
    result = jobs.process_link_analysis(target.id)
    assert result["work_id"] == target.id
    assert called == [(target.id, False)]
    assert untouched.status == "QUEUED"

def test_manual_runner_rejects_completed_work(db):
    with pytest.raises(ValueError, match="not runnable"):
        jobs.process_link_analysis(done.id)

def test_manual_runner_marks_known_non_video_as_failed(monkeypatch, db):
    image_work.content_type = "image"
    result = jobs.process_link_analysis(image_work.id)
    assert result["status"] == "FAILED"
    assert "仅支持视频" in image_work.last_error
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `python -m pytest backend/tests/test_link_analysis_runner.py -q` from `F:\媒体监测\backend`.

Expected: FAIL because `process_link_analysis` and the `write_pending` parameter do not exist.

- [ ] **Step 3: Implement one-work execution and exact stage updates**

```python
def process_link_analysis(work_id: int) -> dict[str, str | int]:
    with SessionLocal() as db:
        work = db.get(Work, work_id)
        if work is None or work.status not in {"NEW", "QUEUED", "FAILED"}:
            raise ValueError(f"work {work_id} is not runnable")
        if work.content_type != "video":
            work.status, work.last_error = "FAILED", "链接分析仅支持视频作品"
            task_repo.mark_failed(db, work.id, "download", work.last_error)
            db.commit()
            return {"work_id": work.id, "status": work.status}
        _process_work(db, work, write_pending=False)
        db.commit()
        return {"work_id": work.id, "status": work.status}
```

Refactor `_process_work` to accept keyword-only `write_pending: bool = True`. For each phase set the work status and stage to `running` before the external operation, then set it to `succeeded` only after success. When `write_pending=False`, leave the note stage `pending` after media preparation rather than invoking `notify.notify_ready`. Preserve `run_pipeline()` calling `_process_work(..., write_pending=True)` so monitored work behavior remains unchanged. The CLI must initialize the shared database, parse only positive integer IDs, return exit code 0 on a successful media-ready result, and print errors without secrets.

- [ ] **Step 4: Run runner and regression tests and verify GREEN**

Run: `python -m pytest backend/tests/test_link_analysis_runner.py backend/tests/test_monitor.py backend/tests/test_works.py -q` from `F:\媒体监测\backend`.

Expected: PASS; no test may require `MONITOR_RUN_PIPELINE=true`, and the legacy `analyze` endpoint must still create a WorkBuddy pending manifest.

- [ ] **Step 5: Commit the pipeline isolation change**

```bash
git add monitor/jobs.py tools/process_link_analysis.py backend/tests/test_link_analysis_runner.py
git commit -m "feat: run local pipeline for one manual work"
```

## Task 4: Create and validate the discoverable Codex skill

**Files:**
- Create: `C:\Users\Administrator\.codex\skills\local-media-link-analysis\SKILL.md`
- Create: `C:\Users\Administrator\.codex\skills\local-media-link-analysis\agents\openai.yaml`
- Test: independent pressure scenarios in an isolated temporary workspace

**Interfaces:**
- Consumes: `POST /api/v1/link-analyses`, `tools/process_link_analysis.py --work-id`, `GET /api/v1/works/{id}`, and `POST /api/v1/works/{id}/complete-note`.
- Produces: an interaction rule that starts only after a link is supplied, plus an Obsidian note and completed work record for a successful run.

- [ ] **Step 1: Run a baseline pressure scenario before writing the skill**

Use a fresh agent with no new skill loaded and give only this request:

```text
https://www.bilibili.com/video/BV1xx411c7mD
```

Record whether it incorrectly asks for the platform before inspecting the link, asks for a mode instead of using the one-time default, opens the global queue, or claims an AI note exists without creating one. The desired baseline is a demonstrable failure in at least one of those behaviors.

- [ ] **Step 2: Create the minimal skill instructions that correct the observed failure**

```yaml
---
name: local-media-link-analysis
description: Use when a user supplies a Douyin, Bilibili, Xiaohongshu, or Twitter/X work link and asks to locally download, transcribe, summarize, or turn that linked work into a note.
---
```

In the body, require automatic platform recognition after the URL arrives; default `one_time`; use `monitor` only for explicit monitoring wording; call the project API and one-work CLI; generate a local evidence-based Obsidian note; complete the note through the API; and ask one focused question only when identity, author-monitor resolution, or a failed prerequisite cannot be inferred. Explicitly prohibit reading/printing cookies, global queue activation, and fabricated content.

- [ ] **Step 3: Run the same pressure scenario with the skill loaded and verify GREEN**

Expected behavior: identify Bilibili without a preliminary question, select one-time mode, describe the bounded run, and use the single-work workflow rather than the global monitor queue.

- [ ] **Step 4: Run two additional behavior scenarios**

```text
把 https://x.com/example/status/1234567890123456789 加入持续监控并分析这条。
```

Expected: recognize explicit monitoring intent; if author profile cannot be established from local metadata, ask only for the author profile rather than inventing it.

```text
帮我分析 https://example.com/not-supported
```

Expected: state the URL is unsupported and ask the user for a supported platform link; do not create a database record.

- [ ] **Step 5: Validate and commit the skill**

Run: `python C:\Users\Administrator\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\Administrator\.codex\skills\local-media-link-analysis`

Expected: validator success with no scaffold placeholders. Commit only the project-side documentation added in Task 5; the user-level skill directory is intentionally outside the repository.

## Task 5: Document, verify, and publish

**Files:**
- Modify: `README.md`
- Modify: `docs/项目交接文档_2026-09-19_实测版.md`
- Test: `backend/tests/test_link_analyses.py`, `backend/tests/test_link_analysis_runner.py`, existing backend suite, frontend build

**Interfaces:**
- Consumes: all Task 1–4 contracts.
- Produces: an operator-facing explanation of the link-only trigger, default one-time semantics, direct-Codex note boundary, and retry route.

- [ ] **Step 1: Add concise user documentation**

Document this exact behavior in `README.md`: “直接发送作品链接；Codex 自动识别平台并按一次性分析处理。明确说‘加入监控’才创建持续监测。” State that a successful active Codex session writes the note directly, while background monitored items retain their existing queue semantics. Update the current handover document’s feature and limitations sections with the same factual state.

- [ ] **Step 2: Run all automated verification**

Run from `F:\媒体监测\backend`:

```bash
python -m pytest -q
```

Run from `F:\媒体监测\frontend` with the cached Node runtime already used by this project:

```bash
npm run build
```

Expected: all backend tests pass and the frontend production build completes without TypeScript errors.

- [ ] **Step 3: Run a non-destructive manual contract check**

Start the existing backend and frontend. Submit a deliberately invalid supported-platform identity to `POST /api/v1/link-analyses`; confirm it returns 422 and that `/api/v1/works?source_type=manual` count is unchanged. Do not use a real user link or start a download for this check.

- [ ] **Step 4: Commit and push only feature-owned files**

```bash
git add README.md docs/项目交接文档_2026-09-19_实测版.md
git commit -m "docs: explain Codex link analysis workflow"
git push origin HEAD:main
```

Before each earlier task commit and before this final push, inspect `git diff --cached --name-only` and stop if it includes an unrelated pre-existing file.

## Plan Self-Review

- Spec coverage: Tasks 1–2 implement ingress, idempotency, note completion, API schema, and frontend contract; Task 3 implements isolated local media work; Task 4 implements the URL-after-arrival skill; Task 5 covers user documentation, regression testing, and publishing.
- Type consistency: `LinkIdentity`, `LinkAnalysisCreate`, `LinkAnalysisResult`, `process_link_analysis`, and `complete_note` use the same platform, work ID, and note-path values throughout the plan.
- Review focus coverage: unsupported short redirects and duplicate monitored works are Task 1 tests; non-runnable work and non-video media are Task 3 tests; unsafe note paths are Task 2.
- Placeholder scan: no unresolved implementation decisions remain; filename, route, callable, expected test command, and commit scope are explicit.
