/* 多维分析面板 —— 雷达图 / 矩阵热力图 / 危害等级直方图
 *
 * 英文版与中文版共用这一个文件，按当前路径自动切换文案。
 * 同时导出 window.ANL 标签助手，给记录条的多维徽章用。
 */
(function() {
    const IS_ZH = /^\/zh(\/|$)/.test(location.pathname);

    const CAT_EN = {
        cyber: 'Cyber Attack',
        malware: 'Malware',
        deception: 'Fraud & Scams',
        violence: 'Violence & Harm',
        self_harm: 'Self-harm',
        privacy: 'Privacy Leak',
        illegal: 'Illegal Acts',
        misinformation: 'Misinformation',
        sexual: 'Sexual Content',
        hate: 'Hate & Discrimination',
        intellectual_property: 'IP Infringement',
        dangerous: 'Dangerous Items',
        harassment: 'Harassment',
        other: 'Other',
    };

    const CAT_ZH = {
        cyber: '网络攻击',
        malware: '恶意软件',
        deception: '诈骗欺诈',
        violence: '暴力伤害',
        self_harm: '自残自杀',
        privacy: '隐私泄露',
        illegal: '违法行为',
        misinformation: '虚假信息',
        sexual: '色情淫秽',
        hate: '仇恨歧视',
        intellectual_property: '知识产权',
        dangerous: '危险物品',
        harassment: '骚扰',
        other: '其他',
    };

    const REF_EN = {
        full_refusal: 'Full refusal',
        partial_refusal: 'Partial refusal',
        partial_compliance: 'Partial compliance',
        full_compliance: 'Full compliance',
    };

    const REF_ZH = {
        full_refusal: '完全拒绝',
        partial_refusal: '部分拒绝',
        partial_compliance: '部分服从',
        full_compliance: '完全服从',
    };

    const UNC = IS_ZH ? '未分类' : 'Unclassified';

    /* 标签助手：记录条徽章、分析面板共用 */
    window.ANL = {
        zh: IS_ZH,
        uncategorized: UNC,
        cat(name) {
            if (!name) return '';
            const m = IS_ZH ? CAT_ZH : CAT_EN;
            return m[name] || name;
        },
        ref(name) {
            if (!name) return '';
            const m = IS_ZH ? REF_ZH : REF_EN;
            return m[name] || name;
        },
        sev(n) {
            return IS_ZH ? '危害 ' + n : 'Severity ' + n;
        },
    };

    const T = IS_ZH ? {
        total: '总记录数',
        totalFoot: '已入库的测试记录',
        success: '越狱成功数',
        successFoot: '目标模型给出实质内容',
        asr: '总体 ASR',
        asrFoot: '成功数 / 总记录数',
        sev: '平均危害等级',
        sevFoot: '1-5 分，未评分记录不计入',
        radar: '越狱成功率雷达图',
        radarNote: '数值 = 该维度下的越狱成功率 (ASR)',
        sevHist: '危害等级分布',
        sevHistNote: '1 分最轻，5 分可直接利用',
        heat: '维度矩阵热力图',
        heatNote: '颜色越红代表该交叉点越狱成功率越高',
        rowDim: '行',
        colDim: '列',
        refresh: '刷新',
        empty: '暂无数据，先跑一轮攻击测试',
        noScore: '暂无评分数据',
        rows: '行',
        cols: '列',
        dims: {
            category: '风险类别',
            dataset: '数据集',
            converter: '转换器',
            harm: '危害子类',
            harm_major: '危害大类',
            refusal_level: '拒答程度',
            severity: '危害等级',
            target_model: '被攻击模型',
            attack_model: '攻击者模型',
            payload: '提示词模板',
        },
        radarDims: {
            category: '风险类别',
            dataset: '数据集',
            converter: '转换器',
            refusal_level: '拒答程度',
        },
        cellTip: '总数 {total} · 成功 {success} · ASR {asr} · 平均危害 {sev}',
        avgSev: '平均危害',
        datasets: '覆盖数据集',
        datasetsFoot: '参与测试的数据集个数',
    } : {
        total: 'Total Records',
        totalFoot: 'Stored test records',
        success: 'Successful Jailbreaks',
        successFoot: 'Target gave substantive content',
        asr: 'Overall ASR',
        asrFoot: 'Success / total records',
        sev: 'Avg Severity',
        sevFoot: 'Score 1-5, unscored records excluded',
        radar: 'Jailbreak Rate Radar',
        radarNote: 'Value = ASR of that dimension',
        sevHist: 'Severity Distribution',
        sevHistNote: '1 is mild, 5 is directly usable',
        heat: 'Dimension Matrix',
        heatNote: 'The redder, the higher the jailbreak rate',
        rowDim: 'Rows',
        colDim: 'Columns',
        refresh: 'Refresh',
        empty: 'No data yet — run an attack round first',
        noScore: 'No scored data yet',
        rows: 'Rows',
        cols: 'Columns',
        dims: {
            category: 'Risk category',
            dataset: 'Dataset',
            converter: 'Transformer',
            harm: 'Harm subtype',
            harm_major: 'Harm group',
            refusal_level: 'Refusal level',
            severity: 'Severity',
            target_model: 'Target model',
            attack_model: 'Attacker model',
            payload: 'Prompt template',
        },
        radarDims: {
            category: 'Risk category',
            dataset: 'Dataset',
            converter: 'Transformer',
            refusal_level: 'Refusal level',
        },
        cellTip: 'total {total} · success {success} · ASR {asr} · avg severity {sev}',
        avgSev: 'Avg severity',
        datasets: 'Datasets Covered',
        datasetsFoot: 'Datasets involved in testing',
    };

    const DIM_KEYS = ['dataset', 'category', 'converter', 'harm', 'harm_major',
        'refusal_level', 'severity', 'target_model', 'attack_model', 'payload'
    ];

    const SEV_COLORS = ['#6ccb5f', '#38b6ff', '#d8b13a', '#e08a3c', '#e05260'];

    function pct(v) { return Math.round((v || 0) * 1000) / 10; }

    const AnalyticsPanel = {
        data() {
            return {
                loading: false,
                err: '',
                ov: null,
                mx: null,
                radarDim: 'category',
                rowKey: 'dataset',
                colKey: 'category',
                T: T,
                dimKeys: DIM_KEYS,
            };
        },
        computed: {
            dimOpts() {
                return this.dimKeys.map(k => ({ key: k, label: T.dims[k] || k }));
            },
            radarDims() {
                return ['category', 'dataset', 'converter', 'refusal_level']
                    .map(k => ({ key: k, label: T.radarDims[k] || k }));
            },
            overall() {
                return (this.ov && this.ov.overall) || { total: 0, success: 0, asr: 0, avg_severity: 0 };
            },
            datasetCount() {
                const axes = (this.ov && this.ov.radar && this.ov.radar.dataset) || [];
                return axes.length;
            },
            radarAxes() {
                const axes = (this.ov && this.ov.radar && this.ov.radar[this.radarDim]) || [];
                return axes.slice(0, 10);
            },
            /* 雷达图几何：中心 (190,145)，半径 100 */
            radarGeo() {
                const axes = this.radarAxes;
                const n = axes.length;
                if (!n) return { rings: [], spokes: [], dots: [], polygon: '' };
                const cx = 190,
                    cy = 140,
                    R = 98;
                const pt = (i, r) => {
                    const a = (-90 + i * 360 / n) * Math.PI / 180;
                    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
                };
                const fmt = (i, r) => pt(i, r).map(v => v.toFixed(1)).join(',');
                const rings = [0.25, 0.5, 0.75, 1].map(f => ({
                    f: f,
                    points: axes.map((_, i) => fmt(i, R * f)).join(' '),
                }));
                const spokes = axes.map((ax, i) => {
                    const [x, y] = pt(i, R);
                    const [lx, ly] = pt(i, R + 20);
                    const cos = Math.cos((-90 + i * 360 / n) * Math.PI / 180);
                    let anchor = 'middle';
                    if (cos > 0.25) anchor = 'start';
                    else if (cos < -0.25) anchor = 'end';
                    return {
                        x1: cx,
                        y1: cy,
                        x2: x,
                        y2: y,
                        lx: lx,
                        ly: ly,
                        anchor: anchor,
                        name: this.dimLabel(this.radarDim, ax.name),
                    };
                });
                const dots = axes.map((ax, i) => {
                    const [x, y] = pt(i, R * (ax.asr || 0));
                    return { x: x, y: y, name: ax.name, asr: ax.asr || 0 };
                });
                const polygon = dots.map(d => d.x.toFixed(1) + ',' + d.y.toFixed(1)).join(' ');
                return { cx: cx, cy: cy, R: R, rings: rings, spokes: spokes, dots: dots, polygon: polygon };
            },
            sevBars() {
                const hist = (this.ov && this.ov.severity_hist) || [];
                const max = Math.max(1, ...hist.map(b => b.total));
                return hist.map(b => ({
                    severity: b.severity,
                    total: b.total,
                    success: b.success,
                    asr: b.asr,
                    pct: Math.round((b.total / max) * 100),
                    color: SEV_COLORS[(b.severity || 1) - 1],
                }));
            },
            hasMatrix() {
                return !!(this.mx && this.mx.rows && this.mx.rows.length && this.mx.cols && this.mx.cols.length);
            },
        },
        mounted() {
            this.load();
        },
        methods: {
            dimLabel(key, raw) {
                if (raw === undefined || raw === null || raw === '') return UNC;
                if (key === 'category') return window.ANL.cat(raw);
                if (key === 'refusal_level') return window.ANL.ref(raw);
                if (key === 'severity') return 'L' + raw;
                if (raw === '未分类') return UNC;
                return raw;
            },
            async load() {
                this.loading = true;
                this.err = '';
                try {
                    const [ov, mx] = await Promise.all([
                        fetch('/api/analytics/overview').then(r => r.json()),
                        this.fetchMatrix(),
                    ]);
                    this.ov = ov;
                    this.mx = mx;
                } catch (e) {
                    this.err = String(e && e.message ? e.message : e);
                }
                this.loading = false;
            },
            async fetchMatrix() {
                const r = await fetch('/api/analytics/matrix?row=' + encodeURIComponent(this.rowKey) +
                    '&col=' + encodeURIComponent(this.colKey));
                return r.json();
            },
            async loadMatrix() {
                try {
                    this.mx = await this.fetchMatrix();
                } catch (e) {
                    this.err = String(e && e.message ? e.message : e);
                }
            },
            cellLevel(cell) {
                if (!cell || !cell.asr) return 0;
                return Math.max(1, Math.min(5, Math.ceil(cell.asr * 5)));
            },
            cellTip(cell) {
                if (!cell) return '';
                return T.cellTip
                    .replace('{total}', cell.total)
                    .replace('{success}', cell.success)
                    .replace('{asr}', pct(cell.asr) + '%')
                    .replace('{sev}', cell.avg_severity || 0);
            },
            sevText(n) {
                return 'L' + n;
            },
        },
        template: `
        <div class="an-panel">
            <div v-if="err" class="an-err">{{ err }}</div>
            <div class="grid-tiles">
                <div class="tile">
                    <div class="tile-label">{{ T.total }}</div>
                    <div class="tile-value">{{ overall.total }}</div>
                    <div class="tile-foot">{{ T.totalFoot }}</div>
                </div>
                <div class="tile">
                    <div class="tile-label">{{ T.success }}</div>
                    <div class="tile-value">{{ overall.success }}</div>
                    <div class="tile-foot">{{ T.successFoot }}</div>
                </div>
                <div class="tile">
                    <div class="tile-label">{{ T.asr }}</div>
                    <div class="tile-value">{{ (overall.asr * 100).toFixed(1) }}<span class="unit">%</span></div>
                    <div class="tile-foot">{{ T.asrFoot }}</div>
                </div>
                <div class="tile tile-accent">
                    <div class="tile-label">{{ T.sev }}</div>
                    <div class="tile-value">{{ overall.avg_severity || 0 }}<span class="unit">/5</span></div>
                    <div class="tile-foot">{{ T.sevFoot }}</div>
                </div>
            </div>

            <div class="an-grid">
                <div class="card">
                    <div class="card-head">
                        <h2 class="card-title">{{ T.radar }}</h2>
                        <span class="card-note">{{ T.radarNote }}</span>
                    </div>
                    <div class="card-body-pad">
                        <div class="seg an-seg">
                            <button v-for="d in radarDims" :key="d.key" class="seg-item"
                                    :class="{on: radarDim===d.key}" @click="radarDim=d.key">{{ d.label }}</button>
                        </div>
                        <div v-if="radarAxes.length" class="an-radar">
                            <svg viewBox="0 0 380 280" role="img" aria-label="radar chart">
                                <polygon v-for="(r, ri) in radarGeo.rings" :key="'ring'+ri"
                                         :points="r.points" class="an-ring" :class="{outer: ri===radarGeo.rings.length-1}"></polygon>
                                <line v-for="(sp, si) in radarGeo.spokes" :key="'sp'+si"
                                      :x1="sp.x1" :y1="sp.y1" :x2="sp.x2" :y2="sp.y2" class="an-spoke"></line>
                                <polygon :points="radarGeo.polygon" class="an-poly"></polygon>
                                <circle v-for="(d, di) in radarGeo.dots" :key="'d'+di"
                                        :cx="d.x" :cy="d.y" r="3.4" class="an-dot"></circle>
                                <text v-for="(sp, si) in radarGeo.spokes" :key="'t'+si"
                                      :x="sp.lx" :y="sp.ly" :text-anchor="sp.anchor" class="an-label">{{ sp.name }}</text>
                            </svg>
                        </div>
                        <div v-else class="empty">{{ T.noScore }}</div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-head">
                        <h2 class="card-title">{{ T.sevHist }}</h2>
                        <span class="card-note">{{ T.sevHistNote }}</span>
                    </div>
                    <div class="card-body-pad">
                        <div class="an-sev-row" v-for="b in sevBars" :key="b.severity">
                            <span class="an-sev-label mono">{{ sevText(b.severity) }}</span>
                            <div class="an-sev-track">
                                <div class="an-sev-fill" :style="{width: b.pct + '%', background: b.color}"></div>
                            </div>
                            <span class="an-sev-num mono">{{ b.total }}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-head">
                    <h2 class="card-title">{{ T.heat }}</h2>
                    <span class="card-note">{{ T.heatNote }}</span>
                </div>
                <div class="card-body-pad">
                    <div class="an-dims">
                        <span class="an-dim-label">{{ T.rowDim }}</span>
                        <select class="input" v-model="rowKey" @change="loadMatrix">
                            <option v-for="d in dimOpts" :key="d.key" :value="d.key">{{ d.label }}</option>
                        </select>
                        <span class="an-x">×</span>
                        <span class="an-dim-label">{{ T.colDim }}</span>
                        <select class="input" v-model="colKey" @change="loadMatrix">
                            <option v-for="d in dimOpts" :key="d.key" :value="d.key">{{ d.label }}</option>
                        </select>
                        <button class="btn btn-ghost btn-sm" @click="loadMatrix">{{ T.refresh }}</button>
                    </div>
                    <div v-if="hasMatrix" class="an-heat-wrap">
                        <table class="an-heat">
                            <thead>
                                <tr>
                                    <th class="an-heat-corner"></th>
                                    <th v-for="c in mx.cols" :key="c">{{ dimLabel(colKey, c) }}</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(r, ri) in mx.rows" :key="r">
                                    <th class="an-heat-rowh">{{ dimLabel(rowKey, r) }}</th>
                                    <td v-for="(cell, ci) in mx.matrix[ri]" :key="ci"
                                        class="an-heat-cell" :class="'lv' + cellLevel(cell)"
                                        :title="cellTip(cell)">
                                        <span v-if="cell">{{ cell.success }}/{{ cell.total }}</span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div v-else class="empty">{{ T.empty }}</div>
                </div>
            </div>
        </div>
        `,
    };

    window.AnalyticsPanel = AnalyticsPanel;
})();