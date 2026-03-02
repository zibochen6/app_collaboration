"""
Base deployer abstract class
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from ..models.device import DeviceConfig

logger = logging.getLogger(__name__)


class BaseDeployer(ABC):
    """Abstract base class for deployers"""

    device_type: str = ""
    ui_traits: dict = {
        "connection": "none",
        "auto_deploy": True,
        "renderer": None,
        "has_targets": False,
        "show_model_selection": False,
        "show_service_warning": False,
        "connection_scope": "device",
    }
    steps: list = []

    @abstractmethod
    async def deploy(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Execute deployment

        Args:
            config: Device configuration
            connection: Connection information (port, host, credentials, etc.)
            progress_callback: Async callback for progress updates
                              Signature: (step_id: str, progress: int, message: str) -> None

        Returns:
            True if deployment successful, False otherwise
        """
        pass

    def _describe_connection(self, connection: Dict[str, Any]) -> str:
        """Summarize connection keys for error messages."""
        keys = sorted(k for k in connection if not k.startswith("_"))
        return f"[{', '.join(keys)}]" if keys else "[empty]"

    async def _report_progress(
        self,
        callback: Optional[Callable],
        step_id: str,
        progress: int,
        message: str,
    ):
        """Helper to report progress if callback is set"""
        if callback:
            await callback(step_id, progress, message)

    def _build_action_context(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build variable substitution context from user_inputs defaults + connection."""
        context = {}
        # Populate defaults from user_inputs config
        for ui in config.user_inputs:
            if ui.default is not None:
                context[ui.id] = ui.default
        # Override with actual connection values
        context.update(connection)
        return context

    async def _execute_actions(
        self,
        phase: str,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable],
        executor,
    ) -> bool:
        """Execute before or after actions.

        Args:
            phase: "before" or "after"
            config: Device configuration
            connection: Connection dict (also used for when-condition evaluation)
            progress_callback: Progress callback
            executor: ActionExecutor instance (Local or SSH)

        Returns:
            True if all actions succeeded (or were skipped), False on failure.
        """
        if not config.actions:
            return True

        actions = getattr(config.actions, phase, [])
        if not actions:
            return True

        step_id = f"actions_{phase}"
        context = self._build_action_context(config, connection)
        total = len(actions)

        await self._report_progress(
            progress_callback,
            step_id,
            0,
            f"Running {phase} actions...",
        )

        for i, action in enumerate(actions):
            # Check 'when' condition
            if action.when:
                field_val = context.get(action.when.field)
                if (
                    action.when.value is not None
                    and str(field_val) != action.when.value
                ):
                    logger.info(
                        f"Skipping action '{action.name}': "
                        f"{action.when.field}={field_val} != {action.when.value}"
                    )
                    continue
                if (
                    action.when.not_value is not None
                    and str(field_val) == action.when.not_value
                ):
                    logger.info(
                        f"Skipping action '{action.name}': "
                        f"{action.when.field}={field_val} == {action.when.not_value}"
                    )
                    continue

            progress = int((i / total) * 100)
            action_label = action.name
            await self._report_progress(
                progress_callback, step_id, progress, action_label
            )

            success = True
            if action.run:
                success = await executor.execute_run(
                    action, context, cwd=config.base_path
                )
            elif action.copy_files:
                success = await executor.execute_copy(
                    action.copy_files, context, base_path=config.base_path
                )

            if not success:
                if action.ignore_error:
                    logger.warning(
                        f"Action '{action.name}' failed but ignore_error=True, continuing"
                    )
                else:
                    await self._report_progress(
                        progress_callback,
                        step_id,
                        0,
                        f"Action failed: {action.name}",
                    )
                    return False

        await self._report_progress(
            progress_callback,
            step_id,
            100,
            f"{phase.capitalize()} actions completed",
        )
        return True
