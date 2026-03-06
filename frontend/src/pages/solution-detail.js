/**
 * Solution Detail Page - Introduction View
 */

import { solutionsApi, getAssetUrl } from '../modules/api.js';
import { t, getLocalizedField, i18n } from '../modules/i18n.js';
import { router } from '../modules/router.js';
import { toast } from '../modules/toast.js';
import { PLACEHOLDER_IMAGE, DEVICE_PLACEHOLDER, escapeHtml, processMarkdownImages } from '../modules/utils.js';

/**
 * Process markdown content to fix image paths for current solution
 */
function processMarkdown(html) {
  if (!currentSolution?.id) return html;
  return processMarkdownImages(html, currentSolution.id, getAssetUrl);
}

let currentSolution = null;
let deviceSelections = {};
let selectedPreset = null;
let carouselTimer = null;

export async function renderSolutionDetailPage(params) {
  const { id } = params;
  const container = document.getElementById('content-area');

  // Show loading state
  container.innerHTML = `
    <div class="back-btn" id="back-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      <span data-i18n="deploy.back">${t('deploy.back')}</span>
    </div>
    <div class="solution-intro">
      <div class="skeleton skeleton-image mb-6" style="height: 256px;"></div>
      <div class="skeleton skeleton-title mb-4" style="width: 60%;"></div>
      <div class="skeleton skeleton-text mb-2"></div>
      <div class="skeleton skeleton-text mb-2"></div>
      <div class="skeleton skeleton-text" style="width: 80%;"></div>
    </div>
  `;

  try {
    currentSolution = await solutionsApi.get(id, i18n.locale);

    // Description is included in the solution response (already localized by API)
    const descriptionHtml = currentSolution.description || '';

    container.innerHTML = renderSolutionIntro(currentSolution, descriptionHtml);
    setupEventHandlers(container, id);
  } catch (error) {
    console.error('Failed to load solution:', error);
    toast.error(t('common.error') + ': ' + error.message);
    container.innerHTML = renderErrorState(error.message);
  }
}

/**
 * Split description HTML into main content and appendix (comparison tables, optional features).
 * Appendix starts at headings like "三种部署方案对比" or "Deployment Options".
 */
function splitDescriptionContent(html) {
  if (!html) return { main: '', appendix: '' };

  // Find the split point: H3 headings for deployment options or comparison tables
  // Chinese: "三种部署方案对比", English: "Deployment Options"
  const splitPatterns = [
    /<h3[^>]*>.*?(三种部署方案对比|Deployment Options).*?<\/h3>/i
  ];

  for (const pattern of splitPatterns) {
    const match = html.match(pattern);
    if (match && match.index !== undefined) {
      return {
        main: html.slice(0, match.index),
        appendix: html.slice(match.index)
      };
    }
  }

  return { main: html, appendix: '' };
}

function renderSolutionIntro(solution, descriptionHtml) {
  const name = getLocalizedField(solution, 'name');
  // API returns fields directly on solution, not nested under intro
  const summary = getLocalizedField(solution, 'summary');
  const stats = solution.stats || {};
  const requiredDevices = solution.required_devices || [];
  const presets = solution.presets || [];
  const deviceCatalog = solution.device_catalog || {};
  const partners = solution.partners || [];
  const gallery = solution.gallery || [];

  // Check if any preset has device groups
  const hasDeviceGroups = presets.some(p => (p.device_groups || []).length > 0);

  // Initialize device selections if device_groups exist
  if (hasDeviceGroups) {
    initializeSelections(solution);
  }

  // Split description into main content and appendix (comparison tables go after architecture)
  const { main: mainDescription, appendix: descriptionAppendix } = splitDescriptionContent(descriptionHtml);

  // Use getAssetUrl to handle Tauri mode (converts relative /api/... paths to full URLs)
  const coverImage = solution.cover_image ? getAssetUrl(solution.id, solution.cover_image) : PLACEHOLDER_IMAGE;

  return `
    <div class="back-btn" id="back-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      <span data-i18n="deploy.back">${t('deploy.back')}</span>
    </div>

    <div class="solution-intro animate-fade-in">
      <!-- Hero Section -->
      <div class="solution-hero">
        ${renderHeroCarousel(solution, coverImage, gallery)}
      </div>

      <!-- Sticky Title Bar -->
      <div class="solution-sticky-header" id="solution-sticky-header">
        <div class="solution-sticky-header-inner">
          <!-- Title Row with Deploy Button -->
          <div class="flex flex-wrap items-start justify-between gap-4 mb-3">
            <div class="flex-1 min-w-0">
              <h1 class="solution-title mb-2">${escapeHtml(name)}</h1>
              <p class="solution-summary mb-0">${escapeHtml(summary)}</p>
            </div>
            <button class="btn-deploy-hero flex-shrink-0" id="start-deploy-btn">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              ${t('solutions.startDeploy')}
            </button>
          </div>

          <!-- Stats -->
          <div class="solution-stats">
            ${stats.difficulty ? `
              <div class="solution-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                </svg>
                <span>${t('solutions.difficulty.' + stats.difficulty)}</span>
              </div>
            ` : ''}
            ${stats.estimated_time ? `
              <div class="solution-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                <span>${stats.estimated_time}</span>
              </div>
            ` : ''}
            ${stats.deployed_count !== undefined ? `
              <div class="solution-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                  <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <span>${stats.deployed_count} ${t('solutions.deployedCount')}</span>
              </div>
            ` : ''}
          </div>
        </div>
      </div>

      <!-- Description (main content) -->
      ${mainDescription ? `
        <div class="markdown-content markdown-content-intro mb-8">
          ${processMarkdown(mainDescription)}
        </div>
      ` : ''}

      <!-- Device Configuration (after main description) -->
      ${hasDeviceGroups ? `
        ${renderDeviceConfigurator(solution)}
      ` : requiredDevices.length > 0 ? `
        <div class="solution-devices-inline">
          ${requiredDevices.map(device => renderRequiredDeviceInline(solution.id, device)).join('')}
        </div>
      ` : ''}

      <!-- Description Appendix (comparison tables, optional features - after architecture) -->
      ${descriptionAppendix ? `
        <div class="markdown-content markdown-content-intro mb-8">
          ${processMarkdown(descriptionAppendix)}
        </div>
      ` : ''}

      <!-- External Links (per-preset or global) -->
      <div id="solution-links-section">
        ${renderLinksSection(solution)}
      </div>

      <!-- Deployment Partners -->
      <div class="section-header">
        <h2 class="section-title" data-i18n="solutions.deploymentPartners">${t('solutions.deploymentPartners')}</h2>
      </div>
      <p class="partners-description">${t('solutions.partnersDescription')}</p>
      ${partners.length > 0 ? `
        <div class="partners-grid">
          ${partners.map(partner => renderPartner(partner)).join('')}
        </div>
      ` : ''}
      <div class="partner-register-box">
        <div class="partner-register-info">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="8.5" cy="7" r="4"/>
            <line x1="20" y1="8" x2="20" y2="14"/>
            <line x1="23" y1="11" x2="17" y2="11"/>
          </svg>
          <span>${t('solutions.partnerRegisterHint')}</span>
        </div>
        <a href="https://www.seeedstudio.com/partner-program" target="_blank" class="btn btn-primary btn-sm">
          ${t('solutions.becomePartner')}
        </a>
      </div>
    </div>
  `;
}

function renderGalleryItem(solutionId, item, index) {
  // API returns full URLs for gallery items
  const src = item.src || PLACEHOLDER_IMAGE;
  const caption = getLocalizedField(item, 'caption');

  if (item.type === 'video') {
    const thumbnail = item.thumbnail || PLACEHOLDER_IMAGE;

    return `
      <div class="gallery-item gallery-video" data-index="${index}" data-type="video" data-src="${src}">
        <img class="gallery-image" src="${thumbnail}" alt="${escapeHtml(caption)}" onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${PLACEHOLDER_IMAGE}';}" />
      </div>
    `;
  }

  return `
    <div class="gallery-item" data-index="${index}" data-type="image" data-src="${src}">
      <img class="gallery-image" src="${src}" alt="${escapeHtml(caption)}" onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${PLACEHOLDER_IMAGE}';}" />
    </div>
  `;
}

function isGifSource(src) {
  return /\.gif($|\?)/i.test(String(src || '').trim());
}

function renderHeroCarousel(solution, coverImage, gallery) {
  // Build slides: cover image first, then gallery images (deduplicated by src)
  const slides = [];
  const seen = new Set();

  const addSlide = (src, type = 'image', caption = '') => {
    const normalizedSrc = String(src || '').trim();
    if (!normalizedSrc || seen.has(normalizedSrc)) return;
    seen.add(normalizedSrc);
    slides.push({
      src: normalizedSrc,
      type,
      caption: caption || '',
      isGif: isGifSource(normalizedSrc),
    });
  };

  addSlide(coverImage, 'image', '');
  for (const item of gallery) {
    // Use getAssetUrl for all paths - it handles /api/ paths, relative paths, and absolute URLs
    const src = getAssetUrl(solution.id, item.src);
    addSlide(src, item.type || 'image', getLocalizedField(item, 'caption'));
  }

  if (slides.length === 0) {
    addSlide(PLACEHOLDER_IMAGE, 'image', '');
  }

  const renderHeroImage = (slide) => `
    <img
      class="hero-carousel-image${slide.isGif ? ' hero-carousel-image-contain' : ''}"
      src="${slide.src}"
      alt="${escapeHtml(slide.caption)}"
      onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${PLACEHOLDER_IMAGE}';}"
    />
  `;

  if (slides.length <= 1) {
    return `
      <div class="hero-carousel">
        ${renderHeroImage(slides[0])}
      </div>
    `;
  }

  return `
    <div class="hero-carousel" data-slide-count="${slides.length}">
      <div class="hero-carousel-track">
        ${slides.map((slide, i) => `
          <div class="hero-carousel-slide ${i === 0 ? 'active' : ''}" data-index="${i}">
            ${renderHeroImage(slide)}
          </div>
        `).join('')}
      </div>
      <div class="hero-carousel-dots">
        ${slides.map((_, i) => `<button class="hero-carousel-dot ${i === 0 ? 'active' : ''}" data-index="${i}"></button>`).join('')}
      </div>
    </div>
  `;
}

function renderRequiredDevice(solutionId, device) {
  const name = getLocalizedField(device, 'name');
  const description = getLocalizedField(device, 'description');
  // Use getAssetUrl to handle Tauri mode
  const image = device.image ? getAssetUrl(solutionId, device.image) : DEVICE_PLACEHOLDER;

  return `
    <div class="required-device">
      <img class="required-device-image" src="${image}" alt="${escapeHtml(name)}" onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
      <div class="required-device-info">
        <div class="required-device-name">${escapeHtml(name)}</div>
        <div class="required-device-desc">${escapeHtml(description)}</div>
      </div>
      ${device.product_url ? `
        <a href="${device.product_url}" target="_blank" class="btn btn-secondary btn-sm">
          ${t('solutions.productDetails')}
        </a>
      ` : ''}
    </div>
  `;
}

function renderRequiredDeviceInline(solutionId, device) {
  const name = getLocalizedField(device, 'name');
  const image = device.image ? getAssetUrl(solutionId, device.image) : DEVICE_PLACEHOLDER;

  return `
    <a href="${device.product_url || '#'}" target="${device.product_url ? '_blank' : '_self'}" class="device-chip">
      <img src="${image}" alt="${escapeHtml(name)}" onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
      <span>${escapeHtml(name)}</span>
    </a>
  `;
}

// ============ Device Configurator ============

function initializeSelections(solution) {
  deviceSelections = {};

  // Default to first preset (or one with badge)
  const presets = solution.presets || [];
  if (presets.length > 0) {
    const badged = presets.find(p => p.badge);
    selectedPreset = badged ? badged.id : presets[0].id;
  } else {
    selectedPreset = null;
  }

  // Initialize selections from the selected preset's device_groups
  const preset = presets.find(p => p.id === selectedPreset);
  const groups = preset?.device_groups || [];
  for (const group of groups) {
    if (group.type === 'single') {
      deviceSelections[group.id] = group.default || (group.options?.[0]?.device_ref) || null;
    } else if (group.type === 'multiple') {
      deviceSelections[group.id] = [...(group.default_selections || [])];
    } else if (group.type === 'quantity') {
      deviceSelections[group.id] = group.default_count || 1;
    }
  }
}

function renderDeviceConfigurator(solution) {
  const presets = solution.presets || [];

  // Get device groups from the selected preset
  const filteredGroups = getFilteredGroups(presets);

  // Get architecture image for selected preset
  const architectureImage = getSelectedPresetArchitecture(presets, solution);

  return `
    <div class="device-configurator">
      ${presets.length > 0 ? renderPresetsSection(presets) : ''}
      <div class="device-chips-row">
        ${filteredGroups.map(group => renderDeviceChipWithDropdown(group, solution)).join('')}
      </div>
      ${architectureImage ? `
        <div class="preset-architecture">
          <img src="${architectureImage}" alt="Architecture" class="preset-architecture-image" />
        </div>
      ` : ''}
    </div>
  `;
}

function getFilteredGroups(presets) {
  if (!selectedPreset || presets.length === 0) return [];
  const preset = presets.find(p => p.id === selectedPreset);
  // Return device groups directly from the preset
  return preset?.device_groups || [];
}

function findDeviceGroupById(groupId) {
  // Find device group in the selected preset
  const presets = currentSolution?.presets || [];
  const preset = presets.find(p => p.id === selectedPreset);
  return preset?.device_groups?.find(g => g.id === groupId);
}

function getSelectedPresetArchitecture(presets, solution) {
  if (!selectedPreset || presets.length === 0) return null;
  const preset = presets.find(p => p.id === selectedPreset);
  if (!preset || !preset.architecture_image) return null;
  return getAssetUrl(solution.id, preset.architecture_image);
}

function renderLinksSection(solution) {
  const presets = solution.presets || [];
  if (!selectedPreset || presets.length === 0) return '';
  const preset = presets.find(p => p.id === selectedPreset);
  const wiki = preset?.links?.wiki || null;
  const github = preset?.links?.github || null;
  if (!wiki && !github) return '';
  return `
    <div class="flex flex-wrap items-center gap-3 mb-8">
      ${wiki ? `
        <a href="${wiki}" target="_blank" class="btn btn-secondary">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
          </svg>
          Wiki
        </a>
      ` : ''}
      ${github ? `
        <a href="${github}" target="_blank" class="btn btn-secondary">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>
          </svg>
          GitHub
        </a>
      ` : ''}
    </div>
  `;
}

function renderPresetsSection(presets) {
  return `
    <div class="presets-section">
      <div class="presets-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/>
          <path d="M2 17l10 5 10-5"/>
          <path d="M2 12l10 5 10-5"/>
        </svg>
        ${t('solutions.quickStart')}
      </div>
      <div class="presets-grid">
        ${presets.map(preset => renderPresetCard(preset)).join('')}
      </div>
    </div>
  `;
}

function renderPresetCard(preset) {
  const name = getLocalizedField(preset, 'name');
  const description = getLocalizedField(preset, 'description');
  const badge = getLocalizedField(preset, 'badge');
  const isSelected = selectedPreset === preset.id;

  return `
    <div class="preset-card ${isSelected ? 'selected' : ''}" data-preset-id="${preset.id}">
      ${badge ? `<span class="preset-badge">${escapeHtml(badge)}</span>` : ''}
      <div class="preset-name">${escapeHtml(name)}</div>
      <div class="preset-description">${escapeHtml(description)}</div>
    </div>
  `;
}

function renderDeviceChipWithDropdown(group, solution) {
  const groupName = getLocalizedField(group, 'name');
  const catalog = solution.device_catalog || {};

  // Get current selected device info
  let selectedDevice = null;
  let selectedName = '';
  let selectedImage = DEVICE_PLACEHOLDER;
  let quantityBadge = '';

  if (group.type === 'quantity') {
    const quantity = deviceSelections[group.id] || group.default_count || 1;
    selectedDevice = group.device_info || catalog[group.device_ref] || {};
    selectedName = getLocalizedField(selectedDevice, 'name') || group.device_ref;
    selectedImage = selectedDevice.image ? getAssetUrl(solution.id, selectedDevice.image) : DEVICE_PLACEHOLDER;
    quantityBadge = `<span class="chip-qty-badge">×${quantity}</span>`;
  } else if (group.type === 'single') {
    const selectedRef = deviceSelections[group.id];
    const option = group.options?.find(o => o.device_ref === selectedRef);
    selectedDevice = option?.device_info || catalog[selectedRef] || {};
    selectedName = getLocalizedField(selectedDevice, 'name') || selectedRef;
    selectedImage = selectedDevice.image ? getAssetUrl(solution.id, selectedDevice.image) : DEVICE_PLACEHOLDER;
  } else if (group.type === 'multiple') {
    const selectedRefs = deviceSelections[group.id] || [];
    if (selectedRefs.length > 0) {
      const firstRef = selectedRefs[0];
      const option = group.options?.find(o => o.device_ref === firstRef);
      selectedDevice = option?.device_info || catalog[firstRef] || {};
      selectedName = getLocalizedField(selectedDevice, 'name') || firstRef;
      selectedImage = selectedDevice.image ? getAssetUrl(solution.id, selectedDevice.image) : DEVICE_PLACEHOLDER;
      if (selectedRefs.length > 1) {
        quantityBadge = `<span class="chip-qty-badge">+${selectedRefs.length - 1}</span>`;
      }
    }
  }

  // Always make chips interactive - show dropdown arrow for all
  const hasMultipleOptions = (group.options && group.options.length > 1) || group.type === 'quantity';
  const isSingleOption = group.type === 'single' && group.options && group.options.length === 1;

  return `
    <div class="device-chip-dropdown" data-group-id="${group.id}">
      <div class="device-chip-trigger has-options">
        <img src="${selectedImage}" alt="${escapeHtml(selectedName)}"
             onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
        <span class="chip-name">${escapeHtml(selectedName)}</span>
        ${quantityBadge}
        ${hasMultipleOptions ? `
          <svg class="chip-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        ` : `
          <svg class="chip-info-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="16" x2="12" y2="12"/>
            <line x1="12" y1="8" x2="12.01" y2="8"/>
          </svg>
        `}
      </div>
      ${renderDropdownPanel(group, solution)}
    </div>
  `;
}

function renderDropdownPanel(group, solution) {
  const catalog = solution.device_catalog || {};

  if (group.type === 'quantity') {
    const currentValue = deviceSelections[group.id] || group.default_count || 1;
    const device = group.device_info || catalog[group.device_ref] || {};
    const deviceImage = device.image ? getAssetUrl(solution.id, device.image) : DEVICE_PLACEHOLDER;
    const purchaseUrl = device.product_url;
    return `
      <div class="chip-dropdown-panel">
        <div class="dropdown-qty-controls">
          <button class="qty-btn qty-minus" data-group-id="${group.id}" ${currentValue <= (group.min_count || 1) ? 'disabled' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
          </button>
          <input type="number" class="qty-input" data-group-id="${group.id}"
                 value="${currentValue}" min="${group.min_count || 1}" max="${group.max_count || 100}" />
          <button class="qty-btn qty-plus" data-group-id="${group.id}" ${currentValue >= (group.max_count || 100) ? 'disabled' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
          </button>
        </div>
        ${purchaseUrl ? `
          <a href="${purchaseUrl}" target="_blank" class="dropdown-qty-purchase">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="9" cy="21" r="1"/>
              <circle cx="20" cy="21" r="1"/>
              <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
            </svg>
            ${t('solutions.productDetails')}
          </a>
        ` : ''}
      </div>
    `;
  }

  // Single or multiple select options
  const currentValue = deviceSelections[group.id];
  const currentValues = Array.isArray(currentValue) ? currentValue : [currentValue];

  // For single-option groups, show device info panel with purchase link
  if (group.options && group.options.length === 1) {
    const option = group.options[0];
    const device = option.device_info || catalog[option.device_ref] || {};
    const name = getLocalizedField(device, 'name') || option.device_ref;
    const description = getLocalizedField(device, 'description');
    const image = device.image ? getAssetUrl(solution.id, device.image) : DEVICE_PLACEHOLDER;
    const purchaseUrl = device.product_url;

    return `
      <div class="chip-dropdown-panel device-info-panel">
        <div class="device-info-content">
          <img src="${image}" alt="${escapeHtml(name)}"
               onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
          <div class="device-info-text">
            <span class="device-info-name">${escapeHtml(name)}</span>
            ${description ? `<span class="device-info-desc">${escapeHtml(description)}</span>` : ''}
          </div>
        </div>
        ${purchaseUrl ? `
          <a href="${purchaseUrl}" target="_blank" class="device-purchase-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="9" cy="21" r="1"/>
              <circle cx="20" cy="21" r="1"/>
              <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
            </svg>
            ${t('solutions.productDetails')}
          </a>
        ` : ''}
      </div>
    `;
  }

  return `
    <div class="chip-dropdown-panel">
      ${group.options.map(option => {
        const device = option.device_info || catalog[option.device_ref] || {};
        const name = getLocalizedField(device, 'name') || option.device_ref;
        const label = getLocalizedField(option, 'label');
        const image = device.image ? getAssetUrl(solution.id, device.image) : DEVICE_PLACEHOLDER;
        const purchaseUrl = device.product_url;
        const isSelected = currentValues.includes(option.device_ref);

        return `
          <div class="dropdown-option ${isSelected ? 'selected' : ''}"
               data-group-id="${group.id}"
               data-device-ref="${option.device_ref}"
               data-type="${group.type}">
            <img src="${image}" alt="${escapeHtml(name)}"
                 onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
            <div class="dropdown-option-info">
              <span class="dropdown-option-name">${escapeHtml(name)}</span>
              ${label ? `<span class="dropdown-option-label">${escapeHtml(label)}</span>` : ''}
            </div>
            <div class="dropdown-option-actions">
              ${purchaseUrl ? `
                <a href="${purchaseUrl}" target="_blank" class="dropdown-purchase-link" title="${t('solutions.productDetails')}" onclick="event.stopPropagation()">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="9" cy="21" r="1"/>
                    <circle cx="20" cy="21" r="1"/>
                    <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
                  </svg>
                </a>
              ` : ''}
              ${isSelected ? `
                <svg class="dropdown-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              ` : ''}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderDeviceGroup(group) {
  const name = getLocalizedField(group, 'name');
  const description = getLocalizedField(group, 'description');

  let content = '';
  if (group.type === 'single') {
    content = renderSingleSelectGroup(group);
  } else if (group.type === 'multiple') {
    content = renderMultipleSelectGroup(group);
  } else if (group.type === 'quantity') {
    content = renderQuantityGroup(group);
  }

  return `
    <div class="device-group" data-group-id="${group.id}">
      <div class="device-group-header">
        <div>
          <div class="device-group-title">
            ${escapeHtml(name)}
            ${group.required ? `<span class="required-badge">*</span>` : ''}
          </div>
          ${description ? `<div class="device-group-desc">${escapeHtml(description)}</div>` : ''}
        </div>
      </div>
      ${content}
    </div>
  `;
}

function renderSingleSelectGroup(group) {
  const currentValue = deviceSelections[group.id];

  return `
    <div class="device-options-grid">
      ${group.options.map(option => {
        const device = option.device_info || {};
        const name = getLocalizedField(device, 'name') || option.device_ref;
        const label = getLocalizedField(option, 'label');
        const image = device.image || DEVICE_PLACEHOLDER;
        const isSelected = currentValue === option.device_ref;

        return `
          <div class="device-option single ${isSelected ? 'selected' : ''}"
               data-group-id="${group.id}"
               data-device-ref="${option.device_ref}">
            <img src="${image}" alt="${escapeHtml(name)}"
                 onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
            <div class="device-option-name">${escapeHtml(name)}</div>
            ${label ? `<div class="device-option-label">${escapeHtml(label)}</div>` : ''}
            <div class="device-option-check"></div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderMultipleSelectGroup(group) {
  const currentValues = deviceSelections[group.id] || [];

  return `
    <div class="device-options-grid">
      ${group.options.map(option => {
        const device = option.device_info || {};
        const name = getLocalizedField(device, 'name') || option.device_ref;
        const label = getLocalizedField(option, 'label');
        const image = device.image || DEVICE_PLACEHOLDER;
        const isSelected = currentValues.includes(option.device_ref);

        return `
          <div class="device-option multiple ${isSelected ? 'selected' : ''}"
               data-group-id="${group.id}"
               data-device-ref="${option.device_ref}">
            <img src="${image}" alt="${escapeHtml(name)}"
                 onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
            <div class="device-option-name">${escapeHtml(name)}</div>
            ${label ? `<div class="device-option-label">${escapeHtml(label)}</div>` : ''}
            <div class="device-option-check"></div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderQuantityGroup(group) {
  const currentValue = deviceSelections[group.id] || group.default_count || 1;
  const device = group.device_info || {};
  const name = getLocalizedField(device, 'name') || group.device_ref;
  const description = getLocalizedField(device, 'description');
  const image = device.image || DEVICE_PLACEHOLDER;

  return `
    <div class="quantity-selector">
      <div class="quantity-device">
        <img src="${image}" alt="${escapeHtml(name)}"
             onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${DEVICE_PLACEHOLDER}';}" />
        <div class="quantity-device-info">
          <div class="quantity-device-name">${escapeHtml(name)}</div>
          ${description ? `<div class="quantity-device-desc">${escapeHtml(description)}</div>` : ''}
        </div>
      </div>
      <div class="quantity-controls">
        <button class="qty-btn qty-minus" data-group-id="${group.id}" ${currentValue <= (group.min_count || 1) ? 'disabled' : ''}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
        <input type="number" class="qty-input" data-group-id="${group.id}"
               value="${currentValue}" min="${group.min_count || 1}" max="${group.max_count || 100}" />
        <button class="qty-btn qty-plus" data-group-id="${group.id}" ${currentValue >= (group.max_count || 100) ? 'disabled' : ''}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
      </div>
    </div>
  `;
}

function renderSelectionSummary(solution) {
  const presets = solution.presets || [];
  const preset = presets.find(p => p.id === selectedPreset);
  const groups = preset?.device_groups || [];
  const catalog = solution.device_catalog || {};

  if (groups.length === 0) return '';

  const items = [];
  for (const group of groups) {
    const groupName = getLocalizedField(group, 'name');
    let valueDisplay = '';

    if (group.type === 'single') {
      const selected = deviceSelections[group.id];
      if (selected) {
        const option = group.options?.find(o => o.device_ref === selected);
        const device = option?.device_info || catalog[selected] || {};
        valueDisplay = getLocalizedField(device, 'name') || selected;
      }
    } else if (group.type === 'multiple') {
      const selected = deviceSelections[group.id] || [];
      valueDisplay = selected.length > 0
        ? selected.map(ref => {
            const option = group.options?.find(o => o.device_ref === ref);
            const device = option?.device_info || catalog[ref] || {};
            return getLocalizedField(device, 'name') || ref;
          }).join(', ')
        : '-';
    } else if (group.type === 'quantity') {
      valueDisplay = `${deviceSelections[group.id] || 1}x`;
    }

    items.push({ name: groupName, value: valueDisplay });
  }

  return `
    <div class="selection-summary-title">${t('solutions.selectedDevices')}</div>
    <div class="selection-summary-list">
      ${items.map(item => `
        <div class="selection-summary-item">
          <span class="name">${escapeHtml(item.name)}</span>
          <span class="value">${escapeHtml(item.value)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function applyPreset(presetId) {
  const preset = currentSolution?.presets?.find(p => p.id === presetId);
  if (preset) {
    selectedPreset = presetId;
    // Apply device selections from preset's device_groups defaults
    deviceSelections = {};
    for (const group of preset.device_groups || []) {
      if (group.type === 'single') {
        deviceSelections[group.id] = group.default || (group.options?.[0]?.device_ref) || null;
      } else if (group.type === 'multiple') {
        deviceSelections[group.id] = [...(group.default_selections || [])];
      } else if (group.type === 'quantity') {
        deviceSelections[group.id] = group.default_count || 1;
      }
    }
  }
}

function updateSelectionSummary() {
  const summaryEl = document.getElementById('selection-summary');
  if (summaryEl && currentSolution) {
    summaryEl.innerHTML = renderSelectionSummary(currentSolution);
  }
}

function updateGroupUI(groupId) {
  const groupEl = document.querySelector(`.device-group[data-group-id="${groupId}"]`);
  if (!groupEl || !currentSolution) return;

  const group = findDeviceGroupById(groupId);
  if (!group) return;

  // Update option selections
  if (group.type === 'single') {
    const currentValue = deviceSelections[groupId];
    groupEl.querySelectorAll('.device-option').forEach(el => {
      const ref = el.dataset.deviceRef;
      el.classList.toggle('selected', ref === currentValue);
    });
  } else if (group.type === 'multiple') {
    const currentValues = deviceSelections[groupId] || [];
    groupEl.querySelectorAll('.device-option').forEach(el => {
      const ref = el.dataset.deviceRef;
      el.classList.toggle('selected', currentValues.includes(ref));
    });
  } else if (group.type === 'quantity') {
    const input = groupEl.querySelector('.qty-input');
    const minusBtn = groupEl.querySelector('.qty-minus');
    const plusBtn = groupEl.querySelector('.qty-plus');
    const currentValue = deviceSelections[groupId] || 1;

    if (input) input.value = currentValue;
    if (minusBtn) minusBtn.disabled = currentValue <= (group.min_count || 1);
    if (plusBtn) plusBtn.disabled = currentValue >= (group.max_count || 100);
  }

  updateSelectionSummary();
}

function renderPartner(partner) {
  const name = getLocalizedField(partner, 'name');
  const regions = partner.regions || [];

  return `
    <div class="partner-card">
      <div class="partner-header">
        ${partner.logo ? `
          <img class="partner-logo" src="${partner.logo}" alt="${escapeHtml(name)}" onerror="this.style.display='none'" />
        ` : `
          <div class="partner-logo-placeholder">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
          </div>
        `}
        <div class="partner-name">${escapeHtml(name)}</div>
      </div>
      <div class="partner-regions">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
          <circle cx="12" cy="10" r="3"/>
        </svg>
        <span>${regions.map(r => escapeHtml(r)).join(', ')}</span>
      </div>
      <div class="partner-actions">
        ${partner.contact ? `
          <a href="mailto:${partner.contact}" class="partner-contact" title="${t('solutions.contactPartner')}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
              <polyline points="22,6 12,13 2,6"/>
            </svg>
            ${escapeHtml(partner.contact)}
          </a>
        ` : ''}
        ${partner.website ? `
          <a href="${partner.website}" target="_blank" class="partner-website" title="${t('solutions.visitWebsite')}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            ${t('solutions.visitWebsite')}
          </a>
        ` : ''}
      </div>
    </div>
  `;
}

function renderErrorState(message) {
  return `
    <div class="back-btn" id="back-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      <span data-i18n="deploy.back">${t('deploy.back')}</span>
    </div>
    <div class="empty-state">
      <svg class="empty-state-icon text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <h3 class="empty-state-title">${t('common.error')}</h3>
      <p class="empty-state-description">${escapeHtml(message)}</p>
    </div>
  `;
}

function setupEventHandlers(container, solutionId) {
  // Back button
  const backBtn = container.querySelector('#back-btn');
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      router.navigate('solutions');
    });
  }

  // Start deploy button - pass selected preset
  const deployBtn = container.querySelector('#start-deploy-btn');
  if (deployBtn) {
    deployBtn.addEventListener('click', () => {
      const params = { id: solutionId };
      if (selectedPreset) {
        params.preset = selectedPreset;
      }
      router.navigate('deploy', params);
    });
  }

  // Sticky header shadow on scroll
  setupStickyHeader(container);

  // Hero Carousel
  setupHeroCarousel(container);

  // Device Configurator Event Handlers
  setupDeviceConfiguratorHandlers(container);
}

function setupStickyHeader(container) {
  const stickyHeader = container.querySelector('#solution-sticky-header');
  if (!stickyHeader) return;

  // Use scroll event to detect when header is stuck
  const contentArea = document.getElementById('content-area');
  if (!contentArea) return;

  const checkSticky = () => {
    const rect = stickyHeader.getBoundingClientRect();
    const contentRect = contentArea.getBoundingClientRect();
    // Header is stuck when its top is at or near the content area top
    stickyHeader.classList.toggle('is-stuck', rect.top <= contentRect.top + 1);
  };

  contentArea.addEventListener('scroll', checkSticky, { passive: true });
  checkSticky();
}

function setupDeviceConfiguratorHandlers(container) {
  // Preset selection
  container.querySelectorAll('.preset-card').forEach(card => {
    card.addEventListener('click', () => {
      const presetId = card.dataset.presetId;
      applyPreset(presetId);

      // Update preset card UI
      container.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');

      // Re-render chips row
      rerenderChipsRow(container);
    });
  });

  // Chip dropdown toggle
  container.querySelectorAll('.device-chip-trigger.has-options').forEach(trigger => {
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const dropdown = trigger.closest('.device-chip-dropdown');
      const panel = dropdown.querySelector('.chip-dropdown-panel');

      // Close other dropdowns
      container.querySelectorAll('.chip-dropdown-panel.open').forEach(p => {
        if (p !== panel) p.classList.remove('open');
      });

      panel?.classList.toggle('open');
    });
  });

  // Close dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.device-chip-dropdown')) {
      container.querySelectorAll('.chip-dropdown-panel.open').forEach(p => {
        p.classList.remove('open');
      });
    }
  });

  // Dropdown option selection
  container.querySelectorAll('.dropdown-option').forEach(option => {
    option.addEventListener('click', (e) => {
      e.stopPropagation();
      const groupId = option.dataset.groupId;
      const deviceRef = option.dataset.deviceRef;
      const type = option.dataset.type;
      const group = findDeviceGroupById(groupId);

      if (!group) return;

      // Visually deselect preset cards to indicate custom configuration,
      // but keep selectedPreset for architecture image display
      container.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));

      if (type === 'single') {
        deviceSelections[groupId] = deviceRef;
        // Close dropdown and re-render
        rerenderChipsRow(container);
      } else if (type === 'multiple') {
        const current = deviceSelections[groupId] || [];
        const index = current.indexOf(deviceRef);
        if (index > -1) {
          current.splice(index, 1);
        } else if (current.length < (group.max_count || 10)) {
          current.push(deviceRef);
        }
        deviceSelections[groupId] = current;
        // Update option state
        option.classList.toggle('selected', current.includes(deviceRef));
        rerenderChipsRow(container);
      }
    });
  });

  // Quantity controls in dropdown
  container.querySelectorAll('.dropdown-qty-controls .qty-minus').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const groupId = btn.dataset.groupId;
      const group = findDeviceGroupById(groupId);
      if (!group) return;

      // Visually deselect preset cards to indicate custom configuration
      container.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));

      const current = deviceSelections[groupId] || 1;
      const min = group.min_count || 1;
      if (current > min) {
        deviceSelections[groupId] = current - 1;
        updateQuantityUI(container, groupId, group);
      }
    });
  });

  container.querySelectorAll('.dropdown-qty-controls .qty-plus').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const groupId = btn.dataset.groupId;
      const group = findDeviceGroupById(groupId);
      if (!group) return;

      // Visually deselect preset cards to indicate custom configuration
      container.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));

      const current = deviceSelections[groupId] || 1;
      const max = group.max_count || 100;
      if (current < max) {
        deviceSelections[groupId] = current + 1;
        updateQuantityUI(container, groupId, group);
      }
    });
  });

  container.querySelectorAll('.dropdown-qty-controls .qty-input').forEach(input => {
    input.addEventListener('change', (e) => {
      e.stopPropagation();
      const groupId = input.dataset.groupId;
      const group = findDeviceGroupById(groupId);
      if (!group) return;

      // Visually deselect preset cards to indicate custom configuration
      container.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));

      let value = parseInt(input.value, 10);
      const min = group.min_count || 1;
      const max = group.max_count || 100;

      if (isNaN(value)) value = min;
      value = Math.max(min, Math.min(max, value));

      deviceSelections[groupId] = value;
      updateQuantityUI(container, groupId, group);
    });

    input.addEventListener('click', (e) => e.stopPropagation());
  });
}

function updateQuantityUI(container, groupId, group) {
  const dropdown = container.querySelector(`.device-chip-dropdown[data-group-id="${groupId}"]`);
  if (!dropdown) return;

  const currentValue = deviceSelections[groupId] || 1;

  // Update badge on chip
  const badge = dropdown.querySelector('.chip-qty-badge');
  if (badge) {
    badge.textContent = `×${currentValue}`;
  }

  // Update input and buttons
  const input = dropdown.querySelector('.qty-input');
  const minusBtn = dropdown.querySelector('.qty-minus');
  const plusBtn = dropdown.querySelector('.qty-plus');

  if (input) input.value = currentValue;
  if (minusBtn) minusBtn.disabled = currentValue <= (group.min_count || 1);
  if (plusBtn) plusBtn.disabled = currentValue >= (group.max_count || 100);
}

function rerenderChipsRow(container) {
  const chipsRow = container.querySelector('.device-chips-row');
  if (chipsRow && currentSolution) {
    const presets = currentSolution.presets || [];
    const filteredGroups = getFilteredGroups(presets);
    chipsRow.innerHTML = filteredGroups.map(group => renderDeviceChipWithDropdown(group, currentSolution)).join('');

    // Update architecture image
    const archContainer = container.querySelector('.preset-architecture');
    if (archContainer) {
      const architectureImage = getSelectedPresetArchitecture(presets, currentSolution);
      if (architectureImage) {
        archContainer.innerHTML = `<img src="${architectureImage}" alt="Architecture" class="preset-architecture-image" />`;
        archContainer.style.display = '';
      } else {
        archContainer.style.display = 'none';
      }
    }

    // Update links section
    const linksSection = document.getElementById('solution-links-section');
    if (linksSection) {
      linksSection.innerHTML = renderLinksSection(currentSolution);
    }

    // Re-attach event handlers for the new elements
    setupDeviceConfiguratorHandlers(container);
  }
}

function setupHeroCarousel(container) {
  if (carouselTimer) { clearInterval(carouselTimer); carouselTimer = null; }
  const carousel = container.querySelector('.hero-carousel');
  if (!carousel) return;
  const slideCount = parseInt(carousel.dataset.slideCount || '0');
  if (slideCount <= 1) return;

  let currentSlide = 0;

  function goToSlide(index) {
    currentSlide = (index + slideCount) % slideCount;
    carousel.querySelectorAll('.hero-carousel-slide').forEach((s, i) => {
      s.classList.toggle('active', i === currentSlide);
    });
    carousel.querySelectorAll('.hero-carousel-dot').forEach((d, i) => {
      d.classList.toggle('active', i === currentSlide);
    });
  }

  function startAutoplay() {
    if (carouselTimer) clearInterval(carouselTimer);
    carouselTimer = setInterval(() => goToSlide(currentSlide + 1), 5000);
  }

  carousel.querySelectorAll('.hero-carousel-dot').forEach(dot => {
    dot.addEventListener('click', () => { goToSlide(parseInt(dot.dataset.index)); startAutoplay(); });
  });

  // Click image to open modal with navigation
  const allSlides = carousel.querySelectorAll('.hero-carousel-slide');
  const slideSrcs = Array.from(allSlides).map(s => s.querySelector('img')?.src || '');
  allSlides.forEach((slide, i) => {
    slide.addEventListener('click', () => { openCarouselModal(slideSrcs, i); });
    slide.style.cursor = 'pointer';
  });

  startAutoplay();
}

function openCarouselModal(slides, startIndex) {
  const modalContainer = document.getElementById('modal-container');
  let idx = startIndex;

  function render() {
    modalContainer.innerHTML = `
      <div class="modal" id="media-modal">
        <div class="carousel-modal-content">
          <button class="carousel-modal-close" id="close-modal">&times;</button>
          ${slides.length > 1 ? `
            <button class="carousel-modal-prev" id="modal-prev">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6"/></svg>
            </button>
            <button class="carousel-modal-next" id="modal-next">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          ` : ''}
          <img class="carousel-modal-image" src="${slides[idx]}" />
          ${slides.length > 1 ? `
            <div class="carousel-modal-counter">${idx + 1} / ${slides.length}</div>
          ` : ''}
        </div>
      </div>
    `;

    document.getElementById('close-modal').addEventListener('click', () => { modalContainer.innerHTML = ''; });
    document.getElementById('media-modal').addEventListener('click', (e) => {
      if (e.target.id === 'media-modal') modalContainer.innerHTML = '';
    });
    const prevBtn = document.getElementById('modal-prev');
    const nextBtn = document.getElementById('modal-next');
    if (prevBtn) prevBtn.addEventListener('click', (e) => { e.stopPropagation(); idx = (idx - 1 + slides.length) % slides.length; render(); });
    if (nextBtn) nextBtn.addEventListener('click', (e) => { e.stopPropagation(); idx = (idx + 1) % slides.length; render(); });
  }

  render();

  // Keyboard navigation
  function onKey(e) {
    if (!document.getElementById('media-modal')) { document.removeEventListener('keydown', onKey); return; }
    if (e.key === 'ArrowLeft') { idx = (idx - 1 + slides.length) % slides.length; render(); }
    else if (e.key === 'ArrowRight') { idx = (idx + 1) % slides.length; render(); }
    else if (e.key === 'Escape') { modalContainer.innerHTML = ''; }
  }
  document.addEventListener('keydown', onKey);
}

function openMediaModal(type, src) {
  const modalContainer = document.getElementById('modal-container');

  if (type === 'video') {
    modalContainer.innerHTML = `
      <div class="modal" id="media-modal">
        <div class="modal-content" style="max-width: 800px;">
          <div class="modal-header">
            <h3>Video</h3>
            <button class="close-btn" id="close-modal">&times;</button>
          </div>
          <div class="modal-body p-0">
            <video controls autoplay style="width: 100%;">
              <source src="${src}" type="video/mp4">
              Your browser does not support video.
            </video>
          </div>
        </div>
      </div>
    `;
  } else {
    modalContainer.innerHTML = `
      <div class="modal" id="media-modal">
        <div class="modal-content" style="max-width: 900px;">
          <div class="modal-header">
            <h3>Image</h3>
            <button class="close-btn" id="close-modal">&times;</button>
          </div>
          <div class="modal-body p-0">
            <img src="${src}" style="width: 100%;" />
          </div>
        </div>
      </div>
    `;
  }

  // Close modal handlers
  const modal = document.getElementById('media-modal');
  const closeBtn = document.getElementById('close-modal');

  closeBtn.addEventListener('click', () => {
    modalContainer.innerHTML = '';
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      modalContainer.innerHTML = '';
    }
  });
}

// Re-render when language changes
i18n.onLocaleChange(() => {
  if (router.currentRoute === 'solution' && currentSolution) {
    renderSolutionDetailPage({ id: currentSolution.id });
  }
});
