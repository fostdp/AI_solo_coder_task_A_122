/**
 * TentMap - 帐篷分布地图组件
 * 基于 Leaflet 的可复用帐篷地图组件
 *
 * 功能:
 *  - 加载 OSM 底图
 *  - 渲染帐篷标记 (⛺ + 标签)
 *  - 点击帐篷触发回调
 *  - 支持高亮选中帐篷
 *
 * 使用示例:
 *   const tentMap = new TentMap('map', { center: [40.14, 94.66], zoom: 17 });
 *   tentMap.loadTents('/api/tents');
 *   tentMap.on('tent-click', (tent) => { ... });
 */
(function (global) {
    'use strict';

    function TentMap(containerId, options) {
        this.containerId = containerId;
        this.options = Object.assign({
            center: [40.1420, 94.6619],
            zoom: 17,
            tileUrl: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            tileAttribution: '© OpenStreetMap',
            markerEmoji: '⛺',
            tentLabelClass: 'tent-label',
            markerClass: 'tent-marker',
        }, options || {});

        this.map = null;
        this.tents = [];
        this.markers = {};
        this._listeners = {};
        this._selectedTentId = null;

        this._init();
    }

    TentMap.prototype._init = function () {
        const opts = this.options;
        this.map = L.map(this.containerId, {
            center: opts.center,
            zoom: opts.zoom,
            zoomControl: true,
        });

        L.tileLayer(opts.tileUrl, {
            attribution: opts.tileAttribution,
            maxZoom: 19,
        }).addTo(this.map);

        // 自适应容器大小
        const self = this;
        setTimeout(function () {
            self.map.invalidateSize();
        }, 100);
    };

    // --- 事件系统 ---
    TentMap.prototype.on = function (event, callback) {
        if (!this._listeners[event]) {
            this._listeners[event] = [];
        }
        this._listeners[event].push(callback);
        return this;
    };

    TentMap.prototype._emit = function (event, data) {
        const listeners = this._listeners[event];
        if (listeners) {
            listeners.forEach(function (cb) { cb(data); });
        }
    };

    // --- 帐篷数据 ---
    TentMap.prototype.loadTents = function (tentsOrUrl) {
        const self = this;

        if (typeof tentsOrUrl === 'string') {
            return fetch(tentsOrUrl)
                .then(function (r) { return r.json(); })
                .then(function (tents) {
                    self.setTents(tents);
                    return tents;
                });
        } else {
            self.setTents(tentsOrUrl);
            return Promise.resolve(tentsOrUrl);
        }
    };

    TentMap.prototype.setTents = function (tents) {
        // 清除旧标记
        var self = this;
        Object.keys(this.markers).forEach(function (id) {
            self.map.removeLayer(self.markers[id]);
        });
        this.markers = {};
        this.tents = tents;

        // 添加新标记
        tents.forEach(function (tent) {
            self._addTentMarker(tent);
        });

        this._emit('tents-loaded', tents);
    };

    TentMap.prototype._addTentMarker = function (tent) {
        var self = this;

        // 帐篷图标
        var icon = L.divIcon({
            className: this.options.markerClass,
            html: this.options.markerEmoji,
            iconSize: [40, 40],
            iconAnchor: [20, 20],
        });

        var marker = L.marker([tent.lat, tent.lng], { icon }).addTo(this.map);

        // Popup
        var popupContent = this._buildPopupHtml(tent);
        marker.bindPopup(popupContent, { maxWidth: 250 });

        // 点击事件
        marker.on('click', function () {
            self.selectTent(tent.id);
            self._emit('tent-click', tent);
        });

        // 标签
        var labelIcon = L.divIcon({
            className: this.options.tentLabelClass,
            html: tent.name,
            iconSize: [80, 20],
            iconAnchor: [40, 30],
        });
        L.marker([tent.lat, tent.lng], { icon: labelIcon, interactive: false }).addTo(this.map);

        this.markers[tent.id] = marker;
    };

    TentMap.prototype._buildPopupHtml = function (tent) {
        var drugs = (tent.drugs || []).join('、');
        return `
            <div class="tent-popup">
                <h3>${tent.name}</h3>
                <p>药材：${drugs}</p>
                <p>传感器：20台 | 水分活度仪：10台</p>
                <button class="popup-btn" data-tent-id="${tent.id}">查看详情</button>
            </div>
        `;
    };

    // --- 选中状态 ---
    TentMap.prototype.selectTent = function (tentId) {
        var prev = this._selectedTentId;
        this._selectedTentId = tentId;

        // 清除之前高亮
        if (prev && this.markers[prev]) {
            var el = this.markers[prev].getElement();
            if (el) el.style.filter = '';
        }

        // 高亮当前
        if (this.markers[tentId]) {
            var el2 = this.markers[tentId].getElement();
            if (el2) el2.style.filter = 'drop-shadow(0 0 10px #d4a853) brightness(1.3)';
        }

        this._emit('tent-selected', tentId);
    };

    TentMap.prototype.getSelectedTent = function () {
        var id = this._selectedTentId;
        if (!id) return null;
        return this.tents.find(function (t) { return t.id === id; }) || null;
    };

    // --- 工具方法 ---
    TentMap.prototype.panToTent = function (tentId) {
        var tent = this.tents.find(function (t) { return t.id === tentId; });
        if (tent) {
            this.map.panTo([tent.lat, tent.lng]);
        }
    };

    TentMap.prototype.invalidateSize = function () {
        this.map.invalidateSize();
    };

    TentMap.prototype.getMap = function () {
        return this.map;
    };

    // 导出
    global.TentMap = TentMap;

})(window);
