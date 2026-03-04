"""
Docker device management service - Local and SSH-based container management
"""

import asyncio
import json
import logging
import platform
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.docker_device import (
    ConnectDeviceRequest,
    ContainerInfo,
    DeviceInfo,
    ManagedApp,
    ManagedAppContainer,
    UpgradeRequest,
)
from ..utils.compose_labels import (
    create_labels,
    inject_labels_to_compose_file,
    parse_container_labels,
)

logger = logging.getLogger(__name__)


def _get_subprocess_kwargs() -> Dict[str, Any]:
    """Get subprocess kwargs with hidden window on Windows"""
    kwargs: Dict[str, Any] = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


class DockerDeviceManager:
    """Manages Docker containers on local and remote devices"""

    # ============================================
    # Local Docker Management
    # ============================================

    async def check_local_docker(self) -> DeviceInfo:
        """Check if Docker is available locally"""
        try:
            # Get Docker version
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                **_get_subprocess_kwargs(),
            )
            if result.returncode != 0:
                raise RuntimeError("Docker not available")

            docker_version = (
                result.stdout.strip().replace("Docker version ", "").split(",")[0]
            )

            # Get hostname
            hostname = socket.gethostname()

            return DeviceInfo(
                hostname=hostname,
                docker_version=docker_version,
                os_info="Local Machine",
            )
        except FileNotFoundError:
            raise RuntimeError("Docker is not installed")
        except Exception as e:
            logger.error(f"Local Docker check failed: {e}")
            raise RuntimeError(f"Docker check failed: {str(e)}")

    async def list_local_containers(self) -> List[ContainerInfo]:
        """List all Docker containers on local machine"""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "ps",
                    "-a",
                    "--format",
                    '{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","ports":"{{.Ports}}","labels":"{{.Labels}}"}',
                ],
                capture_output=True,
                text=True,
                timeout=30,
                **_get_subprocess_kwargs(),
            )

            if result.returncode != 0:
                raise RuntimeError(f"Docker command failed: {result.stderr}")

            containers = []
            output = result.stdout.strip()
            if not output:
                return containers

            for line in output.split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    image = data.get("image", "")
                    if ":" in image:
                        image_name, tag = image.rsplit(":", 1)
                    else:
                        image_name = image
                        tag = "latest"

                    raw_status = data.get("status", "").lower()
                    if "up" in raw_status:
                        status = "running"
                    elif "exited" in raw_status:
                        status = "exited"
                    else:
                        status = "stopped"

                    ports_str = data.get("ports", "")
                    ports = (
                        [p.strip() for p in ports_str.split(",") if p.strip()]
                        if ports_str
                        else []
                    )

                    labels_str = data.get("labels", "")
                    labels = {}
                    if labels_str:
                        for pair in labels_str.split(","):
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                labels[k] = v

                    containers.append(
                        ContainerInfo(
                            container_id=data.get("id", ""),
                            name=data.get("name", ""),
                            image=image_name,
                            current_tag=tag,
                            status=status,
                            ports=ports,
                            labels=labels,
                        )
                    )
                except json.JSONDecodeError:
                    continue

            return containers

        except FileNotFoundError:
            raise RuntimeError("Docker is not installed")
        except Exception as e:
            logger.error(f"Failed to list local containers: {e}")
            raise RuntimeError(f"Failed to list containers: {str(e)}")

    async def list_local_managed_apps(self) -> List[ManagedApp]:
        """List SenseCraft-managed applications on local machine, grouped by solution"""
        containers = await self.list_local_containers()
        return self._group_containers_by_solution(containers)

    def _group_containers_by_solution(
        self, containers: List[ContainerInfo]
    ) -> List[ManagedApp]:
        """Group containers by solution_id into ManagedApp objects"""
        # Group containers by solution_id
        solution_groups: Dict[str, Dict[str, Any]] = {}

        for container in containers:
            sensecraft_meta = parse_container_labels(container.labels or {})
            if not sensecraft_meta:
                continue

            solution_id = sensecraft_meta.get("solution_id")
            if not solution_id:
                continue

            if solution_id not in solution_groups:
                solution_groups[solution_id] = {
                    "solution_id": solution_id,
                    "solution_name": sensecraft_meta.get("solution_name"),
                    "device_id": sensecraft_meta.get("device_id"),
                    "deployed_at": sensecraft_meta.get("deployed_at"),
                    "containers": [],
                    "ports": [],
                    "statuses": [],
                }

            group = solution_groups[solution_id]
            group["containers"].append(
                ManagedAppContainer(
                    container_id=container.container_id,
                    container_name=container.name,
                    image=container.image,
                    tag=container.current_tag,
                    status=container.status,
                    ports=container.ports,
                )
            )
            group["ports"].extend(container.ports)
            group["statuses"].append(container.status)

        # Convert to ManagedApp list
        managed_apps = []
        for group in solution_groups.values():
            # Determine aggregated status: running if any container running
            statuses = group["statuses"]
            if "running" in statuses:
                status = "running"
            elif "exited" in statuses:
                status = "exited"
            else:
                status = "stopped"

            # Check for config manifest to populate config_fields
            config_fields = self._load_config_fields(group["solution_id"])

            managed_apps.append(
                ManagedApp(
                    solution_id=group["solution_id"],
                    solution_name=group["solution_name"],
                    device_id=group["device_id"],
                    deployed_at=group["deployed_at"],
                    status=status,
                    containers=group["containers"],
                    ports=list(set(group["ports"])),  # Deduplicate ports
                    config_fields=config_fields,
                )
            )

        return managed_apps

    async def local_container_action(
        self, container_name: str, action: str
    ) -> Dict[str, Any]:
        """Perform action on a local container (start/stop/restart/remove)"""
        if action not in ("start", "stop", "restart", "remove"):
            raise ValueError(f"Invalid action: {action}")

        try:
            if action == "remove":
                # First stop the container, then remove it
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "stop", container_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    **_get_subprocess_kwargs(),
                )
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "rm", container_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    **_get_subprocess_kwargs(),
                )
            else:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", action, container_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    **_get_subprocess_kwargs(),
                )

            if result.returncode != 0:
                raise RuntimeError(f"Action failed: {result.stderr}")

            action_past = "removed" if action == "remove" else f"{action}ed"
            return {
                "success": True,
                "message": f"Container {container_name} {action_past} successfully",
                "output": result.stdout,
            }
        except Exception as e:
            logger.error(f"Local container action {action} failed: {e}")
            raise RuntimeError(f"Action failed: {str(e)}")

    async def local_remove_app(
        self,
        solution_id: str,
        container_names: List[str],
        remove_images: bool = False,
        remove_volumes: bool = False,
    ) -> Dict[str, Any]:
        """Remove all containers for an app, optionally removing images and volumes"""
        results = []
        images_to_remove = []
        project_names = set()

        # Get container info before removing (to get image references and project name)
        containers = await self.list_local_containers()
        for c in containers:
            if c.name in container_names:
                if remove_images:
                    images_to_remove.append(f"{c.image}:{c.current_tag}")
                # Get compose project name from container labels
                if c.labels.get("com.docker.compose.project"):
                    project_names.add(c.labels["com.docker.compose.project"])

        # Remove containers
        for container_name in container_names:
            try:
                result = await self.local_container_action(container_name, "remove")
                results.append({"container": container_name, "success": True})
            except Exception as e:
                results.append(
                    {"container": container_name, "success": False, "error": str(e)}
                )

        # Remove images if requested
        images_removed = []
        images_skipped = []
        if remove_images and images_to_remove:
            for image in set(images_to_remove):  # deduplicate
                try:
                    # Check if image is used by other containers
                    check_result = await asyncio.to_thread(
                        subprocess.run,
                        [
                            "docker",
                            "ps",
                            "-a",
                            "--filter",
                            f"ancestor={image}",
                            "--format",
                            "{{.Names}}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        **_get_subprocess_kwargs(),
                    )
                    remaining_containers = [
                        n for n in check_result.stdout.strip().split("\n") if n
                    ]

                    if remaining_containers:
                        images_skipped.append(
                            {
                                "image": image,
                                "reason": f"used by: {', '.join(remaining_containers)}",
                            }
                        )
                        continue

                    # Remove the image
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "rmi", image],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        **_get_subprocess_kwargs(),
                    )
                    if result.returncode == 0:
                        images_removed.append(image)
                    else:
                        images_skipped.append(
                            {"image": image, "reason": result.stderr.strip()}
                        )
                except Exception as e:
                    images_skipped.append({"image": image, "reason": str(e)})

        # Remove volumes if requested
        volumes_removed = []
        volumes_skipped = []
        if remove_volumes:
            # Find volumes associated with the compose project
            # Volumes are named like {project_name}_{volume_name}
            # project_name comes from container labels, fallback to solution_id
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "volume", "ls", "--format", "{{.Name}}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    **_get_subprocess_kwargs(),
                )
                all_volumes = [v for v in result.stdout.strip().split("\n") if v]

                # Build list of prefixes to match
                prefixes = list(project_names) if project_names else []
                # Fallback to solution_id patterns if no project_name found
                if not prefixes:
                    prefixes = [solution_id, solution_id.replace("-", "_")]

                solution_volumes = [
                    v
                    for v in all_volumes
                    if any(v.startswith(f"{prefix}_") for prefix in prefixes)
                ]

                for volume in solution_volumes:
                    try:
                        vol_result = await asyncio.to_thread(
                            subprocess.run,
                            ["docker", "volume", "rm", volume],
                            capture_output=True,
                            text=True,
                            timeout=30,
                            **_get_subprocess_kwargs(),
                        )
                        if vol_result.returncode == 0:
                            volumes_removed.append(volume)
                        else:
                            volumes_skipped.append(
                                {"volume": volume, "reason": vol_result.stderr.strip()}
                            )
                    except Exception as e:
                        volumes_skipped.append({"volume": volume, "reason": str(e)})
            except Exception as e:
                logger.warning(f"Failed to list volumes: {e}")

        return {
            "success": all(r["success"] for r in results),
            "containers": results,
            "images_removed": images_removed,
            "images_skipped": images_skipped,
            "volumes_removed": volumes_removed,
            "volumes_skipped": volumes_skipped,
        }

    async def local_prune_images(self) -> Dict[str, Any]:
        """Remove all unused Docker images"""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "image", "prune", "-af"],
                capture_output=True,
                text=True,
                timeout=120,
                **_get_subprocess_kwargs(),
            )

            if result.returncode != 0:
                raise RuntimeError(f"Prune failed: {result.stderr}")

            # Parse output to get space reclaimed
            output = result.stdout
            space_reclaimed = "0B"
            for line in output.split("\n"):
                if "Total reclaimed space:" in line:
                    space_reclaimed = line.split(":")[-1].strip()
                    break

            return {
                "success": True,
                "message": f"Pruned unused images, reclaimed {space_reclaimed}",
                "output": output,
                "space_reclaimed": space_reclaimed,
            }
        except Exception as e:
            logger.error(f"Local image prune failed: {e}")
            raise RuntimeError(f"Prune failed: {str(e)}")

    # ============================================
    # Configuration Management
    # ============================================

    @staticmethod
    def _get_manifests_dir(solution_id: str) -> Path:
        """Get the manifest directory for a solution"""
        return Path.home() / ".sensecraft" / "deployments" / solution_id

    def _load_config_fields(self, solution_id: str) -> Optional[List[Dict[str, Any]]]:
        """Load config fields from manifest files for a solution.

        Returns aggregated fields from all device manifests, or None if no
        reconfigurable fields exist.
        """
        manifests_dir = self._get_manifests_dir(solution_id)
        if not manifests_dir.exists():
            return None

        all_fields = []
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                manifest = json.loads(manifest_file.read_text())
                fields = manifest.get("fields", [])
                if fields:
                    all_fields.extend(fields)
            except Exception as e:
                logger.warning(f"Failed to read manifest {manifest_file}: {e}")

        return all_fields if all_fields else None

    async def get_app_config(self, solution_id: str) -> Optional[Dict[str, Any]]:
        """Get the current configuration for a deployed app.

        Returns config schema with current values from manifest files.
        """
        manifests_dir = self._get_manifests_dir(solution_id)
        if not manifests_dir.exists():
            return None

        configs = []
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                manifest = json.loads(manifest_file.read_text())
                configs.append(manifest)
            except Exception as e:
                logger.warning(f"Failed to read manifest {manifest_file}: {e}")

        if not configs:
            return None

        # Aggregate fields from all device manifests
        all_fields = []
        for config in configs:
            all_fields.extend(config.get("fields", []))

        return {
            "solution_id": solution_id,
            "devices": configs,
            "fields": all_fields,
        }

    async def update_app_config(
        self,
        solution_id: str,
        values: Dict[str, str],
    ) -> Dict[str, Any]:
        """Update configuration for a locally deployed Docker app.

        1. Read manifests to get config_file paths
        2. Load device YAML → get docker.environment + compose settings
        3. Substitute templates with new values → build new env
        4. Inject labels → temp compose file
        5. docker compose up -d with new env
        6. Update manifest with new current_values
        """
        manifests_dir = self._get_manifests_dir(solution_id)
        if not manifests_dir.exists():
            raise RuntimeError(f"No config manifest found for {solution_id}")

        results = []
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                manifest = json.loads(manifest_file.read_text())
                device_type = manifest.get("device_type", "docker_local")

                # Only handle local Docker configs here
                if device_type not in ("docker_local",):
                    continue

                result = await self._reconfigure_local_device(
                    manifest, values, manifest_file
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to reconfigure {manifest_file.stem}: {e}")
                results.append(
                    {"device_id": manifest_file.stem, "success": False, "error": str(e)}
                )

        success = all(r.get("success") for r in results)
        return {"success": success, "results": results}

    async def _reconfigure_local_device(
        self,
        manifest: Dict[str, Any],
        values: Dict[str, str],
        manifest_path: Path,
    ) -> Dict[str, Any]:
        """Reconfigure a single local Docker device with new env values."""
        from ..utils.template import substitute

        config_file = manifest.get("config_file")
        solution_id = manifest.get("solution_id")
        device_id = manifest.get("device_id")

        if not config_file or not solution_id:
            raise RuntimeError("Manifest missing config_file or solution_id")

        # Load device YAML to get docker config
        from .solution_manager import solution_manager

        config = await solution_manager.load_device_config(solution_id, config_file)
        if not config or not config.docker:
            raise RuntimeError(f"Cannot load docker config from {config_file}")

        docker_config = config.docker
        project_name = docker_config.options.get("project_name", "provisioning")

        # Build new environment with substituted values
        # Use values from the form, falling back to manifest current_value
        context = {}
        for field in manifest.get("fields", []):
            field_id = field["id"]
            context[field_id] = values.get(field_id, field.get("current_value", ""))

        env = {}
        for k, v in docker_config.environment.items():
            env[k] = substitute(str(v), context) or ""

        # Get compose file path and inject labels
        compose_file = config.get_asset_path(docker_config.compose_file)
        if not compose_file or not Path(compose_file).exists():
            raise RuntimeError(f"Compose file not found: {docker_config.compose_file}")

        compose_dir = Path(compose_file).parent

        labels = create_labels(
            solution_id=solution_id,
            device_id=device_id,
            solution_name=manifest.get("solution_name"),
            config_file=config_file,
        )
        temp_compose_file = inject_labels_to_compose_file(compose_file, labels)

        try:
            # Run docker compose up -d with new env
            result = await self._run_local_compose(
                temp_compose_file,
                ["up", "-d"],
                project_name,
                env=env,
                working_dir=str(compose_dir),
            )

            if not result["success"]:
                raise RuntimeError(f"docker compose up failed: {result.get('error')}")

            # Update manifest with new current_values
            for field in manifest.get("fields", []):
                field_id = field["id"]
                if field_id in values:
                    field["current_value"] = values[field_id]

            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            logger.info(f"Updated config manifest: {manifest_path}")

            return {"device_id": device_id, "success": True}

        finally:
            # Clean up temp compose file
            if Path(temp_compose_file).exists():
                try:
                    import os

                    os.remove(temp_compose_file)
                except Exception:
                    pass

    async def _run_local_compose(
        self,
        compose_file: str,
        args: list,
        project_name: str = None,
        env: Dict[str, str] = None,
        working_dir: str = None,
    ) -> Dict[str, Any]:
        """Run a local docker compose command."""
        import os

        compose_base = await self._resolve_local_compose_base()
        if not compose_base:
            return {
                "success": False,
                "error": "Docker Compose not found (tried docker compose / docker-compose)",
            }

        cmd = compose_base + ["-f", compose_file]
        if project_name:
            cmd.extend(["-p", project_name])
        cmd.extend(args)

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        cwd = working_dir or str(Path(compose_file).parent)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=full_env,
                cwd=cwd,
            )
            stdout, _ = await process.communicate()
            output = stdout.decode() if stdout else ""

            return {
                "success": process.returncode == 0,
                "output": output,
                "error": output if process.returncode != 0 else None,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _resolve_local_compose_base(self) -> Optional[List[str]]:
        """Resolve local compose command base."""
        probes = (
            (["docker", "compose", "version"], ["docker", "compose"]),
            (["docker-compose", "--version"], ["docker-compose"]),
        )
        for probe, base in probes:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *probe,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0:
                    return base
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return None

    def _resolve_remote_compose_base(self, client) -> str:
        """Resolve remote compose command base."""
        probes = (
            ("docker compose version", "docker compose"),
            ("docker-compose --version", "docker-compose"),
        )
        for probe, base in probes:
            try:
                _, stdout, _ = client.exec_command(probe, timeout=20)
                exit_code = stdout.channel.recv_exit_status()
                if exit_code == 0:
                    return base
            except Exception:
                continue
        raise RuntimeError(
            "Docker Compose not found on remote device (tried docker compose / docker-compose)"
        )

    # ============================================
    # Remote Docker Management (SSH)
    # ============================================

    def _get_ssh_client(self, connection: ConnectDeviceRequest):
        """Create and connect an SSH client

        Raises:
            paramiko.AuthenticationException: If authentication fails
            paramiko.SSHException: If SSH connection fails
            OSError: If network connection fails
        """
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=connection.host,
                port=connection.port,
                username=connection.username,
                password=connection.password,
                timeout=10,
            )
            return client
        except paramiko.AuthenticationException:
            raise RuntimeError(
                f"Authentication failed for {connection.username}@{connection.host}. "
                "Please check your username and password."
            )
        except paramiko.SSHException as e:
            raise RuntimeError(f"SSH connection error: {e}")
        except OSError as e:
            raise RuntimeError(
                f"Cannot connect to {connection.host}:{connection.port}. "
                f"Network error: {e}"
            )

    def _exec_command(self, client, command: str, timeout: int = 30) -> str:
        """Execute a command and return stdout"""
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8").strip()
        if exit_code != 0:
            error = stderr.read().decode("utf-8").strip()
            raise RuntimeError(f"Command failed (exit {exit_code}): {error or output}")
        return output

    async def connect(self, connection: ConnectDeviceRequest) -> DeviceInfo:
        """Test SSH connection and verify Docker is installed"""
        try:
            client = self._get_ssh_client(connection)
            try:
                # Get Docker version
                docker_version = self._exec_command(client, "docker --version")

                # Get hostname
                hostname = self._exec_command(client, "hostname")

                # Get OS info
                try:
                    os_info = self._exec_command(
                        client, "cat /etc/os-release | head -2"
                    )
                except Exception:
                    os_info = ""

                return DeviceInfo(
                    hostname=hostname,
                    docker_version=docker_version.replace("Docker version ", "").split(
                        ","
                    )[0],
                    os_info=os_info,
                )
            finally:
                client.close()

        except ImportError:
            raise RuntimeError("SSH library (paramiko) not installed")
        except Exception as e:
            logger.error(f"Connection failed to {connection.host}: {e}")
            raise RuntimeError(f"Connection failed: {str(e)}")

    async def list_containers(
        self, connection: ConnectDeviceRequest
    ) -> List[ContainerInfo]:
        """List all Docker containers on the device"""
        try:
            client = self._get_ssh_client(connection)
            try:
                # Get container list in JSON format with labels
                output = self._exec_command(
                    client,
                    'docker ps -a --format \'{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","ports":"{{.Ports}}","labels":"{{.Labels}}"}\'',
                )

                containers = []
                if not output:
                    return containers

                for line in output.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        image = data.get("image", "")
                        # Parse image:tag
                        if ":" in image:
                            image_name, tag = image.rsplit(":", 1)
                        else:
                            image_name = image
                            tag = "latest"

                        # Determine status
                        raw_status = data.get("status", "").lower()
                        if "up" in raw_status:
                            status = "running"
                        elif "exited" in raw_status:
                            status = "exited"
                        else:
                            status = "stopped"

                        # Parse ports
                        ports_str = data.get("ports", "")
                        ports = (
                            [p.strip() for p in ports_str.split(",") if p.strip()]
                            if ports_str
                            else []
                        )

                        # Parse labels
                        labels_str = data.get("labels", "")
                        labels = {}
                        if labels_str:
                            for pair in labels_str.split(","):
                                if "=" in pair:
                                    k, v = pair.split("=", 1)
                                    labels[k] = v

                        containers.append(
                            ContainerInfo(
                                container_id=data.get("id", ""),
                                name=data.get("name", ""),
                                image=image_name,
                                current_tag=tag,
                                status=status,
                                ports=ports,
                                labels=labels,
                            )
                        )
                    except json.JSONDecodeError:
                        continue

                return containers
            finally:
                client.close()

        except ImportError:
            raise RuntimeError("SSH library (paramiko) not installed")
        except Exception as e:
            logger.error(f"Failed to list containers on {connection.host}: {e}")
            raise RuntimeError(f"Failed to list containers: {str(e)}")

    async def list_managed_apps(
        self, connection: ConnectDeviceRequest
    ) -> List[ManagedApp]:
        """List only SenseCraft-managed applications on the device, grouped by solution"""
        containers = await self.list_containers(connection)
        return self._group_containers_by_solution(containers)

    async def upgrade(self, request: UpgradeRequest) -> Dict[str, Any]:
        """Upgrade a container using docker compose pull + up"""
        connection = ConnectDeviceRequest(
            host=request.host,
            port=request.port,
            username=request.username,
            password=request.password,
        )

        try:
            client = self._get_ssh_client(connection)
            try:
                compose_base = self._resolve_remote_compose_base(client)
                # Pull new images
                compose_dir = (
                    request.compose_path.rsplit("/", 1)[0]
                    if "/" in request.compose_path
                    else "."
                )
                project_flag = (
                    f"-p {request.project_name}" if request.project_name else ""
                )

                pull_output = self._exec_command(
                    client,
                    f"cd {compose_dir} && {compose_base} {project_flag} pull",
                    timeout=120,
                )

                # Recreate containers
                up_output = self._exec_command(
                    client,
                    f"cd {compose_dir} && {compose_base} {project_flag} up -d",
                    timeout=60,
                )

                return {
                    "success": True,
                    "message": "Container upgraded successfully",
                    "pull_output": pull_output,
                    "up_output": up_output,
                }
            finally:
                client.close()

        except ImportError:
            raise RuntimeError("SSH library (paramiko) not installed")
        except Exception as e:
            logger.error(f"Upgrade failed on {request.host}: {e}")
            raise RuntimeError(f"Upgrade failed: {str(e)}")

    async def container_action(
        self,
        connection: ConnectDeviceRequest,
        container_name: str,
        action: str,
    ) -> Dict[str, Any]:
        """Perform action on a container (start/stop/restart/remove)"""
        if action not in ("start", "stop", "restart", "remove"):
            raise ValueError(f"Invalid action: {action}")

        try:
            client = self._get_ssh_client(connection)
            try:
                if action == "remove":
                    # First stop, then remove
                    try:
                        self._exec_command(
                            client, f"docker stop {container_name}", timeout=30
                        )
                    except Exception:
                        pass  # Container might already be stopped
                    output = self._exec_command(
                        client, f"docker rm {container_name}", timeout=30
                    )
                else:
                    output = self._exec_command(
                        client,
                        f"docker {action} {container_name}",
                        timeout=30,
                    )

                action_past = "removed" if action == "remove" else f"{action}ed"
                return {
                    "success": True,
                    "message": f"Container {container_name} {action_past} successfully",
                    "output": output,
                }
            finally:
                client.close()

        except Exception as e:
            logger.error(f"Container action {action} failed: {e}")
            raise RuntimeError(f"Action failed: {str(e)}")

    async def remove_app(
        self,
        connection: ConnectDeviceRequest,
        solution_id: str,
        container_names: List[str],
        remove_images: bool = False,
        remove_volumes: bool = False,
    ) -> Dict[str, Any]:
        """Remove all containers for an app on remote device, optionally removing images and volumes"""
        results = []
        images_to_remove = []
        project_names = set()

        try:
            client = self._get_ssh_client(connection)
            try:
                # Get container info before removing (to get image references and project name)
                containers = await self.list_containers(connection)
                for c in containers:
                    if c.name in container_names:
                        if remove_images:
                            images_to_remove.append(f"{c.image}:{c.current_tag}")
                        # Get compose project name from container labels
                        if c.labels.get("com.docker.compose.project"):
                            project_names.add(c.labels["com.docker.compose.project"])

                # Remove containers
                for container_name in container_names:
                    try:
                        try:
                            self._exec_command(
                                client, f"docker stop {container_name}", timeout=30
                            )
                        except Exception:
                            pass
                        self._exec_command(
                            client, f"docker rm {container_name}", timeout=30
                        )
                        results.append({"container": container_name, "success": True})
                    except Exception as e:
                        results.append(
                            {
                                "container": container_name,
                                "success": False,
                                "error": str(e),
                            }
                        )

                # Remove images if requested
                images_removed = []
                images_skipped = []
                if remove_images and images_to_remove:
                    for image in set(images_to_remove):
                        try:
                            # Check if image is used by other containers
                            check_output = self._exec_command(
                                client,
                                f"docker ps -a --filter ancestor={image} --format '{{{{.Names}}}}'",
                                timeout=10,
                            )
                            remaining = [
                                n for n in check_output.strip().split("\n") if n
                            ]
                            if remaining:
                                images_skipped.append(
                                    {
                                        "image": image,
                                        "reason": f"used by: {', '.join(remaining)}",
                                    }
                                )
                                continue

                            self._exec_command(
                                client, f"docker rmi {image}", timeout=60
                            )
                            images_removed.append(image)
                        except Exception as e:
                            images_skipped.append({"image": image, "reason": str(e)})

                # Remove volumes if requested
                volumes_removed = []
                volumes_skipped = []
                if remove_volumes:
                    try:
                        # List all volumes and filter by project_name pattern
                        output = self._exec_command(
                            client, "docker volume ls --format '{{.Name}}'", timeout=10
                        )
                        all_volumes = [v for v in output.strip().split("\n") if v]

                        # Build list of prefixes to match
                        prefixes = list(project_names) if project_names else []
                        # Fallback to solution_id patterns if no project_name found
                        if not prefixes:
                            prefixes = [solution_id, solution_id.replace("-", "_")]

                        solution_volumes = [
                            v
                            for v in all_volumes
                            if any(v.startswith(f"{prefix}_") for prefix in prefixes)
                        ]

                        for volume in solution_volumes:
                            try:
                                self._exec_command(
                                    client, f"docker volume rm {volume}", timeout=30
                                )
                                volumes_removed.append(volume)
                            except Exception as e:
                                volumes_skipped.append(
                                    {"volume": volume, "reason": str(e)}
                                )
                    except Exception as e:
                        logger.warning(f"Failed to list volumes: {e}")

                return {
                    "success": all(r["success"] for r in results),
                    "containers": results,
                    "images_removed": images_removed,
                    "images_skipped": images_skipped,
                    "volumes_removed": volumes_removed,
                    "volumes_skipped": volumes_skipped,
                }
            finally:
                client.close()

        except Exception as e:
            logger.error(f"Remove app failed: {e}")
            raise RuntimeError(f"Remove app failed: {str(e)}")

    async def prune_images(self, connection: ConnectDeviceRequest) -> Dict[str, Any]:
        """Remove all unused Docker images on remote device"""
        try:
            client = self._get_ssh_client(connection)
            try:
                output = self._exec_command(
                    client, "docker image prune -af", timeout=120
                )

                # Parse output to get space reclaimed
                space_reclaimed = "0B"
                for line in output.split("\n"):
                    if "Total reclaimed space:" in line:
                        space_reclaimed = line.split(":")[-1].strip()
                        break

                return {
                    "success": True,
                    "message": f"Pruned unused images, reclaimed {space_reclaimed}",
                    "output": output,
                    "space_reclaimed": space_reclaimed,
                }
            finally:
                client.close()

        except Exception as e:
            logger.error(f"Remote image prune failed: {e}")
            raise RuntimeError(f"Prune failed: {str(e)}")

    # ============================================
    # Remote Configuration Management
    # ============================================

    async def update_remote_app_config(
        self,
        connection: ConnectDeviceRequest,
        solution_id: str,
        values: Dict[str, str],
    ) -> Dict[str, Any]:
        """Update configuration for a remotely deployed Docker app via SSH.

        Similar to update_app_config but operates over SSH.
        """
        from ..utils.template import substitute

        manifests_dir = self._get_manifests_dir(solution_id)
        if not manifests_dir.exists():
            raise RuntimeError(f"No config manifest found for {solution_id}")

        results = []
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                manifest = json.loads(manifest_file.read_text())
                device_type = manifest.get("device_type", "docker_remote")

                if device_type not in ("docker_remote",):
                    continue

                config_file = manifest.get("config_file")
                device_id = manifest.get("device_id")

                if not config_file:
                    continue

                # Load device YAML
                from .solution_manager import solution_manager

                config = await solution_manager.load_device_config(
                    solution_id, config_file
                )
                if not config:
                    continue

                docker_config = config.docker_remote or config.docker
                if not docker_config:
                    continue

                project_name = docker_config.options.get("project_name", "provisioning")

                # Build new env
                context = {}
                for field in manifest.get("fields", []):
                    field_id = field["id"]
                    context[field_id] = values.get(
                        field_id, field.get("current_value", "")
                    )

                env_vars = {}
                for k, v in docker_config.environment.items():
                    env_vars[k] = substitute(str(v), context) or ""

                # Build env string for SSH command
                env_str = " ".join(f"{k}={v}" for k, v in env_vars.items())

                # Determine remote compose path
                remote_base = getattr(docker_config, "remote_path", "/opt/provisioning")
                compose_filename = Path(docker_config.compose_file).name
                remote_compose = f"{remote_base}/{compose_filename}"

                client = self._get_ssh_client(connection)
                try:
                    compose_base = self._resolve_remote_compose_base(client)
                    cmd = f"cd {remote_base} && {env_str} {compose_base} -p {project_name} -f {remote_compose} up -d"
                    output = self._exec_command(client, cmd, timeout=60)

                    # Update manifest
                    for field in manifest.get("fields", []):
                        field_id = field["id"]
                        if field_id in values:
                            field["current_value"] = values[field_id]

                    manifest_file.write_text(
                        json.dumps(manifest, indent=2, ensure_ascii=False)
                    )

                    results.append({"device_id": device_id, "success": True})
                finally:
                    client.close()

            except Exception as e:
                logger.error(f"Failed to reconfigure remote {manifest_file.stem}: {e}")
                results.append(
                    {
                        "device_id": manifest_file.stem,
                        "success": False,
                        "error": str(e),
                    }
                )

        success = all(r.get("success") for r in results) if results else False
        return {"success": success, "results": results}


# Global instance
docker_device_manager = DockerDeviceManager()
