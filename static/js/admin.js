// ===== ADMIN JS =====
const INVESTORS_KEY = 'vilastore_investors';

document.addEventListener('DOMContentLoaded', function() {
  if (window.lucide) {
    lucide.createIcons();
  }

  updateAdminDashboard();
  renderInvestors();
  renderAdminShopBoys();

  const investorForm = document.getElementById('investorForm');
  if (investorForm && investorForm.dataset.jsSubmit === 'true') {
    investorForm.addEventListener('submit', handleInvestorSubmit);
  }
});

function switchAdminTab(tab) {
  ['dashboard', 'investors', 'staff', 'shopboys', 'feedback'].forEach(t => {
    const panel = document.getElementById('tab-' + t);
    if (!panel) return;
    panel.style.display = t === tab ? 'block' : 'none';
  });
  document.querySelectorAll('.tax-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  if (window.lucide) {
    lucide.createIcons();
  }
}

function updateAdminDashboard() {
  const revenueEl = document.getElementById('adminRevenue');
  const profitEl = document.getElementById('adminProfit');
  if (!revenueEl && !profitEl) {
    return;
  }

  if (typeof getSales !== 'function' || typeof formatCurrency !== 'function') {
    return;
  }

  const sales = getSales();
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const monthlySales = sales.filter(s => new Date(s.date) >= monthStart);
  const revenue = monthlySales.reduce((s, x) => s + x.totalPrice, 0);
  const profit = revenue * 0.6; // 60% margin estimate
  const investors = JSON.parse(localStorage.getItem(INVESTORS_KEY) || '[]');
  const shops = JSON.parse(localStorage.getItem('vilastore_marketplace_shops') || '[]');

  if (revenueEl) {
    revenueEl.textContent = formatCurrency(revenue);
  }
  if (profitEl) {
    profitEl.textContent = formatCurrency(profit);
  }

  const shopsEl = document.getElementById('adminShops');
  if (shopsEl) {
    shopsEl.textContent = shops.length;
  }

  const investorsEl = document.getElementById('adminInvestors');
  if (investorsEl) {
    investorsEl.textContent = investors.length;
  }
}

function getInvestors() { return JSON.parse(localStorage.getItem(INVESTORS_KEY) || '[]'); }
function saveInvestors(data) { localStorage.setItem(INVESTORS_KEY, JSON.stringify(data)); }

function renderInvestors() {
  const tbody = document.getElementById('investorTableBody');
  if (tbody && tbody.dataset && tbody.dataset.source === 'django') {
    return;
  }
  if (!tbody) {
    return;
  }

  const investors = getInvestors();
  if (investors.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><p>No investors yet</p></td></tr>';
    return;
  }

  let monthlyProfit = 0;
  if (typeof getSales === 'function') {
    const sales = getSales();
    const now = new Date();
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    monthlyProfit = sales.filter(s => new Date(s.date) >= monthStart).reduce((s, x) => s + x.totalPrice, 0) * 0.6;
  }

  const currency = typeof formatCurrency === 'function' ? formatCurrency : (value => value);

  tbody.innerHTML = investors.map(inv => {
    const monthlyReturn = monthlyProfit * (inv.ownership / 100);
    return `<tr>
      <td><strong>${inv.name}</strong></td>
      <td>${inv.email}</td>
      <td>${currency(inv.amount)}</td>
      <td>${inv.ownership}%</td>
      <td class="text-profit">${currency(monthlyReturn)}</td>
      <td><div class="action-buttons">
        <button class="btn btn-ghost btn-sm text-destructive" onclick="deleteInvestor('${inv.id}')"><i data-lucide="trash-2"></i></button>
      </div></td>
    </tr>`;
  }).join('');
  if (window.lucide) {
    lucide.createIcons();
  }
}

function openInvestorModal() {
  document.getElementById('investorForm').reset();
  document.getElementById('investorModal').classList.add('active');
  if (window.lucide) {
    lucide.createIcons();
  }
}

function closeInvestorModal() { document.getElementById('investorModal').classList.remove('active'); }

function handleInvestorSubmit(e) {
  e.preventDefault();
  if (typeof generateId !== 'function') {
    return;
  }

  const investors = getInvestors();
  investors.push({
    id: generateId(),
    name: document.getElementById('invName').value,
    email: document.getElementById('invEmail').value,
    amount: parseFloat(document.getElementById('invAmount').value),
    ownership: parseFloat(document.getElementById('invOwnership').value),
    loginPin: document.getElementById('invPin').value,
    createdAt: new Date().toISOString(),
  });
  saveInvestors(investors);
  closeInvestorModal();
  renderInvestors();
  updateAdminDashboard();
  if (typeof showToast === 'function') {
    showToast('Investor added');
  }
}

function deleteInvestor(id) {
  if (confirm('Delete this investor?')) {
    saveInvestors(getInvestors().filter(i => i.id !== id));
    renderInvestors();
    updateAdminDashboard();
    if (typeof showToast === 'function') {
      showToast('Investor deleted');
    }
  }
}

function renderAdminShopBoys() {
  const tbody = document.getElementById('adminShopBoyTable');
  if (!tbody) {
    return;
  }

  const boys = JSON.parse(localStorage.getItem('vilastore_shopboys') || '[]');
  if (boys.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state"><p>No shop boys registered</p></td></tr>';
    return;
  }
  tbody.innerHTML = boys.map(sb => `<tr>
    <td><strong>${sb.fullName}</strong></td>
    <td>${sb.username}</td>
    <td>${sb.canHandleMarketplace ? '<span class="badge badge-success">Yes</span>' : '<span class="badge badge-warning">No</span>'}</td>
    <td><span class="badge badge-success">Active</span></td>
  </tr>`).join('');
  if (window.lucide) {
    lucide.createIcons();
  }
}

document.querySelectorAll('.modal-overlay').forEach(o => o.addEventListener('click', e => { if (e.target === o) o.classList.remove('active'); }));
