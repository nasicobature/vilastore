document.addEventListener('DOMContentLoaded', function() {
  initMobileDashboardNav();
  initFloatingCart();
  lucide.createIcons();
});

function initMobileDashboardNav() {
  const appContainer = document.querySelector('.app-container');
  const sidebar = appContainer ? appContainer.querySelector(':scope > .sidebar') : null;
  const mainContent = appContainer ? appContainer.querySelector(':scope > .main-content') : null;

  if (!appContainer || !sidebar || !mainContent || document.querySelector('.mobile-topbar')) {
    return;
  }

  const pageTitleNode = mainContent.querySelector('.page-header h1, h1');
  const pageSubtitleNode = mainContent.querySelector('.page-header p, .page-header-content p');
  const activeLink = sidebar.querySelector('.nav-link.active');
  const fallbackTitleNode = activeLink ? activeLink.querySelector('span') : null;

  const pageTitle = pageTitleNode ? pageTitleNode.textContent.trim() : '';
  const pageSubtitle = pageSubtitleNode ? pageSubtitleNode.textContent.trim() : '';
  const fallbackTitle = fallbackTitleNode ? fallbackTitleNode.textContent.trim() : 'VilaStore';

  const topbar = document.createElement('div');
  topbar.className = 'mobile-topbar';
  topbar.innerHTML = `
    <button type="button" class="mobile-menu-btn" aria-label="Open menu" aria-expanded="false">
      <i data-lucide="menu"></i>
    </button>
    <div class="mobile-topbar-brand">
      <div class="mobile-topbar-logo" aria-hidden="true"></div>
      <div class="mobile-topbar-copy">
        <span class="mobile-topbar-label">VilaStore</span>
        <strong class="mobile-topbar-title">${escapeHtml(pageTitle || fallbackTitle)}</strong>
        <span class="mobile-topbar-subtitle">${escapeHtml(pageSubtitle || 'Navigate your store tools from the menu')}</span>
      </div>
    </div>
  `;

  const backdrop = document.createElement('button');
  backdrop.type = 'button';
  backdrop.className = 'mobile-nav-backdrop';
  backdrop.setAttribute('aria-label', 'Close menu');

  document.body.appendChild(topbar);
  document.body.appendChild(backdrop);

  const menuButton = topbar.querySelector('.mobile-menu-btn');

  function isMobileLayout() {
    return window.innerWidth <= 900;
  }

  function closeMenu() {
    document.body.classList.remove('mobile-nav-open');
    if (menuButton) {
      menuButton.setAttribute('aria-expanded', 'false');
    }
  }

  function openMenu() {
    if (!isMobileLayout()) {
      return;
    }
    document.body.classList.add('mobile-nav-open');
    if (menuButton) {
      menuButton.setAttribute('aria-expanded', 'true');
    }
  }

  function syncLayout() {
    if (!isMobileLayout()) {
      closeMenu();
    }
  }

  if (menuButton) {
    menuButton.addEventListener('click', function() {
      if (document.body.classList.contains('mobile-nav-open')) {
        closeMenu();
      } else {
        openMenu();
      }
    });
  }

  backdrop.addEventListener('click', closeMenu);

  sidebar.querySelectorAll('.nav-link').forEach(function(link) {
    link.addEventListener('click', function() {
      closeMenu();
    });
  });

  window.addEventListener('resize', syncLayout);
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      closeMenu();
    }
  });

  syncLayout();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function initFloatingCart() {
  const openButton = document.querySelector('[data-floating-cart-open]');
  const panel = document.getElementById('floatingCartPanel');
  const closeControls = document.querySelectorAll('[data-floating-cart-close]');

  if (!openButton || !panel) {
    return;
  }

  function openCart() {
    document.body.classList.add('floating-cart-open');
    openButton.setAttribute('aria-expanded', 'true');
    panel.setAttribute('tabindex', '-1');
    panel.focus({ preventScroll: true });
  }

  function closeCart() {
    document.body.classList.remove('floating-cart-open');
    openButton.setAttribute('aria-expanded', 'false');
  }

  openButton.addEventListener('click', openCart);
  closeControls.forEach(function(control) {
    control.addEventListener('click', closeCart);
  });

  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      closeCart();
    }
  });
}

let currentProductId = null;
let currentQuantity = 1;
let currentProductStock = 0;
let currentSellingPrice = 0;
let currentCostPrice = 0;

function openSellModal(id, name, sellingPrice, costPrice, stock) {
  if (stock === 0) return;

  currentProductId = id;
  currentQuantity = 1;
  currentProductStock = stock;
  currentSellingPrice = sellingPrice;
  currentCostPrice = costPrice;

  updateSellModalDisplay();

  document.getElementById('sellModal').classList.add('active');
}

function closeSellModal() {
  document.getElementById('sellModal').classList.remove('active');
}

function updateSellModalDisplay() {
  document.getElementById('sellProductName').textContent = currentProductId;
  document.getElementById('sellProductPrice').textContent = "₦" + currentSellingPrice + " per unit";
  document.getElementById('sellQuantity').textContent = currentQuantity;
  document.getElementById('sellTotal').textContent = "₦" + (currentSellingPrice * currentQuantity);
  document.getElementById('sellProfit').textContent = "+₦" + ((currentSellingPrice - currentCostPrice) * currentQuantity);
}

function updateQuantity(delta) {
  const newQty = currentQuantity + delta;

  if (newQty >= 1 && newQty <= currentProductStock) {
    currentQuantity = newQty;
    updateSellModalDisplay();
  }
}

function completeSale() {
  fetch('/api/create-sale/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken')
    },
    body: JSON.stringify({
      product_id: currentProductId,
      quantity: currentQuantity
    })
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      closeSellModal();
      location.reload();   // simple + clean
    } else {
      alert(data.error);
    }
  });
}
