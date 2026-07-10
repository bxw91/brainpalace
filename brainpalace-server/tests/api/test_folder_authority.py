"""POST /index/ folder domain + authority (Phase 6.5).

Covers:
- External path (outside project_root) with no explicit authority in the
  body -> job is enqueued with authority resolved to "reference".
- External path explicitly requesting authority="authoritative" without
  force_authority -> 403 (message names --force).
- Internal path with no explicit authority -> resolved to "authoritative".
- External path WITHOUT allow_external -> 400 from the existing
  JobQueueService._validate_path containment check, before any authority
  logic runs (regression pin: the two gates compose).
- External path with allow_external=true but the folder is INSIDE the
  project root (init -F sends allow_external for in-tree targets too) ->
  authority stays "authoritative": externality comes from the path prefix,
  never from the allow_external flag.
- (Task 5) External path explicitly claiming --domain == the project's own
  domain -> treated as an authoritative claim, 403 without --force. A
  DEFAULTED domain (omitted by the caller) never triggers this — only an
  explicit claim does, so existing external-folder registrations without a
  domain are unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.index import router
from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore


def _build_app(job_service: JobQueueService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/index")
    app.state.job_service = job_service
    return app


@pytest.fixture
async def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
async def job_service(project_root: Path) -> JobQueueService:
    store = JobQueueStore(state_dir=project_root / ".brainpalace" / "state")
    await store.initialize()
    return JobQueueService(store, project_root=project_root)


@pytest.fixture
async def job_service_with_domain(project_root: Path) -> JobQueueService:
    store = JobQueueStore(state_dir=project_root / ".brainpalace" / "state")
    await store.initialize()
    return JobQueueService(store, project_root=project_root, project_domain="code")


@pytest.mark.asyncio
async def test_external_path_defaults_to_reference(
    tmp_path: Path, project_root: Path, job_service: JobQueueService
) -> None:
    """External folder, no authority in body -> resolved as 'reference'."""
    external_dir = tmp_path / "outside"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={"folder_path": str(external_dir)},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service.store.get_job(job_id)
    assert job is not None
    assert job.authority == "reference"


@pytest.mark.asyncio
async def test_external_path_cannot_claim_authoritative_without_force(
    tmp_path: Path, project_root: Path, job_service: JobQueueService
) -> None:
    """External folder explicitly requesting authoritative, no force -> 403."""
    external_dir = tmp_path / "outside2"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={
            "folder_path": str(external_dir),
            "authority": "authoritative",
        },
    )

    assert response.status_code == 403
    assert "--force" in response.json()["detail"]


@pytest.mark.asyncio
async def test_external_path_claims_authoritative_with_force(
    tmp_path: Path, project_root: Path, job_service: JobQueueService
) -> None:
    """External folder + authority=authoritative + force_authority -> allowed."""
    external_dir = tmp_path / "outside3"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={
            "folder_path": str(external_dir),
            "authority": "authoritative",
            "force_authority": True,
        },
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service.store.get_job(job_id)
    assert job is not None
    assert job.authority == "authoritative"


@pytest.mark.asyncio
async def test_internal_path_defaults_authoritative(
    project_root: Path, job_service: JobQueueService
) -> None:
    """Internal folder, no authority in body -> resolved as 'authoritative'."""
    internal_dir = project_root / "docs"
    internal_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        json={"folder_path": str(internal_dir)},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service.store.get_job(job_id)
    assert job is not None
    assert job.authority == "authoritative"


@pytest.mark.asyncio
async def test_external_path_claiming_project_domain_requires_force(
    tmp_path: Path,
    project_root: Path,
    job_service_with_domain: JobQueueService,
) -> None:
    """External folder + explicit --domain == the project's own domain, no
    authority given, no force -> 403 (the domain-claim clause, Task 5)."""
    external_dir = tmp_path / "outside_domain_claim"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service_with_domain))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={"folder_path": str(external_dir), "domain": "code"},
    )

    assert response.status_code == 403
    assert "--force" in response.json()["detail"]


@pytest.mark.asyncio
async def test_external_path_claiming_project_domain_with_force_allowed(
    tmp_path: Path,
    project_root: Path,
    job_service_with_domain: JobQueueService,
) -> None:
    """Same as above but with force_authority=True -> allowed, authoritative."""
    external_dir = tmp_path / "outside_domain_claim_forced"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service_with_domain))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={
            "folder_path": str(external_dir),
            "domain": "code",
            "force_authority": True,
        },
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service_with_domain.store.get_job(job_id)
    assert job is not None
    assert job.authority == "authoritative"
    assert job.domain == "code"


@pytest.mark.asyncio
async def test_external_path_no_domain_defaults_to_project_domain_but_stays_reference(
    tmp_path: Path,
    project_root: Path,
    job_service_with_domain: JobQueueService,
) -> None:
    """External folder, NO --domain (omitted) -> domain defaults to the
    project's own domain server-side for storage, but this default never
    counts as an explicit claim: authority still resolves to 'reference'
    with no 403 (regression pin for the 'defaulted vs explicit' distinction)."""
    external_dir = tmp_path / "outside_domain_default"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service_with_domain))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={"folder_path": str(external_dir)},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service_with_domain.store.get_job(job_id)
    assert job is not None
    assert job.authority == "reference"
    assert job.domain == "code"


@pytest.mark.asyncio
async def test_external_path_different_domain_no_claim(
    tmp_path: Path,
    project_root: Path,
    job_service_with_domain: JobQueueService,
) -> None:
    """External folder + explicit --domain that does NOT match the project's
    domain -> not a claim, stays 'reference', no 403."""
    external_dir = tmp_path / "outside_other_domain"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service_with_domain))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={"folder_path": str(external_dir), "domain": "home"},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service_with_domain.store.get_job(job_id)
    assert job is not None
    assert job.authority == "reference"
    assert job.domain == "home"


@pytest.mark.asyncio
async def test_external_without_allow_external_still_400s(
    tmp_path: Path, project_root: Path, job_service: JobQueueService
) -> None:
    """No allow_external -> the existing containment check 400s first."""
    external_dir = tmp_path / "outside4"
    external_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        json={"folder_path": str(external_dir)},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_in_tree_path_with_allow_external_stays_authoritative(
    project_root: Path, job_service: JobQueueService
) -> None:
    """allow_external=true but the folder is INSIDE project root -> the flag
    must not flip the default; authority stays 'authoritative'."""
    internal_dir = project_root / "src"
    internal_dir.mkdir()

    client = TestClient(_build_app(job_service))
    response = client.post(
        "/index/",
        params={"allow_external": "true"},
        json={"folder_path": str(internal_dir)},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = await job_service.store.get_job(job_id)
    assert job is not None
    assert job.authority == "authoritative"
