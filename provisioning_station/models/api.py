"""
API request/response models
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .deployment import DeploymentStatus, StepStatus


class SolutionSummary(BaseModel):
    """Solution summary for listing"""

    id: str
    name: str
    name_zh: Optional[str] = None
    summary: str
    summary_zh: Optional[str] = None
    category: str
    solution_type: str = "solution"  # "solution" | "technical"
    tags: List[str] = []
    cover_image: Optional[str] = None
    difficulty: str = "beginner"
    estimated_time: str = "30min"
    deployed_count: int = 0
    likes_count: int = 0
    device_count: int = 0
    enabled: bool = True  # Whether solution is visible in public listing
    # File existence flags for management UI
    has_description: bool = False
    has_description_zh: bool = False
    has_guide: bool = False
    has_guide_zh: bool = False


class DeviceSummary(BaseModel):
    """Device summary"""

    id: str
    name: str
    name_zh: Optional[str] = None
    type: str
    required: bool = True


class PartnerInfo(BaseModel):
    """Deployment partner information"""

    name: str
    name_zh: Optional[str] = None
    logo: Optional[str] = None
    regions: List[str] = []  # Service regions
    contact: Optional[str] = None
    website: Optional[str] = None


class SolutionDetail(BaseModel):
    """Detailed solution information"""

    id: str
    name: str
    name_zh: Optional[str] = None
    summary: str
    summary_zh: Optional[str] = None
    description: Optional[str] = None  # Loaded from markdown file
    description_zh: Optional[str] = None
    category: str
    tags: List[str] = []
    cover_image: Optional[str] = None
    gallery: List[Dict[str, Any]] = []
    devices: List[DeviceSummary] = []
    required_devices: List[Dict[str, Any]] = []  # Legacy field
    # New device configuration system
    device_catalog: Dict[str, Dict[str, Any]] = {}
    device_groups: List[Dict[str, Any]] = []
    presets: List[Dict[str, Any]] = []
    partners: List[PartnerInfo] = []  # Deployment partners
    stats: Dict[str, Any] = {}
    links: Dict[str, str] = {}
    deployment_order: List[str] = []
    wiki_url: Optional[str] = None


class DetectedDevice(BaseModel):
    """Detected device information"""

    config_id: str
    name: str
    name_zh: Optional[str] = None
    type: str
    status: str  # detected | not_detected | manual_required | error
    connection_info: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    section: Optional[Dict[str, Any]] = None  # Deployment section info


class DeviceConnectionRequest(BaseModel):
    """Request to configure device connection"""

    ip_address: Optional[str] = None
    host: Optional[str] = None  # Alias for ip_address
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key: Optional[str] = None
    serial_port: Optional[str] = None

    @property
    def effective_host(self) -> Optional[str]:
        """Get the host, preferring 'host' over 'ip_address', with whitespace trimmed"""
        host = self.host or self.ip_address
        return host.strip() if host else None

    @property
    def effective_username(self) -> Optional[str]:
        """Get username with whitespace trimmed"""
        return self.username.strip() if self.username else None


class StartDeploymentRequest(BaseModel):
    """Request to start a deployment"""

    solution_id: str
    preset_id: Optional[str] = None  # Preset ID for new preset-based solutions
    device_connections: Dict[str, Dict[str, Any]] = {}
    options: Dict[str, Any] = {}
    selected_devices: List[str] = []  # If empty, deploy all required


class DeviceDeploymentStatus(BaseModel):
    """Device deployment status"""

    device_id: str
    name: str
    type: str
    status: DeploymentStatus
    current_step: Optional[str] = None
    steps: List[StepStatus] = []
    progress: int = 0
    error: Optional[str] = None


class DeploymentStatusResponse(BaseModel):
    """Deployment status response"""

    id: str
    solution_id: str
    status: DeploymentStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    devices: List[DeviceDeploymentStatus] = []
    overall_progress: int = 0


class LogEntryResponse(BaseModel):
    """Log entry for WebSocket"""

    timestamp: str
    level: str
    device_id: Optional[str] = None
    step_id: Optional[str] = None
    message: str


class StepSummary(BaseModel):
    """Step summary for deployment list"""

    id: str
    name: str
    status: str
    progress: int = 0


class DeploymentListItem(BaseModel):
    """Deployment list item"""

    id: str
    solution_id: str
    solution_name: str
    status: DeploymentStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    device_count: int = 0
    device_id: Optional[str] = None
    steps: List[StepSummary] = []


# ============================================
# Solution Management Models
# ============================================


class SolutionCreate(BaseModel):
    """Request model for creating a new solution"""

    id: str  # Solution ID (directory name, lowercase letters, numbers, underscore)
    name: str  # English name
    name_zh: Optional[str] = None  # Chinese name
    summary: str  # English summary
    summary_zh: Optional[str] = None  # Chinese summary
    category: str = "general"  # Category
    difficulty: str = "beginner"  # beginner | intermediate | advanced
    estimated_time: str = "30min"  # Estimated time


class SolutionUpdate(BaseModel):
    """Request model for updating an existing solution"""

    name: Optional[str] = None
    name_zh: Optional[str] = None
    summary: Optional[str] = None
    summary_zh: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_time: Optional[str] = None
    enabled: Optional[bool] = None


# ============================================
# AI-Friendly Deploy Info Models
# ============================================


class DeployParameter(BaseModel):
    """A single connection parameter for a deployment step"""

    key: str
    type: str = "text"
    required: bool = False
    default: Optional[str] = None
    description: Optional[str] = None
    example: Optional[str] = None


class DeployStepInfo(BaseModel):
    """Step info for AI-friendly deploy-info endpoint"""

    device_id: str
    name: str
    type: str
    required: bool = True
    targets: Optional[List[Dict[str, Any]]] = None
    # List[DeployParameter] for simple steps, Dict[str, List[DeployParameter]] for steps with targets
    parameters: Any = None


class DeployInfoResponse(BaseModel):
    """AI-friendly deployment info with request template"""

    solution_id: str
    solution_name: str
    presets: List[Dict[str, str]]
    steps: List[DeployStepInfo]
    request_template: Dict[str, Any]


# ============================================
# Deployment Summary Models
# ============================================


class StepSummaryInfo(BaseModel):
    """Step summary within a device deployment"""

    name: str
    status: str
    message: Optional[str] = None


class DeviceSummaryInfo(BaseModel):
    """Device deployment summary"""

    device_id: str
    status: str
    steps: List[StepSummaryInfo]
    error: Optional[str] = None


class DeploymentSummaryResponse(BaseModel):
    """Deployment summary with errors and warnings extracted from logs"""

    deployment_id: str
    solution_id: str
    status: str
    started_at: datetime
    duration_seconds: Optional[float] = None
    devices: List[DeviceSummaryInfo]
    errors: List[str]
    warnings: List[str]
