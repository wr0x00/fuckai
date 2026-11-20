/* AI Safety HOT embedded browser panel — English version
 *
 * Real Chromium (Blink) headless engine: a Playwright-driven browser renders
 * pages server-side; frames stream over the /api/engine/ws WebSocket as binary
 * messages and are drawn on a <canvas> at display refresh rate (latest-wins:
 * new frames always replace old ones, vsync-aligned, no decode queuing).
 * Clicks / wheel / keys / address-bar navigation are forwarded to the engine.
 *
 * CJK text & clipboard: host IME composition events can't travel through keydown,
 * so non-ASCII typing / paste goes through the text bar below (a native input;
 * on Enter the whole string is injected via CDP insertText). Ctrl+C / Ctrl+X
 * pull the engine-side selection back into the host clipboard.
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
    <button class="hot-btn" @click="back" title="Back">&#8249;</button>
    <button class="hot-btn" @click="forward" title="Forward">&#8250;</button>
    <button class="hot-btn" @click="reload" title="Reload">&#10227;</button>
    <input class="input hot-url mono" v-model="input" @keyup.enter="go"
           spellcheck="false" placeholder="Type a URL and press Enter">
    <button class="btn btn-primary btn-sm" @click="go">Go</button>
    <button class="btn btn-ghost btn-sm" @click="openExternal" title="Open the original URL in your system browser">New tab</button>
  </div>
  <div class="hot-inputrow">
    <span class="hot-inputlabel">Page input</span>
    <input class="input hot-textin mono" v-model="textInput" @keyup.enter="sendText"
           spellcheck="false" placeholder="Click an input on the picture first, then type (incl. CJK) or paste here, press Enter to send">
    <button class="btn btn-ghost btn-sm" @click="sendText">Send</button>
  </div>
  <div class="hot-frame-wrap" ref="viewport">
    <canvas class="hot-stream" ref="streamCanvas"></canvas>
    <div class="hot-capture" tabindex="0"
         @click="onClick" @wheel.prevent="onWheel" @keydown="onKey"></div>
    <div class="hot-status" v-if="hint">{{ hint }}</div>
  </div>
  <p class="muted hot-note">Rendered by a real Chromium (Blink) engine; WebSocket + canvas at display refresh rate. Clicks / wheel / keys are forwarded to the engine. Use the "Page input" bar above for CJK typing and Ctrl+V; Ctrl+C / Ctrl+X copy the selection in the picture, Ctrl+A selects all.</p>
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
            this._latest = null; // newest decoded bitmap
            this._drawn = null; // bitmap currently on the canvas
            this._lastBmp = null; // previous bitmap (for release)
            this.ws = null;
            this._hidden = false;
        },
        mounted() {
            this.doResize(); // sync visibility check: skip stream+engine boot when hidden
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
            try { this.ws && this.ws.close(); } catch (e) { /* silent */ }
        },
        watch: {
            enabled(on) {
                if (on) this.startEngineView();
                else this.stopEngineView();
            },
        },
        methods: {
            // ---------- picture: WS frames + rAF drawing ----------
            startEngineView() {
                this._closed = false;
                this.hint = 'Starting engine…';
                if (!this.urlTimer) this.urlTimer = setInterval(this.syncUrl, 1500);
                this.doResize();
                if (!this._hidden) this.connectWs();
                if (!this._rafId) this.drawLoop();
            },
            stopEngineView() {
                this._closed = true;
                this.hint = 'AI Safety HOT is disabled';
                if (this.urlTimer) clearInterval(this.urlTimer);
                this.urlTimer = null;
                if (this._rafId) cancelAnimationFrame(this._rafId);
                this._rafId = null;
                try { this.ws && this.ws.close(); } catch (e) { /* silent */ }
                this.ws = null;
                for (const bmp of [this._latest, this._drawn, this._lastBmp]) {
                    if (bmp && bmp.close) bmp.close();
                }
                this._latest = this._drawn = this._lastBmp = null;
                const canvas = this.$refs.streamCanvas;
                if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
            },
            connectWs() {
                if (!this.enabled || this._closed || this._hidden) return;
                try { this.ws && this.ws.close(); } catch (e) { /* silent */ }
                const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
                this.ws = new WebSocket(proto + location.host + '/api/engine/ws');
                this.ws.binaryType = 'blob';
                this.ws.onmessage = (e) => {
                    e.data.arrayBuffer().then((buf) => {
                        createImageBitmap(new Blob([buf], { type: 'image/png' }))
                            .then((bmp) => {
                                if (this._latest && this._latest.close) this._latest.close();
                                this._latest = bmp;
                                this.hint = ''; // clear only when the first frame arrives (keep visible during cold boot)
                            })
                            .catch(() => { /* drop bad frame */ });
                    });
                };
                this.ws.onclose = () => {
                    if (this._closed || this._hidden) return;
                    this.hint = this.hint || 'Stream disconnected, reconnecting…';
                    setTimeout(() => this.connectWs(), 1500);
                };
                this.ws.onerror = () => {
                    try { this.ws.close(); } catch (e) { /* silent */ }
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
            // ---------- generic ----------
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
                    this.hint = 'AI Safety HOT is disabled';
                    return;
                }
                try {
                    const r = await fetch('/api/engine/url');
                    const j = await r.json();
                    if (j.url) this.applyUrl(j.url);
                } catch (e) { /* server briefly unreachable, stay quiet */ }
            },
            // ---------- navigation ----------
            async go() {
                const u = this.normalize(this.input);
                if (!u) return;
                this.hint = 'Opening…';
                const j = await this.post('nav', { url: u });
                if (j.url) this.applyUrl(j.url);
                this.hint = j.ok ? '' : ('Failed: ' + (j.error || ''));
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
                this.hint = 'Reloading…';
                const j = await this.post('reload');
                this.applyUrl(j.url);
                this.hint = '';
            },
            openExternal() {
                const u = this.normalize(this.input) || this.realUrl;
                if (u) window.open(u, '_blank', 'noopener');
            },
            // ---------- viewport auto-fit ----------
            doResize() {
                const rect = this.$refs.viewport.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 50) {
                    // panel hidden: drop the stream so the server can idle-reclaim the browser
                    this._hidden = true;
                    try { this.ws && this.ws.close(); } catch (e) { /* silent */ }
                    return;
                }
                if (!this.enabled) return;
                if (this._hidden) {
                    // back on the panel: reconnect (relaunches the engine on demand)
                    this._hidden = false;
                    this.hint = this.hint || 'Starting engine…';
                    this.connectWs();
                }
                const w = Math.round(rect.width),
                    h = Math.round(rect.height);
                this.viewW = w;
                this.viewH = h;
                this.post('resize', { width: w, height: h, dpr: window.devicePixelRatio || 1 });
            },
            // ---------- interaction ----------
            async onClick(e) {
                const rect = this.$refs.viewport.getBoundingClientRect();
                if (rect.width < 2 || rect.height < 2) return;
                // viewport matches the box 1:1, so map proportionally
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
                // Skip IME composition keydowns (keyCode 229); CJK goes via the text bar
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
            // ---------- CJK / clipboard ----------
            async sendText() {
                const t = this.textInput;
                if (!t) return;
                const j = await this.post('text', { text: t });
                if (j.ok) {
                    this.textInput = '';
                    this.hint = '';
                } else {
                    this.hint = 'Send failed: ' + (j.error || '');
                }
                this.$el.querySelector('.hot-capture').focus();
            },
            async copySelection() {
                try {
                    const r = await fetch('/api/engine/selection');
                    const j = await r.json();
                    const t = j.text || '';
                    if (!t) {
                        this.hint = 'Nothing selected';
                        return;
                    }
                    await navigator.clipboard.writeText(t);
                    this.hint = 'Copied ' + t.length + ' chars';
                } catch (e) {
                    this.hint = 'Copy failed: ' + e;
                }
            },
            async pasteClipboard() {
                try {
                    const t = await navigator.clipboard.readText();
                    if (!t) {
                        this.hint = 'Clipboard has no text';
                        return;
                    }
                    const j = await this.post('text', { text: t });
                    this.hint = j.ok ? ('Pasted ' + t.length + ' chars') : 'Paste failed';
                } catch (e) {
                    this.hint = 'Cannot read clipboard — use the "Page input" bar';
                    const el = this.$el.querySelector('.hot-textin');
                    if (el) el.focus();
                }
            },
        },
    };
})();