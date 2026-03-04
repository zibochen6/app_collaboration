"""
Application update manager service

Handles updating deployed applications:
- Pull latest Docker images
- Restart containers with new images
- Container lifecycle actions (start/stop/restart)
"""

import asyncio
import logging
from typing import Optional

from ..models.kiosk import UpdateResponse
from .deployment_history import deployment_history

logger = logging.getLogger(__name__)


class UpdateManager:
    """Manages application updates for deployments"""

    async def update_deployment(
        self,
        deployment_id: str,
        password: Optional[str] = None,
    ) -> UpdateResponse:
        """
        Update a deployed application

        This will:
        1. Pull the latest Docker image
        2. Restart the container with the new image

        Args:
            deployment_id: The deployment to update
            password: SSH password for remote deployments
        """
        try:
            # Get deployment info
            history = await deployment_history.get_history(limit=100)
            record = next(
                (r for r in history if r.deployment_id == deployment_id), None
            )

            if not record:
                return UpdateResponse(
                    success=False,
                    message="Deployment not found",
                )

            device_type = record.device_type
            metadata = record.metadata or {}

            if device_type == "docker_remote":
                # Remote update via SSH
                return await self._update_remote_docker(
                    host=metadata.get("host"),
                    username=metadata.get("username", "recomputer"),
                    password=password,
                    compose_path=metadata.get(
                        "compose_path", "/home/recomputer/missionpack_knn"
                    ),
                    project_name=metadata.get("project_name", record.solution_id),
                )
            elif device_type == "docker_local":
                # Local update
                return await self._update_local_docker(
                    compose_path=metadata.get("compose_path"),
                    project_name=metadata.get("project_name", record.solution_id),
                )
            else:
                return UpdateResponse(
                    success=False,
                    message=f"Update not supported for device type: {device_type}",
                )

        except Exception as e:
            logger.error(f"Update failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Update failed: {str(e)}",
            )

    async def container_action(
        self,
        deployment_id: str,
        action: str,
        password: Optional[str] = None,
    ) -> UpdateResponse:
        """
        Perform container lifecycle action

        Args:
            deployment_id: The deployment to act on
            action: "start" | "stop" | "restart"
            password: SSH password for remote deployments
        """
        try:
            # Get deployment info
            history = await deployment_history.get_history(limit=100)
            record = next(
                (r for r in history if r.deployment_id == deployment_id), None
            )

            if not record:
                return UpdateResponse(
                    success=False,
                    message="Deployment not found",
                )

            device_type = record.device_type
            metadata = record.metadata or {}

            if device_type == "docker_remote":
                return await self._container_action_remote(
                    host=metadata.get("host"),
                    username=metadata.get("username", "recomputer"),
                    password=password,
                    compose_path=metadata.get(
                        "compose_path", "/home/recomputer/missionpack_knn"
                    ),
                    project_name=metadata.get("project_name", record.solution_id),
                    action=action,
                )
            elif device_type == "docker_local":
                return await self._container_action_local(
                    compose_path=metadata.get("compose_path"),
                    project_name=metadata.get("project_name", record.solution_id),
                    action=action,
                )
            else:
                return UpdateResponse(
                    success=False,
                    message=f"Action not supported for device type: {device_type}",
                )

        except Exception as e:
            logger.error(f"Container action failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Action failed: {str(e)}",
            )

    async def _resolve_local_compose_base(self) -> Optional[list[str]]:
        """Resolve local compose command base: ['docker','compose'] or ['docker-compose']."""
        candidates = (
            (["docker", "compose", "version"], ["docker", "compose"]),
            (["docker-compose", "--version"], ["docker-compose"]),
        )
        for probe, base in candidates:
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

    async def _resolve_remote_compose_base(self, client) -> Optional[str]:
        """Resolve remote compose command base: 'docker compose' or 'docker-compose'."""
        candidates = (
            ("docker compose version", "docker compose"),
            ("docker-compose --version", "docker-compose"),
        )
        for probe, base in candidates:
            try:
                _, stdout, _ = await asyncio.to_thread(
                    client.exec_command, probe, timeout=30
                )
                exit_code = stdout.channel.recv_exit_status()
                if exit_code == 0:
                    return base
            except Exception:
                continue
        return None

    async def _update_local_docker(
        self,
        compose_path: Optional[str],
        project_name: str,
    ) -> UpdateResponse:
        """Update local Docker deployment"""
        try:
            # Determine working directory
            if compose_path:
                cwd = compose_path
            else:
                cwd = None

            compose_base = await self._resolve_local_compose_base()
            if not compose_base:
                return UpdateResponse(
                    success=False,
                    message="Docker Compose not found (tried docker compose / docker-compose)",
                )

            # Pull new images
            pull_cmd = compose_base.copy()
            if project_name:
                pull_cmd.extend(["-p", project_name])
            pull_cmd.append("pull")

            proc = await asyncio.create_subprocess_exec(
                *pull_cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return UpdateResponse(
                    success=False,
                    message=f"Failed to pull images: {stderr.decode()[:200]}",
                )

            # Restart with new images
            up_cmd = compose_base.copy()
            if project_name:
                up_cmd.extend(["-p", project_name])
            up_cmd.extend(["up", "-d", "--remove-orphans"])

            proc = await asyncio.create_subprocess_exec(
                *up_cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return UpdateResponse(
                    success=False,
                    message=f"Failed to restart: {stderr.decode()[:200]}",
                )

            logger.info(f"Local Docker updated: {project_name}")
            return UpdateResponse(
                success=True,
                message="Application updated successfully",
            )

        except Exception as e:
            logger.error(f"Local Docker update failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Update failed: {str(e)}",
            )

    async def _update_remote_docker(
        self,
        host: str,
        username: str,
        password: Optional[str],
        compose_path: str,
        project_name: str,
    ) -> UpdateResponse:
        """Update remote Docker deployment via SSH"""
        try:
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            await asyncio.to_thread(
                client.connect,
                hostname=host,
                port=22,
                username=username,
                password=password,
                timeout=30,
            )

            try:
                compose_base = await self._resolve_remote_compose_base(client)
                if not compose_base:
                    return UpdateResponse(
                        success=False,
                        message="Docker Compose not found on remote device (tried docker compose / docker-compose)",
                    )

                # Pull new images
                pull_cmd = f"cd {compose_path} && {compose_base} -p {project_name} pull"
                stdin, stdout, stderr = await asyncio.to_thread(
                    client.exec_command, pull_cmd, timeout=600
                )
                exit_code = stdout.channel.recv_exit_status()

                if exit_code != 0:
                    error = stderr.read().decode()[:200]
                    return UpdateResponse(
                        success=False,
                        message=f"Failed to pull images: {error}",
                    )

                # Restart with new images
                up_cmd = f"cd {compose_path} && {compose_base} -p {project_name} up -d --remove-orphans"
                stdin, stdout, stderr = await asyncio.to_thread(
                    client.exec_command, up_cmd, timeout=300
                )
                exit_code = stdout.channel.recv_exit_status()

                if exit_code != 0:
                    error = stderr.read().decode()[:200]
                    return UpdateResponse(
                        success=False,
                        message=f"Failed to restart: {error}",
                    )

                logger.info(f"Remote Docker updated: {project_name} on {host}")
                return UpdateResponse(
                    success=True,
                    message="Application updated successfully",
                )

            finally:
                client.close()

        except ImportError:
            return UpdateResponse(
                success=False,
                message="SSH library (paramiko) not installed",
            )
        except paramiko.AuthenticationException:
            return UpdateResponse(
                success=False,
                message=f"Authentication failed for {username}@{host}. Please check your credentials.",
            )
        except paramiko.SSHException as e:
            return UpdateResponse(
                success=False,
                message=f"SSH connection error: {e}",
            )
        except OSError as e:
            return UpdateResponse(
                success=False,
                message=f"Cannot connect to {host}. Network error: {e}",
            )
        except Exception as e:
            logger.error(f"Remote Docker update failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Update failed: {str(e)}",
            )

    async def _container_action_local(
        self,
        compose_path: Optional[str],
        project_name: str,
        action: str,
    ) -> UpdateResponse:
        """Perform container action on local deployment"""
        try:
            compose_base = await self._resolve_local_compose_base()
            if not compose_base:
                return UpdateResponse(
                    success=False,
                    message="Docker Compose not found (tried docker compose / docker-compose)",
                )

            cmd = compose_base.copy()
            if project_name:
                cmd.extend(["-p", project_name])

            if action == "start":
                cmd.extend(["up", "-d"])
            elif action == "stop":
                cmd.append("stop")
            elif action == "restart":
                cmd.append("restart")
            else:
                return UpdateResponse(
                    success=False,
                    message=f"Unknown action: {action}",
                )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=compose_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return UpdateResponse(
                    success=False,
                    message=f"Action failed: {stderr.decode()[:200]}",
                )

            status = "running" if action in ("start", "restart") else "stopped"
            return UpdateResponse(
                success=True,
                message=f"Container {action} successful",
                new_version=status,
            )

        except Exception as e:
            logger.error(f"Container action failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Action failed: {str(e)}",
            )

    async def _container_action_remote(
        self,
        host: str,
        username: str,
        password: Optional[str],
        compose_path: str,
        project_name: str,
        action: str,
    ) -> UpdateResponse:
        """Perform container action on remote deployment via SSH"""
        try:
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            await asyncio.to_thread(
                client.connect,
                hostname=host,
                port=22,
                username=username,
                password=password,
                timeout=30,
            )

            try:
                compose_base = await self._resolve_remote_compose_base(client)
                if not compose_base:
                    return UpdateResponse(
                        success=False,
                        message="Docker Compose not found on remote device (tried docker compose / docker-compose)",
                    )

                if action == "start":
                    compose_cmd = "up -d"
                elif action == "stop":
                    compose_cmd = "stop"
                elif action == "restart":
                    compose_cmd = "restart"
                else:
                    return UpdateResponse(
                        success=False,
                        message=f"Unknown action: {action}",
                    )

                cmd = f"cd {compose_path} && {compose_base} -p {project_name} {compose_cmd}"
                stdin, stdout, stderr = await asyncio.to_thread(
                    client.exec_command, cmd, timeout=300
                )
                exit_code = stdout.channel.recv_exit_status()

                if exit_code != 0:
                    error = stderr.read().decode()[:200]
                    return UpdateResponse(
                        success=False,
                        message=f"Action failed: {error}",
                    )

                status = "running" if action in ("start", "restart") else "stopped"
                return UpdateResponse(
                    success=True,
                    message=f"Container {action} successful",
                    new_version=status,
                )

            finally:
                client.close()

        except ImportError:
            return UpdateResponse(
                success=False,
                message="SSH library (paramiko) not installed",
            )
        except paramiko.AuthenticationException:
            return UpdateResponse(
                success=False,
                message=f"Authentication failed for {username}@{host}. Please check your credentials.",
            )
        except paramiko.SSHException as e:
            return UpdateResponse(
                success=False,
                message=f"SSH connection error: {e}",
            )
        except OSError as e:
            return UpdateResponse(
                success=False,
                message=f"Cannot connect to {host}. Network error: {e}",
            )
        except Exception as e:
            logger.error(f"Remote container action failed: {e}")
            return UpdateResponse(
                success=False,
                message=f"Action failed: {str(e)}",
            )


# Global instance
update_manager = UpdateManager()
