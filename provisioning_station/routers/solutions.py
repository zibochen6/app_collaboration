"""
Solution management API routes
"""

from pathlib import Path
from typing import Dict, List, Optional

import markdown
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..models.api import (
    DeployInfoResponse,
    DeployParameter,
    DeployStepInfo,
    SolutionCreate,
    SolutionDetail,
    SolutionSummary,
    SolutionUpdate,
)
from ..models.solution import DeviceGroupSection
from ..services.solution_manager import solution_manager

router = APIRouter(prefix="/api/solutions", tags=["solutions"])


async def load_device_group_section(
    solution_id: str,
    section: DeviceGroupSection,
    selected_device: Optional[str],
    lang: str,
) -> dict:
    """Load section with template variable replacement"""
    result = {
        "title": (
            section.title_zh if lang == "zh" and section.title_zh else section.title
        ),
    }

    # Select language-specific template file
    template_file = (
        section.description_file_zh
        if lang == "zh" and section.description_file_zh
        else section.description_file
    )
    if not template_file:
        return result

    # Load template content (raw markdown, no HTML conversion yet)
    template_content = await solution_manager.load_markdown(
        solution_id, template_file, convert_to_html=False
    )
    if not template_content:
        return result

    # Replace template variables
    if section.variables and selected_device:
        for var_name, device_files in section.variables.items():
            placeholder = "{{" + var_name + "}}"
            if placeholder in template_content:
                # Get content file for this device
                content_file = device_files.get(selected_device)
                if content_file:
                    # Try language-specific version first
                    if lang == "zh":
                        zh_file = content_file.replace(".md", "_zh.md")
                        content = await solution_manager.load_markdown(
                            solution_id, zh_file, convert_to_html=False
                        )
                        if not content:
                            content = await solution_manager.load_markdown(
                                solution_id, content_file, convert_to_html=False
                            )
                    else:
                        content = await solution_manager.load_markdown(
                            solution_id, content_file, convert_to_html=False
                        )
                    template_content = template_content.replace(
                        placeholder, content or ""
                    )
                else:
                    # No content for this device, clear the placeholder
                    template_content = template_content.replace(placeholder, "")

    # Convert final content to HTML
    md = markdown.Markdown(extensions=["extra", "codehilite", "toc"])
    result["description"] = md.convert(template_content)

    return result


async def load_preset_section(
    solution_id: str,
    section: DeviceGroupSection,
    selections: dict,
    lang: str,
) -> dict:
    """Load preset section with template variable replacement based on selections.

    For preset sections, variables map to device_group selections.
    E.g. variables: {server_config: {server_high: file1.md, server_low: file2.md}}
    The key in selections that matches determines which file to use.
    """
    result = {
        "title": (
            section.title_zh if lang == "zh" and section.title_zh else section.title
        ),
    }

    # Select language-specific template file
    template_file = (
        section.description_file_zh
        if lang == "zh" and section.description_file_zh
        else section.description_file
    )
    if not template_file:
        return result

    # Load template content (raw markdown, no HTML conversion yet)
    template_content = await solution_manager.load_markdown(
        solution_id, template_file, convert_to_html=False
    )
    if not template_content:
        return result

    # Replace template variables using selections
    if section.variables:
        for var_name, device_files in section.variables.items():
            placeholder = "{{" + var_name + "}}"
            if placeholder in template_content:
                # Find which selection value matches a key in device_files
                content_file = None
                for group_id, selected_device in selections.items():
                    if selected_device in device_files:
                        content_file = device_files[selected_device]
                        break

                if content_file:
                    # Try language-specific version first
                    if lang == "zh":
                        zh_file = content_file.replace(".md", "_zh.md")
                        content = await solution_manager.load_markdown(
                            solution_id, zh_file, convert_to_html=False
                        )
                        if not content:
                            content = await solution_manager.load_markdown(
                                solution_id, content_file, convert_to_html=False
                            )
                    else:
                        content = await solution_manager.load_markdown(
                            solution_id, content_file, convert_to_html=False
                        )
                    template_content = template_content.replace(
                        placeholder, content or ""
                    )
                else:
                    template_content = template_content.replace(placeholder, "")

    # Convert final content to HTML
    md = markdown.Markdown(extensions=["extra", "codehilite", "toc"])
    result["description"] = md.convert(template_content)

    return result


@router.get("/", response_model=List[SolutionSummary])
async def list_solutions(
    category: Optional[str] = None,
    solution_type: Optional[str] = None,
    lang: str = Query("en", pattern="^(en|zh)$"),
    include_disabled: bool = Query(
        False, description="Include disabled solutions (for management UI)"
    ),
):
    """List all available solutions"""
    solutions = solution_manager.get_all_solutions()

    result = []
    for solution in solutions:
        # Filter disabled solutions unless include_disabled is True
        if not include_disabled and not solution.enabled:
            continue

        if category and solution.intro.category != category:
            continue

        if solution_type and solution.intro.solution_type != solution_type:
            continue

        # Check file existence for management UI
        base_path = Path(solution.base_path) if solution.base_path else None
        has_description = (
            base_path and (base_path / solution.intro.description_file).exists()
            if solution.intro.description_file
            else False
        )
        has_description_zh = (
            base_path and (base_path / solution.intro.description_file_zh).exists()
            if solution.intro.description_file_zh
            else False
        )
        has_guide = (
            base_path and (base_path / solution.deployment.guide_file).exists()
            if solution.deployment.guide_file
            else False
        )
        has_guide_zh = (
            base_path and (base_path / solution.deployment.guide_file_zh).exists()
            if solution.deployment.guide_file_zh
            else False
        )

        summary = SolutionSummary(
            id=solution.id,
            name=solution.name,  # Always return original values for management
            name_zh=solution.name_zh,
            summary=solution.intro.summary,  # Always return original values
            summary_zh=solution.intro.summary_zh,
            category=solution.intro.category,
            solution_type=solution.intro.solution_type,
            tags=solution.intro.tags,
            cover_image=(
                f"/api/solutions/{solution.id}/assets/{solution.intro.cover_image}"
                if solution.intro.cover_image
                else None
            ),
            difficulty=solution.intro.stats.difficulty,
            estimated_time=solution.intro.stats.estimated_time,
            deployed_count=solution.intro.stats.deployed_count,
            likes_count=solution.intro.stats.likes_count,
            device_count=await solution_manager.count_steps_from_guide(solution.id),
            enabled=solution.enabled,
            has_description=has_description,
            has_description_zh=has_description_zh,
            has_guide=has_guide,
            has_guide_zh=has_guide_zh,
        )
        result.append(summary)

    return result


@router.get("/{solution_id}", response_model=SolutionDetail)
async def get_solution(
    solution_id: str,
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """Get detailed solution information"""
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # Load description from markdown file
    description = None
    description_zh = None
    if solution.intro.description_file:
        description = await solution_manager.load_markdown(
            solution_id, solution.intro.description_file
        )
    if solution.intro.description_file_zh:
        description_zh = await solution_manager.load_markdown(
            solution_id, solution.intro.description_file_zh
        )

    # Build gallery URLs
    gallery = []
    for item in solution.intro.gallery:
        gallery_item = item.model_dump()
        gallery_item["src"] = f"/api/solutions/{solution_id}/assets/{item.src}"
        if item.thumbnail:
            gallery_item["thumbnail"] = (
                f"/api/solutions/{solution_id}/assets/{item.thumbnail}"
            )
        gallery.append(gallery_item)

    # Build devices summary from guide.md or solution.yaml
    devices = []
    all_preset_devices = await solution_manager.get_all_devices_async(solution_id)
    for device in all_preset_devices:
        device_id = device.get("id") if isinstance(device, dict) else device.id
        device_name = device.get("name") if isinstance(device, dict) else device.name
        device_name_zh = (
            device.get("name_zh") if isinstance(device, dict) else device.name_zh
        )
        device_type = device.get("type") if isinstance(device, dict) else device.type
        device_required = (
            device.get("required", True)
            if isinstance(device, dict)
            else device.required
        )
        devices.append(
            {
                "id": device_id,
                "name": (
                    device_name if lang == "en" else (device_name_zh or device_name)
                ),
                "name_zh": device_name_zh,
                "type": device_type,
                "required": device_required,
            }
        )

    # Build required devices with image URLs (legacy)
    required_devices = []
    for device in solution.intro.required_devices:
        dev = device.model_dump()
        if device.image:
            dev["image"] = f"/api/solutions/{solution_id}/assets/{device.image}"
        required_devices.append(dev)

    # Build device catalog by merging global catalog with local overrides
    global_catalog = solution_manager.get_global_device_catalog()
    device_catalog = {}

    # Helper function to resolve device info
    def resolve_device_info(device_id: str, local_device=None) -> dict:
        """Merge global device info with local overrides"""
        result = {}
        # Start with global catalog info
        if device_id in global_catalog:
            result = dict(global_catalog[device_id])
        # Override with local device catalog
        if local_device:
            local_data = (
                local_device.model_dump()
                if hasattr(local_device, "model_dump")
                else dict(local_device)
            )
            for key, value in local_data.items():
                if value is not None:
                    result[key] = value
        # Convert local image paths to URLs
        if result.get("image") and not result["image"].startswith("http"):
            result["image"] = f"/api/solutions/{solution_id}/assets/{result['image']}"
        return result

    # Build local device catalog entries
    for device_id, device in solution.intro.device_catalog.items():
        device_catalog[device_id] = resolve_device_info(device_id, device)

    # Helper function to resolve device group info
    def resolve_device_group(group):
        """Resolve device info for a device group"""
        group_data = group.model_dump()
        # Resolve device_ref for quantity type (check local then global)
        if group.type == "quantity" and group.device_ref:
            if group.device_ref in device_catalog:
                group_data["device_info"] = device_catalog[group.device_ref]
            elif group.device_ref in global_catalog:
                group_data["device_info"] = resolve_device_info(group.device_ref, None)
        # Resolve device_ref for options (check local then global)
        if group.options:
            resolved_options = []
            for opt in group.options:
                opt_data = opt.model_dump()
                if opt.device_ref in device_catalog:
                    opt_data["device_info"] = device_catalog[opt.device_ref]
                elif opt.device_ref in global_catalog:
                    opt_data["device_info"] = resolve_device_info(opt.device_ref, None)
                resolved_options.append(opt_data)
            group_data["options"] = resolved_options
        return group_data

    # Build presets with resolved device groups
    presets = []
    for preset in solution.intro.presets:
        preset_data = preset.model_dump()
        # Resolve device groups within each preset
        if preset.device_groups:
            preset_data["device_groups"] = [
                resolve_device_group(g) for g in preset.device_groups
            ]
        presets.append(preset_data)

    # For backward compatibility: collect all device groups from presets for top-level device_groups field
    device_groups = []
    seen_group_ids = set()
    for preset in solution.intro.presets:
        for group in preset.device_groups:
            if group.id not in seen_group_ids:
                device_groups.append(resolve_device_group(group))
                seen_group_ids.add(group.id)

    # Build partners with logo URLs
    partners = []
    for partner in solution.intro.partners:
        partner_info = {
            "name": partner.name if lang == "en" else (partner.name_zh or partner.name),
            "name_zh": partner.name_zh,
            "logo": (
                f"/api/solutions/{solution_id}/assets/{partner.logo}"
                if partner.logo
                else None
            ),
            "regions": partner.regions_en if lang == "en" else partner.regions,
            "contact": partner.contact,
            "website": partner.website,
        }
        partners.append(partner_info)

    return SolutionDetail(
        id=solution.id,
        name=solution.name if lang == "en" else (solution.name_zh or solution.name),
        name_zh=solution.name_zh,
        summary=(
            solution.intro.summary
            if lang == "en"
            else (solution.intro.summary_zh or solution.intro.summary)
        ),
        summary_zh=solution.intro.summary_zh,
        description=description if lang == "en" else (description_zh or description),
        description_zh=description_zh,
        category=solution.intro.category,
        tags=solution.intro.tags,
        cover_image=(
            f"/api/solutions/{solution_id}/assets/{solution.intro.cover_image}"
            if solution.intro.cover_image
            else None
        ),
        gallery=gallery,
        devices=devices,
        required_devices=required_devices,
        device_catalog=device_catalog,
        device_groups=device_groups,
        presets=presets,
        partners=partners,
        stats=solution.intro.stats.model_dump(),
        links={
            k: v for k, v in solution.intro.links.model_dump().items() if v is not None
        },
        deployment_order=solution.deployment.order,
        wiki_url=solution.intro.links.wiki,
    )


@router.get("/{solution_id}/deployment")
async def get_deployment_info(
    solution_id: str,
    lang: str = Query("en", pattern="^(en|zh)$"),
    use_guide: bool = Query(
        True, description="Load from guide.md (new) vs YAML (legacy)"
    ),
):
    """Get deployment page information.

    By default, loads deployment data from guide.md (simplified structure).
    Set use_guide=false to use the legacy YAML-based loading.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # New: Load deployment data from guide.md
    if use_guide:
        result = await solution_manager.get_deployment_from_guide(solution_id, lang)
        if result:
            return result
        # Fall back to YAML-based loading if guide parsing fails

    # Legacy: Load deployment guide as HTML
    guide = None
    if lang == "zh" and solution.deployment.guide_file_zh:
        guide = await solution_manager.load_markdown(
            solution_id, solution.deployment.guide_file_zh
        )
    elif solution.deployment.guide_file:
        guide = await solution_manager.load_markdown(
            solution_id, solution.deployment.guide_file
        )

    # Build device sections from presets (for backward compatibility)
    devices = []
    all_preset_devices = solution_manager.get_all_devices_from_solution(solution)
    for device in all_preset_devices:
        device_info = {
            "id": device.id,
            "name": device.name if lang == "en" else (device.name_zh or device.name),
            "name_zh": device.name_zh,
            "type": device.type,
            "required": device.required,
            "show_when": device.show_when.model_dump() if device.show_when else None,
        }

        # Load device config to get SSH settings, user_inputs, preview settings, etc.
        if device.config_file:
            config = await solution_manager.load_device_config(
                solution_id, device.config_file
            )
            if config:
                # Include SSH config for SSH-based deployments
                if config.ssh:
                    device_info["ssh"] = config.ssh.model_dump()
                # Include user_inputs for all device types
                if config.user_inputs:
                    device_info["user_inputs"] = [
                        inp.model_dump() for inp in config.user_inputs
                    ]
                # Include preview-specific settings for preview type
                if device.type == "preview":
                    device_info["preview"] = {
                        "user_inputs": (
                            [inp.model_dump() for inp in config.user_inputs]
                            if config.user_inputs
                            else []
                        ),
                        "video": config.video.model_dump() if config.video else None,
                        "mqtt": config.mqtt.model_dump() if config.mqtt else None,
                        "overlay": (
                            config.overlay.model_dump() if config.overlay else None
                        ),
                        "display": (
                            config.display.model_dump() if config.display else None
                        ),
                    }

        if device.section:
            section = device.section
            device_info["section"] = {
                "title": (
                    section.title
                    if lang == "en"
                    else (section.title_zh or section.title)
                ),
                "title_zh": section.title_zh,
            }

            # Load section description
            desc_file = (
                section.description_file_zh
                if lang == "zh"
                else section.description_file
            )
            if desc_file:
                device_info["section"]["description"] = (
                    await solution_manager.load_markdown(solution_id, desc_file)
                )

            # Load troubleshoot content (shown below deploy button)
            troubleshoot_file = (
                section.troubleshoot_file_zh
                if lang == "zh"
                else section.troubleshoot_file
            )
            if troubleshoot_file:
                device_info["section"]["troubleshoot"] = (
                    await solution_manager.load_markdown(solution_id, troubleshoot_file)
                )

            # Add wiring info
            if section.wiring:
                device_info["section"]["wiring"] = {
                    "image": (
                        f"/api/solutions/{solution_id}/assets/{section.wiring.image}"
                        if section.wiring.image
                        else None
                    ),
                    "steps": (
                        section.wiring.steps_zh
                        if lang == "zh"
                        else section.wiring.steps
                    ),
                }

        # Process targets (alternative deployment options within a device step)
        if device.targets:
            targets_data = {}
            for target_id, target in device.targets.items():
                target_info = {
                    "name": (
                        target.name if lang == "en" else (target.name_zh or target.name)
                    ),
                    "name_zh": target.name_zh,
                    "description": (
                        target.description
                        if lang == "en"
                        else (target.description_zh or target.description)
                    ),
                    "description_zh": target.description_zh,
                    "default": target.default,
                    "config_file": target.config_file,
                }
                # Load target section description
                if target.section:
                    target_section = {}
                    desc_file = (
                        target.section.description_file_zh
                        if lang == "zh"
                        else target.section.description_file
                    )
                    if desc_file:
                        target_section["description"] = (
                            await solution_manager.load_markdown(solution_id, desc_file)
                        )
                    # Load troubleshoot content
                    troubleshoot_file = (
                        target.section.troubleshoot_file_zh
                        if lang == "zh"
                        else target.section.troubleshoot_file
                    )
                    if troubleshoot_file:
                        target_section["troubleshoot"] = (
                            await solution_manager.load_markdown(
                                solution_id, troubleshoot_file
                            )
                        )
                    if target.section.wiring:
                        target_section["wiring"] = {
                            "image": (
                                f"/api/solutions/{solution_id}/assets/{target.section.wiring.image}"
                                if target.section.wiring.image
                                else None
                            ),
                            "steps": (
                                target.section.wiring.steps_zh
                                if lang == "zh"
                                else target.section.wiring.steps
                            ),
                        }
                    target_info["section"] = target_section
                targets_data[target_id] = target_info
            device_info["targets"] = targets_data

        devices.append(device_info)

    # Post deployment info
    post_deployment = {}
    if solution.deployment.post_deployment:
        pd = solution.deployment.post_deployment
        if lang == "zh" and pd.success_message_file_zh:
            post_deployment["success_message"] = await solution_manager.load_markdown(
                solution_id, pd.success_message_file_zh
            )
        elif pd.success_message_file:
            post_deployment["success_message"] = await solution_manager.load_markdown(
                solution_id, pd.success_message_file
            )

        post_deployment["next_steps"] = []
        for step in pd.next_steps:
            post_deployment["next_steps"].append(
                {
                    "title": (
                        step.title if lang == "en" else (step.title_zh or step.title)
                    ),
                    "action": step.action,
                    "url": step.url,
                }
            )

    # Helper function to build device group data with section content
    async def build_device_group_data(group):
        """Build device group data with section content"""
        group_data = group.model_dump()

        # Process section for this device group
        if group.section:
            # Get selected device (default)
            selected_device = group.default
            if group.type == "multiple" and group.default_selections:
                selected_device = group.default_selections[0]

            section_data = await load_device_group_section(
                solution_id,
                group.section,
                selected_device,
                lang,
            )
            group_data["section"] = section_data
        else:
            group_data["section"] = None

        return group_data

    # Helper function to build device info for preset.devices
    async def build_preset_device_info(device):
        """Build device info for a device reference within a preset"""
        device_info = {
            "id": device.id,
            "name": device.name if lang == "en" else (device.name_zh or device.name),
            "name_zh": device.name_zh,
            "type": device.type,
            "required": device.required,
        }

        # Load device config to get SSH settings, user_inputs, preview settings, etc.
        if device.config_file:
            config = await solution_manager.load_device_config(
                solution_id, device.config_file
            )
            if config:
                if config.ssh:
                    device_info["ssh"] = config.ssh.model_dump()
                if config.user_inputs:
                    device_info["user_inputs"] = [
                        inp.model_dump() for inp in config.user_inputs
                    ]
                if device.type == "preview":
                    device_info["preview"] = {
                        "user_inputs": (
                            [inp.model_dump() for inp in config.user_inputs]
                            if config.user_inputs
                            else []
                        ),
                        "video": config.video.model_dump() if config.video else None,
                        "mqtt": config.mqtt.model_dump() if config.mqtt else None,
                        "overlay": (
                            config.overlay.model_dump() if config.overlay else None
                        ),
                        "display": (
                            config.display.model_dump() if config.display else None
                        ),
                    }

        if device.section:
            section = device.section
            device_info["section"] = {
                "title": (
                    section.title
                    if lang == "en"
                    else (section.title_zh or section.title)
                ),
                "title_zh": section.title_zh,
            }

            desc_file = (
                section.description_file_zh
                if lang == "zh"
                else section.description_file
            )
            if desc_file:
                device_info["section"]["description"] = (
                    await solution_manager.load_markdown(solution_id, desc_file)
                )

            troubleshoot_file = (
                section.troubleshoot_file_zh
                if lang == "zh"
                else section.troubleshoot_file
            )
            if troubleshoot_file:
                device_info["section"]["troubleshoot"] = (
                    await solution_manager.load_markdown(solution_id, troubleshoot_file)
                )

            if section.wiring:
                device_info["section"]["wiring"] = {
                    "image": (
                        f"/api/solutions/{solution_id}/assets/{section.wiring.image}"
                        if section.wiring.image
                        else None
                    ),
                    "steps": (
                        section.wiring.steps_zh
                        if lang == "zh"
                        else section.wiring.steps
                    ),
                }

        # Process targets
        if device.targets:
            targets_data = {}
            for target_id, target in device.targets.items():
                target_info = {
                    "name": (
                        target.name if lang == "en" else (target.name_zh or target.name)
                    ),
                    "name_zh": target.name_zh,
                    "description": (
                        target.description
                        if lang == "en"
                        else (target.description_zh or target.description)
                    ),
                    "description_zh": target.description_zh,
                    "default": target.default,
                    "config_file": target.config_file,
                }
                if target.section:
                    target_section = {}
                    desc_file = (
                        target.section.description_file_zh
                        if lang == "zh"
                        else target.section.description_file
                    )
                    if desc_file:
                        target_section["description"] = (
                            await solution_manager.load_markdown(solution_id, desc_file)
                        )
                    troubleshoot_file = (
                        target.section.troubleshoot_file_zh
                        if lang == "zh"
                        else target.section.troubleshoot_file
                    )
                    if troubleshoot_file:
                        target_section["troubleshoot"] = (
                            await solution_manager.load_markdown(
                                solution_id, troubleshoot_file
                            )
                        )
                    if target.section.wiring:
                        target_section["wiring"] = {
                            "image": (
                                f"/api/solutions/{solution_id}/assets/{target.section.wiring.image}"
                                if target.section.wiring.image
                                else None
                            ),
                            "steps": (
                                target.section.wiring.steps_zh
                                if lang == "zh"
                                else target.section.wiring.steps
                            ),
                        }
                    target_info["section"] = target_section
                targets_data[target_id] = target_info
            device_info["targets"] = targets_data

        return device_info

    # Build presets with section content and device groups
    presets = []
    for preset in solution.intro.presets:
        preset_data = preset.model_dump()
        # Load preset section
        if preset.section:
            # Build selections from device_groups defaults for template variable replacement
            selections = {}
            for group in preset.device_groups:
                if group.type == "single" and group.default:
                    selections[group.id] = group.default
                elif group.type == "multiple" and group.default_selections:
                    selections[group.id] = group.default_selections[0]
                elif group.type == "quantity":
                    selections[group.id] = group.default_count
            section_data = await load_preset_section(
                solution_id,
                preset.section,
                selections,
                lang,
            )
            preset_data["section"] = section_data
        else:
            preset_data["section"] = None
        # Build device groups with section content
        if preset.device_groups:
            preset_data["device_groups"] = [
                await build_device_group_data(g) for g in preset.device_groups
            ]
        # Build preset-specific devices
        if preset.devices:
            preset_data["devices"] = [
                await build_preset_device_info(d) for d in preset.devices
            ]
        presets.append(preset_data)

    # For backward compatibility: collect all device groups from presets
    device_groups = []
    seen_group_ids = set()
    for preset in solution.intro.presets:
        for group in preset.device_groups:
            if group.id not in seen_group_ids:
                device_groups.append(await build_device_group_data(group))
                seen_group_ids.add(group.id)

    return {
        "solution_id": solution_id,
        "guide": guide,
        "selection_mode": solution.deployment.selection_mode,
        "devices": devices,
        "device_groups": device_groups,
        "presets": presets,
        "order": solution.deployment.order,
        "post_deployment": post_deployment,
    }


@router.get("/{solution_id}/deploy-info", response_model=DeployInfoResponse)
async def get_deploy_info(
    solution_id: str,
    lang: str = Query("en", pattern="^(en|zh)$"),
    preset_id: Optional[str] = Query(
        None, description="Filter steps for a specific preset"
    ),
):
    """AI-friendly deployment info endpoint.

    Returns all parameters needed to start a deployment, plus a ready-to-fill
    request template for POST /api/deployments/start.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    deployment_info = await solution_manager.get_deployment_from_guide(
        solution_id, lang
    )
    if not deployment_info:
        raise HTTPException(
            status_code=404, detail="Deployment guide not found for this solution"
        )

    # Build presets list
    presets = []
    for p in deployment_info.get("presets", []):
        presets.append({"id": p["id"], "name": p.get("name", p["id"])})

    # Determine which devices to include
    if preset_id:
        # Find the preset and only include its devices
        preset_device_ids = None
        for p in deployment_info.get("presets", []):
            if p["id"] == preset_id:
                preset_device_ids = set(p.get("devices", []))
                break
        if preset_device_ids is None:
            raise HTTPException(
                status_code=404, detail=f"Preset '{preset_id}' not found"
            )
    else:
        preset_device_ids = None  # Include all

    # Build steps with parameters
    steps = []
    request_template_connections = {}
    selected_devices = []

    for device in deployment_info.get("devices", []):
        device_id = device["id"]
        device_type = device.get("type", "")

        # Filter by preset if specified
        if preset_device_ids is not None and device_id not in preset_device_ids:
            continue

        selected_devices.append(device_id)

        # Check if device has targets
        targets_data = device.get("targets")
        has_targets = bool(targets_data)

        # Build step info
        step_info = DeployStepInfo(
            device_id=device_id,
            name=device.get("name", device_id),
            type=device_type,
            required=device.get("required", True),
        )

        if has_targets:
            # Build targets list and per-target parameters
            targets_list = []
            params_by_target = {}
            default_target_id = None

            for target_id, target_data in targets_data.items():
                is_default = target_data.get("default", False)
                if is_default:
                    default_target_id = target_id
                targets_list.append(
                    {
                        "id": target_id,
                        "name": target_data.get("name", target_id),
                        "default": is_default,
                    }
                )

                target_params = _extract_parameters(
                    target_data.get("user_inputs", []), lang
                )
                params_by_target[target_id] = target_params

            step_info.targets = targets_list
            step_info.parameters = params_by_target

            # Use default target for template (or first target)
            tmpl_target = default_target_id or (
                list(targets_data.keys())[0] if targets_data else None
            )
            if tmpl_target:
                request_template_connections[device_id] = _build_template_connection(
                    params_by_target.get(tmpl_target, [])
                )
            else:
                request_template_connections[device_id] = {}
        else:
            # Simple device — parameters from user_inputs
            user_inputs = device.get("user_inputs", [])
            params = _extract_parameters(user_inputs, lang)
            step_info.parameters = params
            request_template_connections[device_id] = _build_template_connection(params)

        steps.append(step_info)

    # Build request template
    request_template = {
        "solution_id": solution_id,
        "selected_devices": selected_devices,
        "device_connections": request_template_connections,
    }
    if preset_id:
        request_template["preset_id"] = preset_id
    elif presets:
        request_template["preset_id"] = presets[0]["id"]

    solution_name = solution.name
    if lang == "zh" and solution.name_zh:
        solution_name = solution.name_zh

    return DeployInfoResponse(
        solution_id=solution_id,
        solution_name=solution_name,
        presets=presets,
        steps=steps,
        request_template=request_template,
    )


def _extract_parameters(user_inputs: list, lang: str) -> List[DeployParameter]:
    """Convert user_inputs dicts to DeployParameter list."""
    params = []
    for inp in user_inputs:
        desc = inp.get("description", "")
        if lang == "zh" and inp.get("description_zh"):
            desc = inp["description_zh"]
        name = inp.get("name", "")
        if lang == "zh" and inp.get("name_zh"):
            name = inp["name_zh"]

        params.append(
            DeployParameter(
                key=inp.get("id", ""),
                type=inp.get("type", "text"),
                required=inp.get("required", False),
                default=inp.get("default"),
                description=desc or name,
                example=inp.get("placeholder"),
            )
        )
    return params


def _build_template_connection(params: List[DeployParameter]) -> dict:
    """Build a request template connection dict from parameters."""
    conn = {}
    for p in params:
        if p.default:
            conn[p.key] = p.default
        elif p.required:
            hint = p.description or p.key
            conn[p.key] = f"<REQUIRED: {hint}>"
        else:
            # Optional without default — omit from template
            pass
    return conn


@router.get("/{solution_id}/assets/{path:path}")
async def get_solution_asset(solution_id: str, path: str):
    """Serve solution asset file"""
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    asset_path = Path(solution.base_path) / path
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")

    # Set Content-Disposition: attachment for downloadable file types
    downloadable_extensions = {
        ".xlsx",
        ".xls",
        ".pdf",
        ".zip",
        ".csv",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".mp3",
        ".mp4",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
    }
    file_ext = asset_path.suffix.lower()
    if file_ext in downloadable_extensions:
        return FileResponse(
            asset_path, filename=asset_path.name, media_type="application/octet-stream"
        )

    return FileResponse(asset_path)


@router.get("/{solution_id}/device-group/{group_id}/section")
async def get_device_group_section(
    solution_id: str,
    group_id: str,
    selected_device: str = Query(..., description="Selected device ref"),
    preset_id: str = Query(None, description="Preset ID to find device group in"),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """Get device group section content with template variable replacement"""
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # Find the device group within presets
    group = None
    if preset_id:
        # Find group in specific preset
        for preset in solution.intro.presets:
            if preset.id == preset_id:
                for g in preset.device_groups:
                    if g.id == group_id:
                        group = g
                        break
                break
    else:
        # Search all presets for the group
        for preset in solution.intro.presets:
            for g in preset.device_groups:
                if g.id == group_id:
                    group = g
                    break
            if group:
                break

    if not group:
        raise HTTPException(status_code=404, detail="Device group not found")

    if not group.section:
        return {"section": None}

    section_data = await load_device_group_section(
        solution_id,
        group.section,
        selected_device,
        lang,
    )

    return {"section": section_data}


@router.get("/{solution_id}/preset/{preset_id}/section")
async def get_preset_section(
    solution_id: str,
    preset_id: str,
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """Get preset section content with template variable replacement.

    First tries to get section from guide.md parsing (preferred),
    then falls back to solution.yaml section definition.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # First, try to get preset description from guide.md
    deployment_data = await solution_manager.get_deployment_from_guide(
        solution_id, lang
    )
    if deployment_data:
        presets = deployment_data.get("presets", [])
        for p in presets:
            if p.get("id") == preset_id:
                section = p.get("section")
                if section and section.get("description"):
                    return {"section": section}

    # Fall back to solution.yaml section definition
    preset = None
    for p in solution.intro.presets:
        if p.id == preset_id:
            preset = p
            break

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    if not preset.section:
        return {"section": None}

    # Build selections from device_groups defaults
    selections = {}
    for group in preset.device_groups:
        if group.type == "single" and group.default:
            selections[group.id] = group.default
        elif group.type == "multiple" and group.default_selections:
            selections[group.id] = group.default_selections[0]
        elif group.type == "quantity":
            selections[group.id] = group.default_count

    section_data = await load_preset_section(
        solution_id,
        preset.section,
        selections,
        lang,
    )

    return {"section": section_data}


@router.get("/{solution_id}/parse-guide")
async def parse_guide(
    solution_id: str,
    path: str = Query(..., description="Path to the guide.md file"),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """Parse a bilingual deployment guide and return structured steps.

    This endpoint parses the new bilingual markdown format and returns
    the deployment steps, presets, and success content.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    result = await solution_manager.parse_deployment_guide(solution_id, path)
    if not result:
        raise HTTPException(status_code=404, detail=f"Guide file not found: {path}")

    # Convert to API response format
    response = {
        "solution_id": solution_id,
        "guide_path": path,
        "has_errors": result.has_errors,
        "errors": [
            {
                "type": str(e.error_type.value),
                "message": e.message,
                "line_number": e.line_number,
                "suggestion": e.suggestion,
            }
            for e in result.errors
        ],
        "warnings": [
            {
                "message": w.message,
                "line_number": w.line_number,
            }
            for w in result.warnings
        ],
        "overview": (
            result.overview_en
            if lang == "en"
            else (result.overview_zh or result.overview_en)
        ),
        "presets": [],
        "steps": [],
        "success": None,
    }

    # Format steps
    def format_step(step):
        return {
            "id": step.id,
            "title": (
                step.title_en if lang == "en" else (step.title_zh or step.title_en)
            ),
            "title_en": step.title_en,
            "title_zh": step.title_zh,
            "type": step.type,
            "required": step.required,
            "config_file": step.config_file,
            "section": {
                "title": (
                    step.section.title
                    if lang == "en"
                    else (step.section.title_zh or step.section.title)
                ),
                "description": (
                    step.section.description
                    if lang == "en"
                    else (step.section.description_zh or step.section.description)
                ),
                "troubleshoot": (
                    step.section.troubleshoot
                    if lang == "en"
                    else (step.section.troubleshoot_zh or step.section.troubleshoot)
                ),
                "wiring": (
                    {
                        "image": (
                            f"/api/solutions/{solution_id}/assets/{step.section.wiring.image}"
                            if step.section.wiring.image
                            else None
                        ),
                        "steps": (
                            step.section.wiring.steps
                            if lang == "en"
                            else (
                                step.section.wiring.steps_zh
                                or step.section.wiring.steps
                            )
                        ),
                    }
                    if step.section.wiring
                    else None
                ),
            },
        }

    # Format presets
    for preset in result.presets:
        preset_data = {
            "id": preset.id,
            "name": preset.name if lang == "en" else (preset.name_zh or preset.name),
            "name_en": preset.name,
            "name_zh": preset.name_zh,
            "description": (
                preset.description
                if lang == "en"
                else (preset.description_zh or preset.description)
            ),
            "steps": [format_step(s) for s in preset.steps],
        }
        response["presets"].append(preset_data)

    # Format standalone steps
    response["steps"] = [format_step(s) for s in result.steps]

    # Format success content
    if result.success:
        response["success"] = {
            "content": (
                result.success.content_en
                if lang == "en"
                else (result.success.content_zh or result.success.content_en)
            ),
        }

    return response


@router.get("/{solution_id}/bilingual-content")
async def get_bilingual_content(
    solution_id: str,
    path: str = Query(..., description="Path to the bilingual markdown file"),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    """Get content from a bilingual markdown file for the specified language.

    This endpoint loads a bilingual markdown file and returns the content
    for the requested language.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    content = await solution_manager.load_bilingual_markdown(
        solution_id, path, lang=lang, convert_to_html=True
    )
    if not content:
        raise HTTPException(status_code=404, detail=f"Bilingual file not found: {path}")

    return {
        "solution_id": solution_id,
        "path": path,
        "lang": lang,
        "content": content,
    }


@router.post("/{solution_id}/like")
async def like_solution(solution_id: str):
    """Increment likes count for a solution"""
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    # In a real app, this would persist to a database
    solution.intro.stats.likes_count += 1
    return {"likes_count": solution.intro.stats.likes_count}


@router.get("/{solution_id}/validate-guides")
async def validate_guides(solution_id: str):
    """Validate structure consistency between guide.md and guide_zh.md.

    Returns validation result with errors if EN and ZH guides have
    mismatched preset IDs, step IDs, or step parameters.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    result = await solution_manager.validate_guide_pair(solution_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to validate guides")

    return {
        "solution_id": solution_id,
        "valid": result.valid,
        "errors": [
            {
                "type": str(e.error_type.value),
                "message": e.message,
                "line_number": e.line_number,
                "suggestion": e.suggestion,
            }
            for e in result.errors
        ],
        "warnings": [
            {
                "message": w.message,
                "line_number": getattr(w, "line_number", None),
            }
            for w in result.warnings
        ],
        "en_presets": result.en_presets,
        "zh_presets": result.zh_presets,
        "en_steps_by_preset": {
            preset_id: [step[0] for step in steps]  # Extract step IDs only
            for preset_id, steps in result.en_steps_by_preset.items()
        },
    }


@router.get("/{solution_id}/guide-structure")
async def get_guide_structure(solution_id: str):
    """Get parsed structure from guide files for management UI.

    Returns file status, validation result, and parsed preset/step structure.
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    result = await solution_manager.get_guide_structure(solution_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to get guide structure")

    return result


# ============================================
# Solution Management CRUD Routes
# ============================================


@router.post("/", response_model=SolutionSummary)
async def create_solution(data: SolutionCreate):
    """Create a new solution"""
    try:
        solution = await solution_manager.create_solution(data.model_dump())

        return SolutionSummary(
            id=solution.id,
            name=solution.name,
            name_zh=solution.name_zh,
            summary=solution.intro.summary,
            summary_zh=solution.intro.summary_zh,
            category=solution.intro.category,
            tags=solution.intro.tags,
            cover_image=None,
            difficulty=solution.intro.stats.difficulty,
            estimated_time=solution.intro.stats.estimated_time,
            deployed_count=0,
            likes_count=0,
            device_count=0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create solution: {str(e)}"
        )


@router.put("/{solution_id}", response_model=SolutionSummary)
async def update_solution(solution_id: str, data: SolutionUpdate):
    """Update an existing solution"""
    try:
        # Filter out None values
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        solution = await solution_manager.update_solution(solution_id, update_data)

        return SolutionSummary(
            id=solution.id,
            name=solution.name,
            name_zh=solution.name_zh,
            summary=solution.intro.summary,
            summary_zh=solution.intro.summary_zh,
            category=solution.intro.category,
            tags=solution.intro.tags,
            cover_image=(
                f"/api/solutions/{solution.id}/assets/{solution.intro.cover_image}"
                if solution.intro.cover_image
                else None
            ),
            difficulty=solution.intro.stats.difficulty,
            estimated_time=solution.intro.stats.estimated_time,
            deployed_count=solution.intro.stats.deployed_count,
            likes_count=solution.intro.stats.likes_count,
            device_count=await solution_manager.count_steps_from_guide(solution.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update solution: {str(e)}"
        )


@router.delete("/{solution_id}")
async def delete_solution(
    solution_id: str,
    permanent: bool = Query(
        False, description="Permanently delete instead of moving to trash"
    ),
):
    """Delete a solution (moves to trash by default)"""
    try:
        await solution_manager.delete_solution(solution_id, move_to_trash=not permanent)
        return {"success": True, "message": f"Solution '{solution_id}' deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete solution: {str(e)}"
        )


@router.post("/{solution_id}/assets")
async def upload_asset(
    solution_id: str,
    file: UploadFile = File(...),
    path: str = Form(..., description="Relative path within solution directory"),
    update_field: Optional[str] = Form(
        None, description="Optional YAML field to update with this path"
    ),
):
    """Upload an asset file to a solution"""
    try:
        # Read file content
        content = await file.read()

        # Max file size: 10MB
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")

        # Save the asset
        saved_path = await solution_manager.save_asset(
            solution_id, content, path, update_yaml_field=update_field
        )

        return {
            "success": True,
            "path": saved_path,
            "url": f"/api/solutions/{solution_id}/assets/{saved_path}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload asset: {str(e)}")


# ============================================
# File Management Routes
# ============================================


@router.get("/{solution_id}/files")
async def list_files(solution_id: str):
    """List all files in the solution directory"""
    try:
        return await solution_manager.list_files(solution_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{solution_id}/files/{path:path}")
async def delete_file(solution_id: str, path: str):
    """Delete a file from the solution directory"""
    try:
        await solution_manager.delete_file(solution_id, path)
        return {"success": True, "message": f"File '{path}' deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.get("/{solution_id}/content/{path:path}")
async def get_file_content(solution_id: str, path: str):
    """Get raw text content of a file for editing"""
    try:
        content = await solution_manager.load_markdown(
            solution_id, path, convert_to_html=False
        )
        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        return Response(content=content, media_type="text/plain; charset=utf-8")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{solution_id}/files/{path:path}")
async def save_text_file(solution_id: str, path: str, data: dict):
    """Create or update a text file (md, yaml)"""
    content = data.get("content", "")
    try:
        saved_path = await solution_manager.save_text_file(solution_id, path, content)
        return {"success": True, "path": saved_path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


@router.get("/{solution_id}/structure")
async def get_solution_structure(solution_id: str):
    """Get the complete solution structure for management UI"""
    try:
        return await solution_manager.get_solution_structure(solution_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================
# Preset Management Routes
# ============================================


@router.post("/{solution_id}/presets")
async def add_preset(solution_id: str, data: Dict = None):
    """Add a new preset to the solution"""
    if data is None:
        raise HTTPException(status_code=400, detail="Request body required")
    try:
        return await solution_manager.add_preset(solution_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add preset: {str(e)}")


@router.put("/{solution_id}/presets/{preset_id}")
async def update_preset(solution_id: str, preset_id: str, data: Dict = None):
    """Update an existing preset"""
    if data is None:
        raise HTTPException(status_code=400, detail="Request body required")
    try:
        return await solution_manager.update_preset(solution_id, preset_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update preset: {str(e)}"
        )


@router.delete("/{solution_id}/presets/{preset_id}")
async def delete_preset(solution_id: str, preset_id: str):
    """Delete a preset from the solution"""
    try:
        await solution_manager.delete_preset(solution_id, preset_id)
        return {"success": True, "message": f"Preset '{preset_id}' deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete preset: {str(e)}"
        )


# ============================================
# Preset Device (Deployment Step) Routes
# ============================================


@router.post("/{solution_id}/presets/{preset_id}/devices")
async def add_preset_device(solution_id: str, preset_id: str, data: Dict = None):
    """Add a new device (deployment step) to a preset"""
    if data is None:
        raise HTTPException(status_code=400, detail="Request body required")
    try:
        return await solution_manager.add_preset_device(solution_id, preset_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add device: {str(e)}")


@router.put("/{solution_id}/presets/{preset_id}/devices/{device_id}")
async def update_preset_device(
    solution_id: str, preset_id: str, device_id: str, data: Dict = None
):
    """Update a device in a preset"""
    if data is None:
        raise HTTPException(status_code=400, detail="Request body required")
    try:
        return await solution_manager.update_preset_device(
            solution_id, preset_id, device_id, data
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update device: {str(e)}"
        )


@router.delete("/{solution_id}/presets/{preset_id}/devices/{device_id}")
async def delete_preset_device(solution_id: str, preset_id: str, device_id: str):
    """Delete a device from a preset"""
    try:
        await solution_manager.delete_preset_device(solution_id, preset_id, device_id)
        return {
            "success": True,
            "message": f"Device '{device_id}' deleted from preset '{preset_id}'",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete device: {str(e)}"
        )


# ============================================
# Solution Metadata Routes
# ============================================


@router.put("/{solution_id}/links")
async def update_solution_links(solution_id: str, data: Dict = None):
    """Update solution external links (wiki, github)"""
    if data is None:
        raise HTTPException(status_code=400, detail="Request body required")
    try:
        return await solution_manager.update_solution_links(solution_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update links: {str(e)}")


@router.put("/{solution_id}/tags")
async def update_solution_tags(solution_id: str, data: Dict = None):
    """Update solution tags"""
    if data is None or "tags" not in data:
        raise HTTPException(
            status_code=400, detail="Request body with 'tags' array required"
        )
    try:
        return await solution_manager.update_solution_tags(solution_id, data["tags"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update tags: {str(e)}")


# ============================================
# Content File Management (Simplified API)
# ============================================


@router.post("/{solution_id}/content/{filename}")
async def upload_content_file(
    solution_id: str,
    filename: str,
    data: Dict = None,
):
    """Upload a core content file (guide.md, description.md, etc.).

    This is the simplified API for the management UI. It accepts:
    - guide.md / guide_zh.md: Deployment guide files
    - description.md / description_zh.md: Introduction page files

    When a guide file is uploaded, presets are automatically synced to YAML.
    """
    if data is None or "content" not in data:
        raise HTTPException(
            status_code=400, detail="Request body with 'content' required"
        )

    try:
        saved_path = await solution_manager.save_content_file(
            solution_id, filename, data["content"]
        )
        return {"success": True, "path": saved_path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save content file: {str(e)}"
        )


@router.get("/{solution_id}/preview-structure")
async def get_preview_structure(solution_id: str):
    """Get structure preview parsed from guide.md for management UI.

    Returns the complete structure including:
    - presets with their steps
    - post-deployment content
    - validation status (EN/ZH consistency)
    - content file status
    """
    solution = solution_manager.get_solution(solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")

    result = await solution_manager.get_structure_preview(solution_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to get structure preview")

    return result


@router.put("/{solution_id}/required-devices")
async def update_required_devices(solution_id: str, data: Dict = None):
    """Update required devices from catalog IDs.

    Args:
        data: {"device_ids": ["sensecap_watcher", "recamera", ...]}

    Returns:
        {"devices": [...]} - List of updated devices
    """
    if data is None or "device_ids" not in data:
        raise HTTPException(
            status_code=400, detail="Request body with 'device_ids' array required"
        )
    try:
        devices = await solution_manager.update_required_devices(
            solution_id, data["device_ids"]
        )
        return {"devices": devices}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update required devices: {str(e)}"
        )


@router.put("/{solution_id}/enabled")
async def toggle_solution_enabled(solution_id: str, data: Dict = None):
    """Toggle solution enabled status.

    Args:
        data: {"enabled": true/false}

    Returns:
        {"enabled": bool} - Updated enabled status
    """
    if data is None or "enabled" not in data:
        raise HTTPException(
            status_code=400, detail="Request body with 'enabled' boolean required"
        )
    try:
        solution = await solution_manager.update_solution(
            solution_id, {"enabled": data["enabled"]}
        )
        return {"enabled": solution.enabled}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update enabled status: {str(e)}"
        )
