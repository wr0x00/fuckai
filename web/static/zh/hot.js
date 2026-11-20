/* AI Safety HOT 内嵌浏览器面板 —— 中文版
 *
 * 真实 Chromium（Blink）无头引擎方案：后端 Playwright 驱动真浏览器渲染，
 * 帧经 /api/engine/ws 以 WebSocket 二进制直推，前端 <canvas> 按显示器刷新率
 * 渲染（latest-wins：新帧永远覆盖旧帧，与 vsync 对齐，无解码排队）。
 * 点击 / 滚轮 / 按键 / 地址栏导航全部转发给引擎。
 *
 * 中文与剪贴板：host 输入法的 composition 事件无法经 keydown 转发，
 * 因此中文 / 粘贴走面板下方「输入条」（原生 input，回车后 CDP insertText
 * 整段注入引擎）；Ctrl+C / Ctrl+X 从引擎取选中文本写回剪贴板。
 */
(function() {
    const DEFAULT_URL = 'https://aisafetyhot.com/zh';
    const VIEW_W = 1280,
        VIEW_H = 800;

    window.HotPanel = {
        props: { enabled: { type: Boolean, default: false } },
        template: `
<div class="card hot-card">
  <div class="hot-toolbar">
    <button class="hot-btn" @click="back" title="后退">&#8249;</button>
    <button class="hot-btn" @click="forward" title="前进">&#8250;</button>
    <button class="hot-btn" @click="reload" title="刷新">&#10227;</button>
    <input class="input hot-url mono" v-model="input" @keyup.enter="go"
           spellcheck="false" placeholder="输入网址，回车打开">
    <button class="btn btn-primary btn-sm" @click="go">打开</button>
    <button class="btn btn-ghost btn-sm" @click="openExternal" title="在系统浏览器打开原始网址">新窗口</button>
  </div>
  <div class="hot-inputrow">
    <span class="hot-inputlabel">页面输入</span>
    <input class="input hot-textin mono" v-model="textInput" @keyup.enter="sendText"
           spellcheck="false" placeholder="先点一下画面里的输入框，再在这里打中文 / 粘贴（Ctrl+V），回车送入">
    <button class="btn btn-ghost btn-sm" @click="sendText">送入</button>
  </div>
  <div class="hot-frame-wrap" ref="viewport">
    <canvas class="hot-stream" ref="streamCanvas"></canvas>
    <div class="hot-capture" tabindex="0"
         @click="onClick" @wheel.prevent="onWheel" @keydown="onKey"></div>
    <div class="hot-status" v-if="hint">{{ hint }}</div>
  </div>
  <p class="muted hot-note">真实 Chromium（Blink）引擎渲染，WebSocket + Canvas 按刷新率显示；点击 / 滚轮 / 按键会转发给引擎。中文输入和 Ctrl+V 请用上方「页面输入」条；Ctrl+C / Ctrl+X 复制画面选中内容，Ctrl+A 全选。</p>
</div>
`,
        data() {
            return {
                input: DEFAULT_URL,
                realUrl: DEFAULT_URL,
                textInput: '',
                hint: '',
                urlTimer: null,
                lastWheel: 0,
                viewW: VIEW_W,
                viewH: VIEW_H,
                ro: null,
            };
        },
        created() {
            this.input = DEFAULT_URL;
            this._latest = null; // 最新解码位图
            this._drawn = null; // 画布上已绘制的位图
            this._lastBmp = null; // 上一帧位图（用于释放）
            this.ws = null;
            this._hidden = false;
        },
        mounted() {
            this.doResize(); // 同步判定可见性：面板隐藏时不连画面，免无谓拉起引擎
            this.ro = new ResizeObserver(() => {
                clearTimeout(this._rsT);
                this._rsT = setTimeout(this.doResize, 150);
            });
            if (this.$refs.viewport) this.ro.observe(this.$refs.viewport);
            if (this.enabled) this.startEngineView();
        },
        beforeUnmount() {
            if (this.urlTimer) clearInterval(this.urlTimer);
            if (this.ro) this.ro.disconnect();
            clearTimeout(this._rsT);
            this._closed = true;
            if (this._rafId) cancelAnimationFrame(this._rafId);
            try { this.ws && this.ws.close(); } catch (e) { /* 静默 */ }
        },
        watch: {
            enabled(on) {
                if (on) this.startEngineView();
                else this.stopEngineView();
            },
        },
        methods: {
            // ---------- 画面：WS 接帧 + rAF 绘制 ----------
            startEngineView() {
                this._closed = false;
                this.hint = '引擎启动中…';
                if (!this.urlTimer) this.urlTimer = setInterval(this.syncUrl, 1500);
                this.doResize();
                if (!this._hidden) this.connectWs();
                if (!this._rafId) this.drawLoop();
            },
            stopEngineView() {
                this._closed = true;
                this.hint = 'AI Safety HOT 已关闭';
                if (this.urlTimer) clearInterval(this.urlTimer);
                this.urlTimer = null;
                if (this._rafId) cancelAnimationFrame(this._rafId);
                this._rafId = null;
                try { this.ws && this.ws.close(); } catch (e) { /* 静默 */ }
                this.ws = null;
                for (const bmp of[this._latest, this._drawn, this._lastBmp]) {
                    if (bmp && bmp.close) bmp.close();
                }
                this._latest = this._drawn = this._lastBmp = null;
                const canvas = this.$refs.streamCanvas;
                if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
            },
            connectWs() {
                if (!this.enabled || this._closed || this._hidden) return;
                try { this.ws && this.ws.close(); } catch (e) { /* 静默 */ }
                const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
                this.ws = new WebSocket(proto + location.host + '/api/engine/ws');
                this.ws.binaryType = 'blob';
                this.ws.onmessage = (e) => {
                    e.data.arrayBuffer().then((buf) => {
                        createImageBitmap(new Blob([buf], { type: 'image/png' }))
                            .then((bmp) => {
                                if (this._latest && this._latest.close) this._latest.close();
                                this._latest = bmp;
                                this.hint = ''; // 收到首帧才清提示（引擎冷启动期间保持可见）
                            })
                            .catch(() => { /* 坏帧丢弃 */ });
                    });
                };
                this.ws.onclose = () => {
                    if (this._closed || this._hidden) return;
                    this.hint = this.hint || '画面连接断开，重连中…';
                    setTimeout(() => this.connectWs(), 1500);
                };
                this.ws.onerror = () => {
                    try { this.ws.close(); } catch (e) { /* 静默 */ }
                };
            },
            drawLoop() {
                if (!this.enabled || this._closed) {
                    this._rafId = null;
                    return;
                }
                this._rafId = requestAnimationFrame(this.drawLoop);
                const bmp = this._latest;
                if (!bmp || bmp === this._drawn) return;
                const cv = this.$refs.streamCanvas;
                if (!cv) return;
                if (cv.width !== bmp.width) cv.width = bmp.width;
                if (cv.height !== bmp.height) cv.height = bmp.height;
                cv.getContext('2d').drawImage(bmp, 0, 0);
                this._drawn = bmp;
                if (this._lastBmp && this._lastBmp.close) this._lastBmp.close();
                this._lastBmp = bmp;
            },
            // ---------- 通用 ----------
            normalize(u) {
                u = (u || '').trim();
                if (!u) return '';
                if (!/^https?:\/\//i.test(u)) u = 'https://' + u;
                return u;
            },
            async post(path, body) {
                try {
                    const r = await fetch('/api/engine/' + path, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body || {}),
                    });
                    return await r.json();
                } catch (e) {
                    return { ok: false, error: String(e) };
                }
            },
            applyUrl(u) {
                if (!u) return;
                this.realUrl = u;
                if (document.activeElement !== this.$el.querySelector('.hot-url')) {
                    this.input = u;
                }
            },
            async syncUrl() {
                if (!this.enabled) {
                    this._hidden = false;
                    this.hint = 'AI Safety HOT 已关闭';
                    return;
                }
                try {
                    const r = await fetch('/api/engine/url');
                    const j = await r.json();
                    if (j.url) this.applyUrl(j.url);
                } catch (e) { /* 服务暂不可达，静默 */ }
            },
            // ---------- 导航 ----------
            async go() {
                const u = this.normalize(this.input);
                if (!u) return;
                this.hint = '打开中…';
                const j = await this.post('nav', { url: u });
                if (j.url) this.applyUrl(j.url);
                this.hint = j.ok ? '' : ('打开失败：' + (j.error || ''));
            },
            async back() {
                const j = await this.post('back');
                this.applyUrl(j.url);
            },
            async forward() {
                const j = await this.post('forward');
                this.applyUrl(j.url);
            },
            async reload() {
                this.hint = '刷新中…';
                const j = await this.post('reload');
                this.applyUrl(j.url);
                this.hint = '';
            },
            openExternal() {
                const u = this.normalize(this.input) || this.realUrl;
                if (u) window.open(u, '_blank', 'noopener');
            },
            // ---------- 视口自适应 ----------
            doResize() {
                const rect = this.$refs.viewport.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 50) {
                    // 面板隐藏：断开画面连接，让服务端闲置回收浏览器释放内存
                    this._hidden = true;
                    try { this.ws && this.ws.close(); } catch (e) { /* 静默 */ }
                    return;
                }
                if (!this.enabled) return;
                if (this._hidden) {
                    // 切回面板：重连画面（引擎若已回收会按需拉起）
                    this._hidden = false;
                    this.hint = this.hint || '引擎启动中…';
                    this.connectWs();
                }
                const w = Math.round(rect.width),
                    h = Math.round(rect.height);
                this.viewW = w;
                this.viewH = h;
                this.post('resize', { width: w, height: h, dpr: window.devicePixelRatio || 1 });
            },
            // ---------- 交互 ----------
            async onClick(e) {
                const rect = this.$refs.viewport.getBoundingClientRect();
                if (rect.width < 2 || rect.height < 2) return;
                // 视口已与盒子 1:1 对齐，按比例直接映射
                const x = (e.clientX - rect.left) * this.viewW / rect.width;
                const y = (e.clientY - rect.top) * this.viewH / rect.height;
                await this.post('click', { x: x, y: y });
                this.$el.querySelector('.hot-capture').focus();
            },
            async onWheel(e) {
                const now = Date.now();
                if (now - this.lastWheel < 60) return;
                this.lastWheel = now;
                await this.post('scroll', { dy: e.deltaY });
            },
            async onKey(e) {
                // 输入法 composition 期间（keyCode 229）不转发，中文由输入条处理
                if (e.isComposing || e.keyCode === 229) return;
                if (e.ctrlKey || e.metaKey) {
                    const k = (e.key || '').toLowerCase();
                    if (k === 'c' || k === 'x') {
                        e.preventDefault();
                        await this.copySelection();
                        if (k === 'x') await this.post('key', { key: 'Control+x' });
                        return;
                    }
                    if (k === 'v') {
                        e.preventDefault();
                        await this.pasteClipboard();
                        return;
                    }
                    if (k === 'a') {
                        e.preventDefault();
                        await this.post('key', { key: 'Control+a' });
                        return;
                    }
                    return;
                }
                const nav = ['Enter', 'Backspace', 'Tab', 'Escape', 'Delete',
                    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                    'Home', 'End', 'PageUp', 'PageDown'
                ];
                if (e.key.length === 1 || nav.indexOf(e.key) >= 0) {
                    e.preventDefault();
                    await this.post('key', { key: e.key });
                }
            },
            // ---------- 中文 / 剪贴板 ----------
            async sendText() {
                const t = this.textInput;
                if (!t) return;
                const j = await this.post('text', { text: t });
                if (j.ok) {
                    this.textInput = '';
                    this.hint = '';
                } else {
                    this.hint = '送入失败：' + (j.error || '');
                }
                this.$el.querySelector('.hot-capture').focus();
            },
            async copySelection() {
                try {
                    const r = await fetch('/api/engine/selection');
                    const j = await r.json();
                    const t = j.text || '';
                    if (!t) {
                        this.hint = '没有选中内容';
                        return;
                    }
                    await navigator.clipboard.writeText(t);
                    this.hint = '已复制 ' + t.length + ' 个字符';
                } catch (e) {
                    this.hint = '复制失败：' + e;
                }
            },
            async pasteClipboard() {
                try {
                    const t = await navigator.clipboard.readText();
                    if (!t) {
                        this.hint = '剪贴板没有文本';
                        return;
                    }
                    const j = await this.post('text', { text: t });
                    this.hint = j.ok ? ('已粘贴 ' + t.length + ' 个字符') : '粘贴失败';
                } catch (e) {
                    this.hint = '无法读取剪贴板，请用「页面输入」条粘贴';
                    const el = this.$el.querySelector('.hot-textin');
                    if (el) el.focus();
                }
            },
        },
    };
})();