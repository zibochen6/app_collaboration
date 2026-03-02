"""
Node-RED deployment base class

Provides common functionality for deploying Node-RED flows via Admin HTTP API.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..models.device import DeviceConfig, NodeRedModuleConfig
from .action_executor import LocalActionExecutor
from .base import BaseDeployer

logger = logging.getLogger(__name__)


class NodeRedDeployer(BaseDeployer):
    """Base class for Node-RED flow deployments via Admin HTTP API"""

    async def deploy(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Deploy flow.json to a Node-RED instance.

        Expected connection parameters:
        - nodered_host: IP address or hostname of the Node-RED instance
        - Additional parameters can be overridden by subclasses

        Expected config:
        - nodered.flow_file: Path to flow.json template
        - nodered.port: Node-RED port (default: 1880)
        """
        if not config.nodered:
            raise ValueError("No Node-RED configuration")

        nodered_config = config.nodered

        # Get connection parameters
        nodered_host = (
            connection.get("nodered_host")
            or connection.get("recamera_ip")
            or connection.get("host")
        )
        if not nodered_host:
            received = self._describe_connection(connection)
            await self._report_progress(
                progress_callback,
                "connect",
                0,
                f"Missing host. Expected key: 'host' (or 'nodered_host'/'recamera_ip'). Received: {received}",
            )
            return False

        nodered_port = nodered_config.port or 1880
        base_url = f"http://{nodered_host}:{nodered_port}"

        try:
            import httpx

            # Step 0: Pre-deploy hook (for subclass customization)
            await self._report_progress(
                progress_callback, "prepare", 0, "Preparing deployment..."
            )

            if not await self._pre_deploy_hook(config, connection, progress_callback):
                # Pre-deploy hook returned False, abort
                return False

            await self._report_progress(
                progress_callback, "prepare", 100, "Preparation complete"
            )

            # Before actions
            action_executor = LocalActionExecutor()
            if not await self._execute_actions(
                "before", config, connection, progress_callback, action_executor
            ):
                return False

            # Step 1: Load flow.json template
            await self._report_progress(
                progress_callback, "load_flow", 0, "Loading flow template..."
            )

            flow_file = config.get_asset_path(nodered_config.flow_file)
            if not flow_file or not Path(flow_file).exists():
                await self._report_progress(
                    progress_callback,
                    "load_flow",
                    0,
                    f"Flow file not found: {nodered_config.flow_file}",
                )
                return False

            with open(flow_file, "r", encoding="utf-8") as f:
                flow_data = json.load(f)

            await self._report_progress(
                progress_callback, "load_flow", 100, "Flow template loaded"
            )

            # Step 2: Update flow configuration (subclass hook)
            await self._report_progress(
                progress_callback, "configure", 0, "Configuring flow..."
            )

            flow_data, credentials = await self._update_flow_config(
                flow_data, config, connection
            )

            await self._report_progress(
                progress_callback, "configure", 100, "Configuration updated"
            )

            # Step 3: Connect to Node-RED and verify
            await self._report_progress(
                progress_callback,
                "connect",
                0,
                f"Connecting to Node-RED at {base_url}...",
            )

            async with httpx.AsyncClient(timeout=30.0) as client:
                # Verify Node-RED is accessible
                try:
                    response = await client.get(f"{base_url}/flows")
                    if response.status_code not in [200, 401]:
                        await self._report_progress(
                            progress_callback,
                            "connect",
                            0,
                            f"Node-RED not accessible: HTTP {response.status_code}",
                        )
                        return False
                except httpx.ConnectError as e:
                    await self._report_progress(
                        progress_callback,
                        "connect",
                        0,
                        f"Cannot connect to Node-RED: {str(e)}",
                    )
                    return False

                await self._report_progress(
                    progress_callback, "connect", 100, "Connected to Node-RED"
                )

                # Step 3.5: Ensure required modules are installed
                if nodered_config.modules:
                    await self._ensure_modules(
                        client,
                        base_url,
                        nodered_config.modules,
                        progress_callback,
                        config,
                        connection,
                    )

                # Step 4: Deploy flow
                await self._report_progress(
                    progress_callback, "deploy", 0, "Deploying flow..."
                )

                try:
                    response = await client.post(
                        f"{base_url}/flows",
                        json=flow_data,
                        headers={
                            "Content-Type": "application/json",
                            "Node-RED-Deployment-Type": "full",
                        },
                    )

                    if response.status_code not in [200, 204]:
                        error_msg = (
                            response.text[:200]
                            if response.text
                            else f"HTTP {response.status_code}"
                        )
                        await self._report_progress(
                            progress_callback,
                            "deploy",
                            0,
                            f"Flow deployment failed: {error_msg}",
                        )
                        return False

                except httpx.HTTPError as e:
                    await self._report_progress(
                        progress_callback,
                        "deploy",
                        0,
                        f"HTTP error during deployment: {str(e)}",
                    )
                    return False

                await self._report_progress(
                    progress_callback,
                    "deploy",
                    50,
                    "Flow deployed, setting credentials...",
                )

                # Step 5: Set credentials if provided
                if credentials:
                    for node_id, creds in credentials.items():
                        try:
                            creds_response = await client.put(
                                f"{base_url}/credentials/{node_id}",
                                json=creds,
                                headers={"Content-Type": "application/json"},
                            )
                            if creds_response.status_code not in [200, 204]:
                                logger.warning(
                                    f"Failed to set credentials for {node_id}: {creds_response.status_code}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Failed to set credentials for {node_id}: {e}"
                            )

                await self._report_progress(
                    progress_callback, "deploy", 100, "Flow deployed successfully"
                )

                # Step 6: Verify deployment
                await self._report_progress(
                    progress_callback, "verify", 0, "Verifying deployment..."
                )

                # Wait a moment for Node-RED to process
                await asyncio.sleep(2)

                try:
                    verify_response = await client.get(f"{base_url}/flows")
                    if verify_response.status_code == 200:
                        await self._report_progress(
                            progress_callback, "verify", 100, "Deployment verified"
                        )
                    else:
                        await self._report_progress(
                            progress_callback,
                            "verify",
                            100,
                            "Deployment complete (verification skipped)",
                        )
                except Exception:
                    await self._report_progress(
                        progress_callback,
                        "verify",
                        100,
                        "Deployment complete (verification skipped)",
                    )

            # Post-deploy hook
            await self._post_deploy_hook(config, connection, progress_callback)

            # After actions
            if not await self._execute_actions(
                "after", config, connection, progress_callback, action_executor
            ):
                return False

            return True

        except ImportError:
            await self._report_progress(
                progress_callback,
                "connect",
                0,
                "Missing dependency: httpx",
            )
            return False

        except Exception as e:
            logger.error(f"Node-RED deployment failed: {e}")
            await self._report_progress(
                progress_callback, "deploy", 0, f"Deployment failed: {str(e)}"
            )
            return False

    async def _pre_deploy_hook(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Hook called before deployment starts.

        Subclasses can override to perform pre-deployment tasks like
        stopping conflicting services.

        Returns:
            True to continue with deployment, False to abort
        """
        return True

    async def _update_flow_config(
        self,
        flow_data: List[Dict],
        config: DeviceConfig,
        connection: Dict[str, Any],
    ) -> tuple[List[Dict], Dict[str, Dict]]:
        """
        Update flow configuration before deployment.

        Subclasses should override this to customize flow configuration
        (e.g., update database URLs, API endpoints).

        Args:
            flow_data: The loaded flow JSON data
            config: Device configuration
            connection: Connection parameters

        Returns:
            Tuple of (updated_flow_data, credentials_dict)
            credentials_dict maps node_id -> credential_data
        """
        return flow_data, {}

    async def _post_deploy_hook(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """
        Hook called after successful deployment.

        Subclasses can override to perform post-deployment tasks.
        """
        pass

    async def _ensure_modules(
        self,
        client,
        base_url: str,
        modules: List[NodeRedModuleConfig],
        progress_callback: Optional[Callable] = None,
        config: Optional[DeviceConfig] = None,
        connection: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Ensure required Node-RED modules are installed.

        Three-level fallback per module:
          1. Online install via POST /nodes (device has internet)
          2. Proxy install: download on local machine, SCP to device (subclass hook)
          3. Pre-packaged offline tarball (if offline_package is set)

        If any module was installed via Level 2/3, restarts Node-RED at the end.
        Failures are logged as warnings but do not abort deployment.
        """
        import httpx

        await self._report_progress(
            progress_callback,
            "modules",
            0,
            f"Checking {len(modules)} required module(s)...",
        )

        # Get currently installed modules: GET /nodes returns a flat list of
        # node-set objects, each with a "module" and "version" field.
        try:
            response = await client.get(
                f"{base_url}/nodes",
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                logger.warning(
                    f"Cannot query installed modules: HTTP {response.status_code}"
                )
                return
            nodes_list = response.json()
        except Exception as e:
            logger.warning(f"Failed to query installed modules: {e}")
            return

        # Build {module_name: version} mapping from installed node-sets
        installed: Dict[str, str] = {}
        for node_set in nodes_list:
            mod_name = node_set.get("module")
            mod_ver = node_set.get("version")
            if mod_name and mod_ver:
                installed[mod_name] = mod_ver

        needs_restart = False

        for i, mod in enumerate(modules):
            progress_pct = int((i / len(modules)) * 100)

            current_ver = installed.get(mod.name)
            if current_ver:
                if mod.version and current_ver != mod.version:
                    # Version mismatch → update
                    await self._report_progress(
                        progress_callback,
                        "modules",
                        progress_pct,
                        f"Updating {mod.name} ({current_ver} → {mod.version})...",
                    )
                else:
                    # Already installed, version OK
                    logger.info(f"Module {mod.name}@{current_ver} already installed")
                    continue
            else:
                ver_str = f"@{mod.version}" if mod.version else ""
                await self._report_progress(
                    progress_callback,
                    "modules",
                    progress_pct,
                    f"Installing {mod.name}{ver_str}...",
                )

            # --- Level 1: Online install via POST /nodes ---
            payload: Dict[str, str] = {"module": mod.name}
            if mod.version:
                payload["version"] = mod.version

            level1_ok = False
            try:
                install_response = await client.post(
                    f"{base_url}/nodes",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=120.0,  # npm install can be slow on embedded devices
                )
                if install_response.status_code in [200, 204]:
                    logger.info(f"Installed module {mod.name} (online)")
                    level1_ok = True
                else:
                    logger.warning(
                        f"Online install of {mod.name} failed: "
                        f"HTTP {install_response.status_code} "
                        f"{install_response.text[:200]}"
                    )
            except httpx.TimeoutException:
                logger.warning(f"Timeout installing {mod.name} online (>120s)")
            except Exception as e:
                logger.warning(f"Online install of {mod.name} failed: {e}")

            if level1_ok:
                continue

            # --- Level 2: Proxy install (local machine downloads, SCP to device) ---
            if config and connection:
                ver_str = f"@{mod.version}" if mod.version else ""
                await self._report_progress(
                    progress_callback,
                    "modules",
                    progress_pct,
                    f"Proxy-installing {mod.name}{ver_str} from local machine...",
                )
                level2_ok = await self._proxy_install_module(
                    mod, config, connection, progress_callback
                )
                if level2_ok:
                    logger.info(f"Installed module {mod.name} (proxy)")
                    needs_restart = True
                    continue

            # --- Level 3: Pre-packaged offline tarball ---
            if mod.offline_package and config and connection:
                await self._report_progress(
                    progress_callback,
                    "modules",
                    progress_pct,
                    f"Installing {mod.name} from offline package...",
                )
                level3_ok = await self._install_from_offline_package(
                    mod, config, connection, progress_callback
                )
                if level3_ok:
                    logger.info(f"Installed module {mod.name} (offline package)")
                    needs_restart = True
                    continue

            # All levels failed
            logger.warning(f"Failed to install {mod.name} via all methods")

        # If any module was installed via filesystem (Level 2/3), restart Node-RED
        if needs_restart:
            await self._report_progress(
                progress_callback,
                "modules",
                90,
                "Restarting Node-RED to load new modules...",
            )
            restarted = await self._restart_nodered_service(
                config, connection, progress_callback
            )
            if restarted:
                await self._report_progress(
                    progress_callback,
                    "modules",
                    95,
                    "Node-RED restarted, waiting for ready...",
                )
                # Wait for Node-RED to be ready again
                ready = await self._wait_for_nodered_ready(client, base_url)
                if not ready:
                    logger.warning(
                        "Node-RED did not become ready after restart within timeout"
                    )
            else:
                logger.warning("Failed to restart Node-RED after module install")

        await self._report_progress(
            progress_callback, "modules", 100, "Module check complete"
        )

    async def _proxy_install_module(
        self,
        module: NodeRedModuleConfig,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """Download module on local machine and push to device via SCP.

        Subclasses should override this for device-specific implementation.
        Returns True if the module was successfully installed.
        """
        return False

    async def _install_from_offline_package(
        self,
        module: NodeRedModuleConfig,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """Install module from a pre-packaged offline tarball.

        Subclasses should override this for device-specific implementation.
        Returns True if the module was successfully installed.
        """
        return False

    async def _restart_nodered_service(
        self,
        config: Optional[DeviceConfig],
        connection: Optional[Dict[str, Any]],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """Restart Node-RED service to load filesystem-installed modules.

        Subclasses should override this for device-specific implementation.
        Returns True if Node-RED was successfully restarted.
        """
        return False

    async def _wait_for_nodered_ready(
        self,
        client,
        base_url: str,
        timeout: int = 90,
    ) -> bool:
        """Poll GET /flows until Node-RED is ready after restart.

        Default timeout is 90s — embedded devices with limited RAM (e.g. 180MB)
        can take 40-70s to fully start Node-RED with new modules.
        """
        import httpx

        for i in range(timeout):
            try:
                resp = await client.get(f"{base_url}/flows", timeout=5.0)
                if resp.status_code == 200:
                    logger.info(f"Node-RED ready after {i+1}s")
                    return True
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    async def get_current_flows(
        self,
        host: str,
        port: int = 1880,
    ) -> Optional[List[Dict]]:
        """Get current flows from Node-RED (for backup/reference)"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"http://{host}:{port}/flows")
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"Failed to get flows: {e}")

        return None
