// TagadAI Training Dashboard JavaScript

// Training presets
const PRESETS = {
    'pistol-1v1': {
        fights: 50000,
        epochs: 50,
        batch_size: 256,
        learning_rate: 0.001,
        k_folds: 5,
        patience: 5
    },
    'pistol-1v1-large': {
        fights: 200000,
        epochs: 100,
        batch_size: 512,
        learning_rate: 0.001,
        k_folds: 5,
        patience: 10
    },
    'custom': null
};

class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.charts = {};
        this.trainingState = 'idle'; // idle, running, paused, completed

        // Unified logging system
        this.logs = [];
        this.maxLogs = 500;
        this.logFilter = 'all'; // all, training, scraper, rl
        this.logsDrawerOpen = false;

        this.historyData = {
            steps: [],
            trainLoss: [],
            valLoss: [],
            accuracySteps: [],
            valAccuracy: [],
            lastAccuracy: null
        };
        this.dataSource = 'generate'; // 'generate' or 'scraped'
        this.scrapedFightsCount = 0;
        this.rlInitialized = false;
        this.rlPollInterval = null;
        this.rlState = 'idle';
        this.dataInitialized = false;
        this.equipmentChart = null;

        this.initCharts();
        this.initControls();
        this.initTabs();
        this.initLogsDrawer();
        this.initKeyboardShortcuts();
        this.connect();

        // Load initial data
        this.loadGpuInfo();
        this.loadCheckpoints();
    }

    initCharts() {
        // Chart.js global config
        Chart.defaults.color = '#8b949e';
        Chart.defaults.borderColor = '#30363d';
        Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

        // Fight results pie chart
        const fightCtx = document.getElementById('fight-chart');
        if (fightCtx) {
            this.charts.fights = new Chart(fightCtx.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['Team 1', 'Team 2', 'Draws'],
                    datasets: [{
                        data: [0, 0, 0],
                        backgroundColor: ['#58a6ff', '#f85149', '#8b949e'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }

        // Loss chart
        const lossCtx = document.getElementById('loss-chart');
        if (lossCtx) {
            this.charts.loss = new Chart(lossCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Train Loss',
                            data: [],
                            borderColor: '#58a6ff',
                            backgroundColor: 'rgba(88, 166, 255, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0
                        },
                        {
                            label: 'Val Loss',
                            data: [],
                            borderColor: '#a371f7',
                            backgroundColor: 'rgba(163, 113, 247, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    scales: {
                        x: { display: false },
                        y: {
                            beginAtZero: true,
                            grid: { color: '#21262d' }
                        }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        }

        // Accuracy chart
        const accCtx = document.getElementById('accuracy-chart');
        if (accCtx) {
            this.charts.accuracy = new Chart(accCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Validation Accuracy',
                        data: [],
                        borderColor: '#3fb950',
                        backgroundColor: 'rgba(63, 185, 80, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 2,
                        pointHoverRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            display: true,
                            title: { display: true, text: 'Step' },
                            grid: { color: '#21262d' }
                        },
                        y: {
                            min: 0,
                            max: 100,
                            title: { display: true, text: 'Accuracy %' },
                            grid: { color: '#21262d' }
                        }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        }
    }

    initControls() {
        // Control buttons
        document.getElementById('btn-start')?.addEventListener('click', () => this.startTraining());
        document.getElementById('btn-pause')?.addEventListener('click', () => this.pauseTraining());
        document.getElementById('btn-stop')?.addEventListener('click', () => this.stopTraining());
        document.getElementById('btn-save')?.addEventListener('click', () => this.saveCheckpoint());

        // Preset selector
        document.getElementById('preset-select')?.addEventListener('change', (e) => {
            this.applyPreset(e.target.value);
        });

        // H2H predict button
        document.getElementById('h2h-predict')?.addEventListener('click', () => this.predictH2H());

        // Scraper controls
        document.getElementById('btn-scraper-start')?.addEventListener('click', () => this.startScraper());
        document.getElementById('btn-scraper-pause')?.addEventListener('click', () => this.pauseScraper());
        document.getElementById('btn-scraper-stop')?.addEventListener('click', () => this.stopScraper());
        document.getElementById('btn-refresh-db-stats')?.addEventListener('click', () => this.loadScraperDbStats());
        document.getElementById('scraper-delay')?.addEventListener('change', (e) => this.updateScraperDelay(e.target.value));

        // Data source selector
        document.getElementById('data-source-select')?.addEventListener('change', (e) => {
            this.setDataSource(e.target.value);
        });

        // Apply initial preset
        this.applyPreset('pistol-1v1');

        // Start scraper status polling
        this.scraperState = 'idle';
        this.scraperPollInterval = null;

        // Load initial data source info
        this.updateDataSourceInfo();
    }

    // ========== KEYBOARD SHORTCUTS ==========
    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ignore if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            switch (e.code) {
                case 'Space':
                    e.preventDefault();
                    if (this.trainingState === 'running') {
                        this.pauseTraining();
                    } else if (this.trainingState === 'paused') {
                        this.pauseTraining(); // Toggle back
                    }
                    break;
                case 'Escape':
                    if (this.trainingState === 'running' || this.trainingState === 'paused') {
                        this.stopTraining();
                    } else if (this.logsDrawerOpen) {
                        this.toggleLogsDrawer();
                    }
                    break;
                case 'KeyS':
                    if ((e.ctrlKey || e.metaKey) && this.trainingState !== 'idle') {
                        e.preventDefault();
                        this.saveCheckpoint();
                    }
                    break;
                case 'KeyL':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.toggleLogsDrawer();
                    }
                    break;
            }
        });
    }

    // ========== NOTIFICATIONS ==========
    notify(type, title, message, duration = 5000) {
        const container = document.getElementById('notifications');
        if (!container) return;

        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <span class="notification-icon">${icons[type] || 'ℹ'}</span>
            <div class="notification-content">
                <div class="notification-title">${title}</div>
                <div class="notification-message">${message}</div>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;

        container.appendChild(notification);

        // Auto-remove after duration
        if (duration > 0) {
            setTimeout(() => {
                notification.classList.add('fade-out');
                setTimeout(() => notification.remove(), 300);
            }, duration);
        }
    }

    // ========== DATA SOURCE ==========
    setDataSource(source) {
        this.dataSource = source;
        this.updateDataSourceInfo();

        // Update UI based on source
        const fightsInput = document.getElementById('config-fights');
        const fightsLabel = fightsInput?.parentElement?.querySelector('.config-label');

        if (source === 'scraped') {
            if (fightsLabel) {
                fightsLabel.innerHTML = fightsLabel.innerHTML.replace('Fights to Generate', 'Fights to Use');
            }
            // Cap at available fights
            if (fightsInput && this.scrapedFightsCount > 0) {
                fightsInput.max = this.scrapedFightsCount;
                if (parseInt(fightsInput.value) > this.scrapedFightsCount) {
                    fightsInput.value = this.scrapedFightsCount;
                }
            }
        } else {
            if (fightsLabel) {
                fightsLabel.innerHTML = fightsLabel.innerHTML.replace('Fights to Use', 'Fights to Generate');
            }
            if (fightsInput) {
                fightsInput.removeAttribute('max');
            }
        }
    }

    async updateDataSourceInfo() {
        const infoEl = document.getElementById('data-source-info');
        if (!infoEl) return;

        try {
            const response = await fetch('/api/scraper/database');
            const data = await response.json();

            this.scrapedFightsCount = data.total_fights || 0;

            if (this.dataSource === 'scraped') {
                if (this.scrapedFightsCount >= 1000) {
                    infoEl.textContent = `${this.scrapedFightsCount.toLocaleString()} fights available`;
                    infoEl.className = 'data-source-info available';
                } else if (this.scrapedFightsCount > 0) {
                    infoEl.textContent = `Only ${this.scrapedFightsCount} fights (need 1000+)`;
                    infoEl.className = 'data-source-info warning';
                } else {
                    infoEl.textContent = 'No scraped data yet';
                    infoEl.className = 'data-source-info warning';
                }
            } else {
                infoEl.textContent = 'Will generate fights locally';
                infoEl.className = 'data-source-info';
            }
        } catch (error) {
            infoEl.textContent = '';
        }
    }

    applyPreset(presetName) {
        const preset = PRESETS[presetName];
        if (!preset) {
            // Custom - enable all inputs
            this.setConfigInputsEnabled(true);
            return;
        }

        // Apply preset values
        document.getElementById('config-fights').value = preset.fights;
        document.getElementById('config-epochs').value = preset.epochs;
        document.getElementById('config-batch').value = preset.batch_size;
        document.getElementById('config-lr').value = preset.learning_rate;
        document.getElementById('config-folds').value = preset.k_folds;
        document.getElementById('config-patience').value = preset.patience;

        // Disable inputs for non-custom presets
        this.setConfigInputsEnabled(presetName === 'custom');
    }

    setConfigInputsEnabled(enabled) {
        const inputs = document.querySelectorAll('.config-compact input');
        inputs.forEach(input => {
            input.disabled = !enabled;
        });
    }

    getConfig() {
        return {
            fights: parseInt(document.getElementById('config-fights').value),
            epochs: parseInt(document.getElementById('config-epochs').value),
            batch_size: parseInt(document.getElementById('config-batch').value),
            learning_rate: parseFloat(document.getElementById('config-lr').value),
            k_folds: parseInt(document.getElementById('config-folds').value),
            patience: parseInt(document.getElementById('config-patience').value)
        };
    }

    async startTraining() {
        const config = this.getConfig();
        config.data_source = this.dataSource;
        this.addLog('training', 'info', `Starting training: ${config.fights} fights, ${config.epochs} epochs (source: ${this.dataSource})`);

        try {
            const response = await fetch('/api/training/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            const result = await response.json();
            if (result.success) {
                this.setTrainingState('running');
                this.addLog('training', 'success', 'Training started successfully');
                this.notify('success', 'Training Started', `${config.fights.toLocaleString()} fights, ${config.epochs} epochs`);
            } else {
                this.addLog('training', 'error', `Failed to start: ${result.error}`);
                this.notify('error', 'Failed to Start', result.error);
            }
        } catch (error) {
            this.addLog('training', 'error', `Failed to start training: ${error.message}`);
            this.notify('error', 'Error', error.message);
        }
    }

    async pauseTraining() {
        try {
            const response = await fetch('/api/training/pause', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                if (this.trainingState === 'paused') {
                    this.setTrainingState('running');
                    this.addLog('training', 'info', 'Training resumed');
                    this.notify('info', 'Resumed', 'Training resumed');
                } else {
                    this.setTrainingState('paused');
                    this.addLog('training', 'warning', 'Training paused');
                    this.notify('warning', 'Paused', 'Training paused. Press Space to resume.');
                }
            }
        } catch (error) {
            this.addLog('training', 'error', `Failed to pause: ${error.message}`);
        }
    }

    async stopTraining() {
        if (!confirm('Stop training? Current progress will be saved as a checkpoint.')) {
            return;
        }

        try {
            const response = await fetch('/api/training/stop', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                this.setTrainingState('idle');
                this.addLog('training', 'warning', 'Training stopped');
                this.notify('warning', 'Training Stopped', 'Training has been stopped.');
                if (result.checkpoint) {
                    this.addLog('training', 'success', `Checkpoint saved: ${result.checkpoint}`);
                    this.notify('success', 'Checkpoint Saved', result.checkpoint);
                }
            }
        } catch (error) {
            this.addLog('training', 'error', `Failed to stop: ${error.message}`);
        }
    }

    async saveCheckpoint() {
        try {
            const response = await fetch('/api/training/checkpoint', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                this.addLog('training', 'success', `Checkpoint saved: ${result.name}`);
                this.notify('success', 'Checkpoint Saved', result.name);
                this.loadCheckpoints();
            } else {
                this.addLog('training', 'error', `Failed to save: ${result.error}`);
                this.notify('error', 'Save Failed', result.error);
            }
        } catch (error) {
            this.addLog('training', 'error', `Failed to save checkpoint: ${error.message}`);
        }
    }

    setTrainingState(state) {
        this.trainingState = state;

        const btnStart = document.getElementById('btn-start');
        const btnPause = document.getElementById('btn-pause');
        const btnStop = document.getElementById('btn-stop');
        const banner = document.getElementById('status-banner');

        // Reset classes
        banner.className = 'control-status';

        switch (state) {
            case 'idle':
                btnStart.disabled = false;
                btnPause.disabled = true;
                btnStop.disabled = true;
                document.getElementById('status-icon').textContent = '⏸️';
                document.getElementById('banner-title').textContent = 'Ready to Train';
                document.getElementById('banner-subtitle').textContent = 'Configure parameters and click Start';
                break;

            case 'running':
                btnStart.disabled = true;
                btnPause.disabled = false;
                btnStop.disabled = false;
                btnPause.querySelector('.icon').textContent = '⏸';
                btnPause.querySelector('.icon').nextSibling.textContent = ' Pause';
                banner.classList.add('running');
                document.getElementById('status-icon').textContent = '🏃';
                document.getElementById('banner-title').textContent = 'Training in Progress';
                break;

            case 'paused':
                btnStart.disabled = true;
                btnPause.disabled = false;
                btnStop.disabled = false;
                btnPause.querySelector('.icon').textContent = '▶';
                btnPause.querySelector('.icon').nextSibling.textContent = ' Resume';
                banner.classList.add('paused');
                document.getElementById('status-icon').textContent = '⏸️';
                document.getElementById('banner-title').textContent = 'Training Paused';
                break;

            case 'completed':
                btnStart.disabled = false;
                btnPause.disabled = true;
                btnStop.disabled = true;
                document.getElementById('status-icon').textContent = '✅';
                document.getElementById('banner-title').textContent = 'Training Complete';
                break;
        }

        this.setConfigInputsEnabled(state === 'idle');
    }

    // ========== UNIFIED LOGGING SYSTEM ==========

    initLogsDrawer() {
        // Toggle button
        document.getElementById('btn-toggle-logs')?.addEventListener('click', () => this.toggleLogsDrawer());
        document.getElementById('btn-close-logs')?.addEventListener('click', () => this.toggleLogsDrawer());

        // Log controls
        document.getElementById('btn-clear-logs')?.addEventListener('click', () => this.clearLogs());
        document.getElementById('btn-export-logs')?.addEventListener('click', () => this.exportLogs());

        // Filter buttons
        document.querySelectorAll('.log-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.log-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.logFilter = btn.dataset.filter;
                this.updateLogsDisplay();
            });
        });
    }

    toggleLogsDrawer() {
        const drawer = document.getElementById('logs-drawer');
        const btn = document.getElementById('btn-toggle-logs');

        this.logsDrawerOpen = !this.logsDrawerOpen;

        if (this.logsDrawerOpen) {
            drawer.classList.remove('collapsed');
            drawer.classList.add('open');
        } else {
            drawer.classList.remove('open');
            drawer.classList.add('collapsed');
        }

        if (btn) {
            btn.textContent = this.logsDrawerOpen ? '📋 Hide Logs' : '📋 Logs';
        }
    }

    addLog(category, level, message) {
        const now = new Date();
        const time = now.toTimeString().slice(0, 8);

        this.logs.push({ time, category, level, message });
        if (this.logs.length > this.maxLogs) {
            this.logs.shift();
        }

        this.updateLogsDisplay();

        // Also update scraper activity panel if it's a scraper log
        if (category === 'scraper') {
            this.updateScraperActivity(time, level, message);
        }
    }

    updateLogsDisplay() {
        const panel = document.getElementById('logs-panel');
        if (!panel) return;

        const filtered = this.logFilter === 'all'
            ? this.logs
            : this.logs.filter(log => log.category === this.logFilter);

        panel.innerHTML = filtered.map(log => `
            <div class="log-entry" data-category="${log.category}">
                <span class="log-time">${log.time}</span>
                <span class="log-category">[${log.category}]</span>
                <span class="log-level-${log.level}">${log.message}</span>
            </div>
        `).join('');

        // Auto-scroll to bottom
        panel.scrollTop = panel.scrollHeight;
    }

    updateScraperActivity(time, level, message) {
        const panel = document.getElementById('scraper-activity-panel');
        if (!panel) return;

        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `
            <span class="log-time">${time}</span>
            <span class="log-level-${level}">${message}</span>
        `;

        panel.appendChild(entry);
        panel.scrollTop = panel.scrollHeight;

        // Keep size reasonable
        while (panel.children.length > 50) {
            panel.removeChild(panel.firstChild);
        }
    }

    clearLogs() {
        this.logs = [];
        this.addLog('training', 'info', 'Logs cleared');
    }

    exportLogs() {
        const text = this.logs.map(l => `[${l.time}] [${l.category.toUpperCase()}] [${l.level.toUpperCase()}] ${l.message}`).join('\n');
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `tagadai-logs-${new Date().toISOString().slice(0, 10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // WebSocket connection
    connect() {
        const indicator = document.getElementById('connection-status');
        indicator.classList.remove('connected');
        indicator.classList.add('connecting');

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            indicator.classList.remove('connecting');
            indicator.classList.add('connected');
            this.reconnectAttempts = 0;
            this.addLog('training', 'success', 'Connected to server');
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.updateDashboard(data);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            indicator.classList.remove('connected', 'connecting');
            this.addLog('training', 'warning', 'Disconnected from server');
            this.scheduleReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            console.log(`Reconnecting in ${delay}ms...`);
            setTimeout(() => this.connect(), delay);
        }
    }

    updateDashboard(data) {
        // Update status
        document.getElementById('phase-display').textContent = data.status.phase;
        document.getElementById('status-message').textContent = data.status.message;

        // Update training state from server
        if (data.status.phase === 'training' || data.status.phase === 'generating') {
            if (this.trainingState !== 'running' && this.trainingState !== 'paused') {
                this.setTrainingState('running');
            }
        } else if (data.status.phase === 'done') {
            this.setTrainingState('completed');
        }

        // Update banner subtitle
        const subtitle = document.getElementById('banner-subtitle');
        if (data.status.message) {
            subtitle.textContent = data.status.message;
        }

        // Update progress bars
        const fightsProgress = data.fights.target > 0
            ? (data.fights.generated / data.fights.target * 100)
            : 0;
        const fightsProgressEl = document.getElementById('fights-progress');
        if (fightsProgressEl) {
            fightsProgressEl.style.width = `${fightsProgress}%`;
        }
        const fightsCountEl = document.getElementById('fights-count');
        if (fightsCountEl) {
            fightsCountEl.textContent = `${data.fights.generated.toLocaleString()} / ${data.fights.target.toLocaleString()}`;
        }

        const trainingProgress = data.training.total_epochs > 0
            ? (data.training.epoch / data.training.total_epochs * 100)
            : 0;
        const trainingProgressEl = document.getElementById('training-progress');
        if (trainingProgressEl) {
            trainingProgressEl.style.width = `${trainingProgress}%`;
        }
        const trainingCountEl = document.getElementById('training-count');
        if (trainingCountEl) {
            trainingCountEl.textContent = `Epoch ${data.training.epoch} / ${data.training.total_epochs}`;
        }

        // Update timing
        const elapsedEl = document.getElementById('elapsed-time');
        if (elapsedEl) elapsedEl.textContent = data.timing.elapsed_formatted;

        const etaEl = document.getElementById('eta-time');
        if (etaEl) etaEl.textContent = data.timing.eta_formatted || '--';

        const speedEl = document.getElementById('fights-speed');
        if (speedEl) speedEl.textContent = data.fights.per_second.toFixed(1);

        // Update banner metrics
        const metricAccuracy = document.getElementById('metric-accuracy');
        if (metricAccuracy && data.training.val_accuracy > 0) {
            metricAccuracy.textContent = `${data.training.val_accuracy.toFixed(1)}%`;
        }

        const metricEta = document.getElementById('metric-eta');
        if (metricEta) {
            metricEta.textContent = data.timing.eta_formatted || '--';
        }

        // Update fight stats
        const team1WinsEl = document.getElementById('team1-wins');
        if (team1WinsEl) team1WinsEl.textContent = data.fights.team1_wins.toLocaleString();

        const team2WinsEl = document.getElementById('team2-wins');
        if (team2WinsEl) team2WinsEl.textContent = data.fights.team2_wins.toLocaleString();

        const drawsEl = document.getElementById('draws');
        if (drawsEl) drawsEl.textContent = data.fights.draws.toLocaleString();

        const winRateEl = document.getElementById('win-rate');
        if (winRateEl) winRateEl.textContent = `${data.fights.win_rate}%`;

        // Update fight chart
        if (this.charts.fights) {
            this.charts.fights.data.datasets[0].data = [
                data.fights.team1_wins,
                data.fights.team2_wins,
                data.fights.draws
            ];
            this.charts.fights.update('none');
        }

        // Update training stats
        const trainLossEl = document.getElementById('train-loss');
        if (trainLossEl) trainLossEl.textContent = data.training.train_loss.toFixed(6);

        const valLossEl = document.getElementById('val-loss');
        if (valLossEl) valLossEl.textContent = data.training.val_loss.toFixed(6);

        const valAccuracyEl = document.getElementById('val-accuracy');
        if (valAccuracyEl) valAccuracyEl.textContent = `${data.training.val_accuracy}%`;

        const lrEl = document.getElementById('learning-rate');
        if (lrEl) lrEl.textContent = data.training.learning_rate.toExponential(2);

        // Update history charts if we have training data
        if (data.training.step > 0) {
            this.updateHistoryCharts(data.training);
        }
    }

    updateHistoryCharts(training) {
        const step = training.step;

        // Add new data point (avoid duplicates)
        if (this.historyData.steps.length === 0 ||
            this.historyData.steps[this.historyData.steps.length - 1] !== step) {

            this.historyData.steps.push(step);
            this.historyData.trainLoss.push(training.train_loss);
            this.historyData.valLoss.push(training.val_loss);

            // Keep last 100 points for loss
            const maxPoints = 100;
            if (this.historyData.steps.length > maxPoints) {
                this.historyData.steps.shift();
                this.historyData.trainLoss.shift();
                this.historyData.valLoss.shift();
            }

            // Update loss chart
            if (this.charts.loss) {
                this.charts.loss.data.labels = this.historyData.steps;
                this.charts.loss.data.datasets[0].data = this.historyData.trainLoss;
                this.charts.loss.data.datasets[1].data = this.historyData.valLoss;
                this.charts.loss.update('none');
            }
        }

        // Only add accuracy when it actually changes (sparse updates)
        const currentAccuracy = training.val_accuracy;
        if (currentAccuracy !== this.historyData.lastAccuracy && currentAccuracy > 0) {
            this.historyData.lastAccuracy = currentAccuracy;
            this.historyData.accuracySteps.push(step);
            this.historyData.valAccuracy.push(currentAccuracy);

            // Keep last 50 accuracy points
            if (this.historyData.accuracySteps.length > 50) {
                this.historyData.accuracySteps.shift();
                this.historyData.valAccuracy.shift();
            }

            // Update accuracy chart
            if (this.charts.accuracy) {
                this.charts.accuracy.data.labels = this.historyData.accuracySteps;
                this.charts.accuracy.data.datasets[0].data = this.historyData.valAccuracy;
                this.charts.accuracy.update('none');
            }
        }
    }

    // Load initial history if available
    async loadHistory() {
        try {
            const response = await fetch('/api/history');
            const history = await response.json();

            let lastAccuracy = null;

            for (const point of history) {
                if (point.step && !this.historyData.steps.includes(point.step)) {
                    this.historyData.steps.push(point.step);
                    this.historyData.trainLoss.push(point.train_loss || 0);
                    this.historyData.valLoss.push(point.val_loss || 0);

                    const acc = point.val_accuracy;
                    if (acc && acc > 0 && acc !== lastAccuracy) {
                        lastAccuracy = acc;
                        this.historyData.accuracySteps.push(point.step);
                        this.historyData.valAccuracy.push(acc);
                    }
                }
            }

            this.historyData.lastAccuracy = lastAccuracy;

            if (this.historyData.steps.length > 0 && this.charts.loss) {
                this.charts.loss.data.labels = this.historyData.steps;
                this.charts.loss.data.datasets[0].data = this.historyData.trainLoss;
                this.charts.loss.data.datasets[1].data = this.historyData.valLoss;
                this.charts.loss.update();
            }

            if (this.historyData.accuracySteps.length > 0 && this.charts.accuracy) {
                this.charts.accuracy.data.labels = this.historyData.accuracySteps;
                this.charts.accuracy.data.datasets[0].data = this.historyData.valAccuracy;
                this.charts.accuracy.update();
            }
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    }

    // ========== TAB HANDLING ==========
    initTabs() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                this.switchTab(tabId);
            });
        });
    }

    switchTab(tabId) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });

        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabId}-tab`);
        });

        // Load data for the tab
        if (tabId === 'training') {
            this.loadCheckpoints();
            this.loadGpuInfo();
        } else if (tabId === 'models') {
            this.loadVersions();
            this.loadArena();
        } else if (tabId === 'scraper') {
            this.loadScraperStatus();
            this.loadScraperDbStats();
            this.startScraperPolling();
        } else if (tabId === 'data') {
            if (!this.dataInitialized) {
                this.initAnalytics();
                this.dataInitialized = true;
            }
            this.loadLevelDistribution();
            this.loadExplorationStats();
            this.loadDateDistribution();
        } else if (tabId === 'rl') {
            if (!this.rlInitialized) {
                this.initRL();
                this.rlInitialized = true;
            }
            this.loadRLResults();
        } else if (tabId === 'builds') {
            this.loadMetadataStatus();
            this.loadEquipmentData();
        }

        // Stop scraper polling when leaving scraper tab
        if (tabId !== 'scraper' && this.scraperPollInterval) {
            clearInterval(this.scraperPollInterval);
            this.scraperPollInterval = null;
        }

        // Stop RL polling when leaving RL tab
        if (tabId !== 'rl' && this.rlPollInterval) {
            clearInterval(this.rlPollInterval);
            this.rlPollInterval = null;
        }
    }

    // Load GPU info
    async loadGpuInfo() {
        try {
            const response = await fetch('/api/system/gpu');
            const data = await response.json();

            const gpuStatus = document.getElementById('gpu-status');
            const gpuName = document.getElementById('gpu-name');
            const gpuMemory = document.getElementById('gpu-memory');
            const gpuUtil = document.getElementById('gpu-util');

            if (data.cuda_available) {
                const device = data.devices[0];
                const name = device.name;
                const memTotal = (device.memory_total / 1024 / 1024 / 1024).toFixed(1);

                if (gpuStatus) {
                    gpuStatus.textContent = `GPU: ${name}`;
                    gpuStatus.style.color = '#3fb950';
                }

                if (gpuName) gpuName.textContent = name;
                if (gpuMemory) gpuMemory.textContent = `-- / ${memTotal} GB`;
                if (gpuUtil) gpuUtil.textContent = '--%';

            } else {
                if (gpuStatus) {
                    gpuStatus.textContent = 'GPU: CPU only';
                    gpuStatus.style.color = '#8b949e';
                }
                if (gpuName) gpuName.textContent = 'CPU only';
                if (gpuMemory) gpuMemory.textContent = 'N/A';
                if (gpuUtil) gpuUtil.textContent = 'N/A';
            }
        } catch (error) {
            const gpuStatus = document.getElementById('gpu-status');
            if (gpuStatus) gpuStatus.textContent = 'GPU: unknown';
        }
    }

    // Load checkpoints
    async loadCheckpoints() {
        try {
            const response = await fetch('/api/checkpoints');
            const data = await response.json();

            const listEl = document.getElementById('checkpoint-list');
            if (!listEl) return;

            if (!data.checkpoints || data.checkpoints.length === 0) {
                listEl.innerHTML = '<p class="empty-state compact">No checkpoints yet. Start training to create one.</p>';
                return;
            }

            listEl.innerHTML = data.checkpoints.map(cp => `
                <div class="checkpoint-item">
                    <div class="checkpoint-info">
                        <span class="checkpoint-icon">📁</span>
                        <span class="checkpoint-name">${cp.name}</span>
                        <span class="checkpoint-accuracy">${(cp.accuracy * 100).toFixed(1)}%</span>
                        <span class="checkpoint-date">${cp.created_at}</span>
                    </div>
                    <div class="checkpoint-actions">
                        <button class="btn small danger" onclick="dashboard.deleteCheckpoint('${cp.id}')">Delete</button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('Failed to load checkpoints:', error);
        }
    }

    async deleteCheckpoint(id) {
        if (!confirm('Delete this checkpoint?')) return;

        try {
            await fetch(`/api/checkpoints/${id}`, { method: 'DELETE' });
            this.loadCheckpoints();
            this.addLog('training', 'info', 'Checkpoint deleted');
        } catch (error) {
            this.addLog('training', 'error', `Failed to delete: ${error.message}`);
        }
    }

    // Load versions
    async loadVersions() {
        try {
            const response = await fetch('/api/versions');
            const data = await response.json();

            if (data.error) {
                console.error('Versions error:', data.error);
                return;
            }

            const stats = data.stats || {};
            const versionStats = document.getElementById('version-stats');
            if (versionStats) {
                versionStats.innerHTML = `
                    <span>Total: <strong>${stats.total_versions || 0}</strong></span>
                    <span>Best: <strong>${((stats.highest_accuracy || 0) * 100).toFixed(1)}%</strong></span>
                `;
            }

            const listEl = document.getElementById('version-list');
            if (!listEl) return;

            if (!data.versions || data.versions.length === 0) {
                listEl.innerHTML = '<p class="empty-state compact">No versions yet. Train a model to create one.</p>';
                return;
            }

            listEl.innerHTML = data.versions.map(v => `
                <div class="version-item ${v.name === stats.champion ? 'champion' : ''}">
                    <div class="version-info">
                        <h4>${v.name} ${v.name === stats.champion ? '👑' : ''}</h4>
                        <span class="version-id">${v.id}</span>
                    </div>
                    <div class="version-metrics">
                        <div class="version-metric">
                            <div class="value">${(v.accuracy * 100).toFixed(1)}%</div>
                            <div class="label">Accuracy</div>
                        </div>
                        <div class="version-metric">
                            <div class="value">${v.elo_rating.toFixed(0)}</div>
                            <div class="label">Elo</div>
                        </div>
                        <div class="version-metric">
                            <div class="value">${v.arena_wins}/${v.arena_losses}</div>
                            <div class="label">W/L</div>
                        </div>
                    </div>
                    <div class="version-actions">
                        <button class="btn small" onclick="dashboard.deleteVersion('${v.id}')">Delete</button>
                    </div>
                </div>
            `).join('');

            this.updateH2HSelectors(data.versions);

        } catch (error) {
            console.error('Failed to load versions:', error);
        }
    }

    updateH2HSelectors(versions) {
        const v1Select = document.getElementById('h2h-v1');
        const v2Select = document.getElementById('h2h-v2');
        if (!v1Select || !v2Select) return;

        const options = versions.map(v =>
            `<option value="${v.id}">${v.name} (${v.elo_rating.toFixed(0)})</option>`
        ).join('');

        v1Select.innerHTML = '<option value="">Select Version 1</option>' + options;
        v2Select.innerHTML = '<option value="">Select Version 2</option>' + options;
    }

    async deleteVersion(id) {
        if (!confirm('Delete this version?')) return;

        try {
            await fetch(`/api/versions/${id}`, { method: 'DELETE' });
            this.loadVersions();
            this.loadArena();
        } catch (error) {
            console.error('Failed to delete version:', error);
        }
    }

    // Load arena
    async loadArena() {
        try {
            const response = await fetch('/api/arena/leaderboard');
            const data = await response.json();

            if (data.error) {
                console.error('Arena error:', data.error);
                return;
            }

            const tbody = document.querySelector('#leaderboard tbody');
            if (!tbody) return;

            if (!data.leaderboard || data.leaderboard.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-state compact">No versions in arena yet.</td></tr>';
                return;
            }

            tbody.innerHTML = data.leaderboard.map(v => `
                <tr class="rank-${v.rank}">
                    <td>#${v.rank}</td>
                    <td>${v.name}</td>
                    <td>${v.elo.toFixed(0)}</td>
                    <td>${(v.accuracy * 100).toFixed(1)}%</td>
                    <td>${v.arena_record}</td>
                    <td>${(v.win_rate * 100).toFixed(0)}%</td>
                </tr>
            `).join('');

        } catch (error) {
            console.error('Failed to load arena:', error);
        }
    }

    // Head to head prediction
    async predictH2H() {
        const v1 = document.getElementById('h2h-v1').value;
        const v2 = document.getElementById('h2h-v2').value;

        if (!v1 || !v2 || v1 === v2) {
            alert('Select two different versions');
            return;
        }

        try {
            const response = await fetch(`/api/arena/head-to-head/${v1}/${v2}`);
            const data = await response.json();

            if (data.error) {
                alert(data.error);
                return;
            }

            const v1Pct = (data.expected_v1_win_rate * 100).toFixed(0);
            const v2Pct = (data.expected_v2_win_rate * 100).toFixed(0);

            document.getElementById('h2h-v1-bar').style.width = v1Pct + '%';
            document.getElementById('h2h-v2-bar').style.width = v2Pct + '%';
            document.getElementById('h2h-v1-pct').textContent = v1Pct + '%';
            document.getElementById('h2h-v2-pct').textContent = v2Pct + '%';
            document.getElementById('h2h-result').style.display = 'block';

        } catch (error) {
            console.error('Failed to predict H2H:', error);
        }
    }

    // ========== RL METHODS ==========

    initRL() {
        // RL control buttons
        document.getElementById('btn-rl-duel')?.addEventListener('click', () => this.runDuel());
        document.getElementById('btn-rl-start')?.addEventListener('click', () => this.startScenario());
        document.getElementById('btn-rl-stop')?.addEventListener('click', () => this.stopScenario());

        // Load scenarios
        this.loadScenarios();

        // Poll status
        this.rlPollInterval = null;
        this.rlState = 'idle';
    }

    async loadScenarios() {
        try {
            const response = await fetch('/api/rl/scenarios');
            const data = await response.json();

            const select = document.getElementById('rl-scenario-select');
            if (!select) return;

            select.innerHTML = '<option value="">Select scenario...</option>';
            if (data.scenarios && data.scenarios.length > 0) {
                for (const scenario of data.scenarios) {
                    const opt = document.createElement('option');
                    opt.value = scenario.path;
                    opt.textContent = scenario.name;
                    select.appendChild(opt);
                }
            }
        } catch (error) {
            console.error('Failed to load scenarios:', error);
        }
    }

    async runDuel() {
        const bot1 = document.getElementById('rl-bot1')?.value || 'test/ai/simple.leek';
        const bot2 = document.getElementById('rl-bot2')?.value || 'test/ai/simple.leek';
        const seedInput = document.getElementById('rl-seed');
        const seed = seedInput?.value ? parseInt(seedInput.value) : null;

        this.addLog('rl', 'info', `Running duel: ${bot1} vs ${bot2}${seed ? ` (seed: ${seed})` : ''}`);

        try {
            const response = await fetch('/api/rl/duel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot1, bot2, seed })
            });

            const result = await response.json();

            if (result.error) {
                this.addLog('rl', 'error', `Duel failed: ${result.error}`);
                this.notify('error', 'Duel Failed', result.error);
                return;
            }

            // Show result
            const resultEl = document.getElementById('duel-result');
            const outcomeEl = document.getElementById('duel-outcome');
            const durationEl = document.getElementById('duel-duration');
            const timeEl = document.getElementById('duel-time');

            if (resultEl) resultEl.style.display = 'block';

            const outcomes = { 0: 'Bot 1 wins!', 1: 'Bot 2 wins!', '-1': 'Draw' };
            if (outcomeEl) {
                outcomeEl.textContent = outcomes[result.winner] || 'Unknown';
                outcomeEl.className = 'duel-outcome ' + (result.winner === 0 ? 'win' : result.winner === 1 ? 'loss' : 'draw');
            }
            if (durationEl) durationEl.textContent = result.duration || '--';
            if (timeEl) timeEl.textContent = result.execution_time_ms ? result.execution_time_ms.toFixed(1) : '--';

            // Show telemetry if available
            if (result.telemetry) {
                this.displayTelemetry(result.telemetry);
            }

            this.addLog('rl', 'success', `Duel complete: ${outcomes[result.winner]}`);
            this.notify('success', 'Duel Complete', outcomes[result.winner] || 'Unknown result');

        } catch (error) {
            this.addLog('rl', 'error', `Error: ${error.message}`);
            this.notify('error', 'Error', error.message);
        }
    }

    displayTelemetry(telemetry) {
        const container = document.getElementById('telemetry-display');
        if (!container) return;

        let html = '';
        html += `<div class="telemetry-summary">`;
        html += `<div class="stat-compact"><span class="label">Turns</span><span class="value">${telemetry.total_turns || '--'}</span></div>`;
        html += `<div class="stat-compact"><span class="label">Winner</span><span class="value">Team ${(telemetry.winner || 0) + 1}</span></div>`;
        html += `</div>`;

        if (telemetry.agent_metrics) {
            html += `<div class="telemetry-agents">`;
            for (const [id, metrics] of Object.entries(telemetry.agent_metrics)) {
                html += `<div class="agent-metrics">`;
                html += `<div class="agent-name">${metrics.name} (T${metrics.team})</div>`;
                html += `<div class="agent-stats">`;
                html += `<span>DMG: ${metrics.total_damage_dealt || 0}</span>`;
                html += `<span>HP: ${metrics.final_hp || 0}/${metrics.max_hp || 0}</span>`;
                html += `<span>Eff: ${(metrics.tp_efficiency * 100 || 0).toFixed(0)}%</span>`;
                html += `</div></div>`;
            }
            html += `</div>`;
        }

        container.innerHTML = html;
    }

    async startScenario() {
        const select = document.getElementById('rl-scenario-select');
        const workersInput = document.getElementById('rl-workers');
        const yamlPath = select?.value;
        const workers = parseInt(workersInput?.value) || 4;

        if (!yamlPath) {
            this.notify('warning', 'No Scenario', 'Please select a scenario file');
            return;
        }

        this.addLog('rl', 'info', `Starting scenario: ${yamlPath} (workers: ${workers})`);

        try {
            const response = await fetch('/api/rl/scenario/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ yaml_path: yamlPath, max_workers: workers })
            });

            const result = await response.json();

            if (result.error) {
                this.addLog('rl', 'error', `Failed: ${result.error}`);
                this.notify('error', 'Scenario Failed', result.error);
                return;
            }

            this.setRLState('running');
            this.addLog('rl', 'success', 'Scenario started');
            this.notify('success', 'Scenario Started', `Running ${yamlPath}`);

            // Start polling progress
            this.startRLPolling();

        } catch (error) {
            this.addLog('rl', 'error', `Error: ${error.message}`);
            this.notify('error', 'Error', error.message);
        }
    }

    async stopScenario() {
        try {
            const response = await fetch('/api/rl/scenario/stop', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                this.setRLState('idle');
                this.addLog('rl', 'info', 'Scenario stopped');
                this.stopRLPolling();
            }
        } catch (error) {
            this.addLog('rl', 'error', `Error: ${error.message}`);
        }
    }

    setRLState(state) {
        this.rlState = state;

        const btnDuel = document.getElementById('btn-rl-duel');
        const btnStart = document.getElementById('btn-rl-start');
        const btnStop = document.getElementById('btn-rl-stop');
        const banner = document.getElementById('rl-status-banner');
        const icon = document.getElementById('rl-status-icon');
        const title = document.getElementById('rl-banner-title');
        const subtitle = document.getElementById('rl-banner-subtitle');
        const progressRow = document.getElementById('rl-progress-row');

        banner?.classList.remove('running', 'paused');

        if (state === 'running') {
            if (btnDuel) btnDuel.disabled = true;
            if (btnStart) btnStart.disabled = true;
            if (btnStop) btnStop.disabled = false;
            banner?.classList.add('running');
            if (icon) icon.textContent = '🏃';
            if (title) title.textContent = 'Running';
            if (subtitle) subtitle.textContent = 'Scenario in progress...';
            if (progressRow) progressRow.style.display = 'flex';
        } else {
            if (btnDuel) btnDuel.disabled = false;
            if (btnStart) btnStart.disabled = false;
            if (btnStop) btnStop.disabled = true;
            if (icon) icon.textContent = '⏸️';
            if (title) title.textContent = 'Idle';
            if (subtitle) subtitle.textContent = 'Ready';
            if (progressRow) progressRow.style.display = 'none';
        }
    }

    startRLPolling() {
        if (this.rlPollInterval) return;
        this.rlPollInterval = setInterval(() => this.loadRLProgress(), 1000);
    }

    stopRLPolling() {
        if (this.rlPollInterval) {
            clearInterval(this.rlPollInterval);
            this.rlPollInterval = null;
        }
    }

    async loadRLProgress() {
        try {
            const response = await fetch('/api/rl/scenario/progress');
            const data = await response.json();

            // FIXED: Properly parse progress object
            const progress = data.progress || {};
            const completed = progress.completed || 0;
            const total = progress.total || 0;
            const pct = total > 0 ? (completed / total * 100) : 0;

            // Update progress bar
            const progressBar = document.getElementById('rl-progress-bar');
            const progressCount = document.getElementById('rl-progress-count');

            if (progressBar) progressBar.style.width = `${pct}%`;
            if (progressCount) progressCount.textContent = `${completed} / ${total}`;

            // Update metrics
            const fightsEl = document.getElementById('rl-metric-fights');
            const speedEl = document.getElementById('rl-metric-speed');

            if (fightsEl) fightsEl.textContent = completed;
            if (speedEl) speedEl.textContent = progress.fights_per_sec ? progress.fights_per_sec.toFixed(1) : '--';

            // Update ETA
            const etaEl = document.getElementById('rl-eta');
            if (etaEl && progress.fights_per_sec > 0 && total > completed) {
                const remaining = total - completed;
                const etaSecs = remaining / progress.fights_per_sec;
                etaEl.textContent = etaSecs > 60 ? `${(etaSecs / 60).toFixed(1)}m` : `${etaSecs.toFixed(0)}s`;
            } else if (etaEl) {
                etaEl.textContent = '--';
            }

            // Check if done
            if (!data.is_running && this.rlState === 'running') {
                this.setRLState('idle');
                this.stopRLPolling();
                this.addLog('rl', 'success', 'Scenario completed');
                this.loadRLResults();
            }

        } catch (error) {
            console.error('Failed to load RL progress:', error);
        }
    }

    async loadRLResults() {
        try {
            const response = await fetch('/api/rl/results');
            const data = await response.json();

            const container = document.getElementById('scenario-results');
            if (!container) return;

            if (!data.results || data.results.length === 0) {
                container.innerHTML = '<p class="empty-state compact">No results yet</p>';
                return;
            }

            let html = '';
            for (const result of data.results) {
                const successCount = result.success_count || 0;
                const errorCount = result.error_count || 0;
                const totalCount = successCount + errorCount;

                html += `<div class="scenario-result">`;
                html += `<div class="scenario-name">${result.name}</div>`;
                html += `<div class="scenario-stats">`;
                html += `<span>Fights: ${successCount}/${totalCount}</span>`;
                html += `<span>Time: ${result.total_time?.toFixed(1) || '--'}s</span>`;
                html += `</div></div>`;
            }
            container.innerHTML = html;

        } catch (error) {
            console.error('Failed to load RL results:', error);
        }
    }

    // ========== SCRAPER METHODS ==========

    getScraperConfig() {
        return {
            delay: parseFloat(document.getElementById('scraper-delay')?.value || 1)
        };
    }

    async startScraper() {
        const config = this.getScraperConfig();
        this.addLog('scraper', 'info', `Starting scraper: delay=${config.delay}s`);

        try {
            const response = await fetch('/api/scraper/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            const result = await response.json();
            if (result.success) {
                this.setScraperState('running');
                this.addLog('scraper', 'success', 'Scraper started successfully');
                this.notify('success', 'Scraper Started', `Delay: ${config.delay}s`);
                this.startScraperPolling();
            } else {
                this.addLog('scraper', 'error', `Failed to start: ${result.error}`);
                this.notify('error', 'Scraper Failed', result.error);
            }
        } catch (error) {
            this.addLog('scraper', 'error', `Error: ${error.message}`);
            this.notify('error', 'Error', error.message);
        }
    }

    async pauseScraper() {
        try {
            const response = await fetch('/api/scraper/pause', { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                this.setScraperState(result.paused ? 'paused' : 'running');
                this.addLog('scraper', 'info', result.paused ? 'Scraper paused' : 'Scraper resumed');
                this.notify('info', result.paused ? 'Scraper Paused' : 'Scraper Resumed', '');
            }
        } catch (error) {
            this.addLog('scraper', 'error', `Error: ${error.message}`);
        }
    }

    async stopScraper() {
        try {
            const response = await fetch('/api/scraper/stop', { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                this.setScraperState('idle');
                this.addLog('scraper', 'info', 'Scraper stopped');
            }
        } catch (error) {
            this.addLog('scraper', 'error', `Error: ${error.message}`);
        }
    }

    async updateScraperDelay(delay) {
        // Set flag to prevent polling from overwriting user input
        this.delayUserEdit = true;

        try {
            const response = await fetch('/api/scraper/delay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delay: parseFloat(delay) })
            });
            const result = await response.json();
            if (result.success) {
                this.addLog('scraper', 'info', `Delay updated: ${result.old_delay}s → ${result.new_delay}s`);
                // Clear flag after a delay to let the next poll catch up with the new value
                setTimeout(() => { this.delayUserEdit = false; }, 3000);
            } else {
                this.addLog('scraper', 'error', `Failed to update delay: ${result.error}`);
                this.delayUserEdit = false;
            }
        } catch (error) {
            this.addLog('scraper', 'error', `Error updating delay: ${error.message}`);
            this.delayUserEdit = false;
        }
    }

    setScraperState(state) {
        this.scraperState = state;

        const btnStart = document.getElementById('btn-scraper-start');
        const btnPause = document.getElementById('btn-scraper-pause');
        const btnStop = document.getElementById('btn-scraper-stop');

        if (state === 'running') {
            if (btnStart) btnStart.disabled = true;
            if (btnPause) { btnPause.disabled = false; btnPause.innerHTML = '<span class="icon">⏸</span> Pause'; }
            if (btnStop) btnStop.disabled = false;
        } else if (state === 'paused') {
            if (btnStart) btnStart.disabled = true;
            if (btnPause) { btnPause.disabled = false; btnPause.innerHTML = '<span class="icon">▶</span> Resume'; }
            if (btnStop) btnStop.disabled = false;
        } else {
            if (btnStart) btnStart.disabled = false;
            if (btnPause) { btnPause.disabled = true; btnPause.innerHTML = '<span class="icon">⏸</span> Pause'; }
            if (btnStop) btnStop.disabled = true;
        }

        this.updateScraperBanner(state);
    }

    updateScraperBanner(state, data = null) {
        const banner = document.getElementById('scraper-status-banner');
        const icon = document.getElementById('scraper-status-icon');
        const title = document.getElementById('scraper-banner-title');
        const subtitle = document.getElementById('scraper-banner-subtitle');

        if (state === 'running') {
            banner?.classList.remove('paused', 'error');
            banner?.classList.add('running');
            if (icon) icon.textContent = '🔄';
            if (title) title.textContent = 'Running';
            if (subtitle) subtitle.textContent = data?.current_action || 'Downloading...';
        } else if (state === 'paused') {
            banner?.classList.remove('running', 'error');
            banner?.classList.add('paused');
            if (icon) icon.textContent = '⏸️';
            if (title) title.textContent = 'Paused';
            if (subtitle) subtitle.textContent = 'Resume to continue';
        } else if (state === 'error') {
            banner?.classList.remove('running', 'paused');
            banner?.classList.add('error');
            if (icon) icon.textContent = '❌';
            if (title) title.textContent = 'Error';
            if (subtitle) subtitle.textContent = data?.last_error || 'Unknown error';
        } else {
            banner?.classList.remove('running', 'paused', 'error');
            if (icon) icon.textContent = '⏸️';
            if (title) title.textContent = 'Idle';
            if (subtitle) subtitle.textContent = 'Ready';
        }
    }

    startScraperPolling() {
        if (this.scraperPollInterval) return;
        this.scraperPollInterval = setInterval(() => this.loadScraperStatus(), 2000);
    }

    async loadScraperStatus() {
        try {
            const response = await fetch('/api/scraper/status');
            const data = await response.json();

            if (data.error) {
                console.error('Scraper status error:', data.error);
                return;
            }

            // Update state
            const state = data.status;
            if (state !== this.scraperState) {
                this.setScraperState(state);
            }
            this.updateScraperBanner(state, data);

            // Update metrics in banner
            document.getElementById('scraper-metric-downloaded').textContent = data.fights_downloaded || 0;
            document.getElementById('scraper-metric-queue').textContent = data.queue_size || 0;
            document.getElementById('scraper-metric-total').textContent = data.total_in_db || 0;

            // Update detailed stats
            document.getElementById('stat-fights-downloaded').textContent = data.fights_downloaded || 0;
            document.getElementById('stat-fights-skipped').textContent = data.fights_skipped || 0;
            document.getElementById('stat-fights-failed').textContent = data.fights_failed || 0;
            document.getElementById('stat-requests-made').textContent = data.requests_made || 0;
            document.getElementById('stat-avg-request-time').textContent = data.avg_request_time ? `${data.avg_request_time}s` : '--';
            document.getElementById('stat-current-action').textContent = data.current_action || 'Idle';

            // Sync delay input with server value (only if not recently changed by user)
            const delayInput = document.getElementById('scraper-delay');
            if (delayInput && !this.delayUserEdit && data.delay !== undefined) {
                delayInput.value = data.delay;
            }

            // Show rate limit indicator if any 429s hit
            const rateLimitEl = document.getElementById('stat-rate-limit');
            const rateLimitHitsEl = document.getElementById('stat-rate-limit-hits');
            if (rateLimitEl && rateLimitHitsEl) {
                if (data.rate_limit_hits > 0) {
                    rateLimitEl.style.display = 'flex';
                    rateLimitHitsEl.textContent = data.rate_limit_hits;
                } else {
                    rateLimitEl.style.display = 'none';
                }
            }

            // Show/hide error banner
            const errorBanner = document.getElementById('scraper-error-banner');
            const errorText = document.getElementById('scraper-error-text');
            if (errorBanner && errorText) {
                if (data.last_error) {
                    errorBanner.style.display = 'flex';
                    errorText.textContent = data.last_error;
                } else {
                    errorBanner.style.display = 'none';
                }
            }

            // Also fetch db stats
            this.loadScraperDbStats();

        } catch (error) {
            console.error('Failed to load scraper status:', error);
        }
    }

    async loadScraperDbStats() {
        try {
            const response = await fetch('/api/scraper/database');
            const data = await response.json();

            if (data.error) {
                console.error('DB stats error:', data.error);
                return;
            }

            const container = document.getElementById('db-breakdown');
            if (!container) return;

            const typeNames = { 0: 'Solo', 1: 'Farmer', 2: 'Team' };
            const contextNames = { 2: 'Garden', 3: 'Tourney' };

            let html = '';

            // Total fights
            html += `<div class="stat-compact"><span class="label">Total</span><span class="value">${data.total_fights || 0}</span></div>`;

            // By type (only show non-zero)
            for (const [type, count] of Object.entries(data.by_type || {})) {
                if (count > 0) {
                    const name = typeNames[type] || `T${type}`;
                    html += `<div class="stat-compact"><span class="label">${name}</span><span class="value">${count}</span></div>`;
                }
            }

            // By context (only show non-zero, skip test/challenge)
            for (const [ctx, count] of Object.entries(data.by_context || {})) {
                if (count > 0 && contextNames[ctx]) {
                    html += `<div class="stat-compact"><span class="label">${contextNames[ctx]}</span><span class="value">${count}</span></div>`;
                }
            }

            html += `<div class="stat-compact"><span class="label">Players</span><span class="value">${data.players_scraped || 0}</span></div>`;
            html += `<div class="stat-compact"><span class="label">Leeks</span><span class="value">${data.unique_leeks || 0}</span></div>`;

            // Add DB size
            if (data.db_size_mb !== undefined) {
                html += `<div class="stat-compact"><span class="label">DB Size</span><span class="value">${data.db_size_mb.toFixed(1)} MB</span></div>`;
            }

            container.innerHTML = html;

            // Also update the stats panel elements
            const discoveryQueue = document.getElementById('stat-discovery-queue');
            if (discoveryQueue) discoveryQueue.textContent = data.discovery_queue || 0;

        } catch (error) {
            console.error('Failed to load DB stats:', error);
        }
    }

    // ========== ANALYTICS METHODS (DATA TAB) ==========

    initAnalytics() {
        // Level distribution chart filter
        const filter = document.getElementById('level-chart-filter');
        if (filter) {
            filter.addEventListener('change', () => this.loadLevelDistribution());
        }

        // Date chart bucket selector
        const dateBucket = document.getElementById('date-chart-bucket');
        if (dateBucket) {
            dateBucket.addEventListener('change', () => this.loadDateDistribution());
        }

        // Refresh button
        const refreshBtn = document.getElementById('btn-refresh-analytics');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.loadLevelDistribution();
                this.loadExplorationStats();
                this.loadDateDistribution();
            });
        }
    }

    async loadExplorationStats() {
        try {
            const response = await fetch('/api/scraper/analytics/exploration');
            const data = await response.json();

            if (data.error) {
                console.error('Exploration stats error:', data.error);
                return;
            }

            // Tournament exploration stats
            const tournaments = data.tournaments || {};
            const tournamentsEl = document.getElementById('tournaments-explored');
            const leeksEl = document.getElementById('tournament-leeks');
            const lowLevelEl = document.getElementById('tournament-low-level');
            const dateRangeEl = document.getElementById('tournament-date-range');

            if (tournamentsEl) tournamentsEl.textContent = tournaments.tournaments_explored || 0;
            if (leeksEl) leeksEl.textContent = tournaments.leeks_from_tournaments || 0;
            if (lowLevelEl) lowLevelEl.textContent = tournaments.low_level_from_tournaments || 0;

            // Date range
            if (dateRangeEl && tournaments.oldest_date && tournaments.newest_date) {
                const oldest = new Date(tournaments.oldest_date * 1000).toLocaleDateString();
                const newest = new Date(tournaments.newest_date * 1000).toLocaleDateString();
                dateRangeEl.textContent = `${oldest} - ${newest}`;
            }

            // Level 301 ratio indicator
            const ratio = data.level_301_ratio || 0;
            const ratioEl = document.getElementById('level-301-ratio');
            if (ratioEl) {
                ratioEl.textContent = `301: ${(ratio * 100).toFixed(1)}%`;
                ratioEl.classList.remove('warning', 'good');
                if (ratio > 0.5) {
                    ratioEl.classList.add('warning');
                } else {
                    ratioEl.classList.add('good');
                }
            }

            // Level brackets bar
            this.renderLevelBrackets(data.level_brackets || {});

        } catch (error) {
            console.error('Failed to load exploration stats:', error);
        }
    }

    renderLevelBrackets(brackets) {
        const container = document.getElementById('bracket-bars');
        if (!container) return;

        // Calculate total
        let total = 0;
        for (const bracket in brackets) {
            total += brackets[bracket].count || 0;
        }

        if (total === 0) {
            container.innerHTML = '<span style="padding: 4px;">No data</span>';
            return;
        }

        // Bracket order and CSS classes
        const bracketOrder = ['1-50', '51-100', '101-150', '151-200', '201-250', '251-300', '301'];
        const bracketClasses = {
            '1-50': 'b1-50',
            '51-100': 'b51-100',
            '101-150': 'b101-150',
            '151-200': 'b151-200',
            '201-250': 'b201-250',
            '251-300': 'b251-300',
            '301': 'b301'
        };

        let html = '';
        for (const bracket of bracketOrder) {
            const data = brackets[bracket];
            if (!data || data.count === 0) continue;

            const pct = (data.count / total * 100);
            const cls = bracketClasses[bracket] || '';
            html += `<div class="bracket-segment ${cls}" style="flex: ${pct}" title="${bracket}: ${data.count} (${pct.toFixed(1)}%)">${bracket}</div>`;
        }

        container.innerHTML = html;
    }

    async loadLevelDistribution() {
        const filter = document.getElementById('level-chart-filter');
        const fightType = filter?.value || '';
        const url = fightType
            ? `/api/scraper/analytics/levels?fight_type=${fightType}`
            : '/api/scraper/analytics/levels';

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Analytics error:', data.error);
                return;
            }

            this.renderLevelChart(data.distribution);
        } catch (error) {
            console.error('Failed to load level distribution:', error);
        }
    }

    renderLevelChart(distribution) {
        const ctx = document.getElementById('level-distribution-chart');
        if (!ctx) return;

        // Destroy existing chart
        if (this.levelChart) {
            this.levelChart.destroy();
        }

        if (!distribution || distribution.length === 0) {
            return;
        }

        const labels = distribution.map(d => `Lvl ${d.level}`);
        const counts = distribution.map(d => d.count);
        const uniqueLeeks = distribution.map(d => d.unique_leeks);

        this.levelChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Observations',
                        data: counts,
                        backgroundColor: 'rgba(88, 166, 255, 0.7)',
                        borderColor: 'rgba(88, 166, 255, 1)',
                        borderWidth: 1,
                    },
                    {
                        label: 'Unique Leeks',
                        data: uniqueLeeks,
                        backgroundColor: 'rgba(163, 113, 247, 0.7)',
                        borderColor: 'rgba(163, 113, 247, 1)',
                        borderWidth: 1,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (event, elements) => {
                    if (elements.length > 0) {
                        const index = elements[0].index;
                        const level = distribution[index].level;
                        this.loadLevelDetails(level);
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: '#e6edf3' }
                    },
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const idx = items[0].dataIndex;
                                const d = distribution[idx];
                                const winRate = d.wins / d.count * 100;
                                return `Win Rate: ${winRate.toFixed(1)}%`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    },
                    y: {
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    }
                }
            }
        });
    }

    async loadLevelDetails(level) {
        const filter = document.getElementById('level-chart-filter');
        const fightType = filter?.value || '';
        const url = fightType
            ? `/api/scraper/analytics/level/${level}?fight_type=${fightType}`
            : `/api/scraper/analytics/level/${level}`;

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Level details error:', data.error);
                return;
            }

            this.renderLevelDetails(level, data.stats, data.builds);
        } catch (error) {
            console.error('Failed to load level details:', error);
        }
    }

    renderLevelDetails(level, stats, builds) {
        const card = document.getElementById('level-details-card');
        if (!card) return;

        // Show the card
        card.style.display = 'block';

        // Update header
        document.getElementById('selected-level').textContent = level;

        // Update overview stats
        document.getElementById('level-observations').textContent = stats.observations || 0;
        document.getElementById('level-unique-leeks').textContent = stats.unique_leeks || 0;
        document.getElementById('level-win-rate').textContent =
            stats.win_rate ? `${(stats.win_rate * 100).toFixed(1)}%` : '--';

        // Render stats radar chart
        this.renderStatsChart(stats.avg_stats);

        // Render builds list
        this.renderBuilds(builds);

        // Scroll to the card
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    renderStatsChart(avgStats) {
        const ctx = document.getElementById('level-stats-chart');
        if (!ctx || !avgStats) return;

        // Destroy existing chart
        if (this.statsChart) {
            this.statsChart.destroy();
        }

        const labels = ['STR', 'AGI', 'WIS', 'RES', 'MAG', 'SCI'];
        const values = [
            avgStats.strength || 0,
            avgStats.agility || 0,
            avgStats.wisdom || 0,
            avgStats.resistance || 0,
            avgStats.magic || 0,
            avgStats.science || 0,
        ];

        this.statsChart = new Chart(ctx, {
            type: 'radar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Average Stats',
                    data: values,
                    backgroundColor: 'rgba(88, 166, 255, 0.2)',
                    borderColor: 'rgba(88, 166, 255, 1)',
                    borderWidth: 2,
                    pointBackgroundColor: 'rgba(88, 166, 255, 1)',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    r: {
                        ticks: { color: '#8b949e', backdropColor: 'transparent' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' },
                        pointLabels: { color: '#e6edf3' }
                    }
                }
            }
        });
    }

    renderBuilds(builds) {
        const container = document.getElementById('level-builds');
        if (!container) return;

        if (!builds || builds.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary);">No build data available</p>';
            return;
        }

        const buildTypeColors = {
            'Strength': 'strength',
            'Agility': 'agility',
            'Magic': 'magic',
            'Balanced': 'balanced'
        };

        container.innerHTML = builds.map(build => {
            const colorClass = buildTypeColors[build.build_type] || 'balanced';
            const winRate = (build.win_rate * 100).toFixed(1);
            const winRateClass = build.win_rate >= 0.55 ? 'good' : build.win_rate >= 0.45 ? 'average' : 'poor';

            return `
                <div class="build-item ${colorClass}">
                    <div>
                        <div class="build-name">${build.build_type}</div>
                        <div class="build-stats">
                            <span class="build-stat"><span class="label">STR:</span>${Math.round(build.avg_stats.strength)}</span>
                            <span class="build-stat"><span class="label">AGI:</span>${Math.round(build.avg_stats.agility)}</span>
                            <span class="build-stat"><span class="label">MAG:</span>${Math.round(build.avg_stats.magic)}</span>
                        </div>
                        <div class="build-count">${build.count} observations</div>
                    </div>
                    <div class="build-win-rate ${winRateClass}">${winRate}%</div>
                </div>
            `;
        }).join('');
    }

    // ========== DATE DISTRIBUTION METHODS ==========

    // Cutoff date: Feb 20, 2024 - game balance change
    static DATA_CUTOFF_DATE = new Date('2024-02-20');

    async loadDateDistribution() {
        const bucketSelect = document.getElementById('date-chart-bucket');
        const bucket = bucketSelect?.value || 'month';
        const url = `/api/scraper/analytics/dates?bucket=${bucket}`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                console.error('Date API response not ok:', response.status);
                return;
            }
            const data = await response.json();

            if (data.error) {
                console.error('Date distribution error:', data.error);
                return;
            }

            // Update freshness badges
            if (data.freshness) {
                this.updateFreshnessBadges(data.freshness);
            }

            this.renderDateChart(data.distribution, bucket);
        } catch (error) {
            console.error('Failed to load date distribution:', error);
        }
    }

    updateFreshnessBadges(freshness) {
        const recentBadge = document.getElementById('freshness-recent-badge');
        const oldBadge = document.getElementById('freshness-old-badge');

        const recentRatio = freshness.recent_ratio || 0;
        const oldRatio = freshness.old_ratio || 0;

        if (recentBadge) {
            recentBadge.textContent = `${(recentRatio * 100).toFixed(0)}% new`;
        }
        if (oldBadge) {
            oldBadge.textContent = `${(oldRatio * 100).toFixed(0)}% old`;
        }
    }

    isPeriodBeforeCutoff(period, bucket) {
        // Determine if a period label is before the cutoff date (Feb 20, 2024)
        const cutoff = Dashboard.DATA_CUTOFF_DATE;

        if (bucket === 'month') {
            // Format: "2024-02"
            const [year, month] = period.split('-').map(Number);
            // Feb 2024 is transitional, consider it old
            return year < 2024 || (year === 2024 && month < 3);
        } else if (bucket === 'week') {
            // Format: "2024-W08"
            const [year, weekStr] = period.split('-W');
            const week = parseInt(weekStr);
            // Week 8 of 2024 contains Feb 20, consider weeks before as old
            return parseInt(year) < 2024 || (parseInt(year) === 2024 && week < 8);
        } else {
            // Format: "2024-02-20"
            const date = new Date(period);
            return date < cutoff;
        }
    }

    renderDateChart(distribution, bucket) {
        const ctx = document.getElementById('date-distribution-chart');
        if (!ctx) return;

        // Destroy existing chart
        if (this.dateChart) {
            this.dateChart.destroy();
        }

        if (!distribution || distribution.length === 0) {
            return;
        }

        const labels = distribution.map(d => d.period);
        const counts = distribution.map(d => d.count);
        const avgLevels = distribution.map(d => d.avg_level);

        // Color bars based on whether they're before/after the cutoff
        const barColors = distribution.map(d => {
            const isOld = this.isPeriodBeforeCutoff(d.period, bucket);
            return isOld ? 'rgba(248, 81, 73, 0.6)' : 'rgba(88, 166, 255, 0.7)';
        });
        const borderColors = distribution.map(d => {
            const isOld = this.isPeriodBeforeCutoff(d.period, bucket);
            return isOld ? 'rgba(248, 81, 73, 1)' : 'rgba(88, 166, 255, 1)';
        });

        this.dateChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Fights',
                        data: counts,
                        backgroundColor: barColors,
                        borderColor: borderColors,
                        borderWidth: 1,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Avg Level',
                        data: avgLevels,
                        type: 'line',
                        borderColor: 'rgba(63, 185, 80, 1)',
                        backgroundColor: 'rgba(63, 185, 80, 0.2)',
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: false,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        labels: { color: '#e6edf3' }
                    },
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const idx = items[0].dataIndex;
                                const d = distribution[idx];
                                const isOld = this.isPeriodBeforeCutoff(d.period, bucket);
                                const status = isOld ? '(OLD - pre-patch)' : '(Recent)';
                                return `Avg Level: ${d.avg_level?.toFixed(1) || '--'}\n${status}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: '#8b949e',
                            maxRotation: 45,
                            minRotation: 0
                        },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    },
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {
                            display: true,
                            text: 'Fights',
                            color: '#8b949e'
                        },
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {
                            display: true,
                            text: 'Avg Level',
                            color: '#8b949e'
                        },
                        ticks: { color: '#8b949e' },
                        grid: { drawOnChartArea: false },
                        min: 0,
                        max: 301
                    }
                }
            }
        });
    }

    // ========== BUILDS TAB METHODS ==========

    async loadMetadataStatus() {
        try {
            const response = await fetch('/api/metadata/status');
            const data = await response.json();

            if (data.error) {
                console.error('Metadata status error:', data.error);
                this.addLog('builds', 'error', `Failed to load metadata status: ${data.error}`);
                return;
            }

            const progress = data.progress;
            const pct = progress.progress_percent;

            document.getElementById('meta-total-fights').textContent = progress.total_fights.toLocaleString();
            document.getElementById('meta-extracted').textContent = progress.extracted_fights.toLocaleString();
            document.getElementById('meta-remaining').textContent = progress.remaining_fights.toLocaleString();
            document.getElementById('metadata-progress-bar').style.width = `${pct}%`;
            document.getElementById('metadata-progress-text').textContent = `${pct.toFixed(1)}%`;

            if (progress.last_extraction_time) {
                const date = new Date(progress.last_extraction_time);
                document.getElementById('meta-last-run').textContent = date.toLocaleString();
            }

        } catch (error) {
            console.error('Failed to load metadata status:', error);
            this.addLog('builds', 'error', `Failed to load metadata status: ${error.message}`);
        }
    }

    async extractMetadata() {
        const btn = document.getElementById('btn-extract-metadata');
        const status = document.getElementById('extraction-status');

        btn.disabled = true;
        status.textContent = 'Extracting...';
        status.className = 'extraction-status running';

        try {
            const response = await fetch('/api/metadata/extract?batch_size=500&max_batches=20', {
                method: 'POST'
            });
            const data = await response.json();

            if (data.error) {
                status.textContent = `Error: ${data.error}`;
                status.className = 'extraction-status error';
            } else {
                status.textContent = `Saved ${data.records_saved.toLocaleString()} records`;
                status.className = 'extraction-status success';
                await this.loadMetadataStatus();
            }
        } catch (error) {
            status.textContent = `Error: ${error.message}`;
            status.className = 'extraction-status error';
        } finally {
            btn.disabled = false;
        }
    }

    async loadEquipmentData() {
        const fightType = document.getElementById('equipment-fight-type')?.value || '';
        const url = fightType
            ? `/api/metadata/equipment?fight_type=${fightType}`
            : '/api/metadata/equipment';

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Equipment data error:', data.error);
                this.addLog('builds', 'error', `Failed to load equipment data: ${data.error}`);
                return;
            }

            if (!data.by_level || Object.keys(data.by_level).length === 0) {
                console.warn('No equipment data available');
                this.addLog('builds', 'warning', 'No equipment data available. Click "Extract Metadata" first.');
                return;
            }

            this.renderEquipmentChart(data.by_level);
            this.renderEquipmentTables(data.by_level);
            this.addLog('builds', 'info', `Loaded equipment data for ${Object.keys(data.by_level).length} level brackets`);

        } catch (error) {
            console.error('Failed to load equipment data:', error);
            this.addLog('builds', 'error', `Failed to load equipment data: ${error.message}`);
        }
    }

    renderEquipmentChart(byLevel) {
        const canvas = document.getElementById('equipment-chart');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        if (this.equipmentChart) {
            this.equipmentChart.destroy();
        }

        // Sort buckets by level
        const buckets = Object.keys(byLevel).sort((a, b) => {
            const aNum = parseInt(a.split('-')[0]) || 301;
            const bNum = parseInt(b.split('-')[0]) || 301;
            return aNum - bNum;
        });

        if (buckets.length === 0) {
            return;
        }

        // Get top weapons across all levels
        const weaponCounts = {};
        for (const bucket of buckets) {
            const data = byLevel[bucket];
            for (const [id, info] of Object.entries(data.weapons || {})) {
                if (!weaponCounts[info.name]) {
                    weaponCounts[info.name] = { total: 0, id };
                }
                weaponCounts[info.name].total += info.count;
            }
        }

        const topWeapons = Object.entries(weaponCounts)
            .sort((a, b) => b[1].total - a[1].total)
            .slice(0, 8)
            .map(([name]) => name);

        // Build datasets for top weapons
        const colors = [
            'rgba(88, 166, 255, 0.8)',
            'rgba(163, 113, 247, 0.8)',
            'rgba(87, 171, 90, 0.8)',
            'rgba(255, 166, 87, 0.8)',
            'rgba(255, 99, 132, 0.8)',
            'rgba(75, 192, 192, 0.8)',
            'rgba(255, 205, 86, 0.8)',
            'rgba(201, 203, 207, 0.8)',
        ];

        const datasets = topWeapons.map((weapon, i) => {
            const data = buckets.map(bucket => {
                const weapons = byLevel[bucket].weapons || {};
                for (const [id, info] of Object.entries(weapons)) {
                    if (info.name === weapon) return info.pct;
                }
                return 0;
            });

            return {
                label: weapon,
                data: data,
                backgroundColor: colors[i % colors.length],
                borderColor: colors[i % colors.length].replace('0.8', '1'),
                borderWidth: 1,
            };
        });

        this.equipmentChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: buckets,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { color: '#e6edf3', boxWidth: 12, padding: 8 }
                    },
                    title: {
                        display: true,
                        text: 'Weapon Usage by Level (%)',
                        color: '#e6edf3'
                    }
                },
                scales: {
                    x: {
                        stacked: false,
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    },
                    y: {
                        stacked: false,
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' },
                        title: {
                            display: true,
                            text: '% of leeks using',
                            color: '#8b949e'
                        }
                    }
                }
            }
        });
    }

    renderEquipmentTables(byLevel) {
        const weaponsContainer = document.getElementById('weapons-table');
        const chipsContainer = document.getElementById('chips-table');

        if (!weaponsContainer || !chipsContainer) return;

        // Sort buckets
        const buckets = Object.keys(byLevel).sort((a, b) => {
            const aNum = parseInt(a.split('-')[0]) || 301;
            const bNum = parseInt(b.split('-')[0]) || 301;
            return aNum - bNum;
        });

        // Build weapons table
        let weaponsHtml = '<table class="equipment-table"><thead><tr><th>Level</th><th>Sample</th><th>Top Weapons</th></tr></thead><tbody>';
        for (const bucket of buckets) {
            const data = byLevel[bucket];
            const topWeapons = Object.entries(data.weapons || {})
                .sort((a, b) => b[1].pct - a[1].pct)
                .slice(0, 3)
                .map(([id, info]) => `${info.name} (${info.pct}%)`)
                .join(', ');
            weaponsHtml += `<tr><td>${bucket}</td><td>${data.sample_size.toLocaleString()}</td><td>${topWeapons || '-'}</td></tr>`;
        }
        weaponsHtml += '</tbody></table>';
        weaponsContainer.innerHTML = weaponsHtml;

        // Build chips table
        let chipsHtml = '<table class="equipment-table"><thead><tr><th>Level</th><th>Top Chips</th></tr></thead><tbody>';
        for (const bucket of buckets) {
            const data = byLevel[bucket];
            const topChips = Object.entries(data.chips || {})
                .sort((a, b) => b[1].pct - a[1].pct)
                .slice(0, 4)
                .map(([id, info]) => `${info.name} (${info.pct}%)`)
                .join(', ');
            chipsHtml += `<tr><td>${bucket}</td><td>${topChips || '-'}</td></tr>`;
        }
        chipsHtml += '</tbody></table>';
        chipsContainer.innerHTML = chipsHtml;
    }

    setupBuildsTab() {
        // Extract button
        document.getElementById('btn-extract-metadata')?.addEventListener('click', () => {
            this.extractMetadata();
        });

        // Refresh button
        document.getElementById('btn-refresh-equipment')?.addEventListener('click', () => {
            this.loadEquipmentData();
        });

        // Fight type filter
        document.getElementById('equipment-fight-type')?.addEventListener('change', () => {
            this.loadEquipmentData();
        });

        // Co-occurrence controls
        document.getElementById('btn-refresh-cooccurrence')?.addEventListener('click', () => {
            this.loadCooccurrenceData();
        });

        // Cluster controls
        document.getElementById('btn-refresh-clusters')?.addEventListener('click', () => {
            this.loadClusterData();
        });

        // Evolution controls
        document.getElementById('btn-load-evolution')?.addEventListener('click', () => {
            this.loadEvolutionData();
        });

        // Insights controls
        document.getElementById('btn-load-insights')?.addEventListener('click', () => {
            this.loadInsights();
        });

        // Initial load
        this.loadMetadataStatus();
        this.loadDataFreshness();
    }

    async loadDataFreshness() {
        const textEl = document.getElementById('freshness-text');
        if (!textEl) return;

        try {
            const response = await fetch('/api/scraper/database');
            const data = await response.json();

            const totalFights = data.total_fights || 0;
            const dbSize = data.db_size_mb || 0;

            // Get date range from fights
            const dateResponse = await fetch('/api/data/dates');
            const dateData = await dateResponse.json();
            const range = dateData.date_range || {};

            if (range.oldest_date && range.newest_date) {
                const oldest = new Date(range.oldest_date * 1000).toLocaleDateString();
                const newest = new Date(range.newest_date * 1000).toLocaleDateString();
                textEl.innerHTML = `<strong>${totalFights.toLocaleString()}</strong> fights from <strong>${oldest}</strong> to <strong>${newest}</strong> (${dbSize.toFixed(1)} MB)`;
            } else {
                textEl.innerHTML = `<strong>${totalFights.toLocaleString()}</strong> fights in database (${dbSize.toFixed(1)} MB)`;
            }
        } catch (error) {
            textEl.textContent = 'Unable to load data info';
        }
    }

    async loadInsights() {
        const container = document.getElementById('insights-container');
        container.innerHTML = '<p class="loading-state">Analyzing build trends...</p>';

        try {
            const response = await fetch('/api/metadata/insights');
            const data = await response.json();

            if (data.error) {
                container.innerHTML = `<p class="empty-state">Error: ${data.error}</p>`;
                return;
            }

            if (!data.insights || data.insights.length === 0) {
                container.innerHTML = '<p class="empty-state">No insights available yet</p>';
                return;
            }

            container.innerHTML = data.insights.map(insight => `
                <div class="insight-item ${insight.type}">
                    <span class="insight-icon">${insight.icon}</span>
                    <span class="insight-text">${insight.text}</span>
                </div>
            `).join('');

            this.addLog('builds', 'success', `Generated ${data.insights.length} insights`);

        } catch (error) {
            console.error('Failed to load insights:', error);
            container.innerHTML = `<p class="empty-state">Failed to load: ${error.message}</p>`;
        }
    }

    async loadEvolutionData() {
        const nClusters = document.getElementById('evolution-clusters')?.value || '6';
        const url = `/api/metadata/clusters/evolution?n_clusters=${nClusters}`;

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Evolution data error:', data.error);
                this.addLog('builds', 'error', `Evolution analysis failed: ${data.error}`);
                return;
            }

            this.renderEvolutionChart(data);
            this.addLog('builds', 'success', `Loaded evolution data from ${data.sample_count.toLocaleString()} samples`);

        } catch (error) {
            console.error('Failed to load evolution data:', error);
            this.addLog('builds', 'error', `Evolution analysis failed: ${error.message}`);
        }
    }

    renderEvolutionChart(data) {
        const canvas = document.getElementById('evolution-chart');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        // Destroy existing chart
        if (this.evolutionChart) {
            this.evolutionChart.destroy();
        }

        const { evolution, archetypes, archetype_colors } = data;

        // Build labels (level ranges)
        const labels = evolution.map(e => e.level_range);

        // Build datasets for stacked area chart
        const datasets = archetypes.map(archetype => {
            const color = archetype_colors[archetype] || '#8b949e';
            const dataPoints = evolution.map(e => {
                const cluster = e.clusters[archetype];
                return cluster ? cluster.pct : 0;
            });

            return {
                label: archetype,
                data: dataPoints,
                backgroundColor: color + 'cc',  // Semi-transparent
                borderColor: color,
                borderWidth: 1,
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointHoverRadius: 4,
            };
        });

        this.evolutionChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Level Range',
                            color: '#8b949e'
                        },
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    },
                    y: {
                        stacked: true,
                        min: 0,
                        max: 100,
                        title: {
                            display: true,
                            text: '% of Builds',
                            color: '#8b949e'
                        },
                        ticks: { color: '#8b949e' },
                        grid: { color: 'rgba(48, 54, 61, 0.5)' }
                    }
                },
                plugins: {
                    legend: {
                        display: false  // We'll use custom legend
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.raw.toFixed(1)}%`;
                            }
                        }
                    }
                }
            }
        });

        // Render custom legend with totals
        this.renderEvolutionLegend(data);
    }

    renderEvolutionLegend(data) {
        const container = document.getElementById('evolution-legend');
        if (!container) return;

        const { evolution, archetypes, archetype_colors } = data;

        // Calculate overall percentages
        const totals = {};
        let grandTotal = 0;

        for (const archetype of archetypes) {
            totals[archetype] = 0;
        }

        for (const bucket of evolution) {
            for (const [archetype, info] of Object.entries(bucket.clusters)) {
                totals[archetype] = (totals[archetype] || 0) + info.count;
                grandTotal += info.count;
            }
        }

        // Sort by total count
        const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);

        container.innerHTML = sorted.map(([archetype, count]) => {
            const color = archetype_colors[archetype] || '#8b949e';
            const pct = grandTotal > 0 ? (count / grandTotal * 100).toFixed(1) : 0;
            return `
                <div class="evolution-legend-item">
                    <span class="dot" style="background-color: ${color}"></span>
                    <span>${archetype}</span>
                    <span class="pct">${pct}%</span>
                </div>
            `;
        }).join('');
    }

    async loadClusterData() {
        const levelMin = document.getElementById('cluster-level-min')?.value || '1';
        const levelMax = document.getElementById('cluster-level-max')?.value || '301';
        const nClusters = document.getElementById('cluster-count')?.value || '6';

        const url = `/api/metadata/clusters?n_clusters=${nClusters}&level_min=${levelMin}&level_max=${levelMax}`;

        const container = document.getElementById('clusters-container');
        container.innerHTML = '<p class="loading-state">Analyzing build archetypes...</p>';

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                container.innerHTML = `<p class="empty-state">Error: ${data.error}</p>`;
                this.addLog('builds', 'error', `Cluster analysis failed: ${data.error}`);
                return;
            }

            // Update stats
            document.getElementById('cluster-sample-count').textContent = data.sample_count.toLocaleString();
            document.getElementById('cluster-archetype-count').textContent = data.n_clusters;

            // Render clusters
            this.renderClusters(data.clusters);
            this.addLog('builds', 'success', `Found ${data.clusters.length} archetypes from ${data.sample_count.toLocaleString()} samples`);

        } catch (error) {
            console.error('Failed to load cluster data:', error);
            container.innerHTML = `<p class="empty-state">Failed to load data: ${error.message}</p>`;
            this.addLog('builds', 'error', `Cluster analysis failed: ${error.message}`);
        }
    }

    renderClusters(clusters) {
        const container = document.getElementById('clusters-container');

        if (!clusters || clusters.length === 0) {
            container.innerHTML = '<p class="empty-state">No clusters found. Try adjusting parameters.</p>';
            return;
        }

        let html = '';

        for (const cluster of clusters) {
            // Determine card class based on archetype
            let cardClass = 'hybrid';
            const archLower = cluster.archetype.toLowerCase();
            if (archLower.includes('strength')) cardClass = 'strength';
            else if (archLower.includes('agility')) cardClass = 'agility';
            else if (archLower.includes('magic')) cardClass = 'magic';
            else if (archLower.includes('tank')) cardClass = 'tank';

            // Find dominant stat
            const stats = cluster.centroid;
            const statValues = [
                { name: 'STR', value: stats.strength, key: 'strength' },
                { name: 'AGI', value: stats.agility, key: 'agility' },
                { name: 'MAG', value: stats.magic, key: 'magic' },
                { name: 'RES', value: stats.resistance, key: 'resistance' }
            ];
            const maxStat = Math.max(...statValues.map(s => s.value));

            // Build stat boxes
            const statBoxes = statValues.map(s => {
                const pct = (s.value * 100).toFixed(1);
                const dominant = s.value === maxStat ? 'dominant' : '';
                return `<div class="cluster-stat ${dominant}">
                    <span class="stat-name">${s.name}</span>
                    <span class="stat-pct">${pct}%</span>
                </div>`;
            }).join('');

            // Build equipment tags
            let equipmentHtml = '';
            if (cluster.top_weapons && cluster.top_weapons.length > 0) {
                const weaponTags = cluster.top_weapons.slice(0, 3).map(w => {
                    const name = Array.isArray(w) ? w[0] : w.name;
                    return `<span class="equipment-tag weapon">${name}</span>`;
                }).join('');
                equipmentHtml += `<div class="cluster-equipment-list">${weaponTags}</div>`;
            }
            if (cluster.top_chips && cluster.top_chips.length > 0) {
                const chipTags = cluster.top_chips.slice(0, 4).map(c => {
                    const name = Array.isArray(c) ? c[0] : c.name;
                    return `<span class="equipment-tag chip">${name}</span>`;
                }).join('');
                equipmentHtml += `<div class="cluster-equipment-list" style="margin-top: 4px;">${chipTags}</div>`;
            }

            html += `
                <div class="cluster-card ${cardClass}">
                    <div class="cluster-header">
                        <span class="cluster-name">${cluster.archetype}</span>
                        <span class="cluster-size">${cluster.size.toLocaleString()} leeks</span>
                    </div>
                    <div class="cluster-body">
                        <div class="cluster-radar">
                            <canvas id="radar-${cluster.id}" width="100" height="100"></canvas>
                        </div>
                        <div class="cluster-info">
                            <div class="cluster-stats">${statBoxes}</div>
                            <div class="cluster-avg-level">
                                <span>Avg Level:</span>
                                <span class="value">${cluster.avg_level.toFixed(0)}</span>
                            </div>
                        </div>
                    </div>
                    ${equipmentHtml ? `<div class="cluster-equipment">
                        <div class="cluster-equipment-title">Popular Equipment</div>
                        ${equipmentHtml}
                    </div>` : ''}
                </div>
            `;
        }

        container.innerHTML = html;

        // Render radar charts for each cluster
        for (const cluster of clusters) {
            this.renderClusterRadar(cluster);
        }
    }

    renderClusterRadar(cluster) {
        const canvas = document.getElementById(`radar-${cluster.id}`);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const stats = cluster.centroid;

        // Destroy existing chart if any
        if (this.clusterRadars && this.clusterRadars[cluster.id]) {
            this.clusterRadars[cluster.id].destroy();
        }
        if (!this.clusterRadars) this.clusterRadars = {};

        // Color based on archetype
        let color = '#58a6ff';
        const arch = cluster.archetype.toLowerCase();
        if (arch.includes('str')) color = '#f85149';
        else if (arch.includes('agi')) color = '#3fb950';
        else if (arch.includes('mag')) color = '#a371f7';
        else if (arch.includes('res') || arch.includes('tank')) color = '#d29922';

        this.clusterRadars[cluster.id] = new Chart(ctx, {
            type: 'radar',
            data: {
                labels: ['STR', 'AGI', 'MAG', 'RES'],
                datasets: [{
                    data: [
                        stats.strength * 100,
                        stats.agility * 100,
                        stats.magic * 100,
                        stats.resistance * 100
                    ],
                    backgroundColor: color + '40',
                    borderColor: color,
                    borderWidth: 2,
                    pointRadius: 2,
                    pointBackgroundColor: color,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                        ticks: { display: false, stepSize: 25 },
                        pointLabels: {
                            color: '#8b949e',
                            font: { size: 9 }
                        },
                        grid: { color: '#30363d' },
                        angleLines: { color: '#30363d' }
                    }
                }
            }
        });
    }

    async loadCooccurrenceData() {
        const levelBucket = document.getElementById('cooccurrence-level')?.value || '';
        const itemType = document.getElementById('cooccurrence-type')?.value || '';

        let url = '/api/metadata/cooccurrence?min_cooccurrence=20';
        if (levelBucket) url += `&level_bucket=${levelBucket}`;
        if (itemType) url += `&item_type=${itemType}`;

        const heatmapContainer = document.getElementById('cooccurrence-heatmap');
        const statsContainer = document.getElementById('cooccurrence-stats');

        try {
            heatmapContainer.innerHTML = '<p class="loading-state">Loading co-occurrence data...</p>';

            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                heatmapContainer.innerHTML = `<p class="empty-state">Error: ${data.error}</p>`;
                return;
            }

            if (!data.items || data.items.length === 0) {
                heatmapContainer.innerHTML = '<p class="empty-state">No co-occurrence data available. Try lowering the minimum threshold.</p>';
                return;
            }

            this.renderCooccurrenceHeatmap(data);
            this.renderCooccurrenceStats(data);
            this.addLog('builds', 'info', `Loaded co-occurrence data for ${data.items.length} items`);

        } catch (error) {
            console.error('Failed to load co-occurrence data:', error);
            heatmapContainer.innerHTML = `<p class="empty-state">Failed to load data: ${error.message}</p>`;
        }
    }

    renderCooccurrenceHeatmap(data) {
        const container = document.getElementById('cooccurrence-heatmap');
        const legendContainer = document.getElementById('cooccurrence-legend');
        const { items, matrix } = data;

        if (!items || items.length === 0) {
            container.innerHTML = '<p class="empty-state">No data to display</p>';
            return;
        }

        // Find max value for scaling
        let maxVal = 0;
        for (const row of matrix) {
            for (const val of row) {
                if (val > maxVal) maxVal = val;
            }
        }

        // Build heatmap table
        let html = '<table class="heatmap-table"><thead><tr><th></th>';
        for (const item of items) {
            const shortName = item.name.substring(0, 8);
            html += `<th title="${item.name}">${shortName}</th>`;
        }
        html += '</tr></thead><tbody>';

        for (let i = 0; i < items.length; i++) {
            html += `<tr><th class="row-header" title="${items[i].name}">${items[i].name.substring(0, 10)}</th>`;
            for (let j = 0; j < items.length; j++) {
                const val = matrix[i][j];
                const intensity = maxVal > 0 ? val / maxVal : 0;
                const color = this.getHeatmapColor(intensity);
                const title = `${items[i].name} + ${items[j].name}: ${val}`;
                html += `<td class="heatmap-cell" style="background-color: ${color}" title="${title}">${val > 0 ? '' : ''}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table>';

        container.innerHTML = html;

        // Build legend
        legendContainer.innerHTML = `
            <div class="legend-gradient"></div>
            <div class="legend-labels">
                <span>${maxVal}</span>
                <span>${Math.round(maxVal * 0.66)}</span>
                <span>${Math.round(maxVal * 0.33)}</span>
                <span>0</span>
            </div>
        `;
    }

    getHeatmapColor(intensity) {
        // Purple gradient from dark to bright
        const r = Math.round(48 + (163 - 48) * intensity);
        const g = Math.round(54 + (113 - 54) * intensity);
        const b = Math.round(61 + (247 - 61) * intensity);
        const alpha = 0.3 + intensity * 0.7;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    renderCooccurrenceStats(data) {
        const container = document.getElementById('cooccurrence-stats');
        const { items, matrix, counts } = data;

        // Find top pairs
        const pairs = [];
        for (let i = 0; i < items.length; i++) {
            for (let j = i + 1; j < items.length; j++) {
                if (matrix[i][j] > 0) {
                    pairs.push({
                        item1: items[i],
                        item2: items[j],
                        count: matrix[i][j]
                    });
                }
            }
        }
        pairs.sort((a, b) => b.count - a.count);
        const topPairs = pairs.slice(0, 5);

        // Calculate stats
        const totalPairs = pairs.reduce((sum, p) => sum + p.count, 0);
        const weaponCount = items.filter(i => i.type === 'weapon').length;
        const chipCount = items.filter(i => i.type === 'chip').length;

        let html = `
            <div class="cooccurrence-stat">
                <span class="label">Total Items</span>
                <span class="value">${items.length}</span>
            </div>
            <div class="cooccurrence-stat">
                <span class="label">Weapons</span>
                <span class="value">${weaponCount}</span>
            </div>
            <div class="cooccurrence-stat">
                <span class="label">Chips</span>
                <span class="value">${chipCount}</span>
            </div>
            <div class="cooccurrence-stat">
                <span class="label">Total Pairs</span>
                <span class="value">${totalPairs.toLocaleString()}</span>
            </div>
        `;

        if (topPairs.length > 0) {
            html += '<div class="top-pairs-list" style="width: 100%; margin-top: 12px;"><strong>Top Equipment Pairs:</strong>';
            for (const pair of topPairs) {
                const type1Class = pair.item1.type === 'weapon' ? 'weapon' : 'chip';
                const type2Class = pair.item2.type === 'weapon' ? 'weapon' : 'chip';
                html += `
                    <div class="pair-item">
                        <div class="pair-names">
                            <span class="pair-name ${type1Class}">${pair.item1.name}</span>
                            <span>+</span>
                            <span class="pair-name ${type2Class}">${pair.item2.name}</span>
                        </div>
                        <span class="pair-count">${pair.count}</span>
                    </div>
                `;
            }
            html += '</div>';
        }

        container.innerHTML = html;
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
    window.dashboard.loadHistory();
    window.dashboard.setupBuildsTab();
    window.dashboard.addLog('training', 'info', 'Dashboard initialized');
});
