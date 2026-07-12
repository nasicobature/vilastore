document.addEventListener('DOMContentLoaded', function() {
  initMobileDashboardNav();
  initFloatingCart();
  initPriceSearch();
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
    syncFloatingCartState();
    if (openButton.hidden) {
      return;
    }
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
  window.addEventListener('vilastore:cart-updated', function(event) {
    const count = event && event.detail ? event.detail.count : undefined;
    syncFloatingCartState(count);
  });
  closeControls.forEach(function(control) {
    control.addEventListener('click', closeCart);
  });

  const cartObserver = new MutationObserver(function() {
    syncFloatingCartState();
  });
  cartObserver.observe(panel, { childList: true, subtree: true });

  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      closeCart();
    }
  });

  syncFloatingCartState();
}

function cartQuantityFromNode(node) {
  if (!node) return 0;
  const quantity = Number(node.dataset.productQuantity || node.getAttribute('data-product-quantity') || 1);
  return Number.isFinite(quantity) && quantity > 0 ? quantity : 1;
}

function syncFloatingCartState(overrideCount) {
  const openButton = document.querySelector('[data-floating-cart-open]');
  const panel = document.getElementById('floatingCartPanel');
  if (!openButton || !panel) return;

  const badge = openButton.querySelector('.floating-cart-badge');
  let count = Number(overrideCount);

  if (!Number.isFinite(count)) {
    const serverCount = Array.from(panel.querySelectorAll('[data-offline-cart-item]'))
      .reduce((sum, item) => sum + cartQuantityFromNode(item), 0);
    const offlineCount = Array.from(panel.querySelectorAll('[data-offline-cart-row]'))
      .reduce((sum, item) => sum + cartQuantityFromNode(item), 0);
    count = Math.max(serverCount, offlineCount);
  }

  count = Math.max(0, count);

  if (badge) {
    badge.textContent = count % 1 === 0 ? String(count) : String(Number(count.toFixed(2)));
  }

  openButton.hidden = count <= 0;
  openButton.classList.toggle('floating-cart-button-empty', count <= 0);

  if (count <= 0 && document.body.classList.contains('floating-cart-open')) {
    document.body.classList.remove('floating-cart-open');
    openButton.setAttribute('aria-expanded', 'false');
  }
}

window.VilaStoreCart = {
  sync: syncFloatingCartState
};

function normalizePriceToCents(value) {
  const cleaned = String(value || '').replace(/[^\d.]/g, '');
  if (!cleaned) return null;
  const parts = cleaned.split('.');
  const normalized = parts.length > 1 ? `${parts[0]}.${parts.slice(1).join('')}` : parts[0];
  const amount = Number(normalized);
  if (!Number.isFinite(amount)) return null;
  return Math.round(amount * 100);
}

function formatPrice(value) {
  const amount = Number(String(value || '').replace(/[^\d.-]/g, ''));
  if (!Number.isFinite(amount)) return String(value || '0');
  return amount.toLocaleString(undefined, {
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2
  });
}

function productImageMarkup(product) {
  if (product.image) {
    return `<img src="${escapeHtml(product.image)}" alt="">`;
  }
  return '<div class="price-search-placeholder"><i data-lucide="package"></i></div>';
}

function renderPriceSearchResults(panel, products, query) {
  const results = panel.querySelector('[data-price-search-results]');
  if (!results) return;

  if (!query.trim()) {
    results.innerHTML = '';
    panel.classList.remove('price-search-active');
    return;
  }

  panel.classList.add('price-search-active');

  if (!products.length) {
    results.innerHTML = '<div class="price-search-empty">No products found at this price.</div>';
    return;
  }

  results.innerHTML = products.map(function(product) {
    const disabled = product.stock <= 0 ? ' disabled aria-disabled="true"' : '';
    const stockText = product.stock % 1 === 0 ? String(product.stock) : String(Number(product.stock.toFixed(2)));
    return `
      <button type="button" class="price-search-result" data-price-search-product-id="${escapeHtml(product.id)}"${disabled}>
        <span class="price-search-thumb">${productImageMarkup(product)}</span>
        <span class="price-search-copy">
          <strong>${escapeHtml(product.name)}</strong>
          <span>${escapeHtml(product.category)}</span>
          <small>${escapeHtml(stockText)} in stock</small>
        </span>
        <span class="price-search-price">₦${escapeHtml(formatPrice(product.price))}</span>
      </button>
    `;
  }).join('');

  if (window.lucide) {
    lucide.createIcons();
  }
}

function initPriceSearch() {
  document.querySelectorAll('[data-price-search]').forEach(function(panel) {
    const input = panel.querySelector('[data-price-search-input]');
    if (!input) return;

    const products = Array.from(document.querySelectorAll('[data-offline-product]')).map(function(card) {
      return {
        id: card.dataset.productId || '',
        name: card.dataset.productName || 'Product',
        price: card.dataset.productPrice || '0',
        priceCents: normalizePriceToCents(card.dataset.productPrice),
        stock: Number(card.dataset.productStock || 0),
        category: card.dataset.productCategory || 'Uncategorized',
        image: card.dataset.productImage || '',
        card: card
      };
    }).filter(function(product) {
      return product.id && product.priceCents !== null;
    });

    input.addEventListener('input', function() {
      const targetPrice = normalizePriceToCents(input.value);
      if (targetPrice === null) {
        renderPriceSearchResults(panel, [], input.value);
        return;
      }
      renderPriceSearchResults(panel, products.filter(function(product) {
        return product.priceCents === targetPrice;
      }), input.value);
    });

    panel.addEventListener('click', function(event) {
      const result = event.target.closest('[data-price-search-product-id]');
      if (!result || result.disabled) return;
      const product = products.find(function(item) {
        return item.id === result.dataset.priceSearchProductId;
      });
      if (!product || !product.card) return;
      const form = product.card.querySelector('form');
      const submitButton = form ? form.querySelector('button[type="submit"]') : null;
      if (!form || (submitButton && submitButton.disabled)) return;
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit(submitButton || undefined);
      } else {
        form.submit();
      }
    });
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
