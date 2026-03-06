/**
 * Deploy Page - Preview Functionality
 * Handles preview window initialization, connection, and management
 */

import { t } from '../../modules/i18n.js';
import { getAssetUrl } from '../../modules/api.js';
import { toast } from '../../modules/toast.js';
import { PreviewWindow, fetchOverlayScript } from '../../modules/preview.js';
import { renderers } from '../../modules/overlay-renderers.js';
import {
  getCurrentSolution,
  getDeviceState,
  getPreviewInstance,
  setPreviewInstance,
} from './state.js';
import { getDeviceById, resolveTemplate, loadScript } from './utils.js';
import { updateSectionUI, expandNextSection } from './ui-updates.js';

// ============================================
// Preview Helpers
// ============================================

function collectPreviewInputs(deviceId, preview) {
  const inputs = {};
  const userInputs = preview.user_inputs || [];
  userInputs.forEach(input => {
    const el = document.getElementById(`preview-input-${deviceId}-${input.id}`);
    if (el) {
      inputs[input.id] = el.value;
    }
  });
  return inputs;
}

function normalizeExternalUrl(url) {
  const value = String(url || '').trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) {
    return value;
  }
  return `http://${value}`;
}

// ============================================
// Preview Initialization
// ============================================

/**
 * Initialize preview window for a device
 */
export async function initPreviewWindow(deviceId) {
  const device = getDeviceById(deviceId);
  if (!device || device.type !== 'preview') return;

  const preview = device.preview || {};
  if (preview.video?.type === 'external_url') return;

  const container = document.getElementById(`preview-container-${deviceId}`);
  if (!container) return;

  const currentSolution = getCurrentSolution();
  const state = getDeviceState(deviceId);

  // Create preview window
  const previewWindow = new PreviewWindow(container, {
    aspectRatio: preview.display?.aspect_ratio || '16:9',
    showStats: preview.display?.show_stats !== false,
  });

  // Set up overlay renderer
  if (preview.overlay?.script_file) {
    // Load dependencies first (e.g., simpleheat.js)
    if (preview.overlay.dependencies?.length > 0) {
      for (const dep of preview.overlay.dependencies) {
        const depUrl = getAssetUrl(currentSolution.id, dep);
        await loadScript(depUrl);
      }
    }
    // Load custom script
    const scriptUrl = getAssetUrl(currentSolution.id, preview.overlay.script_file);
    const renderer = await fetchOverlayScript(scriptUrl);
    if (renderer) {
      previewWindow.setOverlayRenderer(renderer);
    }
  } else if (preview.overlay?.renderer) {
    // Use built-in renderer
    const renderer = renderers[preview.overlay.renderer] || renderers.auto;
    previewWindow.setOverlayRenderer(renderer);
  } else {
    // Default to auto renderer
    previewWindow.setOverlayRenderer(renderers.auto);
  }

  // Handle status changes
  previewWindow.onStatus((status, message) => {
    state.previewConnected = status === 'connected';
    updatePreviewUI(deviceId);
  });

  // Handle connect button click from preview window
  container.addEventListener('preview:connect', async () => {
    await startPreview(deviceId, previewWindow);
  });

  // Store instance for cleanup
  setPreviewInstance(deviceId, previewWindow);
}

// ============================================
// Preview Connection
// ============================================

/**
 * Start preview connection
 */
export async function startPreview(deviceId, previewWindow = null) {
  const device = getDeviceById(deviceId);
  if (!device) return;

  const preview = device.preview || {};
  const state = getDeviceState(deviceId);

  // Collect inputs from the form
  const inputs = collectPreviewInputs(deviceId, preview);

  // Store inputs in state
  state.userInputs = { ...state.userInputs, ...inputs };

  // Build connection options
  const options = {};

  // Resolve RTSP URL
  if (preview.video?.rtsp_url_template) {
    options.rtspUrl = resolveTemplate(preview.video.rtsp_url_template, inputs);
  } else if (inputs.rtsp_url) {
    options.rtspUrl = inputs.rtsp_url;
  }

  if (preview.video?.type === 'external_url') {
    try {
      const targetUrl = normalizeExternalUrl(options.rtspUrl);
      if (!targetUrl) {
        throw new Error('Jetson host is required');
      }

      const parsedUrl = new URL(targetUrl);
      if (!parsedUrl.hostname || parsedUrl.hostname.includes('{')) {
        throw new Error('Invalid host or URL');
      }

      const opened = window.open(parsedUrl.toString(), '_blank');
      if (!opened) {
        throw new Error('Popup blocked by browser');
      }

      toast.success(t('preview.connected'));
    } catch (error) {
      console.error('Preview URL open failed:', error);
      toast.error(t('preview.connectionFailed') + ': ' + error.message);
    }
    return;
  }

  if (!previewWindow) {
    toast.error(t('preview.connectionFailed') + ': Preview window is not initialized');
    return;
  }

  // Resolve MQTT config
  if (preview.mqtt?.broker_template) {
    options.mqttBroker = resolveTemplate(preview.mqtt.broker_template, inputs);
  } else if (inputs.mqtt_broker) {
    options.mqttBroker = inputs.mqtt_broker;
  }

  // Resolve MQTT port
  if (preview.mqtt?.port_template) {
    options.mqttPort = parseInt(resolveTemplate(preview.mqtt.port_template, inputs)) || 1883;
  } else {
    options.mqttPort = preview.mqtt?.port || parseInt(inputs.mqtt_port) || 1883;
  }

  // Resolve MQTT topic
  if (preview.mqtt?.topic_template) {
    options.mqttTopic = resolveTemplate(preview.mqtt.topic_template, inputs);
  } else if (inputs.mqtt_topic) {
    options.mqttTopic = inputs.mqtt_topic;
  } else {
    options.mqttTopic = preview.mqtt?.topic || 'inference/results';
  }

  // Resolve MQTT credentials
  if (preview.mqtt?.username_template) {
    const username = resolveTemplate(preview.mqtt.username_template, inputs);
    if (username) {
      options.mqttUsername = username;
      options.mqttPassword = preview.mqtt?.password_template
        ? resolveTemplate(preview.mqtt.password_template, inputs)
        : (preview.mqtt?.password || inputs.mqtt_password);
    }
  } else if (preview.mqtt?.username || inputs.mqtt_username) {
    options.mqttUsername = preview.mqtt?.username || inputs.mqtt_username;
    options.mqttPassword = preview.mqtt?.password || inputs.mqtt_password;
  }

  try {
    await previewWindow.connect(options);
    toast.success(t('preview.connected'));
  } catch (error) {
    console.error('Preview connection failed:', error);
    toast.error(t('preview.connectionFailed') + ': ' + error.message);
  }
}

// ============================================
// Preview UI Updates
// ============================================

/**
 * Update preview UI elements
 */
export function updatePreviewUI(deviceId) {
  const state = getDeviceState(deviceId);
  if (!state) return;

  const btn = document.getElementById(`deploy-btn-${deviceId}`);
  if (btn) {
    btn.innerHTML = getPreviewButtonContent(state);
  }
}

/**
 * Get button content for preview step
 */
export function getPreviewButtonContent(state) {
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

// ============================================
// Preview Button Handler
// ============================================

/**
 * Handle preview button click
 */
export async function handlePreviewButtonClick(deviceId) {
  const device = getDeviceById(deviceId);
  if (!device || device.type !== 'preview') return;

  if (device.preview?.video?.type === 'external_url') {
    await startPreview(deviceId);
    return;
  }

  const state = getDeviceState(deviceId);
  const previewWindow = getPreviewInstance(deviceId);

  if (!previewWindow) {
    // Initialize preview if not done
    await initPreviewWindow(deviceId);
    return;
  }

  if (state.previewConnected) {
    // Disconnect
    await previewWindow.disconnect();
    state.previewConnected = false;
    updatePreviewUI(deviceId);
  } else {
    // Connect
    await startPreview(deviceId, previewWindow);
  }
}

// ============================================
// Preview Completion
// ============================================

/**
 * Mark preview step as complete
 */
export function markPreviewComplete(deviceId) {
  const state = getDeviceState(deviceId);
  if (state) {
    state.deploymentStatus = 'completed';
    updateSectionUI(deviceId);
    toast.success(t('deploy.status.completed'));
    expandNextSection(deviceId);
  }
}
