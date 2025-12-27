// Neural Network Training Dashboard Module

class NNDashboard {
    constructor(dashboard) {
        this.dashboard = dashboard;
        this.charts = {};
        this.historyData = {
            epochs: [],
            trainLoss: [],
            valLoss: [],
            valAccuracy: []
        };
        this.state = 'idle'; // idle, loading, training, done, error
        this.initialized = false;
    }

    init() {
        if (this.initialized) return;
        this.initCharts();
        this.initControls();
        this.loadDataInfo();
        this.loadModels();
        this.initialized = true;
    }

    initCharts() {
        // Chart.js global config
        Chart.defaults.color = '#8b949e';
        Chart.defaults.borderColor = '#30363d';

        // Loss chart
        const lossCtx = document.getElementById('nn-loss-chart');
        if (lossCtx) {
            this.charts.loss = new Chart(lossCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Train Loss',
                        data: [],
                        borderColor: '#58a6ff',
                        backgroundColor: 'rgba(88, 166, 255, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: false
                    }, {
                        label: 'Val Loss',
                        data: [],
                        borderColor: '#f85149',
                        backgroundColor: 'rgba(248, 81, 73, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: false
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    scales: {
                        x: { display: true, title: { display: true, text: 'Epoch' } },
                        y: { display: true, title: { display: true, text: 'Loss' }, beginAtZero: true }
                    },
                    plugins: {
                        legend: { display: true, position: 'top' }
                    }
                }
            });
        }

        // Accuracy chart
        const accCtx = document.getElementById('nn-accuracy-chart');
        if (accCtx) {
            this.charts.accuracy = new Chart(accCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Val Accuracy',
                        data: [],
                        borderColor: '#3fb950',
                        backgroundColor: 'rgba(63, 185, 80, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { display: true, title: { display: true, text: 'Epoch' } },
                        y: { display: true, title: { display: true, text: 'Accuracy %' }, min: 0, max: 100 }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }
    }

    initControls() {
        // Train button
        document.getElementById('btn-nn-train')?.addEventListener('click', () => this.startTraining());

        // Pause button
        document.getElementById('btn-nn-pause')?.addEventListener('click', () => this.pauseTraining());

        // Stop button
        document.getElementById('btn-nn-stop')?.addEventListener('click', () => this.stopTraining());

        // Save button
        document.getElementById('btn-nn-save')?.addEventListener('click', () => this.saveModel());

        // Export button
        document.getElementById('btn-nn-export')?.addEventListener('click', () => this.exportModel());

        // Export button (in sidebar)
        document.getElementById('btn-nn-do-export')?.addEventListener('click', () => this.exportModel());

        // Refresh data info
        document.getElementById('btn-nn-refresh-data')?.addEventListener('click', () => this.loadDataInfo());
    }

    getConfig() {
        const fightLimit = document.getElementById('nn-config-fight-limit')?.value;
        return {
            max_level: parseInt(document.getElementById('nn-config-max-level')?.value || 40),
            fight_limit: fightLimit ? parseInt(fightLimit) : null,
            epochs: parseInt(document.getElementById('nn-config-epochs')?.value || 50),
            batch_size: parseInt(document.getElementById('nn-config-batch')?.value || 64),
            learning_rate: parseFloat(document.getElementById('nn-config-lr')?.value || 0.001),
            hidden1: parseInt(document.getElementById('nn-config-hidden1')?.value || 32),
            hidden2: parseInt(document.getElementById('nn-config-hidden2')?.value || 16),
            early_stopping_patience: parseInt(document.getElementById('nn-config-patience')?.value || 10)
        };
    }

    async startTraining() {
        try {
            const config = this.getConfig();
            const response = await fetch('/api/nn/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            const data = await response.json();

            if (data.success) {
                this.setState('training');
                this.resetCharts();
                this.dashboard?.addLog?.('nn', 'success', 'NN training started');
            } else {
                this.dashboard?.addLog?.('nn', 'error', data.error || 'Failed to start training');
            }
        } catch (error) {
            console.error('Failed to start NN training:', error);
            this.dashboard?.addLog?.('nn', 'error', 'Failed to start training');
        }
    }

    async pauseTraining() {
        try {
            const response = await fetch('/api/nn/pause', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (data.paused) {
                    this.setState('paused');
                    this.dashboard?.addLog?.('nn', 'info', 'NN training paused');
                } else {
                    this.setState('training');
                    this.dashboard?.addLog?.('nn', 'info', 'NN training resumed');
                }
            }
        } catch (error) {
            console.error('Failed to pause NN training:', error);
        }
    }

    async stopTraining() {
        try {
            const response = await fetch('/api/nn/stop', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                this.setState('idle');
                this.dashboard?.addLog?.('nn', 'info', 'NN training stopped');
                this.loadModels();
            }
        } catch (error) {
            console.error('Failed to stop NN training:', error);
        }
    }

    async saveModel() {
        try {
            const name = prompt('Model name (leave empty for auto-generated):', '');
            const response = await fetch('/api/nn/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name || null })
            });
            const data = await response.json();

            if (data.success) {
                this.dashboard?.addLog?.('nn', 'success', `Model saved: ${data.name}`);
                this.loadModels();
            } else {
                this.dashboard?.addLog?.('nn', 'error', data.error || 'Failed to save model');
            }
        } catch (error) {
            console.error('Failed to save model:', error);
        }
    }

    async exportModel() {
        try {
            const outputDir = document.getElementById('nn-export-dir')?.value || 'tagadann/NN';
            const response = await fetch('/api/nn/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ output_dir: outputDir })
            });
            const data = await response.json();

            const statusEl = document.getElementById('nn-export-status');
            if (data.success) {
                if (statusEl) statusEl.innerHTML = '<span class="success">Exported successfully!</span>';
                this.dashboard?.addLog?.('nn', 'success', `Exported to ${outputDir}`);
            } else {
                if (statusEl) statusEl.innerHTML = `<span class="error">${data.error}</span>`;
                this.dashboard?.addLog?.('nn', 'error', data.error || 'Failed to export model');
            }
        } catch (error) {
            console.error('Failed to export model:', error);
        }
    }

    async loadDataInfo() {
        try {
            const response = await fetch('/api/nn/data-info');
            const data = await response.json();

            if (data.success) {
                const soloEl = document.getElementById('nn-data-solo');
                const lowLevelEl = document.getElementById('nn-data-low-level');

                if (soloEl && data.types?.solo) {
                    soloEl.textContent = data.types.solo.count.toLocaleString();
                }
                if (lowLevelEl) {
                    lowLevelEl.textContent = data.low_level_solo?.toLocaleString() || '--';
                }
            }
        } catch (error) {
            console.error('Failed to load data info:', error);
        }
    }

    async loadModels() {
        try {
            const response = await fetch('/api/nn/models');
            const data = await response.json();

            const container = document.getElementById('nn-models-list');
            if (!container) return;

            if (!data.models || data.models.length === 0) {
                container.innerHTML = '<p class="empty-state compact">No models saved</p>';
                return;
            }

            let html = '';
            for (const model of data.models) {
                html += `
                    <div class="nn-model-item">
                        <div class="nn-model-info">
                            <span class="nn-model-name">${model.name}</span>
                            <span class="nn-model-date">${model.created_at}</span>
                        </div>
                        <div class="nn-model-actions">
                            <button class="btn small" onclick="window.nnDashboard.loadModel('${model.path}')">Load</button>
                            <button class="btn small danger" onclick="window.nnDashboard.deleteModel('${model.name}')">Del</button>
                        </div>
                    </div>
                `;
            }
            container.innerHTML = html;
        } catch (error) {
            console.error('Failed to load models:', error);
        }
    }

    async loadModel(path) {
        try {
            const response = await fetch('/api/nn/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            const data = await response.json();

            if (data.success) {
                this.dashboard?.addLog?.('nn', 'success', 'Model loaded');
                document.getElementById('nn-model-params').textContent = data.params?.toLocaleString() || '--';
            } else {
                this.dashboard?.addLog?.('nn', 'error', data.error || 'Failed to load model');
            }
        } catch (error) {
            console.error('Failed to load model:', error);
        }
    }

    async deleteModel(name) {
        if (!confirm(`Delete model "${name}"?`)) return;

        try {
            const response = await fetch(`/api/nn/models/${name}`, { method: 'DELETE' });
            const data = await response.json();

            if (data.success) {
                this.dashboard?.addLog?.('nn', 'info', `Model ${name} deleted`);
                this.loadModels();
            }
        } catch (error) {
            console.error('Failed to delete model:', error);
        }
    }

    setState(state) {
        this.state = state;

        const trainBtn = document.getElementById('btn-nn-train');
        const pauseBtn = document.getElementById('btn-nn-pause');
        const stopBtn = document.getElementById('btn-nn-stop');
        const statusIcon = document.getElementById('nn-status-icon');
        const bannerTitle = document.getElementById('nn-banner-title');
        const banner = document.getElementById('nn-status-banner');

        // Update button states
        if (trainBtn) trainBtn.disabled = state === 'training' || state === 'paused' || state === 'loading';
        if (pauseBtn) pauseBtn.disabled = state !== 'training' && state !== 'paused';
        if (stopBtn) stopBtn.disabled = state !== 'training' && state !== 'paused' && state !== 'loading';

        // Update pause button text
        if (pauseBtn) {
            pauseBtn.innerHTML = state === 'paused'
                ? '<span class="icon">▶</span> Resume'
                : '<span class="icon">⏸</span> Pause';
        }

        // Update banner
        const icons = { idle: '⏸️', loading: '⏳', training: '🔄', paused: '⏸️', done: '✅', error: '❌' };
        const titles = { idle: 'Idle', loading: 'Loading...', training: 'Training', paused: 'Paused', done: 'Done', error: 'Error' };
        const colors = { idle: '', loading: 'loading', training: 'running', paused: 'paused', done: 'success', error: 'error' };

        if (statusIcon) statusIcon.textContent = icons[state] || icons.idle;
        if (bannerTitle) bannerTitle.textContent = titles[state] || titles.idle;
        if (banner) {
            banner.className = 'nn-status-compact';
            if (colors[state]) banner.classList.add(colors[state]);
        }
    }

    resetCharts() {
        this.historyData = { epochs: [], trainLoss: [], valLoss: [], valAccuracy: [] };
        this.updateCharts();
    }

    updateCharts() {
        // Update loss chart
        if (this.charts.loss) {
            this.charts.loss.data.labels = this.historyData.epochs;
            this.charts.loss.data.datasets[0].data = this.historyData.trainLoss;
            this.charts.loss.data.datasets[1].data = this.historyData.valLoss;
            this.charts.loss.update('none');
        }

        // Update accuracy chart
        if (this.charts.accuracy) {
            this.charts.accuracy.data.labels = this.historyData.epochs;
            this.charts.accuracy.data.datasets[0].data = this.historyData.valAccuracy;
            this.charts.accuracy.update('none');
        }
    }

    update(nnData) {
        if (!nnData) return;

        // Update state
        const phase = nnData.phase || 'idle';
        if (phase !== this.state) {
            this.setState(phase);
        }

        // Update banner subtitle
        const subtitle = document.getElementById('nn-banner-subtitle');
        if (subtitle) subtitle.textContent = nnData.status_message || '';

        // Update metrics
        const epochEl = document.getElementById('nn-metric-epoch');
        const accuracyEl = document.getElementById('nn-metric-accuracy');
        const etaEl = document.getElementById('nn-metric-eta');

        if (epochEl) epochEl.textContent = `${nnData.epoch || 0}/${nnData.total_epochs || 0}`;
        if (accuracyEl) accuracyEl.textContent = nnData.val_accuracy ? `${nnData.val_accuracy.toFixed(1)}%` : '--';
        if (etaEl) {
            const eta = nnData.eta_seconds || 0;
            etaEl.textContent = eta > 0 ? this.formatTime(eta) : '--';
        }

        // Update progress bar
        const progressBar = document.getElementById('nn-epoch-progress');
        const progressCount = document.getElementById('nn-epoch-count');
        const pct = nnData.total_epochs > 0 ? (nnData.epoch / nnData.total_epochs * 100) : 0;

        if (progressBar) progressBar.style.width = `${pct}%`;
        if (progressCount) progressCount.textContent = `${nnData.epoch || 0} / ${nnData.total_epochs || 0}`;

        // Update timing
        const elapsedEl = document.getElementById('nn-elapsed-time');
        const etaTimeEl = document.getElementById('nn-eta-time');
        const examplesEl = document.getElementById('nn-examples-count');

        if (elapsedEl) elapsedEl.textContent = this.formatTime(nnData.total_time || 0);
        if (etaTimeEl) etaTimeEl.textContent = nnData.eta_seconds > 0 ? this.formatTime(nnData.eta_seconds) : '--';
        if (examplesEl) {
            const total = (nnData.train_examples || 0) + (nnData.val_examples || 0);
            examplesEl.textContent = total.toLocaleString();
        }

        // Update details
        document.getElementById('nn-train-loss').textContent = nnData.train_loss?.toFixed(6) || '--';
        document.getElementById('nn-val-loss').textContent = nnData.val_loss?.toFixed(6) || '--';
        document.getElementById('nn-best-val-loss').textContent = nnData.best_val_loss?.toFixed(6) || '--';
        document.getElementById('nn-best-epoch').textContent = nnData.best_epoch || '--';
        document.getElementById('nn-current-lr').textContent = nnData.learning_rate?.toExponential(2) || '--';
        document.getElementById('nn-model-params').textContent = nnData.model_params?.toLocaleString() || '--';
        document.getElementById('nn-data-train').textContent = nnData.train_examples?.toLocaleString() || '--';
        document.getElementById('nn-data-val').textContent = nnData.val_examples?.toLocaleString() || '--';

        // Update history for charts
        if (nnData.epoch > 0 && nnData.epoch > (this.historyData.epochs.length || 0)) {
            this.historyData.epochs.push(nnData.epoch);
            this.historyData.trainLoss.push(nnData.train_loss);
            this.historyData.valLoss.push(nnData.val_loss);
            this.historyData.valAccuracy.push(nnData.val_accuracy);
            this.updateCharts();
        }
    }

    formatTime(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${mins}m`;
    }
}

// Initialize NN dashboard module
document.addEventListener('DOMContentLoaded', () => {
    window.nnDashboard = new NNDashboard(window.dashboard);
});
