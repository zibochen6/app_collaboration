"""
Remote Docker Compose deployment via SSH
"""

import asyncio
import logging
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from ..models.device import DeviceConfig, SSHConfig
from ..services.remote_pre_check import remote_pre_check
from ..utils.compose_labels import create_labels, inject_labels_to_compose
from .action_executor import SSHActionExecutor
from .base import BaseDeployer
from .ssh_mixin import SSHMixin

logger = logging.getLogger(__name__)


class RemoteDockerNotInstalled(Exception):
    """Raised when Docker is not installed on remote device"""

    def __init__(
        self, message: str, can_auto_fix: bool = False, fix_action: str = None
    ):
        super().__init__(message)
        self.can_auto_fix = can_auto_fix
        self.fix_action = fix_action


class DockerRemoteDeployer(SSHMixin, BaseDeployer):
    """Deploy Docker Compose applications to remote devices via SSH"""

    device_type = "docker_remote"
    ui_traits = {
        "connection": "ssh",
        "auto_deploy": True,
        "renderer": None,
        "has_targets": False,
        "show_model_selection": False,
        "show_service_warning": False,
        "connection_scope": "device",
    }
    steps = [
        {"id": "connect", "name": "Connect", "name_zh": "连接设备"},
        {"id": "check_os", "name": "Check OS", "name_zh": "检查系统"},
        {"id": "check_docker", "name": "Check Docker", "name_zh": "检查 Docker"},
        {"id": "prepare", "name": "Prepare Environment", "name_zh": "准备环境"},
        {
            "id": "actions_before",
            "name": "Custom Setup",
            "name_zh": "自定义准备",
            "_condition": "actions.before",
        },
        {"id": "upload", "name": "Upload Files", "name_zh": "上传文件"},
        {"id": "pull_images", "name": "Pull Docker Images", "name_zh": "拉取镜像"},
        {"id": "start_services", "name": "Start Services", "name_zh": "启动服务"},
        {"id": "health_check", "name": "Health Check", "name_zh": "健康检查"},
        {
            "id": "actions_after",
            "name": "Custom Config",
            "name_zh": "自定义配置",
            "_condition": "actions.after",
        },
    ]

    async def deploy(
        self,
        config: DeviceConfig,
        connection: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        if not config.docker_remote:
            raise ValueError("No docker_remote configuration")

        docker_config = config.docker_remote
        ssh_config = config.ssh or SSHConfig()

        host = connection.get("host")
        port = connection.get("port", ssh_config.port)
        username = connection.get("username", ssh_config.default_user)
        password = connection.get("password")
        key_file = connection.get("key_file")

        if not host:
            raise ValueError("No host specified for remote Docker deployment")

        # Build substitution context from connection + user_inputs defaults
        self._subst_context = {
            "host": host,
            "port": port,
            "username": username,
        }

        # Store solution metadata for label injection
        self._solution_id = connection.get("_solution_id")
        self._solution_name = connection.get("_solution_name")
        self._device_id = connection.get("_device_id")
        self._config_file = connection.get("_config_file")
        # Add defaults from user_inputs config
        if config.user_inputs:
            for user_input in config.user_inputs:
                if user_input.id not in self._subst_context:
                    # Use value from connection if provided, otherwise use default
                    self._subst_context[user_input.id] = connection.get(
                        user_input.id, user_input.default or ""
                    )

        try:
            import paramiko  # noqa: F401
            from scp import SCPClient  # noqa: F401

            # Step 1: SSH Connect
            await self._report_progress(
                progress_callback, "connect", 0, f"Connecting to {host}..."
            )

            client = await asyncio.to_thread(
                self._create_ssh_connection,
                host,
                port,
                username,
                password,
                key_file,
                ssh_config.connection_timeout,
            )

            if not client:
                await self._report_progress(
                    progress_callback, "connect", 0, "Connection failed"
                )
                return False

            await self._report_progress(
                progress_callback, "connect", 100, "Connected successfully"
            )

            try:
                # Step 1.5: Check remote OS is Linux
                await self._report_progress(
                    progress_callback,
                    "check_os",
                    0,
                    "Checking remote operating system...",
                )

                os_check = await remote_pre_check.check_remote_os(client)
                if not os_check.passed:
                    await self._report_progress(
                        progress_callback, "check_os", 0, os_check.message
                    )
                    return False

                await self._report_progress(
                    progress_callback, "check_os", 100, os_check.message
                )

                # Step 2: Check Docker on remote device
                auto_install_docker = connection.get("auto_install_docker", False)

                await self._report_progress(
                    progress_callback,
                    "check_docker",
                    0,
                    "Checking Docker on remote device...",
                )

                docker_check = await remote_pre_check.check_docker(client)

                if not docker_check.passed:
                    if docker_check.can_auto_fix and auto_install_docker:
                        # User confirmed auto-install
                        await self._report_progress(
                            progress_callback,
                            "check_docker",
                            20,
                            "Docker not found. Installing...",
                        )

                        if docker_check.fix_action == "install_docker":
                            success = await remote_pre_check.install_docker(
                                client, progress_callback
                            )
                            if not success:
                                await self._report_progress(
                                    progress_callback,
                                    "check_docker",
                                    0,
                                    "Docker installation failed",
                                )
                                return False
                        elif docker_check.fix_action == "fix_docker_permission":
                            success = await remote_pre_check.fix_docker_permission(
                                client, username, progress_callback
                            )
                            if not success:
                                return False
                        elif docker_check.fix_action == "start_docker":
                            success = await remote_pre_check.start_docker_service(
                                client, progress_callback
                            )
                            if not success:
                                return False

                        await self._report_progress(
                            progress_callback, "check_docker", 100, "Docker ready"
                        )
                    else:
                        # Docker not installed and no auto-install permission
                        raise RemoteDockerNotInstalled(
                            docker_check.message,
                            can_auto_fix=docker_check.can_auto_fix,
                            fix_action=docker_check.fix_action,
                        )
                else:
                    await self._report_progress(
                        progress_callback, "check_docker", 100, docker_check.message
                    )

                # Determine if we need sudo for docker commands
                # (e.g. after fresh install, group membership not active in current session)
                docker_sudo = ""
                exit_code, _, _ = await asyncio.to_thread(
                    self._exec_with_timeout, client, "docker info", 10
                )
                if exit_code != 0:
                    docker_sudo = "sudo "

                # Step 3: Prepare remote directory
                await self._report_progress(
                    progress_callback, "prepare", 0, "Creating remote directory..."
                )

                # Substitute template variables in remote_path
                remote_path = self._substitute_variables(
                    docker_config.remote_path, self._subst_context
                )
                remote_dir = f"{remote_path}/{config.id}"
                # Escape remote_dir for shell safety (handles spaces and special chars)
                remote_dir_escaped = shlex.quote(remote_dir)

                exit_code, _, stderr = await asyncio.to_thread(
                    self._exec_with_timeout,
                    client,
                    f"mkdir -p {remote_dir_escaped}",
                    30,
                )

                if exit_code != 0:
                    await self._report_progress(
                        progress_callback,
                        "prepare",
                        0,
                        f"Failed to create directory: {stderr[:200]}",
                    )
                    return False

                await self._report_progress(
                    progress_callback, "prepare", 100, f"Directory ready: {remote_dir}"
                )

                compose_path = config.get_asset_path(docker_config.compose_file)
                auto_replace = connection.get("auto_replace_containers", False)
                project_name = docker_config.options.get("project_name", config.id)
                project_name_escaped = shlex.quote(project_name)

                # Before actions
                ssh_executor = SSHActionExecutor(client, password)
                if not await self._execute_actions(
                    "before", config, connection, progress_callback, ssh_executor
                ):
                    return False

                # Resolve compose command across v2 plugin and v1 standalone.
                compose_command = await self._resolve_compose_command(
                    client, docker_sudo
                )
                if not compose_command:
                    await self._report_progress(
                        progress_callback,
                        "check_docker",
                        0,
                        "Docker Compose not found (tried: docker compose / docker-compose)",
                    )
                    return False

                # Check for existing containers that would conflict
                await self._check_existing_remote_containers(
                    client,
                    compose_path,
                    project_name_escaped,
                    remote_dir_escaped,
                    docker_sudo,
                    auto_replace,
                    progress_callback,
                    compose_command,
                )

                # Step 3: Upload compose files
                await self._report_progress(
                    progress_callback, "upload", 0, "Uploading files..."
                )

                success = await self._upload_compose_files(
                    client, config, docker_config, remote_dir, progress_callback
                )

                if not success:
                    await self._report_progress(
                        progress_callback, "upload", 0, "File upload failed"
                    )
                    return False

                await self._report_progress(
                    progress_callback, "upload", 100, "Files uploaded"
                )

                # Step 4: Docker compose pull
                # Pull only when images are missing on remote to avoid blocking
                # deployments in offline / unstable networks when cache exists.
                compose_images = self._get_compose_images(compose_path)
                missing_images = await self._check_remote_images_exist(
                    client, compose_images, docker_sudo
                )

                if not missing_images:
                    await self._report_progress(
                        progress_callback,
                        "pull_images",
                        100,
                        "All images already exist locally, skipping pull",
                    )
                else:
                    await self._report_progress(
                        progress_callback,
                        "pull_images",
                        0,
                        f"Pulling missing images ({len(missing_images)})...",
                    )

                    # Use --quiet to suppress progress bars that flood SSH
                    # channel buffer and cause deadlocks for large images.
                    # Use a longer timeout (30 min) for multi-GB image pulls.
                    pull_timeout = max(ssh_config.command_timeout, 1800)
                    exit_code, stdout, stderr = await asyncio.to_thread(
                        self._exec_with_timeout,
                        client,
                        f"cd {remote_dir_escaped} && {compose_command} pull --quiet",
                        pull_timeout,
                    )

                    if exit_code != 0:
                        # Re-check cache: if all images are now present, continue.
                        still_missing = await self._check_remote_images_exist(
                            client, compose_images, docker_sudo
                        )
                        if still_missing:
                            # Filter out obsolete compose version warning.
                            error_lines = [
                                line
                                for line in stderr.strip().splitlines()
                                if "the attribute `version` is obsolete" not in line
                            ]
                            error_msg = "\n".join(error_lines).strip() or stderr.strip()
                            missing_msg = ", ".join(still_missing)
                            await self._report_progress(
                                progress_callback,
                                "pull_images",
                                0,
                                f"Pull failed: {error_msg[:220]} | Missing images: {missing_msg[:220]}",
                            )
                            return False

                        await self._report_progress(
                            progress_callback,
                            "pull_images",
                            100,
                            "Pull command failed, but all required images already exist locally. Continue...",
                        )
                    else:
                        await self._report_progress(
                            progress_callback, "pull_images", 100, "Images pulled"
                        )

                # Step 5: Docker compose up
                await self._report_progress(
                    progress_callback, "start_services", 0, "Starting services..."
                )

                # Substitute template variables in environment values
                # Quote values properly to handle spaces and special characters
                env_items = []
                for k, v in docker_config.environment.items():
                    substituted_value = self._substitute_variables(
                        str(v), self._subst_context
                    )
                    # Use shlex.quote for proper escaping of all special characters
                    escaped_value = shlex.quote(substituted_value)
                    env_items.append(f"{k}={escaped_value}")
                env_vars = " ".join(env_items)
                env_prefix = f"env {env_vars} " if env_vars else ""

                compose_cmd = f"cd {remote_dir_escaped} && {env_prefix}{compose_command} -p {project_name_escaped} up -d"

                if docker_config.options.get("remove_orphans"):
                    compose_cmd += " --remove-orphans"

                exit_code, stdout, stderr = await asyncio.to_thread(
                    self._exec_with_timeout,
                    client,
                    compose_cmd,
                    ssh_config.command_timeout,
                )

                if exit_code != 0:
                    await self._report_progress(
                        progress_callback,
                        "start_services",
                        0,
                        f"Start failed: {stderr[:200]}",
                    )
                    return False

                await self._report_progress(
                    progress_callback, "start_services", 100, "Services started"
                )

                # Step 6: Health check
                await self._report_progress(
                    progress_callback, "health_check", 0, "Checking services..."
                )

                if docker_config.services:
                    all_healthy = True
                    for service in docker_config.services:
                        if service.health_check_endpoint:
                            health_timeout = (
                                service.health_check_timeout
                                if service.health_check_timeout
                                else 90
                            )
                            healthy = await self._check_remote_service_health(
                                host,
                                service.port,
                                service.health_check_endpoint,
                                timeout=health_timeout,
                                progress_callback=progress_callback,
                            )
                            if not healthy:
                                if service.required:
                                    await self._report_progress(
                                        progress_callback,
                                        "health_check",
                                        0,
                                        f"Service {service.name} is not healthy",
                                    )
                                    all_healthy = False
                                    break
                                else:
                                    logger.warning(
                                        f"Optional service {service.name} is not healthy"
                                    )

                    if not all_healthy:
                        return False

                await self._report_progress(
                    progress_callback, "health_check", 100, "All services healthy"
                )

                # After actions
                if not await self._execute_actions(
                    "after", config, connection, progress_callback, ssh_executor
                ):
                    return False

                # Open browser if configured (post_deployment)
                if (
                    config.post_deployment
                    and config.post_deployment.open_browser
                    and config.post_deployment.url
                ):
                    try:
                        import webbrowser

                        # Substitute template variables in URL (e.g., {{host}})
                        url = self._substitute_variables(
                            config.post_deployment.url, self._subst_context
                        )
                        webbrowser.open(url)
                        logger.info(f"Opened browser: {url}")
                    except Exception as e:
                        logger.warning(f"Failed to open browser: {e}")

                return True

            finally:
                client.close()

        except ImportError as e:
            await self._report_progress(
                progress_callback,
                "connect",
                0,
                f"Missing dependency: {str(e)}",
            )
            return False

        except RemoteDockerNotInstalled:
            raise  # Let deployment engine handle Docker installation dialog
        except Exception as e:
            logger.error(f"Docker remote deployment failed: {e}")
            await self._report_progress(
                progress_callback, "start_services", 0, f"Deployment failed: {str(e)}"
            )
            return False

    async def _upload_compose_files(
        self,
        client,
        config: DeviceConfig,
        docker_config,
        remote_dir: str,
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """Upload compose files and related resources to remote"""
        temp_files = []  # Track temp files for cleanup

        try:

            # Get compose file path
            compose_path = config.get_asset_path(docker_config.compose_file)
            if not compose_path or not Path(compose_path).exists():
                logger.error(f"Compose file not found: {docker_config.compose_file}")
                return False

            # Create labels for injection
            labels = None
            if self._solution_id and self._device_id:
                labels = create_labels(
                    solution_id=self._solution_id,
                    device_id=self._device_id,
                    solution_name=self._solution_name,
                    config_file=self._config_file,
                )

            # If compose_dir is specified, upload entire directory
            if docker_config.compose_dir:
                compose_dir_path = config.get_asset_path(docker_config.compose_dir)
                if compose_dir_path and Path(compose_dir_path).exists():
                    await self._report_progress(
                        progress_callback,
                        "upload",
                        25,
                        f"Uploading directory: {docker_config.compose_dir}",
                    )

                    # Upload contents of directory (not the directory itself)
                    # Labels will be injected to compose files during transfer
                    success = await asyncio.to_thread(
                        self._transfer_directory_contents_with_labels,
                        client,
                        compose_dir_path,
                        remote_dir,
                        labels,
                    )

                    if not success:
                        return False
                else:
                    logger.error(
                        f"Compose directory not found: {docker_config.compose_dir}"
                    )
                    return False
            else:
                # Upload just the compose file with labels injected
                await self._report_progress(
                    progress_callback,
                    "upload",
                    50,
                    f"Uploading: {docker_config.compose_file}",
                )

                remote_compose_path = f"{remote_dir}/docker-compose.yml"

                # Inject labels before upload
                if labels:
                    success = await asyncio.to_thread(
                        self._transfer_compose_with_labels,
                        client,
                        compose_path,
                        remote_compose_path,
                        labels,
                    )
                else:
                    success = await asyncio.to_thread(
                        self._transfer_file, client, compose_path, remote_compose_path
                    )

                if not success:
                    return False

            return True

        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return False

    def _transfer_directory(self, client, local_dir: str, remote_dir: str) -> bool:
        """Transfer entire directory via SCP (blocking, run in thread)"""
        try:
            from scp import SCPClient

            with SCPClient(client.get_transport()) as scp:
                scp.put(local_dir, remote_dir, recursive=True)
            return True
        except Exception as e:
            logger.error(f"Directory transfer failed: {e}")
            return False

    def _transfer_directory_contents(
        self, client, local_dir: str, remote_dir: str
    ) -> bool:
        """Transfer contents of a directory (files and subdirs) directly into remote_dir"""
        try:

            from scp import SCPClient

            local_path = Path(local_dir)
            with SCPClient(client.get_transport()) as scp:
                for item in local_path.iterdir():
                    remote_path = f"{remote_dir}/{item.name}"
                    if item.is_file():
                        scp.put(str(item), remote_path)
                    elif item.is_dir():
                        scp.put(str(item), remote_dir, recursive=True)
            return True
        except Exception as e:
            logger.error(f"Directory contents transfer failed: {e}")
            return False

    def _transfer_compose_with_labels(
        self, client, local_path: str, remote_path: str, labels: Dict[str, str]
    ) -> bool:
        """Transfer compose file with labels injected"""
        try:

            from scp import SCPClient

            # Read and inject labels
            with open(local_path, "r") as f:
                original_content = f.read()

            modified_content = inject_labels_to_compose(original_content, labels)

            # Create a file-like object for SCP
            with SCPClient(client.get_transport()) as scp:
                # Write to temp file and upload
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yml", delete=False
                ) as tmp:
                    tmp.write(modified_content)
                    tmp_path = tmp.name

                try:
                    scp.put(tmp_path, remote_path)
                finally:
                    os.unlink(tmp_path)

            logger.info(f"Uploaded compose file with labels to {remote_path}")
            return True

        except Exception as e:
            logger.error(f"Compose file transfer with labels failed: {e}")
            return False

    def _transfer_directory_contents_with_labels(
        self, client, local_dir: str, remote_dir: str, labels: Optional[Dict[str, str]]
    ) -> bool:
        """Transfer directory contents, injecting labels into compose files"""
        try:
            from scp import SCPClient

            local_path = Path(local_dir)
            compose_names = {
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            }

            with SCPClient(client.get_transport()) as scp:
                for item in local_path.iterdir():
                    remote_path = f"{remote_dir}/{item.name}"

                    if item.is_file():
                        # Check if it's a compose file that needs label injection
                        if labels and item.name.lower() in compose_names:
                            # Inject labels
                            with open(item, "r") as f:
                                original_content = f.read()
                            modified_content = inject_labels_to_compose(
                                original_content, labels
                            )

                            # Write to temp file and upload
                            with tempfile.NamedTemporaryFile(
                                mode="w", suffix=".yml", delete=False
                            ) as tmp:
                                tmp.write(modified_content)
                                tmp_path = tmp.name

                            try:
                                scp.put(tmp_path, remote_path)
                            finally:
                                os.unlink(tmp_path)

                            logger.info(
                                f"Uploaded compose file with labels: {item.name}"
                            )
                        else:
                            scp.put(str(item), remote_path)
                    elif item.is_dir():
                        scp.put(str(item), remote_dir, recursive=True)

            return True

        except Exception as e:
            logger.error(f"Directory contents transfer with labels failed: {e}")
            return False

    def _get_compose_container_names(self, compose_file: str) -> List[str]:
        """Extract container_name values from a local compose file"""
        try:
            with open(compose_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "services" not in data:
                return []
            names = []
            for service_config in data.get("services", {}).values():
                if service_config and "container_name" in service_config:
                    names.append(service_config["container_name"])
            return names
        except Exception as e:
            logger.debug(f"Failed to parse compose file for container names: {e}")
            return []

    def _get_compose_images(self, compose_file: str) -> List[str]:
        """Extract image names from a local compose file."""
        try:
            with open(compose_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "services" not in data:
                return []

            images: List[str] = []
            for service_config in data.get("services", {}).values():
                image = (
                    service_config.get("image")
                    if isinstance(service_config, dict)
                    else None
                )
                if image and isinstance(image, str) and image not in images:
                    images.append(image)
            return images
        except Exception as e:
            logger.debug(f"Failed to parse compose file for images: {e}")
            return []

    async def _check_remote_images_exist(
        self, client, images: List[str], docker_sudo: str
    ) -> List[str]:
        """Return list of images that are missing on the remote device."""
        if not images:
            return []

        missing: List[str] = []
        for image in images:
            inspect_cmd = f"{docker_sudo}docker image inspect {shlex.quote(image)} >/dev/null 2>&1"
            exit_code, _, _ = await asyncio.to_thread(
                self._exec_with_timeout, client, inspect_cmd, 20
            )
            if exit_code != 0:
                missing.append(image)
        return missing

    async def _check_existing_remote_containers(
        self,
        client,
        local_compose_file: str,
        project_name_escaped: str,
        remote_dir_escaped: str,
        docker_sudo: str,
        auto_replace: bool,
        progress_callback=None,
        compose_command: Optional[str] = None,
    ) -> None:
        """Check for existing containers on remote that would conflict.

        Parses the local compose file for container_name values, then checks
        on the remote machine via SSH whether those containers already exist.
        """
        if not local_compose_file:
            return

        container_names = self._get_compose_container_names(local_compose_file)
        if not container_names:
            return

        # Build a single SSH command to check all container names at once
        filter_args = " ".join(
            f"--filter 'name=^/{shlex.quote(n)}$'" for n in container_names
        )
        check_cmd = (
            f"{docker_sudo}docker ps -a {filter_args} "
            "--format '{{.Names}} ({{.Image}}) - {{.Status}}'"
        )

        exit_code, stdout, _ = await asyncio.to_thread(
            self._exec_with_timeout, client, check_cmd, 15
        )

        existing = [line for line in stdout.strip().split("\n") if line.strip()]
        if not existing:
            return

        if auto_replace:
            await self._report_progress(
                progress_callback,
                "prepare",
                50,
                "Stopping existing containers...",
            )

            effective_compose_cmd = compose_command or f"{docker_sudo}docker compose"
            # Run docker compose down for the project
            down_cmd = (
                f"cd {remote_dir_escaped} && "
                f"{effective_compose_cmd} -p {project_name_escaped} down --remove-orphans 2>/dev/null; "
            )
            # Also force remove by container name (cross-project conflicts)
            rm_names = " ".join(shlex.quote(n) for n in container_names)
            down_cmd += f"{docker_sudo}docker rm -f {rm_names} 2>/dev/null || true"

            await asyncio.to_thread(self._exec_with_timeout, client, down_cmd, 60)

            await self._report_progress(
                progress_callback,
                "prepare",
                80,
                "Existing containers removed",
            )
        else:
            container_list = ", ".join(container_names)
            raise RemoteDockerNotInstalled(
                f"Found existing containers: {container_list}. "
                "Would you like to stop and replace them with the new deployment?",
                can_auto_fix=True,
                fix_action="replace_containers",
            )

    async def _resolve_compose_command(self, client, docker_sudo: str) -> Optional[str]:
        """Resolve docker compose command (v2 plugin or v1 standalone)."""
        probes = (
            ("docker compose version", "docker compose"),
            ("docker-compose --version", "docker-compose"),
        )

        # Prefer probing with docker_sudo first because deploy commands may require it.
        for probe_cmd, resolved_cmd in probes:
            exit_code, _, _ = await asyncio.to_thread(
                self._exec_with_timeout, client, f"{docker_sudo}{probe_cmd}", 20
            )
            if exit_code == 0:
                return f"{docker_sudo}{resolved_cmd}"

        # Fallback: probe without sudo, still keep docker_sudo for runtime operations.
        for probe_cmd, resolved_cmd in probes:
            exit_code, _, _ = await asyncio.to_thread(
                self._exec_with_timeout, client, probe_cmd, 20
            )
            if exit_code == 0:
                return f"{docker_sudo}{resolved_cmd}" if docker_sudo else resolved_cmd

        return None

    async def _check_remote_service_health(
        self,
        host: str,
        port: int,
        endpoint: str,
        timeout: int = 30,
        progress_callback=None,
    ) -> bool:
        """Check remote service health via HTTP"""
        try:
            import httpx

            url = f"http://{host}:{port}{endpoint}"
            start_time = asyncio.get_event_loop().time()
            attempt = 0

            while asyncio.get_event_loop().time() - start_time < timeout:
                attempt += 1
                try:
                    async with httpx.AsyncClient() as http_client:
                        response = await http_client.get(url, timeout=5)
                        if response.status_code < 500:
                            return True
                except Exception as e:
                    if progress_callback:
                        elapsed = int(asyncio.get_event_loop().time() - start_time)
                        await self._report_progress(
                            progress_callback,
                            "health_check",
                            min(50, elapsed * 100 // timeout),
                            f"Waiting for service at {host}:{port} (attempt {attempt}, {elapsed}s/{timeout}s)...",
                        )
                    logger.debug(f"Health check attempt {attempt} failed: {e}")
                await asyncio.sleep(2)

            return False

        except ImportError:
            logger.warning("httpx not installed, skipping health check")
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def _substitute_variables(
        self,
        template: str,
        context: Dict[str, Any],
    ) -> str:
        """Substitute {{variable}} placeholders with values from context"""
        import re

        if not template:
            return template

        def replace_var(match):
            var_name = match.group(1)
            value = context.get(var_name)
            if value is None:
                return ""  # Return empty string if variable not found
            return str(value)

        # Replace {{var}} patterns
        result = re.sub(r"\{\{(\w+)\}\}", replace_var, template)
        return result
