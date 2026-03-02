"""
Deployment execution API routes
"""

from typing import List

from fastapi import APIRouter, HTTPException, Query

from ..models.api import (
    DeploymentListItem,
    DeploymentStatusResponse,
    DeploymentSummaryResponse,
    DeviceDeploymentStatus,
    DeviceSummaryInfo,
    StartDeploymentRequest,
    StepSummary,
    StepSummaryInfo,
)
from ..models.deployment import DeploymentStatus
from ..services.deployment_engine import deployment_engine
from ..services.deployment_history import deployment_history
from ..services.solution_manager import solution_manager

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


@router.post("/start")
async def start_deployment(request: StartDeploymentRequest):
    """Start a new deployment"""
    solution = solution_manager.get_solution(request.solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # Start deployment
    deployment_id = await deployment_engine.start_deployment(
        solution=solution,
        device_connections=request.device_connections,
        selected_devices=request.selected_devices,
        options=request.options,
        preset_id=request.preset_id,
    )

    return {
        "deployment_id": deployment_id,
        "message": "Deployment started",
    }


@router.get("/{deployment_id}", response_model=DeploymentStatusResponse)
async def get_deployment_status(deployment_id: str):
    """Get current deployment status"""
    deployment = deployment_engine.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Calculate overall progress
    total_steps = 0
    completed_steps = 0
    for device in deployment.devices:
        total_steps += len(device.steps)
        for step in device.steps:
            if step.status in ("completed", "skipped"):
                completed_steps += 1
            elif step.status == "running":
                completed_steps += step.progress / 100

    overall_progress = int(
        (completed_steps / total_steps * 100) if total_steps > 0 else 0
    )

    # Build device statuses
    device_statuses = []
    for device in deployment.devices:
        device_progress = 0
        if device.steps:
            device_completed = sum(
                (
                    1
                    if s.status in ("completed", "skipped")
                    else (s.progress / 100 if s.status == "running" else 0)
                )
                for s in device.steps
            )
            device_progress = int(device_completed / len(device.steps) * 100)

        device_statuses.append(
            DeviceDeploymentStatus(
                device_id=device.device_id,
                name=device.name,
                type=device.type,
                status=device.status,
                current_step=device.current_step,
                steps=device.steps,
                progress=device_progress,
                error=device.error,
            )
        )

    return DeploymentStatusResponse(
        id=deployment.id,
        solution_id=deployment.solution_id,
        status=deployment.status,
        started_at=deployment.started_at,
        completed_at=deployment.completed_at,
        devices=device_statuses,
        overall_progress=overall_progress,
    )


@router.get("/{deployment_id}/summary", response_model=DeploymentSummaryResponse)
async def get_deployment_summary(deployment_id: str):
    """Get a concise deployment summary with errors and warnings.

    Extracts actionable information from deployment logs:
    - Per-device and per-step status
    - Error messages (from error-level logs)
    - Warning signals (from logs mentioning clock, sync, retry, timeout, etc.)
    - Duration in seconds
    """
    deployment = deployment_engine.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Calculate duration
    duration_seconds = None
    if deployment.completed_at and deployment.started_at:
        duration_seconds = (
            deployment.completed_at - deployment.started_at
        ).total_seconds()

    # Build device summaries
    devices = []
    for device in deployment.devices:
        step_summaries = []
        for step in device.steps:
            step_summaries.append(
                StepSummaryInfo(
                    name=step.name,
                    status=step.status,
                    message=step.message,
                )
            )
        devices.append(
            DeviceSummaryInfo(
                device_id=device.device_id,
                status=(
                    device.status.value
                    if hasattr(device.status, "value")
                    else str(device.status)
                ),
                steps=step_summaries,
                error=device.error,
            )
        )

    # Extract errors and warnings from logs
    errors = []
    warnings = []
    warning_keywords = {"warning", "warn", "clock", "sync", "retry", "timeout", "slow"}

    for log in deployment.logs:
        if log.level == "error":
            errors.append(log.message)
        elif log.level == "warning":
            warnings.append(log.message)
        elif log.level == "info":
            msg_lower = log.message.lower()
            if any(kw in msg_lower for kw in warning_keywords):
                warnings.append(log.message)

    return DeploymentSummaryResponse(
        deployment_id=deployment.id,
        solution_id=deployment.solution_id,
        status=(
            deployment.status.value
            if hasattr(deployment.status, "value")
            else str(deployment.status)
        ),
        started_at=deployment.started_at,
        duration_seconds=duration_seconds,
        devices=devices,
        errors=errors,
        warnings=warnings,
    )


@router.post("/{deployment_id}/cancel")
async def cancel_deployment(deployment_id: str):
    """Cancel a running deployment"""
    deployment = deployment_engine.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.status != DeploymentStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Deployment is not running")

    await deployment_engine.cancel_deployment(deployment_id)

    return {"message": "Deployment cancelled"}


@router.get("/", response_model=List[DeploymentListItem])
async def list_deployments(
    limit: int = Query(20, ge=1, le=100),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """List recent deployments - merges active + persisted history"""
    result = []
    seen_ids = set()

    def get_solution_name(solution, fallback: str) -> str:
        """Get localized solution name"""
        if not solution:
            return fallback
        if lang == "zh" and solution.name_zh:
            return solution.name_zh
        return solution.name

    # 1. Active deployments (real-time step progress)
    active_deployments = deployment_engine.list_deployments(limit=limit)
    for deployment in active_deployments:
        solution = solution_manager.get_solution(deployment.solution_id)
        # Build steps from all devices
        steps = []
        device_id = None
        for device in deployment.devices:
            if not device_id:
                device_id = device.device_id
            for step in device.steps:
                steps.append(
                    StepSummary(
                        id=step.id,
                        name=step.name,
                        status=step.status,
                        progress=step.progress,
                    )
                )
        result.append(
            DeploymentListItem(
                id=deployment.id,
                solution_id=deployment.solution_id,
                solution_name=get_solution_name(solution, deployment.solution_id),
                status=deployment.status,
                started_at=deployment.started_at,
                completed_at=deployment.completed_at,
                device_count=len(deployment.devices),
                device_id=device_id,
                steps=steps,
            )
        )
        seen_ids.add(deployment.id)

    # 2. Persisted history records
    history_records = await deployment_history.get_history(limit=limit)
    for record in history_records:
        if record.deployment_id in seen_ids:
            continue
        seen_ids.add(record.deployment_id)
        solution = solution_manager.get_solution(record.solution_id)
        steps = [
            StepSummary(
                id=s.id,
                name=s.name,
                status=s.status,
                progress=100 if s.status == "completed" else 0,
            )
            for s in record.steps
        ]
        result.append(
            DeploymentListItem(
                id=record.deployment_id,
                solution_id=record.solution_id,
                solution_name=get_solution_name(solution, record.solution_id),
                status=(
                    DeploymentStatus.COMPLETED
                    if record.status == "completed"
                    else DeploymentStatus.FAILED
                ),
                started_at=record.deployed_at,
                completed_at=record.deployed_at,
                device_count=1,
                device_id=record.device_id,
                steps=steps,
            )
        )

    # Sort by started_at descending
    result.sort(key=lambda d: d.started_at, reverse=True)
    return result[:limit]


@router.delete("/{deployment_id}")
async def delete_deployment(deployment_id: str):
    """Delete a deployment record from history"""
    removed = await deployment_history.remove_deployment(deployment_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Deployment record not found")
    return {"message": "Deployment record deleted"}


@router.get("/{deployment_id}/logs")
async def get_deployment_logs(
    deployment_id: str,
    device_id: str = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get deployment logs"""
    deployment = deployment_engine.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if device_id:
        device = deployment.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        logs = device.logs[-limit:]
    else:
        logs = deployment.logs[-limit:]

    return {
        "logs": [
            {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "device_id": log.device_id,
                "step_id": log.step_id,
                "message": log.message,
            }
            for log in logs
        ]
    }
