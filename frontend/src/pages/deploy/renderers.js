/**
 * Deploy Page - Rendering Functions
 * All UI rendering functions for the deployment page
 */

import { t, getLocalizedField } from '../../modules/i18n.js';
import { getAssetUrl } from '../../modules/api.js';
import { escapeHtml, processMarkdownImages } from '../../modules/utils.js';

/**
 * Process markdown content to fix image paths for current solution
 * @param {string} html - HTML content from markdown
 * @returns {string} HTML with fixed image paths
 */
function processMarkdown(html) {
  const currentSolution = getCurrentSolution();
  if (!currentSolution?.id) return html;
  return processMarkdownImages(html, currentSolution.id, getAssetUrl);
}

/**
 * Convert basic inline markdown to HTML
 * Supports: `code`, **bold**
 * @param {string} text - Plain text with markdown
 * @returns {string} HTML string
 */
function inlineMarkdown(text) {
  if (!text) return '';
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
import {
  getCurrentSolution,
  getDeviceStates,
  getDeviceState,
  getSelectedDevice,
  getSelectedPresetId,
  getDeviceGroupSelections,
  getShowDetailedLogs,
} from './state.js';
import {
  getFilteredDeviceGroups,
  getFilteredDevices,
  getSelectedTarget,
  collectPreviousInputs,
  resolveTemplate,
  getStatusClass,
  getStatusIcon,
  getStatusText,
  getButtonClass,
  getDeployButtonContent,
  getFilteredLogs,
  areAllRequiredDevicesCompleted,
} from './utils.js';

// ============================================
// Main Content Renderer
// ============================================

export function renderDeployContent(container) {
  const currentSolution = getCurrentSolution();
  const deviceStates = getDeviceStates();
  const selectedDevice = getSelectedDevice();
  const selectedPresetId = getSelectedPresetId();

  const deployment = currentSolution.deployment || {};
  const devices = deployment.devices || [];
  const presets = deployment.presets || [];
  const name = getLocalizedField(currentSolution, 'name');
  const selectionMode = deployment.selection_mode || 'sequential';

  // Check if current preset is disabled
  const selectedPreset = presets.find(p => p.id === selectedPresetId);
  const isPresetDisabled = selectedPreset?.disabled === true;

  // Render device group sections (with template-based instructions)
  const filteredDeviceGroups = getFilteredDeviceGroups(presets);
  const deviceGroupSectionsHtml = renderDeviceGroupSections(filteredDeviceGroups);

  // Check if we need preset selector (multiple presets means user can switch between them)
  const hasMultiplePresets = presets.length > 1;

  // Render preset selector and section (Level 1)
  const presetSelectorHtml = hasMultiplePresets ? renderPresetSelector(presets) : '';
  // Preset section content only if current preset has a section
  const presetSectionHtml = renderPresetSectionContent(presets);

  container.innerHTML = `
    <div class="back-btn" id="back-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      <span>${t('deploy.back')}</span>
    </div>

    <div class="deploy-page">
      <div class="page-header">
        <h1 class="page-title">${t('deploy.title')}: ${escapeHtml(name)}</h1>
        ${!hasMultiplePresets && deployment.guide ? `
          <p class="text-sm text-text-secondary mt-2">${escapeHtml(currentSolution.summary || '')}</p>
        ` : ''}
      </div>

      ${isPresetDisabled ? `
        <div class="deploy-disabled-banner">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>${t('deploy.warnings.presetDisabled')}</span>
        </div>
      ` : ''}

      ${selectionMode === 'single_choice' ? `
        <!-- Single Choice Mode: Radio options -->
        <div class="deploy-choice-section">
          <div class="deploy-choice-header">
            <h3 class="deploy-choice-title">${t('deploy.selectMode')}</h3>
            <p class="deploy-choice-desc">${t('deploy.selectModeDesc')}</p>
          </div>
          <div class="deploy-choice-options">
            ${devices.map(device => renderDeployOption(device)).join('')}
          </div>
        </div>

        <!-- Selected device details -->
        <div class="deploy-selected-section" id="selected-device-section">
          ${selectedDevice ? renderSelectedDeviceContent(devices.find(d => d.id === selectedDevice)) : ''}
        </div>
      ` : `
        <!-- Level 1: Preset Selector + Section -->
        ${presetSelectorHtml}
        ${presetSectionHtml}

        <!-- Level 2: Device Group Sections (template-based instructions) -->
        <div id="deploy-device-groups-container">
          ${deviceGroupSectionsHtml}
        </div>

        <!-- Sequential Mode: Steps -->
        <div class="deploy-sections" id="deploy-sections-container">
          ${getFilteredDevices(devices).map((device, index) => renderDeploySection(device, index + 1)).join('')}
        </div>
      `}

      <!-- Post-Deployment Success Section -->
      <div id="post-deployment-container">
        ${renderPostDeploymentSection(deployment)}
      </div>

      ${currentSolution.wiki_url ? `
        <div class="mt-6 text-center">
          <a href="${currentSolution.wiki_url}" target="_blank" class="btn btn-secondary">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
              <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
            </svg>
            ${t('deploy.viewWiki')}
          </a>
        </div>
      ` : ''}
    </div>
  `;
}

// ============================================
// Post-Deployment Success Section
// ============================================

/**
 * Render post-deployment success section
 * Only shown when all required devices are completed
 * Uses preset-level completion content if available, falls back to global post_deployment
 */
export function renderPostDeploymentSection(deployment) {
  const currentSolution = getCurrentSolution();
  const devices = deployment.devices || [];

  // Check if all required devices are completed
  const allCompleted = areAllRequiredDevicesCompleted(devices);
  if (!allCompleted) return '';

  // Get current preset's completion content (preferred)
  const selectedPresetId = getSelectedPresetId();
  const presets = deployment?.presets || [];
  const selectedPreset = presets.find(p => p.id === selectedPresetId);

  // Use preset completion if available, otherwise fall back to global post_deployment
  const postDeployment = selectedPreset?.completion || deployment?.post_deployment;
  if (!postDeployment) return '';

  const successMessage = postDeployment.success_message || '';
  const nextSteps = postDeployment.next_steps || [];

  return `
    <div class="post-deployment-section">
      <div class="post-deployment-header">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="post-deployment-icon">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
        <h2 class="post-deployment-title">${t('deploy.postDeployment.title')}</h2>
      </div>

      ${successMessage ? `
        <div class="post-deployment-content markdown-body">
          ${processMarkdown(successMessage)}
        </div>
      ` : ''}

      ${nextSteps.length > 0 ? `
        <div class="post-deployment-next-steps">
          <h3 class="post-deployment-next-steps-title">${t('deploy.postDeployment.nextSteps')}</h3>
          <div class="post-deployment-actions">
            ${nextSteps.map(step => {
              const title = getLocalizedField(step, 'title');
              const description = getLocalizedField(step, 'description');
              return `
                <a href="${step.url || '#'}" target="_blank" class="post-deployment-action-btn">
                  <span class="post-deployment-action-title">${escapeHtml(title)}</span>
                  ${description ? `<span class="post-deployment-action-desc">${escapeHtml(description)}</span>` : ''}
                </a>
              `;
            }).join('')}
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

// ============================================
// Preset Selector (Level 1)
// ============================================

/**
 * Render preset selector (Level 1 tab group)
 * Shown when multiple presets exist for switching deployment paths
 */
export function renderPresetSelector(presets) {
  const selectedPresetId = getSelectedPresetId();
  // Don't show selector for single preset
  if (presets.length <= 1) return '';

  return `
    <div class="deploy-preset-selector">
      ${presets.map(preset => {
        const isSelected = preset.id === selectedPresetId;
        const name = getLocalizedField(preset, 'name');
        const badge = getLocalizedField(preset, 'badge');
        return `
          <button class="deploy-preset-btn ${isSelected ? 'selected' : ''}"
                  data-preset-id="${preset.id}">
            ${escapeHtml(name)}
            ${badge ? `<span class="deploy-preset-badge">${escapeHtml(badge)}</span>` : ''}
          </button>
        `;
      }).join('')}
    </div>
  `;
}

/**
 * Render preset section content (Level 1 deployment guide)
 */
export function renderPresetSectionContent(presets) {
  const selectedPresetId = getSelectedPresetId();
  const selectedPreset = presets.find(p => p.id === selectedPresetId);
  if (!selectedPreset || !selectedPreset.section) return '';

  const section = selectedPreset.section;
  const title = section.title || '';
  const description = section.description || '';

  if (!description) return '';

  return `
    <div class="deploy-preset-section" id="deploy-preset-section">
      ${title ? `<h3 class="deploy-preset-section-title">${escapeHtml(title)}</h3>` : ''}
      <div class="deploy-preset-section-content markdown-content" id="deploy-preset-section-content">
        ${processMarkdown(description)}
      </div>
    </div>
  `;
}

// ============================================
// Device Group Sections (Level 2)
// ============================================

/**
 * Render device group sections with template-based instructions
 */
export function renderDeviceGroupSections(deviceGroups) {
  return deviceGroups
    .filter(group => group.section?.description)
    .map(group => {
      const section = group.section;
      const title = section.title || getLocalizedField(group, 'name');
      const hasMultipleOptions = group.options && group.options.length > 1;

      return `
        <div class="deploy-device-group-section" data-group-id="${group.id}">
          <div class="deploy-device-group-header">
            <h3 class="deploy-device-group-title">${escapeHtml(title)}</h3>
            ${hasMultipleOptions ? renderDeviceGroupSelector(group) : ''}
          </div>
          <div class="deploy-device-group-content markdown-content" id="device-group-content-${group.id}">
            ${processMarkdown(section.description)}
          </div>
        </div>
      `;
    })
    .join('');
}

/**
 * Render device selector for device group
 */
export function renderDeviceGroupSelector(group) {
  const deviceGroupSelections = getDeviceGroupSelections();
  const currentSelection = deviceGroupSelections[group.id] || group.default;

  return `
    <select class="device-group-selector" data-group-id="${group.id}">
      ${group.options.map(opt => {
        const deviceInfo = opt.device_info || {};
        const name = getLocalizedField(deviceInfo, 'name') || opt.label || opt.device_ref;
        const selected = opt.device_ref === currentSelection ? 'selected' : '';
        return `<option value="${opt.device_ref}" ${selected}>${escapeHtml(name)}</option>`;
      }).join('')}
    </select>
  `;
}

// ============================================
// Single Choice Mode Renderers
// ============================================

export function renderDeployOption(device) {
  const deviceStates = getDeviceStates();
  const selectedDevice = getSelectedDevice();
  const state = deviceStates[device.id] || {};
  const name = getLocalizedField(device, 'name');
  const section = device.section || {};
  const sectionTitle = getLocalizedField(section, 'title') || name;
  const isSelected = selectedDevice === device.id;
  const isCompleted = state.deploymentStatus === 'completed';

  // Get icon based on device type
  const icon = getDeviceTypeIcon(device.type);

  return `
    <label class="deploy-choice-option ${isSelected ? 'selected' : ''} ${isCompleted ? 'completed' : ''}"
           data-device-id="${device.id}">
      <input type="radio" name="deploy-choice" value="${device.id}"
             ${isSelected ? 'checked' : ''} ${isCompleted ? 'disabled' : ''}>
      <div class="deploy-choice-radio">
        ${isCompleted ? `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        ` : ''}
      </div>
      <div class="deploy-choice-content">
        <div class="deploy-choice-icon">${icon}</div>
        <div class="deploy-choice-info">
          <div class="deploy-choice-name">${escapeHtml(sectionTitle)}</div>
          <div class="deploy-choice-type">${escapeHtml(name)}</div>
        </div>
      </div>
      ${isCompleted ? `
        <div class="deploy-choice-status completed">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <span>${t('deploy.status.completed')}</span>
        </div>
      ` : ''}
    </label>
  `;
}

export function renderSelectedDeviceContent(device) {
  if (!device) return '';

  const currentSolution = getCurrentSolution();
  const deviceStates = getDeviceStates();
  const state = deviceStates[device.id] || {};
  const section = device.section || {};
  const sectionTroubleshoot = section.troubleshoot || '';

  // Build controls based on ui_traits
  const traits = device.ui_traits || {};
  let controls = '';

  // Serial port selector for serial connection devices
  if (traits.connection === 'serial') {
    controls += renderSerialPortSelector(device);
  }

  // Model selection
  if (traits.show_model_selection) {
    controls += renderModelSelection(device);
  }

  // SSH form for SSH connection devices
  if (traits.connection === 'ssh') {
    controls += renderSSHForm(device);
  }

  return `
    <div class="deploy-selected-card" data-device-id="${device.id}">
      <!-- Service Switch Warning -->
      ${traits.show_service_warning ? renderServiceSwitchWarning(device.type) : ''}

      <!-- Content area: wiring + description -->
      ${renderWiringSection(section.wiring, currentSolution?.id)}
      ${renderDescriptionSection(section.description)}

      <!-- Deploy controls -->
      ${controls}

      <!-- Deploy Action Area (simplified button for single_choice mode) -->
      <div class="deploy-action-area">
        <button class="deploy-action-btn ${getButtonClass(state)}"
                id="deploy-btn-${device.id}"
                data-device-id="${device.id}"
                ${state.deploymentStatus === 'running' ? 'disabled' : ''}>
          ${getDeployButtonContent(state, false)}
        </button>
      </div>

      <!-- Troubleshoot Section (shown below deploy button) -->
      ${sectionTroubleshoot ? `
        <div class="deploy-troubleshoot">
          <div class="markdown-content">${processMarkdown(sectionTroubleshoot)}</div>
        </div>
      ` : ''}

      <!-- Logs Section -->
      ${renderLogsSection(device.id, state)}
    </div>
  `;
}

// ============================================
// Sequential Mode Section Renderer
// ============================================

export function renderDeploySection(device, stepNumber) {
  const deviceStates = getDeviceStates();
  const state = deviceStates[device.id] || {};
  const name = getLocalizedField(device, 'name');
  const section = device.section || {};
  const sectionTitle = getLocalizedField(section, 'title') || name;
  const sectionDescription = section.description || '';
  const traits = device.ui_traits || {};
  const isManual = !traits.auto_deploy && !traits.renderer;
  const isScript = device.type === 'script';  // layout quirk: user_inputs before description
  const isPreview = traits.renderer === 'preview';
  const isSerialCamera = traits.renderer === 'serial-camera';
  const hasTargets = traits.has_targets && device.targets;
  const isDeviceScopeTargets = hasTargets && traits.connection_scope === 'device';
  const isTargetScopeTargets = hasTargets && traits.connection_scope === 'target';

  // For devices with targets, get troubleshoot and post_deploy from selected target's section
  let sectionTroubleshoot = section.troubleshoot || '';
  let sectionPostDeploy = section.post_deploy || '';
  if (hasTargets && device.targets) {
    const target = getSelectedTarget(device);
    if (target?.section?.troubleshoot) {
      sectionTroubleshoot = target.section.troubleshoot;
    }
    if (target?.section?.post_deploy) {
      sectionPostDeploy = target.section.post_deploy;
    }
  }
  const isCompleted = state.deploymentStatus === 'completed';

  return `
    <div class="deploy-section ${isCompleted ? 'completed' : ''}" id="section-${device.id}" data-device-id="${device.id}">
      <!-- Section Header (clickable to expand/collapse) -->
      <div class="deploy-section-header" id="section-header-${device.id}" data-device-id="${device.id}">
        <div class="deploy-section-step ${isCompleted ? 'completed' : ''}" id="step-${device.id}">
          ${isCompleted ? `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          ` : stepNumber}
        </div>
        <div class="deploy-section-info">
          <div class="deploy-section-title">${escapeHtml(sectionTitle)}</div>
          ${section.subtitle ? `<div class="deploy-section-subtitle">${escapeHtml(section.subtitle)}</div>` : ''}
        </div>
        <div class="deploy-section-status ${getStatusClass(state)}" id="status-${device.id}">
          ${getStatusIcon(state)}
          <span>${getStatusText(state)}</span>
        </div>
        <svg class="deploy-section-chevron ${state.sectionExpanded ? 'expanded' : ''}"
             id="chevron-${device.id}"
             width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </div>

      <!-- Section Content (collapsible) -->
      <div class="deploy-section-content ${state.sectionExpanded ? 'expanded' : ''}" id="content-${device.id}">
        ${isManual ? renderManualSectionContent(device, state, sectionDescription) :
          isPreview ? renderPreviewSectionContent(device, state, sectionDescription) :
          isSerialCamera ? renderSerialCameraSectionContent(device, state, sectionDescription) :
          hasTargets ? renderTargetSectionContent(device, state) :
          renderAutoSectionContent(device, state, sectionDescription, isScript)}

        <!-- Post-Deploy Section -->
        ${sectionPostDeploy ? `
          <div class="deploy-post-deploy">
            <div class="markdown-content">${processMarkdown(sectionPostDeploy)}</div>
          </div>
        ` : ''}

        <!-- Troubleshoot Section (shown below deploy button) -->
        ${sectionTroubleshoot ? `
          <div class="deploy-troubleshoot">
            <div class="markdown-content">${processMarkdown(sectionTroubleshoot)}</div>
          </div>
        ` : ''}

        <!-- Logs Section (collapsible) -->
        ${renderLogsSection(device.id, state)}
      </div>
    </div>
  `;
}

// ============================================
// Unified Rendering Architecture
// ============================================

// Legacy constants kept for reference — trait-based checks are preferred.
// SSH: device.ui_traits?.connection === 'ssh'
// Serial: device.ui_traits?.connection === 'serial'

/**
 * Render wiring section (diagram + steps)
 * Unified wiring renderer for all device types
 * @param {Object} wiring - Wiring config with image and steps
 * @param {string} solutionId - Solution ID for asset URL
 * @returns {string} HTML string
 */
export function renderWiringSection(wiring, solutionId) {
  if (!wiring) return '';

  const wiringSteps = getLocalizedField(wiring, 'steps') || [];
  if (wiringSteps.length === 0 && !wiring.image) return '';

  return `
    <div class="deploy-wiring-section">
      ${wiring.image ? `
        <div class="deploy-wiring-image">
          <img src="${getAssetUrl(solutionId, wiring.image)}" alt="Wiring diagram">
        </div>
      ` : ''}
      ${wiringSteps.length > 0 ? `
        <div class="deploy-wiring-steps">
          <ol>
            ${wiringSteps.map(step => `<li>${inlineMarkdown(step)}</li>`).join('')}
          </ol>
        </div>
      ` : ''}
    </div>
  `;
}

/**
 * Render description section (markdown content)
 * Unified description renderer for all device types
 * @param {string} description - Markdown description content
 * @returns {string} HTML string
 */
export function renderDescriptionSection(description) {
  if (!description) return '';

  return `
    <div class="deploy-pre-instructions">
      <div class="markdown-content">
        ${processMarkdown(description)}
      </div>
    </div>
  `;
}

/**
 * Render content area (wiring + description)
 * Used for all device types with targets
 * @param {Object} device - Device config
 * @param {Object} targetOverride - Optional target to use instead of selected target
 * @returns {string} HTML string
 */
export function renderContentArea(device, targetOverride = null) {
  const currentSolution = getCurrentSolution();
  const target = targetOverride || getSelectedTarget(device);

  // For devices with targets, use target section
  if (target) {
    const targetSection = target.section || {};
    return `
      ${renderWiringSection(targetSection.wiring, currentSolution?.id)}
      ${renderDescriptionSection(targetSection.description)}
    `;
  }

  // For devices without targets, use device section
  const section = device.section || {};
  return `
    ${renderWiringSection(section.wiring, currentSolution?.id)}
    ${renderDescriptionSection(section.description)}
  `;
}

/**
 * Render deploy controls (SSH form, serial port, model selection, user inputs)
 * Unified control renderer - device type only affects which controls are shown
 * @param {Object} device - Device config
 * @param {Object} options - Additional options
 * @returns {string} HTML string
 */
export function renderDeployControls(device, options = {}) {
  const { isRemote = false, target = null } = options;
  const traits = device.ui_traits || {};
  const isSSH = traits.connection === 'ssh';
  const isSerial = traits.connection === 'serial';
  const controls = [];

  // SSH form for SSH-based devices
  if (isSSH) {
    if (isRemote) {
      // Remote SSH: merge user_inputs into the SSH form
      const excludeIds = ['host', 'username', 'password', 'port'];
      const userInputsContent = target?.user_inputs
        ? renderUserInputs(device, target.user_inputs, excludeIds, true)
        : (device.user_inputs ? renderUserInputs(device, device.user_inputs, excludeIds, true) : '');
      controls.push(renderSSHForm(device, target, userInputsContent));
    } else {
      controls.push(renderSSHForm(device));
    }
  }

  // SSH form for target-scoped devices with remote target (e.g. docker_deploy)
  if (!isSSH && traits.connection_scope === 'target' && isRemote) {
    const excludeIds = ['host', 'username', 'password', 'port'];
    const userInputsContent = target?.user_inputs
      ? renderUserInputs(device, target.user_inputs, excludeIds, true)
      : '';
    controls.push(renderSSHForm(device, target, userInputsContent));
  }

  // Serial port selector
  if (isSerial) {
    controls.push(renderSerialPortSelector(device));
  }

  // Model selection
  if (traits.show_model_selection) {
    controls.push(renderModelSelection(device));
  }

  // Generic user_inputs rendering for any device type not already handled above.
  const userInputsAlreadyRendered =
    (isSSH && isRemote) ||
    isSerial ||
    (!isSSH && traits.connection_scope === 'target' && isRemote);

  if (!userInputsAlreadyRendered) {
    const inputs = target?.user_inputs || device.user_inputs;
    if (inputs) {
      // For SSH device types, exclude SSH fields (already shown in SSH form)
      if (isSSH) {
        const sshExcludeIds = ['host', 'username', 'password', 'port'];
        controls.push(renderUserInputs(device, inputs, sshExcludeIds));
      } else {
        controls.push(renderUserInputs(device, inputs));
      }
    }
  }

  return controls.join('');
}

/**
 * Render deploy action area (button with title and description)
 * Unified button renderer for all device types
 * @param {Object} device - Device config
 * @param {Object} state - Device state
 * @param {boolean} isManual - Whether this is a manual step
 * @returns {string} HTML string
 */
export function renderDeployActionArea(device, state, isManual = false) {
  const icon = isManual
    ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="9 11 12 14 22 4"/>
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
      </svg>`
    : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
        <path d="M2 17l10 5 10-5"/>
        <path d="M2 12l10 5 10-5"/>
      </svg>`;

  const title = isManual ? t('deploy.actions.manual') : t('deploy.actions.auto');
  const desc = isManual ? t('deploy.actions.manualDesc') : t('deploy.actions.autoDesc');

  return `
    <div class="deploy-action-area">
      <div class="deploy-action-title">
        ${icon}
        ${title}
      </div>
      <p class="deploy-action-desc">${desc}</p>
      <button class="deploy-action-btn ${getButtonClass(state)}"
              id="deploy-btn-${device.id}"
              data-device-id="${device.id}"
              ${state.deploymentStatus === 'running' ? 'disabled' : ''}>
        ${getDeployButtonContent(state, isManual)}
      </button>
    </div>
  `;
}

// ============================================
// Section Content Renderers (Unified Structure)
// ============================================

/**
 * Render section content for devices with targets (docker_deploy, recamera_cpp)
 * Unified structure: target selector -> warnings -> content -> controls -> action
 */
function renderTargetSectionContent(device, state) {
  const traits = device.ui_traits || {};
  const target = getSelectedTarget(device);
  const isRemote = target?.id === 'remote' || target?.id?.endsWith('_remote') || target?.id?.includes('remote');
  const stepDescription = device.section?.description || '';
  const isDeviceScope = traits.connection_scope === 'device';

  return `
    <!-- Step-level description -->
    ${renderDescriptionSection(stepDescription)}

    <!-- Target selector -->
    ${renderDockerTargetSelector(device)}

    <!-- Service Switch Warning -->
    ${traits.show_service_warning ? renderServiceSwitchWarning(device.type) : ''}

    <!-- Connection settings before content for device-scope SSH -->
    ${traits.connection === 'ssh' && isDeviceScope ? renderSSHForm(device) : ''}

    <!-- Content area (wiring + description) -->
    <div class="deploy-target-content" id="target-content-${device.id}">
      ${renderContentArea(device)}
      ${!isDeviceScope ? renderDeployControls(device, { isRemote, target }) : ''}
    </div>

    <!-- Deploy button -->
    ${renderDeployActionArea(device, state)}
  `;
}

/**
 * Render manual section content
 * Structure: wiring -> description -> mark done button
 */
function renderManualSectionContent(device, state, sectionDescription) {
  const section = device.section || {};
  return `
    ${renderWiringSection(section.wiring, getCurrentSolution()?.id)}
    ${renderDescriptionSection(sectionDescription)}
    ${renderDeployActionArea(device, state, true)}
  `;
}

/**
 * Render preview section content
 * Structure: description -> preview inputs -> preview container -> action
 */
function renderPreviewSectionContent(device, state, sectionDescription) {
  const isExternalUrl = device.preview?.video?.type === 'external_url';
  return `
    ${renderDescriptionSection(sectionDescription)}
    ${renderPreviewInputs(device)}
    ${isExternalUrl ? '' : `<div class="preview-container-wrapper" id="preview-container-${device.id}"></div>`}
    ${renderPreviewActionArea(device, state)}
  `;
}

function getPreviewActionButtonContent(state) {
  if (state.previewConnected) {
    return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="6" y="4" width="4" height="16"/>
      <rect x="14" y="4" width="4" height="16"/>
    </svg> ${t('preview.actions.disconnect')}`;
  }
  if (state.deploymentStatus === 'completed') {
    return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> ${t('deploy.status.completed')}`;
  }
  return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polygon points="5 3 19 12 5 21 5 3"/>
  </svg> ${t('preview.actions.connect')}`;
}

function renderPreviewActionArea(device, state) {
  return `
    <div class="deploy-action-area">
      <div class="deploy-action-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <polygon points="10 8 16 11 10 14 10 8"/>
          <line x1="8" y1="21" x2="16" y2="21"/>
          <line x1="12" y1="17" x2="12" y2="21"/>
        </svg>
        ${t('preview.title')}
      </div>
      <p class="deploy-action-desc">${t('preview.description')}</p>
      <button class="deploy-action-btn ${getButtonClass(state)}"
              id="deploy-btn-${device.id}"
              data-device-id="${device.id}"
              ${state.deploymentStatus === 'running' ? 'disabled' : ''}>
        ${getPreviewActionButtonContent(state)}
      </button>
    </div>
  `;
}

/**
 * Render serial camera section content
 * Structure: description -> port status -> camera container -> panel containers
 */
function renderSerialCameraSectionContent(device, state, sectionDescription) {
  const serialCamera = device.serial_camera || {};
  const cameraRef = serialCamera.camera_port?.port_from_device;
  const panels = serialCamera.panels || [];
  const deviceStates = getDeviceStates();

  // Per-component port warnings (all inside the port-status div so dynamic updater can clear them)
  const warnings = [];
  if (cameraRef) {
    const cameraPort = deviceStates[cameraRef]?.port;
    if (!cameraPort) {
      warnings.push(`<div class="port-status-warning" data-port-type="camera"><div>${escapeHtml(t('serialCamera.cameraPortMissing', { step: cameraRef }))}</div></div>`);
    }
  }

  for (const panel of panels) {
    const dbRef = panel.database_port?.port_from_device;
    if (dbRef) {
      const dbPort = deviceStates[dbRef]?.port;
      if (!dbPort) {
        warnings.push(`<div class="port-status-warning" data-port-type="crud"><div>${escapeHtml(t('serialCamera.crudPortMissing', { step: dbRef }))}</div></div>`);
      }
    }
  }

  const statusHtml = warnings.length > 0
    ? warnings.join('')
    : `<div class="port-status-ready">${t('serialCamera.portsReady')}</div>`;

  return `
    ${renderDescriptionSection(sectionDescription)}
    <div id="port-status-${device.id}">${statusHtml}</div>
    <div class="serial-camera-container-wrapper" id="serial-camera-container-${device.id}"></div>
    ${panels.length > 0 ? `<div class="serial-camera-panel-wrapper" id="serial-camera-panel-${device.id}"></div>` : ''}
  `;
}

/**
 * Render auto section content (for devices without targets)
 * Unified structure: warning -> user inputs -> description -> controls -> action
 */
function renderAutoSectionContent(device, state, sectionDescription, isScript) {
  const traits = device.ui_traits || {};
  const isSSH = traits.connection === 'ssh';
  const isSerial = traits.connection === 'serial';
  const sshExclude = ['host', 'username', 'password', 'port'];

  return `
    <!-- Service Switch Warning -->
    ${traits.show_service_warning ? renderServiceSwitchWarning(device.type) : ''}

    <!-- User Inputs (for script type, placed before description) -->
    ${isScript && device.user_inputs ? renderUserInputs(device, device.user_inputs) : ''}

    <!-- Content area: wiring + description -->
    ${renderWiringSection(device.section?.wiring, getCurrentSolution()?.id)}
    ${renderDescriptionSection(sectionDescription)}

    <!-- Deploy controls (SSH form, serial port, or generic user inputs) -->
    ${isSSH ? renderSSHForm(device) : ''}
    ${isSSH && device.user_inputs ? renderUserInputs(device, device.user_inputs, sshExclude) : ''}
    ${isSerial ? renderSerialPortSelector(device) : ''}
    ${!isScript && !isSSH && !isSerial && device.user_inputs ? renderUserInputs(device, device.user_inputs) : ''}

    <!-- Deploy button -->
    ${renderDeployActionArea(device, state)}
  `;
}

// ============================================
// Logs Section
// ============================================

function renderLogsSection(deviceId, state) {
  return `
    <div class="deploy-logs" id="logs-${deviceId}">
      <div class="deploy-logs-toggle" id="logs-toggle-${deviceId}" data-device-id="${deviceId}">
        <span class="deploy-logs-label">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          ${t('deploy.logs.title')}
          <span class="deploy-logs-count" id="logs-count-${deviceId}">${getFilteredLogs(state.logs || []).length}</span>
        </span>
        <svg class="deploy-section-chevron ${state.logsExpanded ? 'expanded' : ''}"
             id="logs-chevron-${deviceId}"
             width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </div>
      <div class="deploy-logs-panel ${state.logsExpanded ? 'expanded' : ''}" id="logs-panel-${deviceId}">
        <div class="deploy-logs-options">
          <label class="deploy-logs-detail-toggle">
            <input type="checkbox" id="detailed-logs-${deviceId}" ${getShowDetailedLogs() ? 'checked' : ''}>
            <span>${t('deploy.logs.detailed')}</span>
          </label>
        </div>
        <div class="deploy-logs-viewer" id="logs-viewer-${deviceId}">
          ${getFilteredLogs(state.logs || []).length === 0 ? `
            <div class="deploy-logs-empty">${t('deploy.logs.empty')}</div>
          ` : getFilteredLogs(state.logs || []).map(log => renderLogEntry(log)).join('')}
        </div>
      </div>
    </div>
  `;
}

export function renderLogEntry(log) {
  return `
    <div class="deploy-log-entry ${log.level}">
      <span class="time">${log.timestamp}</span>
      <span class="msg">${escapeHtml(log.message)}</span>
    </div>
  `;
}

// ============================================
// User Inputs
// ============================================

export function renderUserInputs(device, inputs, excludeIds = [], noWrapper = false) {
  if (!inputs || !inputs.length) return '';

  // Filter out excluded inputs (e.g., those already handled by SSH form)
  const filteredInputs = inputs.filter(input => !excludeIds.includes(input.id));
  if (!filteredInputs.length) return '';

  const renderSingleInput = (input, inRow = false) => {
    if (input.type === 'checkbox') {
      const isChecked = input.default === 'true' || input.default === true;
      return `
        <div class="form-group form-group-checkbox"${inRow ? ' style="min-width: 160px;"' : ''}>
          <label class="checkbox-label">
            <input
              type="checkbox"
              id="input-${device.id}-${input.id}"
              ${isChecked ? 'checked' : ''}
            />
            <span>${getLocalizedField(input, 'name')}</span>
          </label>
          ${input.description ? `<p class="text-xs text-text-muted">${getLocalizedField(input, 'description')}</p>` : ''}
        </div>
      `;
    }
    if (input.type === 'select' && input.options?.length) {
      const options = input.options.map(opt => {
        const label = getLocalizedField(opt, 'label');
        const selected = String(opt.value) === String(input.default) ? ' selected' : '';
        return `<option value="${opt.value}"${selected}>${label}</option>`;
      }).join('');
      return `
        <div class="form-group${inRow ? ' flex-1' : ''}">
          <label>${getLocalizedField(input, 'name')}</label>
          ${input.description ? `<p class="text-xs text-text-muted mb-1">${getLocalizedField(input, 'description')}</p>` : ''}
          <select
            id="input-${device.id}-${input.id}"
            ${input.required ? 'required' : ''}
          >${options}</select>
        </div>
      `;
    }
    return `
      <div class="form-group${inRow ? ' flex-1' : ''}">
        <label>${getLocalizedField(input, 'name')}</label>
        ${input.description ? `<p class="text-xs text-text-muted mb-1">${getLocalizedField(input, 'description')}</p>` : ''}
        <input
          type="${input.type === 'password' ? 'password' : 'text'}"
          id="input-${device.id}-${input.id}"
          placeholder="${input.placeholder || ''}"
          value="${input.default || ''}"
          ${input.required ? 'required' : ''}
        />
      </div>
    `;
  };

  // Group inputs by row property while preserving order
  // Inputs with same row number go in same flex row
  // Inputs without row property render as standalone
  // Order is determined by first appearance of each row/standalone item
  const rows = new Map(); // row number -> inputs[]
  const renderOrder = []; // { type: 'row', row: number } or { type: 'standalone', input }

  filteredInputs.forEach(input => {
    if (input.row !== undefined) {
      if (!rows.has(input.row)) {
        rows.set(input.row, []);
        renderOrder.push({ type: 'row', row: input.row });
      }
      rows.get(input.row).push(input);
    } else {
      renderOrder.push({ type: 'standalone', input });
    }
  });

  let content = '';

  // Render in original order
  for (const item of renderOrder) {
    if (item.type === 'row') {
      const rowInputs = rows.get(item.row);
      if (rowInputs.length > 1) {
        content += `<div class="flex gap-4 items-start">${rowInputs.map(input => renderSingleInput(input, true)).join('')}</div>`;
      } else {
        content += renderSingleInput(rowInputs[0], false);
      }
    } else {
      content += renderSingleInput(item.input, false);
    }
  }

  return noWrapper ? content : `<form class="deploy-user-inputs" onsubmit="event.preventDefault()">${content}</form>`;
}

// ============================================
// Docker Target Selector
// ============================================

/**
 * Render target selector for docker_deploy type
 * Allows user to choose between local and remote deployment
 */
export function renderDockerTargetSelector(device) {
  const deviceStates = getDeviceStates();
  const state = deviceStates[device.id] || {};
  const targets = device.targets || {};
  const selectedTarget = state.selectedTarget || 'local';

  const targetEntries = Object.entries(targets);
  if (!targetEntries.length) return '';

  return `
    <div class="deploy-mode-selector">
      <div class="deploy-mode-options">
        ${targetEntries.map(([targetId, target]) => {
          const isSelected = selectedTarget === targetId;
          const targetName = getLocalizedField(target, 'name');
          const targetDesc = getLocalizedField(target, 'description');
          const isLocal = targetId === 'local';
          let icon;
          if (device.type === 'recamera_cpp') {
            // Model variant icon (AI chip)
            icon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
                <rect x="9" y="9" width="6" height="6"/>
                <path d="M15 2v2M15 20v2M9 2v2M9 20v2M2 15h2M20 15h2M2 9h2M20 9h2"/>
              </svg>`;
          } else {
            icon = isLocal
              ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="2" y="7" width="20" height="14" rx="2"/>
                  <path d="M12 7V3M7 7V5M17 7V5"/>
                </svg>`
              : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="2" y="2" width="20" height="8" rx="2"/>
                  <rect x="2" y="14" width="20" height="8" rx="2"/>
                  <line x1="6" y1="6" x2="6.01" y2="6"/>
                  <line x1="6" y1="18" x2="6.01" y2="18"/>
                </svg>`;
          }

          return `
            <label class="deploy-mode-option ${isSelected ? 'selected' : ''}"
                   data-device-id="${device.id}"
                   data-target-id="${targetId}">
              <input type="radio" name="target-${device.id}" value="${targetId}"
                     ${isSelected ? 'checked' : ''}>
              <div class="deploy-mode-radio"></div>
              <div class="deploy-mode-icon">${icon}</div>
              <div class="deploy-mode-info">
                <div class="deploy-mode-name">${escapeHtml(targetName)}</div>
                ${targetDesc ? `<div class="deploy-mode-desc">${escapeHtml(targetDesc)}</div>` : ''}
              </div>
            </label>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

/**
 * Render content based on selected docker target
 * Uses unified content and control renderers
 */
export function renderDockerTargetContent(device) {
  const target = getSelectedTarget(device);
  if (!target) return '';

  const isRemote = target.id === 'remote' || target.id?.endsWith('_remote') || target.id?.includes('remote');

  return `
    ${renderContentArea(device)}
    ${renderDeployControls(device, { isRemote, target })}
  `;
}

/**
 * Render content based on selected recamera_cpp target
 * Uses unified content renderer (wiring + description)
 */
export function renderRecameraCppTargetContent(device) {
  return renderContentArea(device);
}

// ============================================
// SSH Form
// ============================================

export function renderSSHForm(device, mode = null, additionalContent = '') {
  const deviceStates = getDeviceStates();
  const state = deviceStates[device.id] || {};
  const conn = state.connection || {};

  // Get defaults from mode config or device config
  const defaultHost = mode?.ssh?.default_host || device.ssh?.default_host || '';
  const defaultUser = mode?.ssh?.default_user || device.ssh?.default_user || 'root';

  return `
    <form class="deploy-user-inputs" onsubmit="event.preventDefault()">
      <div class="flex gap-4">
        <div class="form-group flex-1">
          <label>${t('deploy.connection.host')}</label>
          <div class="input-with-scan">
            <input type="text" id="ssh-host-${device.id}" value="${conn.host || defaultHost}" placeholder="192.168.42.1">
            <button type="button" class="btn btn-secondary btn-scan" id="scan-mdns-${device.id}" data-device-id="${device.id}" title="${t('deploy.connection.scanHint')}">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
              </svg>
              ${t('deploy.connection.scan')}
            </button>
          </div>
          <div class="mdns-devices-dropdown" id="mdns-dropdown-${device.id}" style="display: none;"></div>
        </div>
        <div class="form-group" style="width: 100px;">
          <label>${t('deploy.connection.port')}</label>
          <input type="number" id="ssh-port-${device.id}" value="${conn.port || 22}">
        </div>
      </div>
      <div class="flex gap-4">
        <div class="form-group flex-1">
          <label>${t('deploy.connection.username')}</label>
          <input type="text" id="ssh-user-${device.id}" value="${conn.username || defaultUser}">
        </div>
        <div class="form-group flex-1">
          <label>${t('deploy.connection.password')}</label>
          <input type="password" id="ssh-pass-${device.id}" value="${conn.password || ''}">
        </div>
      </div>
      ${additionalContent}
      <button class="btn btn-secondary w-full" id="test-ssh-${device.id}" data-device-id="${device.id}">
        ${t('deploy.connection.test')}
      </button>
    </form>
  `;
}

// ============================================
// Serial Port Selector
// ============================================

export function renderSerialPortSelector(device) {
  return `
    <div class="deploy-user-inputs">
      <div class="form-group">
        <label>${t('deploy.connection.selectPort')}</label>
        <div class="flex gap-2">
          <select id="serial-port-${device.id}" class="flex-1">
            <option value="">${t('deploy.connection.selectPort')}...</option>
          </select>
          <button class="btn btn-secondary" id="refresh-ports-${device.id}" data-device-id="${device.id}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M23 4v6h-6M1 20v-6h6"/>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  `;
}

// ============================================
// Model Selection
// ============================================

/**
 * Render model selection UI for Himax devices
 */
export function renderModelSelection(device) {
  const models = device.details?.firmware?.flash_config?.models || [];
  if (!models.length) return '';

  return `
    <div class="model-selection" id="model-select-${device.id}">
      <label class="input-label">${t('deploy.models.title')}</label>
      <p class="input-desc text-xs text-text-muted mb-2">${t('deploy.models.description')}</p>
      <div class="model-list">
        ${models.map(model => {
          const modelName = getLocalizedField(model, 'name');
          const modelDesc = getLocalizedField(model, 'description');
          return `
            <label class="model-item ${model.required ? 'required' : ''}">
              <input type="checkbox"
                     name="model_${model.id}"
                     value="${model.id}"
                     data-device="${device.id}"
                     ${model.required || model.default ? 'checked' : ''}
                     ${model.required ? 'disabled' : ''}>
              <div class="model-info">
                <span class="model-name">${escapeHtml(modelName)}</span>
                ${model.size_hint ? `<span class="model-size">${model.size_hint}</span>` : ''}
                ${model.required ? `<span class="badge required">${t('deploy.models.required')}</span>` : ''}
              </div>
              ${modelDesc ? `<p class="model-desc">${escapeHtml(modelDesc)}</p>` : ''}
            </label>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

// ============================================
// Preview Inputs
// ============================================

/**
 * Render user inputs for preview step with auto-fill from previous steps
 */
export function renderPreviewInputs(device) {
  const currentSolution = getCurrentSolution();
  const preview = device.preview || {};
  const userInputs = preview.user_inputs || [];

  if (!userInputs.length) return '';

  // Get previous inputs for template resolution
  // Use filtered devices to find current device (supports preset devices)
  const deployment = currentSolution.deployment || {};
  const globalDevices = deployment.devices || [];
  const filteredDevices = getFilteredDevices(globalDevices);
  const currentIndex = filteredDevices.findIndex(d => d.id === device.id);
  const previousInputs = collectPreviousInputs(filteredDevices, currentIndex);

  // Helper to render a single input field
  const renderInput = (input, extraClass = '') => {
    let defaultValue = input.default || '';
    if (input.default_template) {
      defaultValue = resolveTemplate(input.default_template, previousInputs);
    }
    if (input.type === 'select' && input.options?.length) {
      const options = input.options.map(opt => {
        const label = getLocalizedField(opt, 'label');
        const selected = String(opt.value) === String(defaultValue) ? ' selected' : '';
        return `<option value="${opt.value}"${selected}>${label}</option>`;
      }).join('');
      return `
        <div class="form-group ${extraClass}">
          <label>${getLocalizedField(input, 'name')}</label>
          <select
            id="preview-input-${device.id}-${input.id}"
            class="preview-input"
            data-device-id="${device.id}"
            data-input-id="${input.id}"
            ${input.required ? 'required' : ''}
          >${options}</select>
        </div>
      `;
    }
    return `
      <div class="form-group ${extraClass}">
        <label>${getLocalizedField(input, 'name')}</label>
        <input
          type="${input.type === 'password' ? 'password' : 'text'}"
          id="preview-input-${device.id}-${input.id}"
          class="preview-input"
          data-device-id="${device.id}"
          data-input-id="${input.id}"
          placeholder="${input.placeholder || ''}"
          value="${escapeHtml(defaultValue)}"
          ${input.required ? 'required' : ''}
        />
      </div>
    `;
  };

  // Group inputs by row for compact layout
  const getInput = (id) => userInputs.find(i => i.id === id);
  const rtspUrl = getInput('rtsp_url');
  const mqttBroker = getInput('mqtt_broker');
  const mqttPort = getInput('mqtt_port');
  const mqttTopic = getInput('mqtt_topic');
  const mqttUsername = getInput('mqtt_username');
  const mqttPassword = getInput('mqtt_password');

  // Check if we have the expected MQTT inputs for compact layout
  const hasCompactLayout = mqttBroker && mqttPort;

  if (hasCompactLayout) {
    return `
      <form class="deploy-user-inputs preview-inputs" onsubmit="event.preventDefault()">
        ${rtspUrl ? renderInput(rtspUrl) : ''}
        <div class="flex gap-4">
          ${mqttBroker ? renderInput(mqttBroker, 'flex-1') : ''}
          ${mqttPort ? `<div class="form-group" style="width: 100px;">
            <label>${getLocalizedField(mqttPort, 'name')}</label>
            <input
              type="text"
              id="preview-input-${device.id}-${mqttPort.id}"
              class="preview-input"
              data-device-id="${device.id}"
              data-input-id="${mqttPort.id}"
              placeholder="${mqttPort.placeholder || ''}"
              value="${escapeHtml(mqttPort.default || '')}"
            />
          </div>` : ''}
        </div>
        ${mqttTopic ? renderInput(mqttTopic) : ''}
        ${(mqttUsername || mqttPassword) ? `
          <div class="flex gap-4">
            ${mqttUsername ? renderInput(mqttUsername, 'flex-1') : ''}
            ${mqttPassword ? renderInput(mqttPassword, 'flex-1') : ''}
          </div>
        ` : ''}
      </form>
    `;
  }

  // Fallback: render all inputs vertically
  return `
    <form class="deploy-user-inputs preview-inputs" onsubmit="event.preventDefault()">
      ${userInputs.map(input => renderInput(input)).join('')}
    </form>
  `;
}

// ============================================
// Service Switch Warning
// ============================================

/**
 * Render service switch warning banner.
 * Callers should check ui_traits.show_service_warning before calling.
 */
export function renderServiceSwitchWarning(deviceType) {
  const isReCamera = deviceType.startsWith('recamera_');
  const warningText = isReCamera
    ? t('deploy.warnings.recameraSwitch')
    : t('deploy.warnings.serviceSwitch');

  return `
    <div class="deploy-warning-banner">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span>${warningText}</span>
    </div>
  `;
}

// ============================================
// Device Type Icons
// ============================================

export function getDeviceTypeIcon(type) {
  switch (type) {
    case 'docker_local':
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="7" width="20" height="14" rx="2"/>
        <path d="M12 7V3M7 7V5M17 7V5"/>
      </svg>`;
    case 'docker_remote':
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="2" width="20" height="8" rx="2"/>
        <rect x="2" y="14" width="20" height="8" rx="2"/>
        <line x1="6" y1="6" x2="6.01" y2="6"/>
        <line x1="6" y1="18" x2="6.01" y2="18"/>
      </svg>`;
    case 'esp32_usb':
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="4" y="4" width="16" height="16" rx="2"/>
        <circle cx="9" cy="9" r="1"/><circle cx="15" cy="9" r="1"/>
        <circle cx="9" cy="15" r="1"/><circle cx="15" cy="15" r="1"/>
      </svg>`;
    case 'preview':
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="3" width="20" height="14" rx="2"/>
        <polygon points="10 8 16 11 10 14 10 8"/>
        <line x1="8" y1="21" x2="16" y2="21"/>
        <line x1="12" y1="17" x2="12" y2="21"/>
      </svg>`;
    case 'serial_camera':
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
        <circle cx="12" cy="13" r="4"/>
      </svg>`;
    default:
      return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
        <path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
      </svg>`;
  }
}
