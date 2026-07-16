(function () {
  'use strict';

  const cfg = window.PDF_OFX_CONFIG || {};
  const apiBase = (cfg.apiBase || '/api').replace(/\/$/, '');
  const CONVERT_TIMEOUT_MS = 120000;

  const el = {
    fileInput: document.getElementById('pdfofx-file-input'),
    fileLabel: document.getElementById('pdfofx-file-label'),
    dropzone: document.getElementById('pdfofx-dropzone'),
    btnConverter: document.getElementById('pdfofx-btn-converter'),
    stateCard: document.getElementById('pdfofx-state-card'),
    alert: document.getElementById('pdfofx-alert'),
    previewSection: document.getElementById('pdfofx-preview-section'),
    contaInfo: document.getElementById('pdfofx-conta-info'),
    btnDownload: document.getElementById('pdfofx-btn-download'),
    metricTotal: document.getElementById('pdfofx-metric-total'),
    metricCreditos: document.getElementById('pdfofx-metric-creditos'),
    metricDebitos: document.getElementById('pdfofx-metric-debitos'),
    metricSaldo: document.getElementById('pdfofx-metric-saldo'),
    tableBody: document.getElementById('pdfofx-table-body'),
  };

  let selectedFile = null;
  let converting = false;

  function getCsrf() {
    return cfg.csrfToken || '';
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function showAlert(message, type) {
    if (!el.alert) return;
    const styles = {
      success: 'border-green-200 bg-green-50 text-green-800',
      error: 'border-red-200 bg-red-50 text-red-800',
      warning: 'border-amber-200 bg-amber-50 text-amber-900',
      info: 'border-primary-200 bg-primary-50 text-primary-900',
    };
    el.alert.className =
      'mt-4 rounded-lg border px-4 py-3 text-sm whitespace-pre-wrap ' + (styles[type] || styles.success);
    el.alert.textContent = message;
    el.alert.hidden = false;
    el.alert.classList.remove('hidden');
  }

  function hideAlert() {
    if (!el.alert) return;
    el.alert.hidden = true;
    el.alert.classList.add('hidden');
  }

  function setConverting(visible, label) {
    if (!el.stateCard) return;
    if (!visible) {
      el.stateCard.hidden = true;
      el.stateCard.classList.add('hidden');
      return;
    }
    el.stateCard.className =
      'ofx-state-card mt-4 rounded-lg border px-4 py-4 border-primary-200 bg-primary-50 dark:border-primary-800 dark:bg-primary-900/20 text-primary-900 dark:text-primary-300';
    el.stateCard.innerHTML =
      '<p class="text-sm font-semibold flex items-center gap-2">' +
      '<svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">' +
      '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
      '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>' +
      '</svg>' +
      escapeHtml(label || 'Convertendo…') +
      '</p>';
    el.stateCard.hidden = false;
    el.stateCard.classList.remove('hidden');
  }

  function showPreview(visible) {
    if (!el.previewSection) return;
    el.previewSection.hidden = !visible;
    el.previewSection.classList.toggle('hidden', !visible);
  }

  function formatMoney(value) {
    const n = Number(value) || 0;
    return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatDate(iso) {
    if (!iso) return '—';
    const parts = String(iso).split('-');
    if (parts.length !== 3) return iso;
    return parts[2] + '/' + parts[1] + '/' + parts[0];
  }

  function renderRow(txn) {
    const isCredit = txn.tipo === 'credit';
    const amtClass = isCredit ? 'ofx-amount--credit' : 'ofx-amount--debit';
    const sign = isCredit ? '+' : '−';
    return (
      '<tr>' +
      '<td class="whitespace-nowrap">' + escapeHtml(formatDate(txn.data)) + '</td>' +
      '<td class="ofx-col-amount ' + amtClass + '">' + sign + ' ' + escapeHtml(formatMoney(Math.abs(txn.valor))) + '</td>' +
      '<td class="max-w-md truncate" title="' + escapeHtml(txn.descricao) + '">' + escapeHtml(txn.descricao || '—') + '</td>' +
      '</tr>'
    );
  }

  function renderTable(amostraInicio, amostraFim, total) {
    if (!el.tableBody) return;
    const rows = [];
    (amostraInicio || []).forEach(function (t) {
      rows.push(renderRow(t));
    });
    if (total > (amostraInicio || []).length + (amostraFim || []).length) {
      rows.push(
        '<tr class="ofx-table-empty"><td colspan="3" class="px-4 py-3 text-center text-stone-400">⋯</td></tr>',
      );
    }
    (amostraFim || []).forEach(function (t) {
      rows.push(renderRow(t));
    });
    el.tableBody.innerHTML = rows.join('') ||
      '<tr class="ofx-table-empty"><td colspan="3" class="px-4 py-12 text-center text-stone-400">Nenhum lançamento.</td></tr>';
  }

  function getSelectedBanco() {
    const checked = document.querySelector('input[name="pdfofx-banco"]:checked');
    return checked ? checked.value : 'bradesco';
  }

  function updateFileLabel() {
    if (!el.fileLabel) return;
    el.fileLabel.textContent = selectedFile ? selectedFile.name : 'Selecione o PDF do extrato';
  }

  async function apiFetch(path, options) {
    const opts = Object.assign(
      { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } },
      options || {},
    );
    if (opts.method && opts.method !== 'GET') {
      opts.headers['X-CSRFToken'] = getCsrf();
    }
    return fetch(apiBase + path, opts);
  }

  async function readJsonResponse(res) {
    const text = await res.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (err) {
      throw new Error('Resposta inválida do servidor (HTTP ' + res.status + ').');
    }
  }

  async function converterPdf() {
    if (converting) return;
    if (!selectedFile) {
      showAlert('Selecione um arquivo PDF antes de converter.', 'warning');
      return;
    }

    converting = true;
    if (el.btnConverter) el.btnConverter.disabled = true;
    hideAlert();
    showPreview(false);
    setConverting(true, 'Convertendo extrato em PDF para OFX…');

    try {
      const form = new FormData();
      form.append('banco', getSelectedBanco());
      form.append('arquivo', selectedFile);

      const controller = new AbortController();
      const timer = setTimeout(function () {
        controller.abort();
      }, CONVERT_TIMEOUT_MS);

      let res;
      try {
        res = await apiFetch('/converter', {
          method: 'POST',
          body: form,
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }

      const data = await readJsonResponse(res);
      if (!res.ok) {
        throw new Error(data.error || 'Não foi possível converter o arquivo.');
      }

      if (el.contaInfo) {
        el.contaInfo.textContent =
          data.bancoNome + ' · Conta ' + data.conta + ' · Período ' +
          formatDate(data.periodo.inicio) + ' a ' + formatDate(data.periodo.fim);
      }
      if (el.metricTotal) el.metricTotal.textContent = data.totais.transacoes;
      if (el.metricCreditos) el.metricCreditos.textContent = formatMoney(data.totais.creditos);
      if (el.metricDebitos) el.metricDebitos.textContent = formatMoney(data.totais.debitos);
      if (el.metricSaldo) el.metricSaldo.textContent = formatMoney(data.totais.saldo);
      if (el.btnDownload) {
        el.btnDownload.href = apiBase + '/' + data.downloadId + '/baixar';
      }

      renderTable(data.amostraInicio, data.amostraFim, data.totais.transacoes);
      showPreview(true);
      showAlert('Conversão concluída: ' + data.totais.transacoes + ' lançamento(s) encontrados.', 'success');
    } catch (err) {
      if (err.name === 'AbortError') {
        showAlert('Tempo esgotado ao converter o arquivo. Tente novamente.', 'error');
      } else {
        showAlert(err.message || 'Erro ao converter o arquivo.', 'error');
      }
    } finally {
      converting = false;
      if (el.btnConverter) el.btnConverter.disabled = false;
      setConverting(false);
    }
  }

  function bindEvents() {
    if (el.fileInput) {
      el.fileInput.addEventListener('change', function () {
        const files = el.fileInput.files;
        selectedFile = files && files.length ? files[0] : null;
        updateFileLabel();
      });
    }
    if (el.dropzone && el.fileInput) {
      el.dropzone.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          el.fileInput.click();
        }
      });
    }
    if (el.btnConverter) {
      el.btnConverter.addEventListener('click', converterPdf);
    }
  }

  bindEvents();
})();
