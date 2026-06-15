/**
 * DrugRiskHeatmap - 药品变质风险热力图组件
 * 基于 Canvas ImageData 复用实现的高性能热力图
 * 修复移动端内存泄漏问题 (v2)
 *
 * 功能:
 *  - 绘制药材变质风险热力图 (网格布局)
 *  - 支持工具提示
 *  - ImageData 复用, 避免频繁 GC
 *  - 响应式尺寸
 *
 * 使用示例:
 *   const heatmap = new DrugRiskHeatmap('heatmapCanvas');
 *   heatmap.setData(heatmapData);
 *   heatmap.render();
 */
(function (global) {
    'use strict';

    function DrugRiskHeatmap(canvasId, options) {
        this.canvas = typeof canvasId === 'string'
            ? document.getElementById(canvasId)
            : canvasId;

        if (!this.canvas) {
            throw new Error('Canvas element not found: ' + canvasId);
        }

        this.options = Object.assign({
            cols: 5,
            cellPadding: 4,
            paddingX: 60,
            paddingY: 50,
            title: '药品变质风险热力图',
            titleColor: '#d4a853',
            bgColor: '#1a2332',
            textColor: '#ffffff',
            subTextColor: '#aaaaaa',
            highRiskColor: '#ff6b6b',
            showLabels: true,
            showValues: true,
            cornerRadius: 4,
        }, options || {});

        this.data = [];
        this.hitAreas = [];

        // ImageData 缓存 (避免重复分配)
        this._cachedImageData = null;
        this._cachedWidth = 0;
        this._cachedHeight = 0;
        this._ctxCache = null;

        this._init();
    }

    DrugRiskHeatmap.prototype._init = function () {
        var self = this;
        this.ctx = this._getCtx();

        // 工具提示
        this.tooltipEl = document.createElement('div');
        this.tooltipEl.className = 'heatmap-tooltip';
        this.tooltipEl.style.display = 'none';
        this.tooltipEl.style.cssText = [
            'position:absolute',
            'background:rgba(0,0,0,0.9)',
            'color:#fff',
            'padding:8px 12px',
            'border-radius:6px',
            'font-size:12px',
            'pointer-events:none',
            'z-index:100',
            'border:1px solid #d4a853',
            'line-height:1.5',
        ].join(';');
        document.body.appendChild(this.tooltipEl);

        // 鼠标事件
        this.canvas.addEventListener('mousemove', function (e) {
            self._onMouseMove(e);
        });
        this.canvas.addEventListener('mouseleave', function () {
            self.tooltipEl.style.display = 'none';
        });

        // 响应式
        window.addEventListener('resize', function () {
            self._cachedImageData = null; // 尺寸变化需重新分配
        });
    };

    DrugRiskHeatmap.prototype._getCtx = function () {
        if (!this._ctxCache || this._ctxCache.canvas !== this.canvas) {
            this._ctxCache = this.canvas.getContext('2d', { alpha: false });
        }
        return this._ctxCache;
    };

    // --- 数据设置 ---
    DrugRiskHeatmap.prototype.setData = function (data) {
        this.data = data || [];
        return this;
    };

    // --- 渲染 ---
    DrugRiskHeatmap.prototype.render = function () {
        var ctx = this.ctx;
        var W = this.canvas.width;
        var H = this.canvas.height;
        var opts = this.options;

        // 背景
        ctx.fillStyle = opts.bgColor;
        ctx.fillRect(0, 0, W, H);

        if (!this.data || this.data.length === 0) {
            ctx.fillStyle = '#9ca3af';
            ctx.font = '14px Microsoft YaHei';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', W / 2, H / 2);
            this.hitAreas = [];
            return this;
        }

        // 标题
        ctx.fillStyle = opts.titleColor;
        ctx.font = 'bold 14px Microsoft YaHei';
        ctx.textAlign = 'center';
        ctx.fillText(opts.title, W / 2, 30);

        // 计算网格
        var cols = opts.cols;
        var rows = Math.ceil(this.data.length / cols);
        var padX = opts.paddingX;
        var padY = opts.paddingY;
        var cellW = (W - padX * 2) / cols;
        var cellH = (H - padY * 2) / rows;

        // 获取 ImageData 并绘制单元格 (像素级)
        var imgData = this._getOrCreateImageData(W, H);
        this.hitAreas = [];

        var self = this;
        this.data.forEach(function (item, idx) {
            var col = item.x !== undefined ? item.x : idx % cols;
            var row = item.y !== undefined ? item.y : Math.floor(idx / cols);
            var x = padX + col * cellW;
            var y = padY + row * cellH;
            var x0 = x + opts.cellPadding;
            var y0 = y + opts.cellPadding;
            var x1 = x + cellW - opts.cellPadding;
            var y1 = y + cellH - opts.cellPadding;

            var rgb = self._riskToRGB(item.risk_score);
            self._paintRectToImageData(imgData, x0, y0, x1, y1, rgb, opts.cornerRadius);

            self.hitAreas.push({ x: x, y: y, w: cellW, h: cellH, data: item });
        });

        // 提交像素
        ctx.putImageData(imgData, 0, 0);

        // 文字层 (必须在 putImageData 之后)
        ctx.textAlign = 'center';

        this.hitAreas.forEach(function (area) {
            var item = area.data;
            var cx = area.x + area.w / 2;
            var cy = area.y + area.h / 2;

            if (opts.showLabels) {
                ctx.fillStyle = opts.textColor;
                ctx.font = 'bold 12px Microsoft YaHei';
                ctx.fillText(item.drug_name, cx, cy - 10);
            }

            if (opts.showValues) {
                ctx.fillStyle = opts.textColor;
                ctx.font = '11px Microsoft YaHei';
                ctx.fillText('Aw: ' + item.avg_aw.toFixed(3), cx, cy + 6);

                ctx.fillStyle = item.risk_score > 0.5
                    ? opts.highRiskColor
                    : opts.subTextColor;
                ctx.font = '10px Microsoft YaHei';
                ctx.fillText('风险: ' + (item.risk_score * 100).toFixed(0) + '%', cx, cy + 20);
            }
        });

        return this;
    };

    // --- 颜色映射 ---
    DrugRiskHeatmap.prototype._riskToRGB = function (risk) {
        var r, g, b;
        if (risk < 0.25) {
            var t = risk / 0.25;
            r = 34 + Math.floor(t * 200);
            g = 197 - Math.floor(t * 50);
            b = 94 - Math.floor(t * 50);
        } else if (risk < 0.5) {
            var t2 = (risk - 0.25) / 0.25;
            r = 234;
            g = 179 - Math.floor(t2 * 40);
            b = 8 + Math.floor(t2 * 10);
        } else if (risk < 0.75) {
            var t3 = (risk - 0.5) / 0.25;
            r = 249;
            g = 115 - Math.floor(t3 * 30);
            b = 22 - Math.floor(t3 * 10);
        } else {
            var t4 = (risk - 0.75) / 0.25;
            r = 239;
            g = 68 - Math.floor(t4 * 30);
            b = 68 - Math.floor(t4 * 30);
        }
        return [r, g, b];
    };

    // --- ImageData 操作 ---
    DrugRiskHeatmap.prototype._getOrCreateImageData = function (w, h) {
        if (this._cachedImageData && this._cachedWidth === w && this._cachedHeight === h) {
            this._cachedImageData.data.fill(0);
            return this._cachedImageData;
        }
        this._releaseImageData();
        this._cachedImageData = this.ctx.createImageData(w, h);
        this._cachedWidth = w;
        this._cachedHeight = h;
        return this._cachedImageData;
    };

    DrugRiskHeatmap.prototype._releaseImageData = function () {
        if (this._cachedImageData) {
            this._cachedImageData.data = null;
            this._cachedImageData = null;
            this._cachedWidth = 0;
            this._cachedHeight = 0;
        }
    };

    DrugRiskHeatmap.prototype._paintRectToImageData = function (imgData, x0, y0, x1, y1, rgb, radius) {
        var w = this._cachedWidth;
        var data = imgData.data;
        var r = rgb[0], g = rgb[1], b = rgb[2];

        var xs = Math.max(0, Math.floor(x0));
        var xe = Math.min(w, Math.ceil(x1));
        var ys = Math.max(0, Math.floor(y0));
        var ye = Math.min(this._cachedHeight, Math.ceil(y1));
        var cr = radius || 4;

        for (var y = ys; y < ye; y++) {
            for (var x = xs; x < xe; x++) {
                var dx = Math.min(x - xs, xe - 1 - x);
                var dy = Math.min(y - ys, ye - 1 - y);

                var isCorner = dx < cr && dy < cr && (dx + dy < cr + Math.SQRT2 - 1);
                var inside = dx + dy >= cr - 0.5;

                if (!isCorner || inside) {
                    var idx = (y * w + x) * 4;
                    data[idx] = r;
                    data[idx + 1] = g;
                    data[idx + 2] = b;
                    data[idx + 3] = 255;
                }
            }
        }
    };

    // --- 鼠标交互 ---
    DrugRiskHeatmap.prototype._onMouseMove = function (e) {
        var rect = this.canvas.getBoundingClientRect();
        var scaleX = this.canvas.width / rect.width;
        var scaleY = this.canvas.height / rect.height;
        var mx = (e.clientX - rect.left) * scaleX;
        var my = (e.clientY - rect.top) * scaleY;

        var found = null;
        for (var i = 0; i < this.hitAreas.length; i++) {
            var a = this.hitAreas[i];
            if (mx >= a.x && mx <= a.x + a.w && my >= a.y && my <= a.y + a.h) {
                found = a.data;
                break;
            }
        }

        if (found) {
            this.tooltipEl.style.display = 'block';
            this.tooltipEl.style.left = (e.clientX + 12) + 'px';
            this.tooltipEl.style.top = (e.clientY - 10) + 'px';
            this.tooltipEl.innerHTML = [
                '<b>' + found.drug_name + '</b>',
                '水分活度: ' + found.avg_aw.toFixed(3),
                '霉变风险: ' + (found.mold_risk * 100).toFixed(1) + '%',
                '有效期: ' + found.shelf_life_days.toFixed(0) + '天',
                '综合风险: ' + (found.risk_score * 100).toFixed(1) + '%',
            ].join('<br>');
        } else {
            this.tooltipEl.style.display = 'none';
        }
    };

    // --- 销毁 ---
    DrugRiskHeatmap.prototype.destroy = function () {
        this._releaseImageData();
        this._ctxCache = null;
        if (this.tooltipEl && this.tooltipEl.parentNode) {
            this.tooltipEl.parentNode.removeChild(this.tooltipEl);
        }
        this.data = [];
        this.hitAreas = [];
    };

    // 导出
    global.DrugRiskHeatmap = DrugRiskHeatmap;

})(window);
