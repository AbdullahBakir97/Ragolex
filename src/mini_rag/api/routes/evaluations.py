from typing import Annotated

from fastapi import APIRouter, Depends, Query

from mini_rag.api.dependencies import ADMIN, PrincipalDep, UnitOfWorkDep
from mini_rag.api.schemas import (
    EvaluationRunListResponse,
    EvaluationRunResponse,
    Pagination,
)

router = APIRouter(prefix="/api/v1", tags=["evaluations"], dependencies=[ADMIN])


@router.get(
    "/evaluations",
    summary="The tenant's evaluation runs, most recent first",
    description="Each `mini-rag eval` run records its dataset, parameters and metrics for the "
                "tenant it names (`--tenant`, the default tenant otherwise), to follow "
                "retrieval and answer quality over time.",
)
async def list_evaluation_runs(
    principal: PrincipalDep, uow: UnitOfWorkDep, page: Annotated[Pagination, Depends()],
    dataset: Annotated[str | None, Query(max_length=255,
                                         description="Only runs of this dataset.")] = None,
) -> EvaluationRunListResponse:
    runs = uow.evaluations
    items = await runs.list_for_tenant(principal.tenant_id, dataset=dataset,
                                       offset=page.offset, limit=page.limit)
    return EvaluationRunListResponse(
        total=await runs.count_for_tenant(principal.tenant_id, dataset=dataset),
        offset=page.offset, limit=page.limit,
        items=[EvaluationRunResponse(
            id=run.id, dataset=run.dataset, dataset_version=run.dataset_version,
            cases=run.cases, parameters=run.parameters, metrics=run.metrics,
            answer_metrics=run.answer_metrics, version=run.version,
            created_at=run.created_at) for run in items])
