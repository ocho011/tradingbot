// Trading Chart Dashboard - Main JavaScript
// Handles real-time chart updates, ICT indicators, and WebSocket communication

class TradingChart {
    constructor() {
        this.chart = null;
        this.candleSeries = null;
        this.ws = null;
        this.currentTimeframe = '15m';
        this.currentSymbol = 'BTCUSDT';
        this.indicators = {
            orderBlocks: [],
            fvgs: [],
            liquidityLevels: [],
            signals: []
        };
        this.markers = [];

        this.init();
    }

    init() {
        this.setupChart();
        this.setupEventListeners();
        this.connectWebSocket();
    }

    setupChart() {
        const container = document.getElementById('chartContainer');

        this.chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 600,
            layout: {
                background: { color: '#1e2139' },
                textColor: '#9ca3af',
            },
            grid: {
                vertLines: { color: '#2d3748' },
                horzLines: { color: '#2d3748' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: '#2d3748',
            },
            timeScale: {
                borderColor: '#2d3748',
                timeVisible: true,
                secondsVisible: false,
            },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#10b981',
            downColor: '#ef4444',
            borderUpColor: '#10b981',
            borderDownColor: '#ef4444',
            wickUpColor: '#10b981',
            wickDownColor: '#ef4444',
        });

        // Handle window resize
        window.addEventListener('resize', () => {
            this.chart.applyOptions({ width: container.clientWidth });
        });
    }

    setupEventListeners() {
        // Timeframe tabs
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const timeframe = e.target.dataset.timeframe;
                this.switchTimeframe(timeframe);
            });
        });

        // Indicator toggles
        document.getElementById('showOrderBlocks').addEventListener('change', (e) => {
            this.toggleIndicators('orderBlocks', e.target.checked);
        });
        document.getElementById('showFVG').addEventListener('change', (e) => {
            this.toggleIndicators('fvgs', e.target.checked);
        });
        document.getElementById('showLiquidity').addEventListener('change', (e) => {
            this.toggleIndicators('liquidityLevels', e.target.checked);
        });
        document.getElementById('showSignals').addEventListener('change', (e) => {
            this.toggleSignals(e.target.checked);
        });

        // Chart controls
        document.getElementById('btnZoomIn').addEventListener('click', () => {
            this.chart.timeScale().scrollToPosition(5, true);
        });
        document.getElementById('btnZoomOut').addEventListener('click', () => {
            this.chart.timeScale().scrollToPosition(-5, true);
        });
        document.getElementById('btnFitContent').addEventListener('click', () => {
            this.chart.timeScale().fitContent();
        });
        document.getElementById('btnResetChart').addEventListener('click', () => {
            this.resetChart();
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus('connected');

            // Subscribe to topics
            this.ws.send(JSON.stringify({
                type: 'subscribe',
                topics: ['candles', 'indicators', 'signals', 'positions'],
                filters: { symbol: this.currentSymbol }
            }));
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleWebSocketMessage(message);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus('disconnected');
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.updateConnectionStatus('disconnected');

            // Reconnect after 3 seconds
            setTimeout(() => this.connectWebSocket(), 3000);
        };
    }

    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'candle_update':
                this.updateCandle(message.data);
                break;
            case 'indicator_update':
                this.updateIndicators(message.data);
                break;
            case 'signal':
                this.addSignal(message.data);
                break;
            case 'position_update':
                this.updatePositions(message.data);
                break;
            case 'pong':
                // Heartbeat response
                break;
            default:
                console.log('Unknown message type:', message.type);
        }
    }

    updateCandle(data) {
        if (!data || !data.candle) return;

        const candle = data.candle;
        const candleData = {
            time: Math.floor(candle.timestamp / 1000),
            open: parseFloat(candle.open),
            high: parseFloat(candle.high),
            low: parseFloat(candle.low),
            close: parseFloat(candle.close),
        };

        this.candleSeries.update(candleData);

        // Update price display
        this.updatePriceDisplay(candleData.close, candle.open);
    }

    updatePriceDisplay(currentPrice, openPrice) {
        const priceEl = document.getElementById('currentPrice');
        const changeEl = document.getElementById('priceChange');

        priceEl.textContent = `$${currentPrice.toFixed(2)}`;

        const change = ((currentPrice - openPrice) / openPrice * 100).toFixed(2);
        changeEl.textContent = `${change >= 0 ? '+' : ''}${change}%`;
        changeEl.className = `change ${change >= 0 ? '' : 'negative'}`;
    }

    updateIndicators(data) {
        if (!data) return;

        // Update Order Blocks
        if (data.order_blocks) {
            this.indicators.orderBlocks = data.order_blocks;
            this.renderOrderBlocks();
        }

        // Update FVGs
        if (data.fair_value_gaps) {
            this.indicators.fvgs = data.fair_value_gaps;
            this.renderFVGs();
        }

        // Update Liquidity Levels
        if (data.liquidity_levels) {
            this.indicators.liquidityLevels = data.liquidity_levels;
            this.renderLiquidityLevels();
        }

        // Update indicators panel
        this.updateIndicatorsPanel();
    }

    renderOrderBlocks() {
        // Order Blocks are rendered as rectangles on the chart
        // This is a simplified version - in production, you'd use custom series or markers
        this.indicators.orderBlocks.forEach(ob => {
            if (ob.state !== 'ACTIVE') return;

            // Add to chart (simplified - would need custom rendering)
            console.log('Order Block:', ob);
        });
    }

    renderFVGs() {
        // Fair Value Gaps are rendered as shaded areas
        this.indicators.fvgs.forEach(fvg => {
            if (fvg.state !== 'ACTIVE') return;

            console.log('FVG:', fvg);
        });
    }

    renderLiquidityLevels() {
        // Liquidity levels are rendered as horizontal lines
        this.indicators.liquidityLevels.forEach(level => {
            if (level.state !== 'ACTIVE') return;

            console.log('Liquidity Level:', level);
        });
    }

    addSignal(signal) {
        // Add signal marker to chart
        const marker = {
            time: Math.floor(signal.timestamp / 1000),
            position: signal.direction === 'LONG' ? 'belowBar' : 'aboveBar',
            color: signal.direction === 'LONG' ? '#10b981' : '#ef4444',
            shape: signal.direction === 'LONG' ? 'arrowUp' : 'arrowDown',
            text: signal.direction,
        };

        this.markers.push(marker);
        this.candleSeries.setMarkers(this.markers);

        // Update signals panel
        this.updateSignalsPanel(signal);
    }

    updatePositions(positions) {
        const panel = document.getElementById('positionsPanel');

        if (!positions || positions.length === 0) {
            panel.innerHTML = '<div class="loading">No active positions</div>';
            return;
        }

        panel.innerHTML = positions.map(pos => `
            <div class="position-item">
                <div class="position-header">
                    <span class="position-side ${pos.side.toLowerCase()}">${pos.side}</span>
                    <span class="position-pnl ${pos.unrealized_pnl >= 0 ? 'positive' : 'negative'}">
                        ${pos.unrealized_pnl >= 0 ? '+' : ''}$${pos.unrealized_pnl.toFixed(2)}
                    </span>
                </div>
                <div class="position-details">
                    <div class="position-detail">
                        <span class="position-label">Entry:</span>
                        <span class="position-value">$${pos.entry_price.toFixed(2)}</span>
                    </div>
                    <div class="position-detail">
                        <span class="position-label">Size:</span>
                        <span class="position-value">${pos.quantity}</span>
                    </div>
                    <div class="position-detail">
                        <span class="position-label">Leverage:</span>
                        <span class="position-value">${pos.leverage}x</span>
                    </div>
                    <div class="position-detail">
                        <span class="position-label">ROI:</span>
                        <span class="position-value">${(pos.unrealized_pnl / pos.entry_value * 100).toFixed(2)}%</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    updateIndicatorsPanel() {
        const panel = document.getElementById('indicatorsPanel');
        const allIndicators = [
            ...this.indicators.orderBlocks.filter(ob => ob.state === 'ACTIVE').map(ob => ({
                type: 'Order Block',
                class: 'order-block',
                price: ob.high,
                details: `${ob.type} | Strength: ${ob.strength.toFixed(0)}`
            })),
            ...this.indicators.fvgs.filter(fvg => fvg.state === 'ACTIVE').map(fvg => ({
                type: 'Fair Value Gap',
                class: 'fvg',
                price: fvg.high,
                details: `${fvg.type} | Size: ${fvg.size_percentage.toFixed(2)}%`
            })),
            ...this.indicators.liquidityLevels.filter(lvl => lvl.state === 'ACTIVE').map(lvl => ({
                type: 'Liquidity Level',
                class: 'liquidity',
                price: lvl.price,
                details: `${lvl.type} | Strength: ${lvl.strength.toFixed(0)}`
            }))
        ];

        if (allIndicators.length === 0) {
            panel.innerHTML = '<div class="loading">No active indicators</div>';
            return;
        }

        panel.innerHTML = allIndicators.slice(0, 10).map(ind => `
            <div class="indicator-item ${ind.class}">
                <div class="indicator-header">
                    <span class="indicator-type">${ind.type}</span>
                    <span class="indicator-price">$${ind.price.toFixed(2)}</span>
                </div>
                <div class="indicator-details">${ind.details}</div>
            </div>
        `).join('');
    }

    updateSignalsPanel(signal) {
        const panel = document.getElementById('signalsPanel');

        // Create signal element
        const signalEl = document.createElement('div');
        signalEl.className = `signal-item ${signal.direction.toLowerCase()}`;
        signalEl.innerHTML = `
            <div class="signal-header">
                <span class="signal-direction ${signal.direction.toLowerCase()}">${signal.direction}</span>
                <span class="signal-time">${new Date(signal.timestamp).toLocaleTimeString()}</span>
            </div>
            <div class="signal-details">
                <div class="signal-detail">
                    <span class="signal-label">Entry:</span>
                    <span class="signal-value">$${signal.entry_price.toFixed(2)}</span>
                </div>
                <div class="signal-detail">
                    <span class="signal-label">Strategy:</span>
                    <span class="signal-value">${signal.strategy || 'N/A'}</span>
                </div>
                <div class="signal-detail">
                    <span class="signal-label">Confidence:</span>
                    <span class="signal-value">${(signal.confidence * 100).toFixed(0)}%</span>
                </div>
                <div class="signal-detail">
                    <span class="signal-label">Timeframe:</span>
                    <span class="signal-value">${signal.timeframe}</span>
                </div>
            </div>
        `;

        // Prepend to panel (newest first)
        if (panel.querySelector('.loading')) {
            panel.innerHTML = '';
        }
        panel.insertBefore(signalEl, panel.firstChild);

        // Keep only last 10 signals
        while (panel.children.length > 10) {
            panel.removeChild(panel.lastChild);
        }
    }

    switchTimeframe(timeframe) {
        this.currentTimeframe = timeframe;

        // Update active tab
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.timeframe === timeframe);
        });

        // Resubscribe to WebSocket with new timeframe
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'subscribe',
                topics: ['candles', 'indicators', 'signals'],
                filters: {
                    symbol: this.currentSymbol,
                    timeframe: timeframe
                }
            }));
        }

        // Clear and reload chart
        this.resetChart();
    }

    toggleIndicators(type, show) {
        // Toggle visibility of specific indicator type
        console.log(`Toggle ${type}:`, show);
        // In production, this would show/hide the rendered indicators
    }

    toggleSignals(show) {
        if (show) {
            this.candleSeries.setMarkers(this.markers);
        } else {
            this.candleSeries.setMarkers([]);
        }
    }

    resetChart() {
        this.candleSeries.setData([]);
        this.markers = [];
        this.candleSeries.setMarkers([]);
    }

    updateConnectionStatus(status) {
        const statusEl = document.getElementById('connectionStatus');
        const dot = statusEl.querySelector('.status-dot');
        const text = statusEl.querySelector('.status-text');

        dot.className = `status-dot ${status}`;

        switch (status) {
            case 'connected':
                text.textContent = 'Connected';
                break;
            case 'disconnected':
                text.textContent = 'Disconnected';
                break;
            default:
                text.textContent = 'Connecting...';
        }
    }
}

// Initialize chart when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.tradingChart = new TradingChart();
});
