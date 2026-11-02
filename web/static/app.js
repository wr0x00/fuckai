/* fuckai Web 前端逻辑（Vue 3 全局构建，无构建步骤） */
const { createApp } = Vue;

const ICO = {
    dash: '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7.5" height="8.5" rx="1.4" stroke="currentColor" stroke-width="1.6"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="1.4" stroke="currentColor" stroke-width="1.6"/><rect x="13.5" y="11.5" width="7.5" height="9.5" rx="1.4" stroke="currentColor" stroke-width="1.6"/><rect x="3" y="14.5" width="7.5" height="6.5" rx="1.4" stroke="currentColor" stroke-width="1.6"/></svg>',
    arsenal: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 7.5h16M4 12h16M4 16.5h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="19" cy="16.5" r="2.2" stroke="currentColor" stroke-width="1.6"/></svg>',
    attack: '<svg viewBox="0 0 24 24" fill="none"><path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12l1-8Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
    records: '<svg viewBox="0 0 24 24" fill="none"><rect x="3.5" y="4" width="17" height="16" rx="2" stroke="currentColor" stroke-width="1.6"/><path d="M3.5 9h17M8.5 4v16" stroke="currentColor" stroke-width="1.6"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.6"/><path d="M19.4 14.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H2.5a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V2.5a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    update: '<svg viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v4.5h-4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    topic: '<svg viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 1 1-3.2-6.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M20 3.5V9h-5.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    tpl: '<svg viewBox="0 0 24 24" fill="none"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    convert: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 8h13m0 0-3.5-3.5M17 8l-3.5 3.5M20 16H7m0 0 3.5-3.5M7 16l3.5 3.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    target: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="4.5" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>',
    score: '<svg viewBox="0 0 24 24" fill="none"><path d="m4 12.5 5 5L20 6.5" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    save: '<svg viewBox="0 0 24 24" fill="none"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M17 21v-8H7v8M7 3v5h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

const emptyArsenal = {
    stats: {},
    local_groups: [],
    jailbreaks: [],
    executors: [],
    converters: [],
};

createApp({
    data() {
        return {
            page: 'dash',
            dark: localStorage.getItem('fuckai-theme') === 'dark',
            arsenal: JSON.parse(JSON.stringify(emptyArsenal)),
            records: { total: 0, success: 0, rate: 0, items: [] },
            cfg: {
                attack_base_url: '',
                attack_api_key: '',
                attack_model: '',
                attack_temperature: 0.7,
                target_base_url: '',
                target_api_key: '',
                target_model: '',
                target_temperature: 0,
                timeout: 120,
                max_tokens: 1024,
                variation_count: 3,
                sample_size: 10,
                repo_url: '',
            },
            conn: { attack_model: null, target_model: null },
            connState: { cls: '', text: '未检测' },
            busy: { conn: false, save: false, update: false },
            arsenalTab: 'conv',
            arsenalQuery: '',
            recQuery: '',
            recFilter: 'all',
            expandId: null,
            expandedRecord: null,
            atk: {
                objective_group: '',
                manual: '',
                sample_size: 10,
                use_all: false,
                converter_ids: ['direct'],
                payload_name: '',
            },
            running: false,
            abort: null,
            runRows: [],
            planTotal: 0,
            doneCount: 0,
            lastSummary: null,
            upd: { repo_url: '', result: '', ok: true },
            toast: null,
            toastTimer: null,
        };
    },

    computed: {
        navItems() {
            return [
                { key: 'dash', label: '概览', icon: ICO.dash, sub: '管线总览与连接状态' },
                { key: 'arsenal', label: '弹药库', icon: ICO.arsenal, sub: '话题 / 模板 / 变换器', badge: () => this.totalObjectives },
                { key: 'attack', label: '攻击测试', icon: ICO.attack, sub: '执行并实时观测结果' },
                { key: 'records', label: '测试记录', icon: ICO.records, sub: '历史结果与报告导出', badge: () => this.records.total },
                { key: 'settings', label: '模型配置', icon: ICO.settings, sub: '攻击模型与目标模型' },
                { key: 'update', label: '从 GitHub 更新', icon: ICO.update, sub: '拉取最新源码' },
            ];
        },
        currentNav() { return this.navItems.find(n => n.key === this.page) || {}; },
        totalObjectives() {
            return this.arsenal.local_groups.reduce((s, g) => s + g.count, 0);
        },
        arsenalTabs() {
            return [
                { key: 'conv', label: '变换器', count: () => this.arsenal.converters.length },
                { key: 'tpl', label: '提示词模板', count: () => this.arsenal.jailbreaks.length + this.arsenal.executors.length },
                { key: 'obj', label: '话题集', count: () => this.totalObjectives },
            ];
        },
        filteredConverters() {
            const q = this.arsenalQuery.trim().toLowerCase();
            if (!q) return this.arsenal.converters;
            return this.arsenal.converters.filter(
                c => c.id.toLowerCase().includes(q) || c.label.toLowerCase().includes(q));
        },
        filteredTemplates() {
            const q = this.arsenalQuery.trim().toLowerCase();
            const all = [...this.arsenal.jailbreaks, ...this.arsenal.executors];
            if (!q) return all;
            return all.filter(p => p.name.toLowerCase().includes(q) || p.value.toLowerCase().includes(q));
        },
        filteredRecords() {
            const q = this.recQuery.trim().toLowerCase();
            return this.records.items.filter(r => {
                if (this.recFilter === 'true' && !r.success) return false;
                if (this.recFilter === 'false' && r.success) return false;
                if (!q) return true;
                return (r.objective || '').toLowerCase().includes(q) ||
                    (r.converter || '').toLowerCase().includes(q);
            });
        },
        connModels() {
            return [
                { key: 'attack_model', label: '攻击模型' },
                { key: 'target_model', label: '被攻击模型' },
            ].map(m => ({...m, ...(this.conn[m.key] || {}) }));
        },
        progress() {
            if (!this.planTotal) return 0;
            return Math.min(100, Math.round((this.doneCount / this.planTotal) * 100));
        },
        pipeline() {
            return [
                { t: '话题', d: '问什么', icon: ICO.topic },
                { t: '提示词模板', d: '怎么包', icon: ICO.tpl },
                { t: '变换器', d: '怎么变形', icon: ICO.convert },
                { t: '目标模型', d: '接收 prompt', icon: ICO.target },
                { t: '评分', d: 'True / False', icon: ICO.score },
                { t: '记录', d: '落库可导出', icon: ICO.save },
            ];
        },
    },

    created() {
        this.applyTheme();
        this.loadAll();
    },

    methods: {
        async api(path, opts = {}) {
            const res = await fetch(path, {
                headers: { 'Content-Type': 'application/json' },
                ...opts,
            });
            const text = await res.text();
            let data = null;
            try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
            if (!res.ok) {
                const msg = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
                throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }
            return data;
        },

        async loadAll() {
            try {
                const [ars, rec, cfg, upd] = await Promise.all([
                    this.api('/api/arsenal'),
                    this.api('/api/records?limit=300'),
                    this.api('/api/config'),
                    this.api('/api/update/source'),
                ]);
                this.arsenal = Object.assign(JSON.parse(JSON.stringify(emptyArsenal)), ars);
                this.records = rec;
                this.cfg = Object.assign(this.cfg, cfg);
                this.upd.repo_url = upd.repo_url || this.cfg.repo_url || '';
            } catch (e) {
                this.notify('加载失败: ' + e.message, 'err');
            }
        },

        notify(msg, cls = '') {
            this.toast = { msg, cls };
            clearTimeout(this.toastTimer);
            this.toastTimer = setTimeout(() => { this.toast = null; }, 3200);
        },

        toggleTheme() {
            this.dark = !this.dark;
            localStorage.setItem('fuckai-theme', this.dark ? 'dark' : 'light');
            this.applyTheme();
        },
        applyTheme() {
            document.documentElement.setAttribute('data-theme', this.dark ? 'dark' : 'light');
        },

        async testConn() {
            this.busy.conn = true;
            this.connState = { cls: 'busy', text: '检测中' };
            try {
                const r = await this.api('/api/config/test', { method: 'POST' });
                this.conn = r;
                const bad = Object.values(r).filter(v => !v.ok).length;
                if (bad) this.connState = { cls: 'err', text: `${bad} 个连接失败` };
                else this.connState = { cls: 'ok', text: '模型连接正常' };
            } catch (e) {
                this.connState = { cls: 'err', text: '检测失败' };
                this.notify('检测失败: ' + e.message, 'err');
            } finally {
                this.busy.conn = false;
            }
        },

        async saveConfig() {
            this.busy.save = true;
            try {
                await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.cfg) });
                this.notify('配置已保存');
                this.conn = { attack_model: null, target_model: null };
                this.connState = { cls: '', text: '未检测' };
            } catch (e) {
                this.notify('保存失败: ' + e.message, 'err');
            } finally {
                this.busy.save = false;
            }
        },

        toggleConv(id) {
            const i = this.atk.converter_ids.indexOf(id);
            if (i >= 0) {
                if (this.atk.converter_ids.length > 1) this.atk.converter_ids.splice(i, 1);
            } else {
                this.atk.converter_ids.push(id);
            }
        },

        resetRun() {
            if (this.abort) this.abort.abort();
            this.running = false;
        },

        async runAttack() {
            const objectives = this.atk.objective_group ?
                [] :
                this.atk.manual.split('\n').map(s => s.trim()).filter(Boolean);
            if (!this.atk.objective_group && !objectives.length) {
                this.notify('请先填写测试话题或选择话题来源', 'err');
                return;
            }
            this.running = true;
            this.runRows = [];
            this.doneCount = 0;
            this.lastSummary = null;
            const ctrl = new AbortController();
            this.abort = ctrl;
            let uid = 0;
            try {
                const resp = await fetch('/api/attack/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        objectives,
                        converter_ids: this.atk.converter_ids,
                        payload_name: this.atk.payload_name,
                        objective_group: this.atk.objective_group,
                        sample_size: this.atk.sample_size,
                        use_all: this.atk.use_all,
                    }),
                    signal: ctrl.signal,
                });
                if (!resp.ok) {
                    const t = await resp.text();
                    let m = t;
                    try { m = JSON.parse(t).detail || t; } catch (e) {}
                    throw new Error(m);
                }
                const reader = resp.body.getReader();
                const dec = new TextDecoder();
                let buf = '';
                for (;;) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    buf += dec.decode(value, { stream: true });
                    const parts = buf.split('\n\n');
                    buf = parts.pop();
                    for (const chunk of parts) {
                        const line = chunk.split('\n').find(l => l.startsWith('data: '));
                        if (!line) continue;
                        const ev = JSON.parse(line.slice(6));
                        if (ev.type === 'start') {
                            this.planTotal = ev.total;
                        } else if (ev.type === 'item') {
                            this.runRows.push({...ev.record, id: ++uid });
                            this.doneCount = ev.done;
                            this.planTotal = ev.total;
                            this.$nextTick(this.scrollStream);
                        } else if (ev.type === 'done') {
                            this.lastSummary = { total: ev.total, success: ev.success, rate: ev.rate };
                        }
                    }
                }
                this.notify('攻击完成');
                await this.loadRecords();
            } catch (e) {
                if (e.name !== 'AbortError') this.notify('执行失败: ' + e.message, 'err');
            } finally {
                this.running = false;
                this.abort = null;
            }
        },

        scrollStream() {
            const el = this.$refs.streamEl;
            if (el) el.scrollTop = el.scrollHeight;
        },

        async loadRecords() {
            try {
                this.records = await this.api('/api/records?limit=300');
            } catch (e) { /* 静默 */ }
        },

        toggleExpand(id) {
            if (this.expandId === id) {
                this.expandId = null;
                this.expandedRecord = null;
                return;
            }
            this.expandId = id;
            this.expandedRecord = this.records.items.find(r => r.id === id) || null;
        },

        async exportReport(fmt) {
            try {
                const r = await this.api('/api/report/export?fmt=' + fmt);
                window.open(r.download, '_blank');
                this.notify(`已导出 ${r.count} 条记录 -> ${r.path}`);
            } catch (e) {
                this.notify('导出失败: ' + e.message, 'err');
            }
        },

        async clearRecords() {
            if (!confirm('确定清空全部测试记录？此操作不可撤销。')) return;
            try {
                await this.api('/api/records', { method: 'DELETE' });
                this.expandId = null;
                this.expandedRecord = null;
                await this.loadRecords();
                this.notify('记录已清空');
            } catch (e) {
                this.notify('清空失败: ' + e.message, 'err');
            }
        },

        async doUpdate() {
            this.busy.update = true;
            this.upd.result = '';
            try {
                const r = await this.api('/api/update', {
                    method: 'POST',
                    body: JSON.stringify({ repo_url: this.upd.repo_url }),
                });
                this.upd.ok = true;
                this.upd.result = r.summary;
                this.notify('更新完成，请重启服务');
            } catch (e) {
                this.upd.ok = false;
                this.upd.result = e.message;
                this.notify('更新失败: ' + e.message, 'err');
            } finally {
                this.busy.update = false;
            }
        },
    },
}).mount('#app');