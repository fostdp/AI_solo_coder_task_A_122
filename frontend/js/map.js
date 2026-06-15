const TentMap = {
    map: null,
    markers: {},
    tents: [],

    async init() {
        this.map = L.map('map', {
            center: [40.1420, 94.6619],
            zoom: 17,
            zoomControl: true,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap',
            maxZoom: 19,
        }).addTo(this.map);

        try {
            const resp = await fetch('/api/tents');
            this.tents = await resp.json();
        } catch (e) {
            this.tents = [
                { id: 1, name: "悬泉置·东帐", lat: 40.1435, lng: 94.6635, drugs: ["当归", "大黄", "甘草"] },
                { id: 2, name: "悬泉置·西帐", lat: 40.1415, lng: 94.6600, drugs: ["黄芪", "白术", "茯苓"] },
                { id: 3, name: "悬泉置·南帐", lat: 40.1405, lng: 94.6625, drugs: ["川芎", "白芍", "熟地"] },
                { id: 4, name: "悬泉置·北帐", lat: 40.1445, lng: 94.6610, drugs: ["桂枝", "麻黄", "细辛"] },
                { id: 5, name: "悬泉置·中帐", lat: 40.1420, lng: 94.6619, drugs: ["人参", "丹参", "五味子"] },
            ];
        }

        this.tents.forEach(tent => this.addTentMarker(tent));

        setTimeout(() => this.map.invalidateSize(), 200);
    },

    addTentMarker(tent) {
        const icon = L.divIcon({
            className: 'tent-marker',
            html: '⛺',
            iconSize: [40, 40],
            iconAnchor: [20, 20],
        });

        const marker = L.marker([tent.lat, tent.lng], { icon }).addTo(this.map);

        const popupContent = `
            <div class="tent-popup">
                <h3>${tent.name}</h3>
                <p>药材：${tent.drugs.join('、')}</p>
                <p>传感器：20台 | 水分活度仪：10台</p>
                <button class="popup-btn" onclick="openTentDetail(${tent.id})">查看详情</button>
            </div>
        `;

        marker.bindPopup(popupContent, { maxWidth: 250 });
        marker.on('click', () => {
            marker.openPopup();
        });

        const label = L.divIcon({
            className: 'tent-label',
            html: tent.name,
            iconSize: [80, 20],
            iconAnchor: [40, 30],
        });
        L.marker([tent.lat, tent.lng], { icon: label, interactive: false }).addTo(this.map);

        this.markers[tent.id] = marker;
    },

    highlightTent(tentId) {
        Object.values(this.markers).forEach(m => {
            m.getElement().style.filter = '';
        });
        if (this.markers[tentId]) {
            this.markers[tentId].getElement().style.filter = 'drop-shadow(0 0 10px #d4a853) brightness(1.3)';
        }
    }
};
