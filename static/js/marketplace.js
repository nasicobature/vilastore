// ===== MARKETPLACE JS (Server-backed) =====
document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const form = document.getElementById('filterForm');
  const categoryInput = document.getElementById('categoryInput');
  const locationInput = document.getElementById('locationInput');
  const clearBtn = document.getElementById('clearFiltersBtn');

  document.querySelectorAll('[data-filter="category"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      categoryInput.value = btn.getAttribute('data-value') || '';
      form.submit();
    });
  });

  document.querySelectorAll('[data-filter="location"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      locationInput.value = btn.getAttribute('data-value') || '';
      form.submit();
    });
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      document.getElementById('shopSearch').value = '';
      categoryInput.value = '';
      locationInput.value = '';
      const verified = form.querySelector('input[name="verified"]');
      if (verified) verified.checked = false;
      const sort = form.querySelector('select[name="sort"]');
      if (sort) sort.value = 'rating';
      form.submit();
    });
  }

  form.addEventListener('change', function (e) {
    if (e.target && (e.target.name === 'verified' || e.target.name === 'sort')) {
      form.submit();
    }
  });
});
