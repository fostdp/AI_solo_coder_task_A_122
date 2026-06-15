const TrendChart = {
    colors: {
        temperature: '#ef4444',
        humidity: '#3b82f6',
        light: '#eab308',
        ethylene: '#a855f7',
        co2: '#22c55e',
    },

    labels: {
        temperature: '温度 (°C)',
        humidity: '湿度 (%RH)',
        light: '光照 (lux)',
        ethylene: '乙烯 (ppm)',
        co2: 'CO₂ (ppm)',
    },

    draw(canvas, data) {
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;
        const pad = { top: 30, right: 80, bottom: 50, left: 60 };
        const chartW = W - pad.left - pad.right;
        const chartH = H - pad.top - pad.bottom;

        ctx.fillStyle = '#1a2332';
        ctx.fillRect(0, 0, W, H);

        if (!data || !data.timestamps || data.timestamps.length === 0) {
            ctx.fillStyle = '#9ca3af';
            ctx.font = '14px Microsoft YaHei';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', W / 2, H / 2);
            return;
        }

        const metrics = ['temperature', 'humidity', 'light', 'ethylene', 'co2'];
        const n = data.timestamps.length;

        ctx.strokeStyle = '#2a3a4a';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 5; i++) {
            const y = pad.top + (chartH / 5) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + chartW, y);
            ctx.stroke();
        }

        const labelStep = Math.max(1, Math.floor(n / 8));
        ctx.fillStyle = '#9ca3af';
        ctx.font = '10px Microsoft YaHei';
        ctx.textAlign = 'center';
        for (let i = 0; i < n; i += labelStep) {
            const x = pad.left + (i / (n - 1)) * chartW;
            const label = data.timestamps[i].split(' ')[1] || data.timestamps[i];
            ctx.fillText(label, x, H - pad.bottom + 20);
        }

        metrics.forEach(metric => {
            const values = data[metric];
            if (!values || values.length === 0) return;

            const minV = Math.min(...values);
            const maxV = Math.max(...values);
            const range = maxV - minV || 1;

            ctx.strokeStyle = this.colors[metric];
            ctx.lineWidth = 2;
            ctx.beginPath();

            values.forEach((v, i) => {
                const x = pad.left + (i / (n - 1)) * chartW;
                const y = pad.top + chartH - ((v - minV) / range) * chartH;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            const lastVal = values[values.length - 1];
            const lastX = pad.left + chartW + 5;
            const lastY = pad.top + chartH - ((lastVal - minV) / range) * chartH;
            ctx.fillStyle = this.colors[metric];
            ctx.font = '10px Microsoft YaHei';
            ctx.textAlign = 'left';
            ctx.fillText(lastVal.toFixed(1), lastX, lastY + 4);
        });

        ctx.fillStyle = '#9ca3af';
        ctx.font = '10px Microsoft YaHei';
        ctx.textAlign = 'center';
        ctx.fillText('时间', W / 2, H - 5);
    },

    renderLegend(containerId) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        Object.keys(this.colors).forEach(key => {
            const item = document.createElement('div');
            item.className = 'trend-legend-item';
            item.innerHTML = `
                <span class="trend-legend-color" style="background:${this.colors[key]}"></span>
                <span>${this.labels[key]}</span>
            `;
            container.appendChild(item);
        });
    }
};
