(function () {
  'use strict';

  var KEY = 'analisegroup-theme';

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function syncToggleButtons(isDark) {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
      btn.setAttribute('aria-label', isDark ? 'Ativar modo claro' : 'Ativar modo escuro');
      btn.title = isDark ? 'Modo claro' : 'Modo escuro';
    });
  }

  function applyTheme(theme) {
    var isDark = theme === 'dark';
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    document.documentElement.classList.toggle('dark', isDark);
    try {
      localStorage.setItem(KEY, isDark ? 'dark' : 'light');
    } catch (e) { /* ignore */ }
    syncToggleButtons(isDark);
  }

  function toggleTheme() {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  }

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-theme-toggle]')) {
      toggleTheme();
    }
  });

  syncToggleButtons(currentTheme() === 'dark');
})();
