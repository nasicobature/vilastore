// ===== LOCAL STORAGE MANAGER =====
// Handles data persistence - replaces hardcoded data.js

const STORAGE_KEYS = {
  PRODUCTS: 'vilastore_products',
  SALES: 'vilastore_sales',
  EXPENSES: 'vilastore_expenses',
  CATEGORIES: 'vilastore_categories',
  USER: 'vilastore_user'
};

// ===== DEFAULT DATA =====
const DEFAULT_CATEGORIES = ['All', 'Electronics', 'Accessories', 'Phones', 'Audio', 'Wearables'];

const DEFAULT_PRODUCTS = [
  { id: '1', name: 'iPhone 12', category: 'Phones', costPrice: 280000, sellingPrice: 350000, stock: 5, image: null, lowStockThreshold: 3 },
  { id: '2', name: 'Samsung Galaxy A54', category: 'Phones', costPrice: 180000, sellingPrice: 220000, stock: 8, image: null, lowStockThreshold: 3 },
  { id: '3', name: 'USB-C Cable', category: 'Accessories', costPrice: 500, sellingPrice: 1500, stock: 45, image: null, lowStockThreshold: 10 },
  { id: '4', name: 'Wireless Earbuds', category: 'Audio', costPrice: 8000, sellingPrice: 15000, stock: 12, image: null, lowStockThreshold: 5 },
  { id: '5', name: 'Phone Case', category: 'Accessories', costPrice: 800, sellingPrice: 2500, stock: 2, image: null, lowStockThreshold: 10 },
  { id: '6', name: 'Power Bank 10000mAh', category: 'Electronics', costPrice: 5000, sellingPrice: 9000, stock: 15, image: null, lowStockThreshold: 5 },
  { id: '7', name: 'Bluetooth Speaker', category: 'Audio', costPrice: 12000, sellingPrice: 18000, stock: 7, image: null, lowStockThreshold: 3 },
  { id: '8', name: 'Smart Watch', category: 'Wearables', costPrice: 25000, sellingPrice: 35000, stock: 4, image: null, lowStockThreshold: 2 }
];

const DEFAULT_SALES = [];

const DEFAULT_EXPENSES = [];

// ===== STORAGE FUNCTIONS =====

function initializeStorage() {
  // Initialize with defaults if empty
  if (!localStorage.getItem(STORAGE_KEYS.PRODUCTS)) {
    localStorage.setItem(STORAGE_KEYS.PRODUCTS, JSON.stringify(DEFAULT_PRODUCTS));
  }
  if (!localStorage.getItem(STORAGE_KEYS.SALES)) {
    localStorage.setItem(STORAGE_KEYS.SALES, JSON.stringify(DEFAULT_SALES));
  }
  if (!localStorage.getItem(STORAGE_KEYS.EXPENSES)) {
    localStorage.setItem(STORAGE_KEYS.EXPENSES, JSON.stringify(DEFAULT_EXPENSES));
  }
  if (!localStorage.getItem(STORAGE_KEYS.CATEGORIES)) {
    localStorage.setItem(STORAGE_KEYS.CATEGORIES, JSON.stringify(DEFAULT_CATEGORIES));
  }
}

// Products
function getProducts() {
  const data = localStorage.getItem(STORAGE_KEYS.PRODUCTS);
  return data ? JSON.parse(data) : [];
}

function saveProducts(products) {
  localStorage.setItem(STORAGE_KEYS.PRODUCTS, JSON.stringify(products));
}

function getProductById(id) {
  const products = getProducts();
  return products.find(p => p.id === id);
}

function updateProduct(product) {
  const products = getProducts();
  const index = products.findIndex(p => p.id === product.id);
  if (index !== -1) {
    products[index] = product;
    saveProducts(products);
  }
}

function addProduct(product) {
  const products = getProducts();
  products.push(product);
  saveProducts(products);
}

function deleteProduct(id) {
  const products = getProducts().filter(p => p.id !== id);
  saveProducts(products);
}

// Sales
function getSales() {
  const data = localStorage.getItem(STORAGE_KEYS.SALES);
  return data ? JSON.parse(data) : [];
}

function saveSales(sales) {
  localStorage.setItem(STORAGE_KEYS.SALES, JSON.stringify(sales));
}

function addSale(sale) {
  const sales = getSales();
  sales.unshift(sale);
  saveSales(sales);
}

// Expenses
function getExpenses() {
  const data = localStorage.getItem(STORAGE_KEYS.EXPENSES);
  return data ? JSON.parse(data) : [];
}

function saveExpenses(expenses) {
  localStorage.setItem(STORAGE_KEYS.EXPENSES, JSON.stringify(expenses));
}

function addExpense(expense) {
  const expenses = getExpenses();
  expenses.unshift(expense);
  saveExpenses(expenses);
}

function deleteExpense(id) {
  const expenses = getExpenses().filter(e => e.id !== id);
  saveExpenses(expenses);
}

// Categories
function getCategories() {
  const data = localStorage.getItem(STORAGE_KEYS.CATEGORIES);
  return data ? JSON.parse(data) : DEFAULT_CATEGORIES;
}

function saveCategories(categories) {
  localStorage.setItem(STORAGE_KEYS.CATEGORIES, JSON.stringify(categories));
}

function addCategory(name) {
  const categories = getCategories();
  if (!categories.includes(name)) {
    categories.push(name);
    saveCategories(categories);
  }
}

function deleteCategory(name) {
  if (name === 'All') return;
  const categories = getCategories().filter(c => c !== name);
  saveCategories(categories);
}

// User/Auth
function getUser() {
  const data = localStorage.getItem(STORAGE_KEYS.USER);
  return data ? JSON.parse(data) : null;
}

function saveUser(user) {
  localStorage.setItem(STORAGE_KEYS.USER, JSON.stringify(user));
}

function clearUser() {
  localStorage.removeItem(STORAGE_KEYS.USER);
}

function isLoggedIn() {
  return getUser() !== null;
}

// ===== UTILITY FUNCTIONS =====

function formatCurrency(amount) {
  return '₦' + amount.toLocaleString('en-NG');
}

function formatTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleTimeString('en-NG', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' });
}

function isLowStock(product) {
  return product.stock <= product.lowStockThreshold;
}

function isOutOfStock(product) {
  return product.stock === 0;
}

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Initialize storage on load
initializeStorage();
