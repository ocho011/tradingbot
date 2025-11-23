// =====================================
// Configuration & Constants
// =====================================
const API_BASE = '';

const AVAILABLE_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT',
    'DOGEUSDT', 'XRPUSDT', 'MATICUSDT', 'DOTUSDT', 'AVAXUSDT'
];

// =====================================
// State Management
// =====================================
let currentConfig = {};
let isLoading = false;

// =====================================
// Utility Functions
// =====================================
function showToast(type, message) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span>${getToastIcon(type)}</span>
        <div>${message}</div>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function getToastIcon(type) {
    const icons = {
        success: '✓',
        error: '✗',
        warning: '⚠',
        info: 'ℹ'
    };
    return icons[type] || 'ℹ';
}

function showModal(title, message, onConfirm) {
    const modal = document.getElementById('confirmModal');
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalMessage').textContent = message;

    modal.classList.add('show');

    const confirmBtn = document.getElementById('modalConfirm');
    const cancelBtn = document.getElementById('modalCancel');

    const handleConfirm = () => {
        modal.classList.remove('show');
        onConfirm();
        cleanup();
    };

    const handleCancel = () => {
        modal.classList.remove('show');
        cleanup();
    };

    const cleanup = () => {
        confirmBtn.removeEventListener('click', handleConfirm);
        cancelBtn.removeEventListener('click', handleCancel);
    };

    confirmBtn.addEventListener('click', handleConfirm);
    cancelBtn.addEventListener('click', handleCancel);
}

// =====================================
// API Functions
// =====================================
async function fetchConfig() {
    try {
        const response = await fetch(`${API_BASE}/config`);
        if (!response.ok) throw new Error('Failed to fetch configuration');
        const data = await response.json();
        return data.configuration || data.config || data;
    } catch (error) {
        console.error('Error fetching config:', error);
        showToast('error', 'Failed to load configuration');
        return null;
    }
}

async function fetchSystemStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        if (!response.ok) throw new Error('Failed to fetch status');
        return await response.json();
    } catch (error) {
        console.error('Error fetching status:', error);
        return null;
    }
}

async function updateConfig(section, updates) {
    try {
        const response = await fetch(`${API_BASE}/config/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                section: section,
                updates: updates,
                validate: true
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Update failed');
        }

        return await response.json();
    } catch (error) {
        console.error('Error updating config:', error);
        throw error;
    }
}

async function updateConfigBatch(updatesBySection) {
    try {
        const response = await fetch(`${API_BASE}/config/update-batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                updates_by_section: updatesBySection,
                validate: true
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Batch update failed');
        }

        return await response.json();
    } catch (error) {
        console.error('Error updating config batch:', error);
        throw error;
    }
}

async function switchEnvironment(toTestnet) {
    try {
        const response = await fetch(`${API_BASE}/config/switch-environment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_testnet: toTestnet })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Environment switch failed');
        }

        return await response.json();
    } catch (error) {
        console.error('Error switching environment:', error);
        throw error;
    }
}

async function rollbackConfig(steps = 1) {
    try {
        const response = await fetch(`${API_BASE}/config/rollback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steps: steps })
        });

        if (!response.ok) {
            const error = await response.json();
            const err = new Error(error.detail || 'Rollback failed');
            err.status = response.status;
            throw err;
        }

        return await response.json();
    } catch (error) {
        console.error('Error rolling back config:', error);
        throw error;
    }
}

async function fetchConfigHistory(limit = 10) {
    try {
        const response = await fetch(`${API_BASE}/config/history?limit=${limit}`);
        if (!response.ok) throw new Error('Failed to fetch history');
        return await response.json();
    } catch (error) {
        console.error('Error fetching history:', error);
        return null;
    }
}

// =====================================
// UI Update Functions
// =====================================
function updateSystemStatus(status) {
    const statusEl = document.getElementById('systemStatus');
    const isOnline = status && (status.system_state === 'online' || status.system_state === 'running');

    statusEl.innerHTML = `
        <span class="status-dot ${isOnline ? 'online' : 'offline'}"></span>
        <span class="status-text">${isOnline ? 'ONLINE' : 'OFFLINE'}</span>
    `;
}

// initializeSymbolGrid removed - now using refreshSymbolGrid() for dynamic management

function populateForm() {
    // Environment
    const isTestnet = currentConfig.binance?.testnet ?? true;
    document.getElementById('envToggle').checked = !isTestnet;
    document.getElementById('envDisplay').textContent = isTestnet ? 'Testnet' : 'Mainnet';

    // Trading mode - removed from UI, defaults to live
    // document.getElementById('tradingMode').value = currentConfig.trading?.mode || 'paper';

    // Trading settings
    document.getElementById('leverage').value = currentConfig.trading?.default_leverage || 10;
    document.getElementById('maxPosition').value = currentConfig.trading?.max_position_size_usdt || 1000;
    document.getElementById('riskPercent').value = currentConfig.trading?.risk_per_trade_percent || 1.0;

    // Strategies
    document.getElementById('strategy1').checked = currentConfig.strategy?.enable_strategy_1 ?? true;
    document.getElementById('strategy2').checked = currentConfig.strategy?.enable_strategy_2 ?? true;
    document.getElementById('strategy3').checked = currentConfig.strategy?.enable_strategy_3 ?? true;

    // ICT indicators
    document.getElementById('fvgSize').value = currentConfig.ict?.fvg_min_size_percent || 0.1;
    document.getElementById('obLookback').value = currentConfig.ict?.ob_lookback_periods || 100;
    document.getElementById('liqSweep').value = currentConfig.ict?.liquidity_sweep_threshold || 0.5;

    // Timeframes
    document.getElementById('primaryTf').value = currentConfig.market?.primary_timeframe || '15m';
    document.getElementById('higherTf').value = currentConfig.market?.higher_timeframe || '1h';
    document.getElementById('lowerTf').value = currentConfig.market?.lower_timeframe || '5m';

    // Symbol grid is now managed by refreshSymbolGrid()
}

// getSelectedSymbols removed - symbols are now managed via API

// =====================================
// Event Handlers
// =====================================
async function handleSaveChanges() {
    const btn = document.getElementById('saveBtn');
    const originalText = btn.innerHTML;

    if (isLoading) return;
    isLoading = true;

    // Loading state
    btn.classList.add('loading');
    btn.innerHTML = '⏳ Saving...';

    try {
        // Collect all changes
        const updates = {
            market: {
                // active_symbols now managed via /api/symbols/add and /api/symbols/remove
                primary_timeframe: document.getElementById('primaryTf').value,
                higher_timeframe: document.getElementById('higherTf').value,
                lower_timeframe: document.getElementById('lowerTf').value
            },
            trading: {
                mode: 'live', // Default to live as per new requirement
                default_leverage: parseInt(document.getElementById('leverage').value),
                max_position_size_usdt: parseFloat(document.getElementById('maxPosition').value),
                risk_per_trade_percent: parseFloat(document.getElementById('riskPercent').value)
            },
            strategy: {
                enable_strategy_1: document.getElementById('strategy1').checked,
                enable_strategy_2: document.getElementById('strategy2').checked,
                enable_strategy_3: document.getElementById('strategy3').checked
            },
            ict: {
                fvg_min_size_percent: parseFloat(document.getElementById('fvgSize').value),
                ob_lookback_periods: parseInt(document.getElementById('obLookback').value),
                liquidity_sweep_threshold: parseFloat(document.getElementById('liqSweep').value)
            }
        };

        // Use batch update
        await updateConfigBatch(updates);

        showToast('success', 'Configuration saved successfully!');
        await loadConfig(); // Reload config to confirm

        // Success state
        btn.classList.remove('loading');
        btn.classList.add('success');
        btn.innerHTML = '✅ Saved!';

        // Reset after 2 seconds
        setTimeout(() => {
            btn.classList.remove('success');
            btn.innerHTML = originalText;
        }, 2000);

    } catch (error) {
        showToast('error', `Failed to save: ${error.message}`);
        btn.classList.remove('loading');
        btn.innerHTML = originalText;
    } finally {
        isLoading = false;
    }
}

function handleEnvironmentToggle() {
    const toggle = document.getElementById('envToggle');
    const toTestnet = !toggle.checked;
    const targetEnv = toTestnet ? 'Testnet' : 'Mainnet';

    showModal(
        '⚠️ Environment Switch',
        `Are you sure you want to switch to ${targetEnv}? This will affect all trading operations.`,
        async () => {
            try {
                await switchEnvironment(toTestnet);
                document.getElementById('envDisplay').textContent = targetEnv;
                showToast('success', `Switched to ${targetEnv}`);
                await loadConfig();
            } catch (error) {
                toggle.checked = !toggle.checked;
                showToast('error', `Failed to switch: ${error.message}`);
            }
        }
    );
}

async function handleRollback() {
    const btn = document.getElementById('rollbackBtn');
    const originalText = btn.innerHTML;

    showModal(
        '↩️ Rollback Configuration',
        'This will revert to the previous configuration state. Continue?',
        async () => {
            try {
                btn.classList.add('loading');
                btn.innerHTML = '⏳ Rolling back...';

                await rollbackConfig(1);
                showToast('success', 'Configuration rolled back');
                await loadConfig();

                // Success state
                btn.classList.remove('loading');
                btn.classList.add('success');
                btn.innerHTML = '✅ Done!';

                setTimeout(() => {
                    btn.classList.remove('success');
                    btn.innerHTML = originalText;
                    window.location.reload(); // Force reload to ensure UI reflects rollback
                }, 1000);

            } catch (error) {
                console.log('Rollback error caught:', error.message, error.status);

                // Smart handling: If 400 Bad Request (No history) or message matches
                if (error.status === 400 || error.message.includes('No configuration history') || error.message.includes('history available')) {
                    showToast('info', 'No saved history. Resetting unsaved changes...');

                    // Visual feedback
                    btn.classList.remove('loading');
                    btn.innerHTML = '🔄 Resetting...';

                    setTimeout(() => {
                        window.location.reload();
                    }, 1500);
                } else {
                    showToast('error', `Rollback failed: ${error.message}`);
                    btn.classList.remove('loading');
                    btn.innerHTML = originalText;
                }
            }
        }
    );
}

async function handleShowHistory() {
    const btn = document.getElementById('historyBtn');
    const originalText = btn.innerHTML;
    const historySection = document.getElementById('historySection');
    const historyList = document.getElementById('historyList');

    // Toggle visibility
    if (historySection.style.display === 'none') {
        try {
            btn.classList.add('loading');
            btn.innerHTML = '⏳ Loading...';

            const data = await fetchConfigHistory(10);
            if (data && data.history) {
                historyList.innerHTML = '';
                data.history.forEach(item => {
                    const historyItem = document.createElement('div');
                    historyItem.className = 'history-item';
                    historyItem.innerHTML = `
                        <span class="history-timestamp">${new Date(item.timestamp).toLocaleString()}</span>
                        <span class="history-description">${item.reason || 'Configuration updated'}</span>
                    `;
                    historyList.appendChild(historyItem);
                });
            }
            historySection.style.display = 'block';
        } catch (error) {
            showToast('error', 'Failed to load history');
        } finally {
            btn.classList.remove('loading');
            btn.innerHTML = originalText;
        }
    } else {
        historySection.style.display = 'none';
    }
}

// =====================================
// Initialization
// =====================================
async function loadConfig() {
    const config = await fetchConfig();
    if (config) {
        currentConfig = config;
        populateForm();
    }
}

async function loadStatus() {
    const status = await fetchSystemStatus();
    if (status) {
        updateSystemStatus(status);
    }
}

async function init() {
    // Load initial data
    await loadConfig();
    await loadStatus();
    await refreshSymbolGrid(); // Load active symbols

    // Set up event listeners
    document.getElementById('saveBtn').addEventListener('click', handleSaveChanges);
    document.getElementById('rollbackBtn').addEventListener('click', handleRollback);
    document.getElementById('historyBtn').addEventListener('click', handleShowHistory);
    document.getElementById('envToggle').addEventListener('change', handleEnvironmentToggle);

    // Symbol management listeners
    document.getElementById('addSymbolBtn').addEventListener('click', handleAddSymbol);
    document.getElementById('newSymbol').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleAddSymbol();
        }
    });

    // Auto-refresh status every 10 seconds
    setInterval(loadStatus, 10000);

    // Auto-refresh symbols every 30 seconds
    setInterval(refreshSymbolGrid, 30000);

    console.log('Admin dashboard initialized');
}

// =====================================
// Symbol Management Functions
// =====================================
async function fetchActiveSymbols() {
    try {
        const response = await fetch(`${API_BASE}/api/symbols/active`);
        if (!response.ok) throw new Error('Failed to fetch active symbols');
        return await response.json();
    } catch (error) {
        console.error('Error fetching active symbols:', error);
        return null;
    }
}

async function addSymbol(symbol, timeframes = null) {
    try {
        const response = await fetch(`${API_BASE}/api/symbols/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol: symbol,
                timeframes: timeframes
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add symbol');
        }

        return await response.json();
    } catch (error) {
        console.error('Error adding symbol:', error);
        throw error;
    }
}

async function removeSymbol(symbol) {
    try {
        const response = await fetch(`${API_BASE}/api/symbols/remove`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: symbol })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to remove symbol');
        }

        return await response.json();
    } catch (error) {
        console.error('Error removing symbol:', error);
        throw error;
    }
}

async function refreshSymbolGrid() {
    const grid = document.getElementById('symbolGrid');
    grid.innerHTML = '<div class="loading-spinner">Loading symbols...</div>';

    try {
        const data = await fetchActiveSymbols();
        if (!data || !data.active_symbols) {
            throw new Error('No symbol data received');
        }

        grid.innerHTML = '';
        const activeSymbols = data.active_symbols;

        if (activeSymbols.length === 0) {
            grid.innerHTML = '<div class="no-symbols">No active symbols. Add one above.</div>';
            return;
        }

        activeSymbols.forEach(symbol => {
            const symbolCard = document.createElement('div');
            symbolCard.className = 'symbol-card';
            symbolCard.innerHTML = `
                <div class="symbol-name">${symbol}</div>
                <button class="symbol-remove-btn" data-symbol="${symbol}" title="Remove ${symbol}">
                    ✕
                </button>
            `;

            const removeBtn = symbolCard.querySelector('.symbol-remove-btn');
            removeBtn.addEventListener('click', () => handleRemoveSymbol(symbol));

            grid.appendChild(symbolCard);
        });
    } catch (error) {
        console.error('Error refreshing symbol grid:', error);
        grid.innerHTML = '<div class="error-message">Failed to load symbols</div>';
        showToast('error', 'Failed to load active symbols');
    }
}

async function handleAddSymbol() {
    const input = document.getElementById('newSymbol');
    const btn = document.getElementById('addSymbolBtn');
    const symbol = input.value.trim().toUpperCase();

    if (!symbol) {
        showToast('warning', 'Please enter a symbol');
        return;
    }

    // Basic validation
    if (!/^[A-Z]+USDT$/.test(symbol)) {
        showToast('warning', 'Symbol must end with USDT (e.g., ETHUSDT)');
        return;
    }

    const originalText = btn.innerHTML;
    btn.classList.add('loading');
    btn.innerHTML = '⏳ Adding...';
    btn.disabled = true;

    try {
        const result = await addSymbol(symbol);
        showToast('success', `${symbol} added successfully! Historical data loaded.`);
        input.value = '';
        await refreshSymbolGrid();

        // Success animation
        btn.classList.remove('loading');
        btn.classList.add('success');
        btn.innerHTML = '✅ Added!';

        setTimeout(() => {
            btn.classList.remove('success');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 2000);

    } catch (error) {
        showToast('error', `Failed to add ${symbol}: ${error.message}`);
        btn.classList.remove('loading');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function handleRemoveSymbol(symbol) {
    showModal(
        '🗑️ Remove Symbol',
        `Are you sure you want to remove ${symbol}? This will stop all data collection for this symbol.`,
        async () => {
            try {
                await removeSymbol(symbol);
                showToast('success', `${symbol} removed successfully`);
                await refreshSymbolGrid();
            } catch (error) {
                showToast('error', `Failed to remove ${symbol}: ${error.message}`);
            }
        }
    );
}

// Start the app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
