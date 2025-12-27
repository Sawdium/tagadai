// RL (Reinforcement Learning) Dashboard Module

class RLDashboard {
    constructor(dashboard) {
        this.dashboard = dashboard;
        this.pollInterval = null;
        this.state = 'idle';
        this.initialized = false;
    }

    init() {
        if (this.initialized) return;

        // RL control buttons
        document.getElementById('btn-rl-duel')?.addEventListener('click', () => this.runDuel());
        document.getElementById('btn-rl-start')?.addEventListener('click', () => this.startScenario());
        document.getElementById('btn-rl-stop')?.addEventListener('click', () => this.stopScenario());

        // Load scenarios
        this.loadScenarios();

        this.initialized = true;
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

        this.dashboard?.addLog?.('rl', 'info', `Running duel: ${bot1} vs ${bot2}${seed ? ` (seed: ${seed})` : ''}`);

        try {
            const response = await fetch('/api/rl/duel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot1, bot2, seed })
            });

            const result = await response.json();

            if (result.error) {
                this.dashboard?.addLog?.('rl', 'error', `Duel failed: ${result.error}`);
                this.dashboard?.notify?.('error', 'Duel Failed', result.error);
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

            this.dashboard?.addLog?.('rl', 'success', `Duel complete: ${outcomes[result.winner]}`);
            this.dashboard?.notify?.('success', 'Duel Complete', outcomes[result.winner] || 'Unknown result');

        } catch (error) {
            this.dashboard?.addLog?.('rl', 'error', `Error: ${error.message}`);
            this.dashboard?.notify?.('error', 'Error', error.message);
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
            this.dashboard?.notify?.('warning', 'No Scenario', 'Please select a scenario file');
            return;
        }

        this.dashboard?.addLog?.('rl', 'info', `Starting scenario: ${yamlPath} (workers: ${workers})`);

        try {
            const response = await fetch('/api/rl/scenario/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ yaml_path: yamlPath, max_workers: workers })
            });

            const result = await response.json();

            if (result.error) {
                this.dashboard?.addLog?.('rl', 'error', `Failed: ${result.error}`);
                this.dashboard?.notify?.('error', 'Scenario Failed', result.error);
                return;
            }

            this.setState('running');
            this.dashboard?.addLog?.('rl', 'success', 'Scenario started');
            this.dashboard?.notify?.('success', 'Scenario Started', `Running ${yamlPath}`);

            // Start polling progress
            this.startPolling();

        } catch (error) {
            this.dashboard?.addLog?.('rl', 'error', `Error: ${error.message}`);
            this.dashboard?.notify?.('error', 'Error', error.message);
        }
    }

    async stopScenario() {
        try {
            const response = await fetch('/api/rl/scenario/stop', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                this.setState('idle');
                this.dashboard?.addLog?.('rl', 'info', 'Scenario stopped');
                this.stopPolling();
            }
        } catch (error) {
            this.dashboard?.addLog?.('rl', 'error', `Error: ${error.message}`);
        }
    }

    setState(state) {
        this.state = state;

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

    startPolling() {
        if (this.pollInterval) return;
        this.pollInterval = setInterval(() => this.loadProgress(), 1000);
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    async loadProgress() {
        try {
            const response = await fetch('/api/rl/scenario/progress');
            const data = await response.json();

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
            if (!data.is_running && this.state === 'running') {
                this.setState('idle');
                this.stopPolling();
                this.dashboard?.addLog?.('rl', 'success', 'Scenario completed');
                this.loadResults();
            }

        } catch (error) {
            console.error('Failed to load RL progress:', error);
        }
    }

    async loadResults() {
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
}

// Initialize RL dashboard module
document.addEventListener('DOMContentLoaded', () => {
    window.rlDashboard = new RLDashboard(window.dashboard);
});
