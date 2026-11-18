/* 通用悬停简介气泡
   用法：给任意元素加 data-tip="简介文本" 即可，
   鼠标悬停时在元素下方（空间不足则上方）显示一个跟随视口的浮层。
   气泡挂在 body 上，避免被卡片/列表的 overflow 裁剪。
*/
(function() {
    let box = null;

    function ensureBox() {
        if (!box) {
            box = document.createElement('div');
            box.className = 'fk-tip';
            box.setAttribute('role', 'tooltip');
            document.body.appendChild(box);
        }
        return box;
    }

    function place(el) {
        const b = ensureBox();
        const r = el.getBoundingClientRect();
        const bw = b.offsetWidth;
        const bh = b.offsetHeight;
        let left = r.left + r.width / 2 - bw / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - bw - 8));
        let top = r.bottom + 8;
        let up = false;
        if (top + bh > window.innerHeight - 8) {
            top = Math.max(8, r.top - bh - 8);
            up = true;
        }
        b.classList.toggle('up', up);
        b.style.left = left + 'px';
        b.style.top = top + 'px';
    }

    function show(el) {
        const text = (el.getAttribute('data-tip') || '').trim();
        if (!text) return;
        const b = ensureBox();
        b.textContent = text;
        b.classList.add('on');
        place(el);
    }

    function hide() {
        if (box) box.classList.remove('on');
    }

    document.addEventListener('mouseover', (e) => {
        const el = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
        if (el) show(el);
    });

    document.addEventListener('mouseout', (e) => {
        const el = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
        if (!el) return;
        const to = e.relatedTarget;
        if (to && el.contains(to)) return;
        hide();
    });

    // 滚动或点击时收起，避免气泡留在原地
    window.addEventListener('scroll', hide, true);
    document.addEventListener('click', hide);
    window.addEventListener('resize', hide);
})();