let currentTentId = null;
let heatmapHitAreas = [];

async function init() {
    await TentMap.init();
    TrendChart.renderLegend('trendLegend');
    updateClock();
    setInterval(updateClock, 1000);
    checkSystemHealth();
    setInterval(checkSystemHealth, 30000);
    // [FIX v1.1] 移动端页面切后台/销毁时释放 Canvas ImageData 缓存
    window.addEventListener('pagehide', () => {
        if (typeof HeatmapCanvasV2 !== 'undefined') HeatmapCanvasV2.destroy();
    });
    window.addEventListener('beforeunload', () => {
        if (typeof HeatmapCanvasV2 !== 'undefined') HeatmapCanvasV2.destroy();
    });
}

function updateClock() {
    const now = new Date();
    document.getElementById('systemTime').textContent = now.toLocaleString('zh-CN');
}

async function checkSystemHealth() {
    try {
        const resp = await fetch('/api/health');
        const data = await resp.json();
        document.getElementById('systemStatus').style.background = '#22c55e';
    } catch {
        document.getElementById('systemStatus').style.background = '#ef4444';
    }
}

function openTentDetail(tentId) {
    currentTentId = tentId;
    const detail = document.getElementById('detailSection');
    detail.style.display = 'flex';

    const tent = TentMap.tents.find(t => t.id === tentId);
    document.getElementById('tentName').textContent = tent ? tent.name : `帐篷 ${tentId}`;

    TentMap.highlightTent(tentId);

    switchTab('heatmap');
    loadHeatmap(tentId);
}

function closeDetail() {
    document.getElementById('detailSection').style.display = 'none';
    currentTentId = null;
    TentMap.highlightTent(null);
}

function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });

    if (!currentTentId) return;

    switch (tabName) {
        case 'heatmap': loadHeatmap(currentTentId); break;
        case 'trend': loadTrend(); break;
        case 'priority': loadPriorities(currentTentId); break;
        case 'alerts': loadAlerts(currentTentId); break;
    }
}

async function loadHeatmap(tentId) {
    const canvas = document.getElementById('heatmapCanvas');
    try {
        const resp = await fetch(`/api/drugs/heatmap/${tentId}`);
        const data = await resp.json();
        // [FIX v1.1] 切换到 V2 ImageData 复用渲染器, 避免移动端内存泄漏
        heatmapHitAreas = (typeof HeatmapCanvasV2 !== 'undefined')
            ? HeatmapCanvasV2.draw(canvas, data)
            : HeatmapRenderer.draw(canvas, data);
    } catch (e) {
        console.error('Heatmap load failed:', e);
        const empty = (typeof HeatmapCanvasV2 !== 'undefined')
            ? HeatmapCanvasV2.draw(canvas, [])
            : HeatmapRenderer.draw(canvas, []);
        heatmapHitAreas = empty;
    }

    canvas.onmousemove = (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mx = (e.clientX - rect.left) * scaleX;
        const my = (e.clientY - rect.top) * scaleY;

        const tooltip = document.getElementById('heatmapTooltip');
        let found = null;
        for (const area of heatmapHitAreas) {
            if (mx >= area.x && mx <= area.x + area.w && my >= area.y && my <= area.y + area.h) {
                found = area.data;
                break;
            }
        }

        if (found) {
            tooltip.style.display = 'block';
            tooltip.style.left = (e.clientX + 12) + 'px';
            tooltip.style.top = (e.clientY - 10) + 'px';
            tooltip.innerHTML = `
                <b>${found.drug_name}</b><br>
                水分活度: ${found.avg_aw.toFixed(3)}<br>
                霉变风险: ${(found.mold_risk * 100).toFixed(1)}%<br>
                有效期: ${found.shelf_life_days.toFixed(0)}天<br>
                综合风险: ${(found.risk_score * 100).toFixed(1)}%
            `;
        } else {
            tooltip.style.display = 'none';
        }
    };

    canvas.onmouseleave = () => {
        document.getElementById('heatmapTooltip').style.display = 'none';
    };
}

async function loadTrend() {
    if (!currentTentId) return;
    const hours = document.getElementById('trendHours').value;
    const canvas = document.getElementById('trendChart');

    try {
        const resp = await fetch(`/api/sensors/trend/${currentTentId}?hours=${hours}`);
        const data = await resp.json();
        TrendChart.draw(canvas, data);
    } catch (e) {
        console.error('Trend load failed:', e);
        TrendChart.draw(canvas, null);
    }
}

async function loadPriorities(tentId) {
    const tbody = document.querySelector('#priorityTable tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">加载中...</td></tr>';

    try {
        const resp = await fetch(`/api/drugs/priorities/${tentId}`);
        const data = await resp.json();

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-state">暂无数据</td></tr>';
            return;
        }

        tbody.innerHTML = data.map(item => {
            const levelClass = {
                '紧急': 'priority-urgent',
                '高': 'priority-high',
                '中': 'priority-medium',
                '低': 'priority-low',
            }[item.priority_level] || 'priority-low';

            return `
                <tr>
                    <td>${item.drug_name}</td>
                    <td><span class="priority-badge ${levelClass}">${item.priority_level}</span></td>
                    <td>${item.priority_score}</td>
                    <td>${item.reason}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Priority load failed:', e);
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">加载失败</td></tr>';
    }
}

async function loadAlerts(tentId) {
    const container = document.getElementById('alertList');
    container.innerHTML = '<div class="empty-state"><div class="icon">📡</div>加载中...</div>';

    try {
        const resp = await fetch(`/api/alerts/?tent_id=${tentId}&hours=72`);
        const data = await resp.json();

        if (data.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="icon">✅</div>暂无告警</div>';
            return;
        }

        container.innerHTML = data.map(alert => {
            const severityClass = alert.severity === 'critical' ? 'critical' : 'warning';
            const typeLabel = {
                'high_temp': '🌡️ 高温告警',
                'high_aw': '💧 水分活度告警',
                'combined': '⚠️ 综合告警',
            }[alert.alert_type] || alert.alert_type;

            return `
                <div class="alert-item ${severityClass}">
                    <div class="alert-item-header">
                        <span class="alert-type">${typeLabel}</span>
                        <span class="alert-time">${alert.timestamp}</span>
                    </div>
                    <div class="alert-message">${alert.message}</div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Alert load failed:', e);
        container.innerHTML = '<div class="empty-state">加载失败</div>';
    }
}

document.addEventListener('DOMContentLoaded', init);
