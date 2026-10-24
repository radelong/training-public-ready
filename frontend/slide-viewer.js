(() => {
  'use strict';

  const version = '20261022-one-slide-1';
  const instances = new Set();
  const pendingHosts = new Set();
  const pageByModule = new Map();
  let pdfjsPromise;

  function loadPdfjs() {
    if (!pdfjsPromise) {
      pdfjsPromise = import(`/static/vendor/pdfjs/pdf.mjs?v=${version}`).then(pdfjs => {
        pdfjs.GlobalWorkerOptions.workerSrc = `/static/vendor/pdfjs/pdf.worker.mjs?v=${version}`;
        return pdfjs;
      });
    }
    return pdfjsPromise;
  }

  function instanceFor(host) {
    return [...instances].find(instance => instance.host === host);
  }

  function setStatus(instance, message, error = false) {
    const status = instance.host.querySelector('[data-slide-status]');
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
    status.classList.toggle('slide-status-error', error);
  }

  function updateControls(instance) {
    const { host, pageNumber, pdf } = instance;
    const total = pdf?.numPages || 0;
    const input = host.querySelector('[data-slide-page]');
    const count = host.querySelector('[data-slide-total]');
    const previous = host.querySelector('[data-slide-action="previous"]');
    const next = host.querySelector('[data-slide-action="next"]');
    const progress = host.querySelector('[data-slide-progress]');
    const bar = host.querySelector('[data-slide-progress-bar]');

    if (input) {
      input.value = String(pageNumber);
      input.max = String(Math.max(total, 1));
      input.disabled = total < 2;
    }
    if (count) count.textContent = total ? String(total) : '—';
    if (previous) previous.disabled = !total || pageNumber <= 1;
    if (next) next.disabled = !total || pageNumber >= total;
    if (progress) progress.setAttribute('aria-valuenow', total ? String(Math.round(pageNumber / total * 100)) : '0');
    if (bar) bar.style.width = total ? `${pageNumber / total * 100}%` : '0%';

    const stage = host.querySelector('[data-slide-stage]');
    if (stage) stage.setAttribute('aria-label', total ? `Slide ${pageNumber} of ${total}` : 'Slide viewer');
  }

  async function renderPage(instance) {
    if (!instance.pdf || !instance.host.isConnected) return;
    const pageNumber = Math.max(1, Math.min(instance.pdf.numPages, instance.pageNumber));
    instance.pageNumber = pageNumber;
    pageByModule.set(instance.moduleKey, pageNumber);
    updateControls(instance);

    if (instance.renderTask) {
      instance.renderTask.cancel();
      instance.renderTask = null;
    }
    const renderId = ++instance.renderId;
    const stage = instance.host.querySelector('[data-slide-stage]');
    const canvas = instance.host.querySelector('[data-slide-canvas]');
    const text = instance.host.querySelector('[data-slide-accessible]');
    if (!stage || !canvas) return;

    try {
      const page = await instance.pdf.getPage(pageNumber);
      if (renderId !== instance.renderId || !instance.host.isConnected) return;
      const original = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(240, stage.clientWidth - 40);
      const availableHeight = Math.max(180, stage.clientHeight - 40);
      const fit = Math.min(availableWidth / original.width, availableHeight / original.height);
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale: fit * pixelRatio });
      const cssWidth = Math.round(original.width * fit);
      const cssHeight = Math.round(original.height * fit);

      canvas.width = Math.max(1, Math.round(viewport.width));
      canvas.height = Math.max(1, Math.round(viewport.height));
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${cssHeight}px`;
      canvas.hidden = false;
      const context = canvas.getContext('2d', { alpha: false });
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);

      const task = page.render({ canvasContext: context, viewport });
      instance.renderTask = task;
      await task.promise;
      if (renderId !== instance.renderId || !instance.host.isConnected) return;

      if (text) {
        const content = await page.getTextContent();
        text.textContent = content.items.map(item => item.str).filter(Boolean).join(' ');
      }
      setStatus(instance, '');
    } catch (error) {
      if (error?.name === 'RenderingCancelledException' || renderId !== instance.renderId) return;
      setStatus(instance, 'This slide could not be displayed. Open the original PDF to continue.', true);
      canvas.hidden = true;
    }
  }

  async function mount(host) {
    if (!host || instanceFor(host)) return;
    const assetId = host.dataset.assetId;
    const moduleKey = host.dataset.moduleKey || assetId;
    const instance = {
      host,
      assetId,
      moduleKey,
      pageNumber: pageByModule.get(moduleKey) || 1,
      pdf: null,
      loadingTask: null,
      renderTask: null,
      renderId: 0,
      resizeObserver: null,
    };
    instances.add(instance);
    updateControls(instance);

    const stage = host.querySelector('[data-slide-stage]');
    if (stage && 'ResizeObserver' in window) {
      instance.resizeObserver = new ResizeObserver(() => {
        if (instance.pdf) renderPage(instance);
      });
      instance.resizeObserver.observe(stage);
      stage.addEventListener('click', event => {
        if (event.target.closest('canvas')) stage.focus({ preventScroll: true });
      });
    }

    try {
      const pdfjs = await loadPdfjs();
      if (!host.isConnected) return;
      const url = `/api/content/${encodeURIComponent(assetId)}`;
      instance.loadingTask = pdfjs.getDocument({
        url,
        cMapUrl: '/static/vendor/pdfjs/cmaps/',
        cMapPacked: true,
        standardFontDataUrl: '/static/vendor/pdfjs/standard_fonts/',
        useSystemFonts: true,
        useWasm: false,
      });
      instance.pdf = await instance.loadingTask.promise;
      if (!host.isConnected) return;
      updateControls(instance);
      await renderPage(instance);
    } catch (error) {
      if (!host.isConnected) return;
      const canvas = host.querySelector('[data-slide-canvas]');
      if (canvas) canvas.hidden = true;
      setStatus(instance, 'Slides could not be loaded. Check your connection, or open the original PDF.', true);
    }
  }

  function unmount(instance) {
    if (instance.renderTask) instance.renderTask.cancel();
    instance.resizeObserver?.disconnect();
    instance.loadingTask?.destroy();
    instances.delete(instance);
  }

  function mountAll(root = document) {
    root.querySelectorAll('[data-slide-viewer]').forEach(host => {
      if (instanceFor(host) || pendingHosts.has(host)) return;
      if (deckObserver) {
        pendingHosts.add(host);
        deckObserver.observe(host);
      } else mount(host);
    });
  }

  const deckObserver = 'IntersectionObserver' in window
    ? new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        deckObserver.unobserve(entry.target);
        pendingHosts.delete(entry.target);
        mount(entry.target);
      }
    }, { rootMargin: '240px 0px' })
    : null;

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-slide-action]');
    if (!button) return;
    const host = button.closest('[data-slide-viewer]');
    const instance = host && instanceFor(host);
    if (!instance) return;

    if (button.dataset.slideAction === 'previous' && instance.pageNumber > 1) {
      instance.pageNumber -= 1;
      renderPage(instance);
    } else if (button.dataset.slideAction === 'next' && instance.pdf && instance.pageNumber < instance.pdf.numPages) {
      instance.pageNumber += 1;
      renderPage(instance);
    } else if (button.dataset.slideAction === 'fullscreen') {
      if (document.fullscreenElement === host) document.exitFullscreen?.();
      else host.requestFullscreen?.();
    }
  });

  document.addEventListener('change', event => {
    const input = event.target.closest('[data-slide-page]');
    if (!input) return;
    const host = input.closest('[data-slide-viewer]');
    const instance = host && instanceFor(host);
    if (!instance?.pdf) return;
    const nextPage = Number(input.value);
    if (!Number.isInteger(nextPage) || nextPage < 1 || nextPage > instance.pdf.numPages) {
      input.value = String(instance.pageNumber);
      return;
    }
    instance.pageNumber = nextPage;
    renderPage(instance);
  });

  document.addEventListener('keydown', event => {
    const host = event.target.closest?.('[data-slide-viewer]');
    const instance = host && instanceFor(host);
    if (!instance?.pdf || event.target.matches('input, textarea, select, button')) return;
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      if (instance.pageNumber > 1) {
        event.preventDefault();
        instance.pageNumber -= 1;
        renderPage(instance);
      }
    } else if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      if (instance.pageNumber < instance.pdf.numPages) {
        event.preventDefault();
        instance.pageNumber += 1;
        renderPage(instance);
      }
    }
  });

  const cleanupObserver = new MutationObserver(() => {
    for (const instance of [...instances]) {
      if (!instance.host.isConnected) unmount(instance);
    }
    for (const host of [...pendingHosts]) {
      if (!host.isConnected) {
        deckObserver?.unobserve(host);
        pendingHosts.delete(host);
      }
    }
  });
  if (document.body) cleanupObserver.observe(document.body, { childList: true, subtree: true });
  window.AcademySlideViewer = { mountAll };
})();
