/**
 * Solutions Page - List and Grid View
 */

import { solutionsApi, getAssetUrl } from '../modules/api.js';
import { t, getLocalizedField, i18n } from '../modules/i18n.js';
import { router } from '../modules/router.js';
import { toast } from '../modules/toast.js';
import { PLACEHOLDER_IMAGE, escapeHtml } from '../modules/utils.js';

let solutions = [];
let activeTypeFilter = 'all'; // 'all' | 'solution' | 'technical'

export async function renderSolutionsPage() {
  const container = document.getElementById('content-area');

  // Show loading state
  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title" data-i18n="solutions.title">${t('solutions.title')}</h1>
    </div>
    <div class="solutions-grid">
      ${renderSkeletonCards(6)}
    </div>
  `;

  try {
    solutions = await solutionsApi.list(i18n.locale);

    if (solutions.length === 0) {
      container.innerHTML = renderEmptyState();
      return;
    }

    renderFilteredView(container);
  } catch (error) {
    console.error('Failed to load solutions:', error);
    toast.error(t('common.error') + ': ' + error.message);
    container.innerHTML = renderErrorState(error.message);
  }
}

function renderFilteredView(container) {
  const filtered = activeTypeFilter === 'all'
    ? solutions
    : solutions.filter(s => (s.solution_type || 'solution') === activeTypeFilter);

  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title" data-i18n="solutions.title">${t('solutions.title')}</h1>
    </div>
    ${renderFilterTabs()}
    <div class="solutions-grid">
      ${filtered.length > 0 ? filtered.map(renderSolutionCard).join('') : `<p class="text-text-muted">${t('solutions.empty')}</p>`}
    </div>
  `;

  // Add filter tab handlers
  container.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      activeTypeFilter = tab.dataset.type;
      renderFilteredView(container);
    });
  });

  // Add card click handlers
  container.querySelectorAll('.solution-card').forEach(card => {
    card.addEventListener('click', () => {
      const solutionId = card.dataset.solutionId;
      router.navigate('solution', { id: solutionId });
    });
  });
}

function renderFilterTabs() {
  const types = ['all', 'solution', 'technical'];
  return `
    <div class="filter-tabs">
      ${types.map(type => `
        <button class="filter-tab ${activeTypeFilter === type ? 'active' : ''}" data-type="${type}">
          ${t('solutions.type.' + type)}
        </button>
      `).join('')}
    </div>
  `;
}

function renderSolutionCard(solution) {
  const name = getLocalizedField(solution, 'name');
  // API returns flat structure, not nested under intro
  const summary = getLocalizedField(solution, 'summary');
  // Use getAssetUrl to handle Tauri mode (converts relative /api/... paths to full URLs)
  const coverImage = solution.cover_image ? getAssetUrl(solution.id, solution.cover_image) : PLACEHOLDER_IMAGE;
  const isGifCover = /\.gif($|\?)/i.test(coverImage || '');
  const imageClass = `solution-card-image${isGifCover ? ' solution-card-image-gif' : ''}`;

  const categoryLabel = t('management.categories.' + (solution.category || 'general'));

  return `
    <div class="solution-card" data-solution-id="${solution.id}">
      <div class="solution-card-image-wrapper">
        <img
          class="${imageClass}"
          src="${coverImage}"
          alt="${escapeHtml(name)}"
          onerror="if(!this.dataset.err){this.dataset.err='1';this.src='${PLACEHOLDER_IMAGE}';}"
        />
        <div class="solution-card-overlays">
          ${solution.solution_type === 'technical' ? `
            <span class="solution-overlay-tag overlay-type">${t('solutions.type.technical')}</span>
          ` : ''}
          <span class="solution-overlay-tag overlay-category">${escapeHtml(categoryLabel)}</span>
        </div>
      </div>
      <div class="solution-card-content">
        <h3 class="solution-card-title">${escapeHtml(name)}</h3>
        <p class="solution-card-description">${escapeHtml(summary)}</p>
        <div class="solution-card-meta">
          ${solution.difficulty ? `
            <span class="solution-card-tag">
              ${t('solutions.difficulty.' + solution.difficulty)}
            </span>
          ` : ''}
          ${solution.estimated_time ? `
            <span>${t('solutions.estimatedTime')}: ${solution.estimated_time}</span>
          ` : ''}
          ${solution.deployed_count !== undefined ? `
            <span>${t('solutions.deployedCount')}: ${solution.deployed_count}</span>
          ` : ''}
        </div>
      </div>
    </div>
  `;
}

function renderSkeletonCards(count) {
  return Array(count).fill(0).map(() => `
    <div class="solution-card">
      <div class="skeleton skeleton-image"></div>
      <div class="solution-card-content">
        <div class="skeleton skeleton-title mb-2"></div>
        <div class="skeleton skeleton-text mb-1"></div>
        <div class="skeleton skeleton-text" style="width: 70%;"></div>
      </div>
    </div>
  `).join('');
}

function renderEmptyState() {
  return `
    <div class="empty-state">
      <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
      </svg>
      <h3 class="empty-state-title" data-i18n="solutions.empty">${t('solutions.empty')}</h3>
      <p class="empty-state-description" data-i18n="solutions.emptyDescription">${t('solutions.emptyDescription')}</p>
    </div>
  `;
}

function renderErrorState(message) {
  return `
    <div class="empty-state">
      <svg class="empty-state-icon text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <h3 class="empty-state-title">${t('common.error')}</h3>
      <p class="empty-state-description">${escapeHtml(message)}</p>
      <button class="btn btn-primary mt-4" onclick="window.location.reload()">
        ${t('common.retry')}
      </button>
    </div>
  `;
}

// Re-render when language changes
i18n.onLocaleChange(() => {
  if (router.currentRoute === 'solutions') {
    renderSolutionsPage();
  }
});
