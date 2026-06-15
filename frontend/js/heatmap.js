const HeatmapRenderer = {
    riskToColor(risk) {
        if (risk < 0.25) {
            const t = risk / 0.25;
            return `rgb(${Math.round(34 + t * 200)}, ${Math.round(197 - t * 50)}, ${Math.round(94 - t * 50)})`;
        } else if (risk < 0.5) {
            const t = (risk - 0.25) / 0.25;
            return `rgb(${Math.round(234)}, ${Math.round(179 - t * 40)}, ${Math.round(8 + t * 10)})`;
        } else if (risk < 0.75) {
            const t = (risk - 0.5) / 0.25;
            return `rgb(${Math.round(249)}, ${Math.round(115 - t * 30)}, ${Math.round(22 - t * 10)})`;
        } else {
            const t = (risk - 0.75) / 0.25;
            return `rgb(${Math.round(239)}, ${Math.round(68 - t * 30)}, ${Math.round(68 - t * 30)})`;
        }
    },

    draw(canvas, data) {
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;

        ctx.fillStyle = '#1a2332';
        ctx.fillRect(0, 0, W, H);

        if (!data || data.length === 0) {
            ctx.fillStyle = '#9ca3af';
            ctx.font = '14px Microsoft YaHei';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', W / 2, H / 2);
            return [];
        }

        const cols = 5;
        const rows = Math.ceil(data.length / cols);
        const padX = 60;
        const padY = 50;
        const cellW = (W - padX * 2) / cols;
        const cellH = (H - padY * 2) / rows;

        ctx.fillStyle = '#d4a853';
        ctx.font = 'bold 14px Microsoft YaHei';
        ctx.textAlign = 'center';
        ctx.fillText('药品变质风险热力图', W / 2, 30);

        const hitAreas = [];

        data.forEach((item, idx) => {
            const col = item.x !== undefined ? item.x : idx % cols;
            const row = item.y !== undefined ? item.y : Math.floor(idx / cols);
            const x = padX + col * cellW;
            const y = padY + row * cellH;

            ctx.fillStyle = this.riskToColor(item.risk_score);
            ctx.beginPath();
            ctx.roundRect(x + 4, y + 4, cellW - 8, cellH - 8, 6);
            ctx.fill();

            ctx.strokeStyle = 'rgba(255,255,255,0.1)';
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.fillStyle = '#fff';
            ctx.font = 'bold 12px Microsoft YaHei';
            ctx.textAlign = 'center';
            ctx.fillText(item.drug_name, x + cellW / 2, y + cellH / 2 - 10);

            ctx.font = '11px Microsoft YaHei';
            ctx.fillText(`Aw: ${item.avg_aw.toFixed(3)}`, x + cellW / 2, y + cellH / 2 + 6);

            ctx.fillStyle = item.risk_score > 0.5 ? '#ff6b6b' : '#aaa';
            ctx.font = '10px Microsoft YaHei';
            ctx.fillText(`风险: ${(item.risk_score * 100).toFixed(0)}%`, x + cellW / 2, y + cellH / 2 + 20);

            hitAreas.push({ x, y, w: cellW, h: cellH, data: item });
        });

        return hitAreas;
    }
};
