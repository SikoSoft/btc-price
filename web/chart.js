/**
 * chart.js — TradingView Lightweight Charts integration
 *
 * Responsibilities:
 *   - Initialize the candlestick chart
 *   - Fetch and render OHLCV price data
 *   - Render anomaly markers (reversals, amplifications, stagnations)
 *   - Handle click events and delegate to controls.js via window.onAnomalyClick
 *
 * Exposes:
 *   window.App.loadAnomalies(config) — called by controls.js after param changes
 */

(function () {
  'use strict';

  const API_BASE = window.API_BASE || 'http://localhost:8000';

  let chart = null;
  let candleSeries = null;
  let allAnomalies = [];

  // -----------------------------------------------------------------------
  // Initialisation
  // -----------------------------------------------------------------------

  async function initChart() {
    const container = document.getElementById('chart');

    chart = LightweightCharts.createChart(container, {
      width:  container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: 'solid', color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#363a45',
      },
      timeScale: {
        borderColor: '#363a45',
        timeVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: true,
      handleScale: true,
    });

    candleSeries = chart.addCandlestickSeries({
      upColor:       '#26a69a',
      downColor:     '#ef5350',
      borderVisible: false,
      wickUpColor:   '#26a69a',
      wickDownColor: '#ef5350',
    });

    // Keep chart sized to its container
    const ro = new ResizeObserver(() => {
      chart.applyOptions({
        width:  container.clientWidth,
        height: container.clientHeight,
      });
    });
    ro.observe(container);

    // Anomaly click detection
    chart.subscribeClick(function (param) {
      if (!param.time) return;
      const dateStr = utcToDateStr(param.time);
      const anomaly = findNearest(dateStr, 4);
      if (anomaly && window.onAnomalyClick) {
        window.onAnomalyClick(anomaly);
      }
    });

    await loadPrices();
  }

  // -----------------------------------------------------------------------
  // Price data
  // -----------------------------------------------------------------------

  async function loadPrices() {
    setLoading(true, 'Loading price data…');
    try {
      const resp = await fetch(`${API_BASE}/prices`);
      if (!resp.ok) throw new Error(`/prices returned ${resp.status}`);
      const data = await resp.json();

      const candles = data.prices.map(function (p) {
        return { time: p.date, open: p.open, high: p.high, low: p.low, close: p.close };
      });

      candleSeries.setData(candles);
      chart.timeScale().fitContent();
    } catch (err) {
      showError('Failed to load price data. Is the API server running?');
      throw err;
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------------------------------------------------
  // Anomaly markers
  // -----------------------------------------------------------------------

  async function loadAnomalies(config) {
    config = config || {};
    setLoading(true, 'Calculating anomalies…');
    clearError();
    try {
      const resp = await fetch(`${API_BASE}/anomalies`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(config),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(function () { return {}; });
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();

      allAnomalies = [].concat(data.reversals, data.amplifications, data.stagnations);
      renderMarkers(allAnomalies);
      return data;
    } catch (err) {
      showError('Anomaly detection failed: ' + err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }

  function renderMarkers(anomalies) {
    var markers = anomalies.map(function (a) {
      var color, shape, position;

      if (a.type === 'reversal') {
        color    = '#ef5350';
        shape    = 'arrowDown';
        position = 'aboveBar';
      } else if (a.type === 'amplification') {
        color    = '#26a69a';
        shape    = 'arrowUp';
        position = 'belowBar';
      } else {
        color    = '#ffb300';
        shape    = 'circle';
        position = 'aboveBar';
      }

      return {
        time:     a.date,
        position: position,
        color:    color,
        shape:    shape,
        size:     1,
        id:       a.id,
      };
    });

    // Lightweight Charts requires markers sorted by time
    markers.sort(function (a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });

    candleSeries.setMarkers(markers);
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  function utcToDateStr(utcSeconds) {
    // lightweight-charts returns click time as seconds since Unix epoch
    if (typeof utcSeconds === 'number') {
      return new Date(utcSeconds * 1000).toISOString().slice(0, 10);
    }
    return String(utcSeconds);
  }

  function findNearest(dateStr, thresholdDays) {
    var clickMs = new Date(dateStr).getTime();
    var best    = null;
    var bestDiff = Infinity;
    var msPerDay = 86400000;

    for (var i = 0; i < allAnomalies.length; i++) {
      var a    = allAnomalies[i];
      var diff = Math.abs(new Date(a.date).getTime() - clickMs) / msPerDay;
      if (diff < thresholdDays && diff < bestDiff) {
        bestDiff = diff;
        best     = a;
      }
    }

    return best;
  }

  function setLoading(visible, msg) {
    var overlay = document.getElementById('loading-overlay');
    var msgEl   = document.getElementById('loading-msg');
    overlay.hidden = !visible;
    if (msg && msgEl) msgEl.textContent = msg;
  }

  function showError(msg) {
    var banner = document.getElementById('error-banner');
    banner.textContent = msg;
    banner.hidden = false;
  }

  function clearError() {
    var banner = document.getElementById('error-banner');
    banner.hidden = true;
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  window.App = window.App || {};
  window.App.loadAnomalies = loadAnomalies;

  // Boot on DOMContentLoaded; expose the promise so controls.js can await it
  window.App.chartReady = null;
  document.addEventListener('DOMContentLoaded', function () {
    window.App.chartReady = initChart();
  });

}());
