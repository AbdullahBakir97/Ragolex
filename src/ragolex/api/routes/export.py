import os
import tempfile
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ragolex.api.dependencies import (
    ADMIN,
    FileStorageDep,
    PrincipalDep,
    SettingsDep,
    UnitOfWorkDep,
)
from ragolex.services.audit import record
from ragolex.services.tenant_data_service import TenantDataService

router = APIRouter(prefix="/api/v1", tags=["export"], dependencies=[ADMIN])


@router.get(
    "/export",
    summary="Everything the tenant has, as a ZIP archive",
    description="Every project with its files as uploaded, sources, chat widgets, webhooks "
                "(without their secrets), conversations with their feedback and answer usage, "
                "and the tenant's API keys (names and prefixes only), members, invitations and "
                "audit log, as JSON files and the files themselves. Chunks and embeddings are "
                "left out: "
                "processing the files again makes them. `manifest.json` lists what is inside. "
                "Recorded in the audit log as `tenant.exported`.",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}},
                     "description": "The archive, named <tenant>-<date>.zip."}},
)
async def export_tenant(principal: PrincipalDep, uow: UnitOfWorkDep, storage: FileStorageDep,
                        settings: SettingsDep) -> FileResponse:
    tenant = await uow.tenants.get_or_create(principal.tenant_name)
    export = await TenantDataService(uow, storage).export(tenant)
    await record(uow, tenant.id, "tenant.exported", tenant.name, **export.counts)
    await uow.commit()

    # Written to a temporary file off the event loop, sent, then removed.
    descriptor, path = tempfile.mkstemp(prefix="ragolex-export-", suffix=".zip")
    try:
        with os.fdopen(descriptor, "wb") as target:
            await anyio.to_thread.run_sync(export.write, target, settings.APP_VERSION)
    except BaseException:
        os.unlink(path)
        raise
    name = f"{tenant.name}-{datetime.now(UTC):%Y-%m-%d}.zip"
    return FileResponse(path, media_type="application/zip", filename=name,
                        background=BackgroundTask(os.unlink, path))
