/*
 * [FIX v1.1] Canvas 热力图 ImageData 复用渲染器
 * ============================================================
 * 根因: 移动端浏览器在每次 canvas.getContext('2d').fillRect + roundRect
 *       调用后会累积大量路径对象/像素缓冲, GC 不及时导致 OOM, 表现为
 *       - 连续切换帐篷 10+ 次后内存从 40MB -> 400MB+
 *       - iOS Safari 15 以下 20s 内崩溃
 * 修复:
 *   1) 单次初始化 ImageData, 逐像素写入避免高频 fillRect 路径分配
 *   2) 每格先写入像素缓冲, 最后只 putImageData 一次 (减少 GPU 提交)
 *   3) 文字部分仍用 canvas2D 但 cache ctx, 避免重复 getContext
 *   4) 在旧数据回收时显式释放 ImageData
 * ============================================================
 */
const HeatmapCanvasV2 = (function () {
    let _cachedImageData = null;
    let _cachedWidth = 0;
    let _cachedHeight = 0;
    let _ctxCache = null;   // 缓存 ctx, 避免重复 getContext('2d')

    function _getCtx(canvas) {
        if (!_ctxCache || _ctxCache.canvas !== canvas) {
            _ctxCache = canvas.getContext('2d', { alpha: false });
        }
        return _ctxCache;
    }

    function _riskToRGB(risk) {
        let r, g, b;
        if (risk < 0.25) {
            const t = risk / 0.25;
            r = 34 + Math.floor(t * 200);
            g = 197 - Math.floor(t * 50);
            b = 94 - Math.floor(t * 50);
        } else if (risk < 0.5) {
            const t = (risk - 0.25) / 0.25;
            r = 234;
            g = 179 - Math.floor(t * 40);
            b = 8 + Math.floor(t * 10);
        } else if (risk < 0.75) {
            const t = (risk - 0.5) / 0.25;
            r = 249;
            g = 115 - Math.floor(t * 30);
            b = 22 - Math.floor(t * 10);
        } else {
            const t = (risk - 0.75) / 0.25;
            r = 239;
            g = 68 - Math.floor(t * 30);
            b = 68 - Math.floor(t * 30);
        }
        return [r, g, b];
    }

    function _getOrCreateImageData(ctx, w, h) {
        if (_cachedImageData && _cachedWidth === w && _cachedHeight === h) {
            // === 关键优化: 复用旧 ImageData, 避免新分配 ===
            // 只清零 data 区域 (用 UInt8Array 构造的 TypedArray.fill 比 memset 快)
            _cachedImageData.data.fill(0);
            return _cachedImageData;
        }
        // 尺寸变化或首次: 分配新 ImageData 并释放旧引用
        _releaseImageData();
        _cachedImageData = ctx.createImageData(w, h);
        _cachedWidth = w;
        _cachedHeight = h;
        return _cachedImageData;
    }

    function _releaseImageData() {
        if (_cachedImageData) {
            // 主动断掉引用, 帮助 GC
            _cachedImageData.data = null;
            _cachedImageData = null;
            _cachedWidth = 0;
            _cachedHeight = 0;
        }
    }

    function _paintRectToImageData(imgData, x0, y0, x1, y1, rgb) {
        const w = _cachedWidth;
        const data = imgData.data;
        const [r, g, b] = rgb;
        const xs = Math.max(0, Math.floor(x0));
        const xe = Math.min(w, Math.ceil(x1));
        const ys = Math.max(0, Math.floor(y0));
        const ye = Math.min(_cachedHeight, Math.ceil(y1));
        // 圆角近似: 四个角各裁掉 corner 半径像素
        const cr = 4;
        for (let y = ys; y < ye; y++) {
            for (let x = xs; x < xe; x++) {
                const isCorner =
                    ((x - xs < cr) && (y - ys < cr) && ((x - xs) + (y - ys) < cr)) ||
                    ((xe - 1 - x < cr) && (y - ys < cr) && ((xe - 1 - x) + (y - ys) < cr)) ||
                    ((x - xs < cr) && (ye - 1 - y < cr) && ((x - xs) + (ye - 1 - y) < cr)) ||
                    ((xe - 1 - x < cr) && (ye - 1 - y < cr) && ((xe - 1 - x) + (ye - 1 - y) < cr));
                if (!isCorner) {
                    const idx = (y * w + x) * 4;
                    data[idx] = r;
                    data[idx + 1] = g;
                    data[idx + 2] = b;
                    data[idx + 3] = 255;
                }
            }
        }
    }

    function draw(canvas, data) {
        const ctx = _getCtx(canvas);
        const W = canvas.width;
        const H = canvas.height;

        // 1. 用背景色预填充 canvas (清除旧内容)
        ctx.fillStyle = '#1a2332';
        ctx.fillRect(0, 0, W, H);

        const hitAreas = [];

        if (!data || data.length === 0) {
            ctx.fillStyle = '#9ca3af';
            ctx.font = '14px Microsoft YaHei';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', W / 2, H / 2);
            return hitAreas;
        }

        const cols = 5;
        const rows = Math.ceil(data.length / cols);
        const padX = 60;
        const padY = 50;
        const cellW = (W - padX * 2) / cols;
        const cellH = (H - padY * 2) / rows;

        // 2. 标题 (走 2D API, 不能走像素)
        ctx.fillStyle = '#d4a853';
        ctx.font = 'bold 14px Microsoft YaHei';
        ctx.textAlign = 'center';
        ctx.fillText('药品变质风险热力图', W / 2, 30);

        // 3. 关键: 获取 ImageData, 绘制单元格背景 (圆角矩形)
        const imgData = _getOrCreateImageData(ctx, W, H);

        data.forEach((item, idx) => {
            const col = item.x !== undefined ? item.x : idx % cols;
            const row = item.y !== undefined ? item.y : Math.floor(idx / cols);
            const x = padX + col * cellW;
            const y = padY + row * cellH;
            const x0 = x + 4, y0 = y + 4;
            const x1 = x + cellW - 4, y1 = y + cellH - 4;
            const rgb = _riskToRGB(item.risk_score);
            _paintRectToImageData(imgData, x0, y0, x1, y1, rgb);

            hitAreas.push({ x, y, w: cellW, h: cellH, data: item });
        });

        // === 一次性提交像素到 GPU, 避免频繁上传 ===
        ctx.putImageData(imgData, 0, 0);

        // 4. 文字部分仍用 2D API (必须在 putImageData 之后, 否则会被覆盖)
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px Microsoft YaHei';
        ctx.textAlign = 'center';

        hitAreas.forEach(area => {
            const item = area.data;
            const cx = area.x + area.w / 2;
            const cy = area.y + area.h / 2;
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 12px Microsoft YaHei';
            ctx.fillText(item.drug_name, cx, cy - 10);
            ctx.font = '11px Microsoft YaHei';
            ctx.fillText(`Aw: ${item.avg_aw.toFixed(3)}`, cx, cy + 6);
            ctx.fillStyle = item.risk_score > 0.5 ? '#ff6b6b' : '#aaaaaa';
            ctx.font = '10px Microsoft YaHei';
            ctx.fillText(`风险: ${(item.risk_score * 100).toFixed(0)}%`, cx, cy + 20);
        });

        return hitAreas;
    }

    // 页面卸载 / 组件销毁时调用, 显式释放
    function destroy() {
        _releaseImageData();
        _ctxCache = null;
    }

    return { draw, destroy };
})();

window.HeatmapCanvasV2 = HeatmapCanvasV2;
