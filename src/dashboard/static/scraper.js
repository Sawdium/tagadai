// Scraper Dashboard Module

class ScraperDashboard {
    constructor(dashboard) {
        this.dashboard = dashboard;
        this.pollInterval = null;
        this.state = 'idle';
        this.delayUserEdit = false;
        this.initialized = false;
    }

    init() {
        if (this.initialized) return;

        // Scraper control buttons
        document.getElementById('btn-scraper-start')?.addEventListener('click', () => this.start());
        document.getElementById('btn-scraper-pause')?.addEventListener('click', () => this.pause());
        document.getElementById('btn-scraper-stop')?.addEventListener('click', () => this.stop());
        document.getElementById('btn-refresh-db-stats')?.addEventListener('click', () => this.loadDbStats());

        // Delay input
        const delayInput = document.getElementById('scraper-delay');
        if (delayInput) {
            delayInput.addEventListener('change', (e) => this.updateDelay(e.target.value));
        }

        // Load initial status
        this.loadStatus();
        this.loadDbStats();

        this.initialized = true;
    }

    getConfig() {
        return {
            delay: parseFloat(document.getElementById('scraper-delay')?.value || 1)
        };
    }

    async start() {
        const config = this.getConfig();
        this.dashboard?.addLog?.('scraper', 'info', `Starting scraper: delay=${config.delay}s`);

        try {
            const response = await fetch('/api/scraper/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            const result = await response.json();
            if (result.success) {
                this.setState('running');
                this.dashboard?.addLog?.('scraper', 'success', 'Scraper started successfully');
                this.dashboard?.notify?.('success', 'Scraper Started', `Delay: ${config.delay}s`);
                this.startPolling();
            } else {
                this.dashboard?.addLog?.('scraper', 'error', `Failed to start: ${result.error}`);
                this.dashboard?.notify?.('error', 'Scraper Failed', result.error);
            }
        } catch (error) {
            this.dashboard?.addLog?.('scraper', 'error', `Error: ${error.message}`);
            this.dashboard?.notify?.('error', 'Error', error.message);
        }
    }

    async pause() {
        try {
            const response = await fetch('/api/scraper/pause', { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                this.setState(result.paused ? 'paused' : 'running');
                this.dashboard?.addLog?.('scraper', 'info', result.paused ? 'Scraper paused' : 'Scraper resumed');
                this.dashboard?.notify?.('info', result.paused ? 'Scraper Paused' : 'Scraper Resumed', '');
            }
        } catch (error) {
            this.dashboard?.addLog?.('scraper', 'error', `Error: ${error.message}`);
        }
    }

    async stop() {
        try {
            const response = await fetch('/api/scraper/stop', { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                this.setState('idle');
                this.dashboard?.addLog?.('scraper', 'info', 'Scraper stopped');
            }
        } catch (error) {
            this.dashboard?.addLog?.('scraper', 'error', `Error: ${error.message}`);
        }
    }

    async updateDelay(delay) {
        this.delayUserEdit = true;

        try {
            const response = await fetch('/api/scraper/delay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delay: parseFloat(delay) })
            });
            const result = await response.json();
            if (result.success) {
                this.dashboard?.addLog?.('scraper', 'info', `Delay updated: ${result.old_delay}s → ${result.new_delay}s`);
                setTimeout(() => { this.delayUserEdit = false; }, 3000);
            } else {
                this.dashboard?.addLog?.('scraper', 'error', `Failed to update delay: ${result.error}`);
                this.delayUserEdit = false;
            }
        } catch (error) {
            this.dashboard?.addLog?.('scraper', 'error', `Error updating delay: ${error.message}`);
            this.delayUserEdit = false;
        }
    }

    setState(state) {
        this.state = state;

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

        this.updateBanner(state);
    }

    updateBanner(state, data = null) {
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

    startPolling() {
        if (this.pollInterval) return;
        this.pollInterval = setInterval(() => this.loadStatus(), 2000);
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    async loadStatus() {
        try {
            const response = await fetch('/api/scraper/status');
            const data = await response.json();

            if (data.error) {
                console.error('Scraper status error:', data.error);
                return;
            }

            // Update state
            const state = data.status;
            if (state !== this.state) {
                this.setState(state);
            }
            this.updateBanner(state, data);

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

            // Sync delay input
            const delayInput = document.getElementById('scraper-delay');
            if (delayInput && !this.delayUserEdit && data.delay !== undefined) {
                delayInput.value = data.delay;
            }

            // Rate limit indicator
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

            // Error banner
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

            this.loadDbStats();

        } catch (error) {
            console.error('Failed to load scraper status:', error);
        }
    }

    async loadDbStats() {
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
            html += `<div class="stat-compact"><span class="label">Total</span><span class="value">${data.total_fights || 0}</span></div>`;

            for (const [type, count] of Object.entries(data.by_type || {})) {
                if (count > 0) {
                    const name = typeNames[type] || `T${type}`;
                    html += `<div class="stat-compact"><span class="label">${name}</span><span class="value">${count}</span></div>`;
                }
            }

            for (const [ctx, count] of Object.entries(data.by_context || {})) {
                if (count > 0 && contextNames[ctx]) {
                    html += `<div class="stat-compact"><span class="label">${contextNames[ctx]}</span><span class="value">${count}</span></div>`;
                }
            }

            html += `<div class="stat-compact"><span class="label">Players</span><span class="value">${data.players_scraped || 0}</span></div>`;
            html += `<div class="stat-compact"><span class="label">Leeks</span><span class="value">${data.unique_leeks || 0}</span></div>`;

            if (data.db_size_mb !== undefined) {
                html += `<div class="stat-compact"><span class="label">DB Size</span><span class="value">${data.db_size_mb.toFixed(1)} MB</span></div>`;
            }

            container.innerHTML = html;

            const discoveryQueue = document.getElementById('stat-discovery-queue');
            if (discoveryQueue) discoveryQueue.textContent = data.discovery_queue || 0;

        } catch (error) {
            console.error('Failed to load DB stats:', error);
        }
    }
}

// Initialize scraper dashboard module
document.addEventListener('DOMContentLoaded', () => {
    window.scraperDashboard = new ScraperDashboard(window.dashboard);
});
