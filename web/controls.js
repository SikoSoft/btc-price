/**
 * controls.js — Parameter controls, news panel, app orchestration
 *
 * Responsibilities:
 *   - Fetch default config from GET /config/defaults
 *   - Render parameter sliders + number inputs
 *   - Trigger anomaly reload on "Apply"
 *   - Show/hide news panel when an anomaly is clicked
 *   - Fetch and display news articles per anomaly
 */

(function () {
  'use strict';

  const API_BASE = window.API_BASE || 'http://localhost:8000';

  // Saved so the Reset button can restore them
  let originalDefaults = null;

  // Parameter definitions — order controls display order
  const PARAMS = [
    { key: 'reversal_lookback',         label: 'Reversal lookback (days)',        min: 1,   max: 90,  step: 1    },
    { key: 'reversal_lookforward',      label: 'Reversal lookforward (days)',     min: 1,   max: 90,  step: 1    },
    { key: 'reversal_min_score',        label: 'Reversal min score',              min: 0,   max: 2,   step: 0.01 },
    { key: 'amplification_lookback',    label: 'Amplification lookback (days)',   min: 1,   max: 90,  step: 1    },
    { key: 'amplification_lookforward', label: 'Amplification lookforward (days)',min: 1,   max: 90,  step: 1    },
    { key: 'amplification_min_score',   label: 'Amplification min score',         min: 0,   max: 2,   step: 0.01 },
    { key: 'stagnation_window',         label: 'Stagnation window (days)',        min: 5,   max: 180, step: 1    },
    { key: 'stagnation_min_score',      label: 'Stagnation min score',            min: 0,   max: 1,   step: 0.01 },
    { key: 'top_n',                     label: 'Results per category',            min: 1,   max: 20,  step: 1    },
  ];

  // -----------------------------------------------------------------------
  // Boot sequence
  // -----------------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', async function () {
    // Wire up UI chrome
    document.getElementById('controls-toggle').addEventListener('click', toggleControls);
    document.getElementById('news-panel-close').addEventListener('click', closeNewsPanel);

    // Wait for chart + prices to load before triggering anomaly detection
    await window.App.chartReady;

    // Fetch defaults, render controls, then load first anomaly set
    await initControls();

    // Register the click handler exposed by chart.js
    window.onAnomalyClick = showNewsPanel;
  });

  // -----------------------------------------------------------------------
  // Controls
  // -----------------------------------------------------------------------

  async function initControls() {
    let defaults;
    try {
      const resp = await fetch(`${API_BASE}/config/defaults`);
      if (!resp.ok) throw new Error('non-200');
      const data = await resp.json();
      defaults = data.analysis;
    } catch (_) {
      // Fall back to hard-coded defaults if the API is unreachable
      defaults = {
        reversal_lookback: 10, reversal_lookforward: 10, reversal_min_score: 0.05,
        amplification_lookback: 10, amplification_lookforward: 10, amplification_min_score: 0.05,
        stagnation_window: 30, stagnation_min_score: 0.0, top_n: 10,
      };
    }

    originalDefaults = defaults;
    renderControls(defaults);
    await window.App.loadAnomalies(defaults);
  }

  function renderControls(values) {
    const grid = document.getElementById('controls-grid');

    grid.innerHTML = PARAMS.map(function (p) {
      const v = values[p.key] !== undefined ? values[p.key] : p.min;
      return (
        '<div class="control-group">' +
          '<label for="ctrl-' + p.key + '">' + p.label + '</label>' +
          '<div class="control-row">' +
            '<input type="range" id="ctrl-' + p.key + '-range"' +
              ' min="' + p.min + '" max="' + p.max + '" step="' + p.step + '"' +
              ' value="' + v + '">' +
            '<input type="number" id="ctrl-' + p.key + '"' +
              ' min="' + p.min + '" max="' + p.max + '" step="' + p.step + '"' +
              ' value="' + v + '">' +
          '</div>' +
        '</div>'
      );
    }).join('') +
    '<div class="controls-actions">' +
      '<button class="btn btn-primary" id="apply-btn">Apply</button>' +
      '<button class="btn btn-secondary" id="reset-btn">Reset to defaults</button>' +
    '</div>';

    // Link each slider ↔ number input
    PARAMS.forEach(function (p) {
      const range  = document.getElementById('ctrl-' + p.key + '-range');
      const number = document.getElementById('ctrl-' + p.key);
      range.addEventListener('input',  function () { number.value = range.value; });
      number.addEventListener('input', function () { range.value  = number.value; });
    });

    document.getElementById('apply-btn').addEventListener('click', applyConfig);
    document.getElementById('reset-btn').addEventListener('click', function () {
      renderControls(originalDefaults);
      window.App.loadAnomalies(originalDefaults);
    });
  }

  function readConfig() {
    const config = {};
    PARAMS.forEach(function (p) {
      const el = document.getElementById('ctrl-' + p.key);
      config[p.key] = parseFloat(el.value);
    });
    return config;
  }

  async function applyConfig() {
    closeNewsPanel();
    await window.App.loadAnomalies(readConfig());
  }

  // -----------------------------------------------------------------------
  // Controls panel toggle
  // -----------------------------------------------------------------------

  function toggleControls() {
    const panel  = document.getElementById('controls-panel');
    const btn    = document.getElementById('controls-toggle');
    const isOpen = panel.classList.contains('open');
    panel.classList.toggle('open', !isOpen);
    btn.classList.toggle('active', !isOpen);
  }

  // -----------------------------------------------------------------------
  // News panel
  // -----------------------------------------------------------------------

  async function showNewsPanel(anomaly) {
    const panel    = document.getElementById('news-panel');
    const badge    = document.getElementById('news-type-badge');
    const dateEl   = document.getElementById('news-panel-date');
    const body     = document.getElementById('news-panel-body');
    const hint     = document.getElementById('click-hint');

    // Reveal panel
    panel.classList.remove('hidden');
    hint.classList.add('hidden');

    // Header
    const labels = { reversal: 'Reversal', amplification: 'Amplification', stagnation: 'Stagnation' };
    badge.textContent = labels[anomaly.type] || anomaly.type;
    badge.className   = 'news-type-badge ' + anomaly.type;
    dateEl.textContent = anomaly.date;

    // Loading state
    body.innerHTML =
      '<div class="news-loading"><div class="spinner"></div><span>Loading…</span></div>';

    try {
      const resp = await fetch(API_BASE + '/news/' + anomaly.id);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();

      if (!data.fetched) {
        renderFetchPrompt(body, anomaly);
      } else {
        renderArticles(body, anomaly, data.articles);
      }
    } catch (err) {
      body.innerHTML =
        '<div class="news-empty">Could not load news (' + err.message + ')</div>';
    }
  }

  function renderFetchPrompt(body, anomaly) {
    body.innerHTML =
      '<div class="news-unfetched">' +
        '<p>News has not been fetched for this anomaly yet.</p>' +
        '<button class="btn btn-primary" id="fetch-news-btn">Fetch from GDELT</button>' +
      '</div>';

    document.getElementById('fetch-news-btn').addEventListener('click', async function () {
      body.innerHTML =
        '<div class="news-loading"><div class="spinner"></div><span>Fetching from GDELT…</span></div>';
      try {
        const resp = await fetch(API_BASE + '/news/' + anomaly.id + '/fetch', { method: 'POST' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        renderArticles(body, anomaly, data.articles);
      } catch (err) {
        body.innerHTML =
          '<div class="news-empty">Fetch failed: ' + err.message + '</div>';
      }
    });
  }

  function renderArticles(body, anomaly, articles) {
    let meta;
    try {
      meta = typeof anomaly.metadata === 'string'
        ? JSON.parse(anomaly.metadata)
        : (anomaly.metadata || {});
    } catch (_) {
      meta = {};
    }

    const metaHtml = buildMetaHtml(anomaly.type, meta);

    if (!articles || articles.length === 0) {
      body.innerHTML =
        metaHtml +
        '<div class="news-empty">No news articles found for this period.<br>' +
        '<small>GDELT coverage extends ~1 year back.</small></div>';
      return;
    }

    const articleCards = articles.map(function (a) {
      const date = a.published_at ? a.published_at.slice(0, 10) : '';
      return (
        '<div class="article-card">' +
          '<div class="article-meta">' +
            '<span class="source-badge">' + escHtml(a.source_name) + '</span>' +
            '<span class="article-date">' + date + '</span>' +
          '</div>' +
          '<a class="article-title" href="' + escHtml(a.url) + '" target="_blank" rel="noopener noreferrer">' +
            escHtml(a.title) +
          '</a>' +
        '</div>'
      );
    }).join('');

    body.innerHTML =
      metaHtml +
      '<div class="articles-label">Top ' + articles.length + ' news articles</div>' +
      '<div class="articles-list">' + articleCards + '</div>';
  }

  function buildMetaHtml(type, meta) {
    let rows = '';

    if (type === 'reversal' || type === 'amplification') {
      const back = meta.backward_momentum != null
        ? (meta.backward_momentum * 100).toFixed(1) + '%' : '—';
      const fwd  = meta.forward_momentum != null
        ? (meta.forward_momentum * 100).toFixed(1) + '%' : '—';
      const dir  = type === 'amplification' && meta.direction
        ? ' (' + meta.direction + ')' : '';
      const price = meta.close != null
        ? '$' + Number(meta.close).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—';

      rows =
        '<div class="meta-row"><span>Prior momentum</span><span>' + back + '</span></div>' +
        '<div class="meta-row"><span>Forward momentum</span><span>' + fwd + dir + '</span></div>' +
        '<div class="meta-row"><span>Close price</span><span>' + price + '</span></div>';

    } else if (type === 'stagnation') {
      const start = meta.window_start || '—';
      const end   = meta.window_end   || '—';
      const vol   = meta.volatility != null
        ? (meta.volatility * 100).toFixed(3) + '%' : '—';

      rows =
        '<div class="meta-row"><span>Period start</span><span>' + start + '</span></div>' +
        '<div class="meta-row"><span>Period end</span><span>' + end + '</span></div>' +
        '<div class="meta-row"><span>Daily volatility</span><span>' + vol + '</span></div>';
    }

    return rows
      ? '<div class="anomaly-meta">' + rows + '</div>'
      : '';
  }

  function closeNewsPanel() {
    document.getElementById('news-panel').classList.add('hidden');
    document.getElementById('click-hint').classList.remove('hidden');
  }

  // -----------------------------------------------------------------------
  // Utilities
  // -----------------------------------------------------------------------

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

}());
