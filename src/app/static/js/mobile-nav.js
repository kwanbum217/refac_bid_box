/*
 * mobile-nav.js
 *
 * 768px 미만에서 쓰는 왼쪽 서랍(주 메뉴, 챗봇 대화 목록)의 열기/닫기를 맡습니다.
 * CSP 가 script-src 'self' 'nonce-...' 라 인라인 핸들러를 쓸 수 없어 base.html 에서
 * static 경로로 불러옵니다.
 *
 * 토글 버튼은 aria-controls 로 서랍 id 를 가리키고 aria-expanded 로 상태를
 * 알립니다. Esc, 배경 클릭, 닫기 표시가 있는 항목 클릭으로 닫히며, 열릴 때 첫
 * 항목으로 포커스를 옮기고 닫힐 때 토글 버튼으로 되돌립니다.
 */
(function () {
    'use strict';

    var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function setupDrawer(config) {
        var toggle = config.toggle;
        var drawer = config.drawer;
        var overlay = config.overlay;
        if (!toggle || !drawer) {
            return;
        }

        var focusSelector = config.focusSelector || null;
        var closeSelector = config.closeSelector || '[data-mobile-nav-close]';
        var lastFocus = null;

        function isOpen() {
            return drawer.classList.contains('is-open');
        }

        function isDesktop() {
            return window.matchMedia('(min-width: 768px)').matches;
        }

        // 데스크톱 폭에서는 챗봇 대화 목록처럼 계속 보이는 서랍도 있으므로,
        // aria-hidden 은 뷰포트와 열림 상태를 함께 보고 정한다.
        function syncAria() {
            if (isDesktop()) {
                drawer.removeAttribute('aria-hidden');
                return;
            }
            drawer.setAttribute('aria-hidden', isOpen() ? 'false' : 'true');
        }

        function firstItem() {
            if (focusSelector) {
                var preferred = drawer.querySelector(focusSelector);
                if (preferred) {
                    return preferred;
                }
            }
            return drawer.querySelector(FOCUSABLE);
        }

        function open() {
            lastFocus = document.activeElement;
            drawer.classList.add('is-open');
            if (overlay) {
                overlay.classList.add('is-open');
            }
            toggle.setAttribute('aria-expanded', 'true');
            document.body.style.overflow = 'hidden';
            syncAria();
            var target = firstItem();
            if (target) {
                target.focus();
            }
        }

        function close(returnFocus) {
            if (!isOpen()) {
                syncAria();
                return;
            }
            drawer.classList.remove('is-open');
            if (overlay) {
                overlay.classList.remove('is-open');
            }
            toggle.setAttribute('aria-expanded', 'false');
            document.body.style.overflow = '';
            syncAria();
            if (returnFocus !== false) {
                var target = lastFocus && typeof lastFocus.focus === 'function' ? lastFocus : toggle;
                target.focus();
            }
        }

        toggle.addEventListener('click', function (event) {
            event.preventDefault();
            if (isOpen()) {
                close();
            } else {
                open();
            }
        });

        if (overlay) {
            overlay.addEventListener('click', function () {
                close();
            });
        }

        drawer.querySelectorAll(closeSelector).forEach(function (item) {
            item.addEventListener('click', function () {
                close(false);
            });
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && isOpen()) {
                close();
            }
        });

        // 768px 이상으로 넓어지면 열린 서랍 상태를 남기지 않는다.
        var desktopQuery = window.matchMedia('(min-width: 768px)');

        function handleDesktop(event) {
            if (event.matches) {
                close(false);
            }
            syncAria();
        }

        if (typeof desktopQuery.addEventListener === 'function') {
            desktopQuery.addEventListener('change', handleDesktop);
        } else if (typeof desktopQuery.addListener === 'function') {
            desktopQuery.addListener(handleDesktop);
        }

        syncAria();
    }

    document.addEventListener('DOMContentLoaded', function () {
        setupDrawer({
            toggle: document.querySelector('[data-mobile-nav-toggle]'),
            drawer: document.getElementById('mobile-nav-drawer'),
            overlay: document.getElementById('mobile-nav-overlay'),
            focusSelector: '[data-mobile-nav-link]',
            closeSelector: '[data-mobile-nav-close]',
        });
        setupDrawer({
            toggle: document.querySelector('[data-chat-sessions-toggle]'),
            drawer: document.getElementById('chat-sessions-panel'),
            overlay: document.getElementById('chat-sessions-overlay'),
            focusSelector: '.session-item-li',
            closeSelector: '.session-item-li',
        });
    });
})();
