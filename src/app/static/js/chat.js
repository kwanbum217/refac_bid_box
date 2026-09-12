$(document).ready(function() {
    const chatContainer = $('#chat-messages');
    const input = $('#chat-input');
    const btnSend = $('#btn-send');
    const btnStop = $('#btn-stop');
    const interface = $('#chat-interface');
    const welcomeState = $('#welcome-state');
    const jobPollers = new Map();
    let activeChatRequest = null;
    let activeLoadingId = '';
    let requestStoppedByUser = false;

    const CONFIG = {
        chatUrl: interface.data('chat-url'),
        // streamUrl 의 final 이벤트는 chatUrl 응답과 같은 ChatResponse 입니다.
        // 플래너, 자동화 확인, 차트 페이로드, 세션 저장이 모두 실려 오므로
        // 렌더링은 handleBotPayload 하나로 통일합니다. 토큰은 체감 속도용입니다.
        streamUrl: interface.data('stream-url'),
        newSessionUrl: interface.data('new-session-url'),
        csrfToken: interface.data('csrf-token'),
        confirmUrlTemplate: interface.data('confirm-url-template') || '',
        statusUrlTemplate: interface.data('status-url-template') || '',
        cancelUrlTemplate: interface.data('cancel-url-template') || '',
        chatPageUrl: interface.data('chat-page-url') || ''
    };

    marked.setOptions({ breaks: true, gfm: true });

    function getAppSettings() {
        if (window.BIDBOX_SETTINGS && typeof window.BIDBOX_SETTINGS.get === 'function') {
            return window.BIDBOX_SETTINGS.get();
        }
        return {
            showSources: true,
            pollIntervalMs: 5000,
        };
    }

    function resolvePollDelay(fallbackDelay) {
        const configuredDelay = Number(getAppSettings().pollIntervalMs);
        if (Number.isFinite(configuredDelay) && configuredDelay > 0) {
            return configuredDelay;
        }
        return fallbackDelay;
    }

    function setAndSend(text) {
        input.val(text);
        sendMessage();
    }
    window.setAndSend = setAndSend;

    function toggleWelcome(show) {
        if (show) {
            welcomeState.show();
        } else {
            welcomeState.hide();
        }
    }

    function clearConversation() {
        chatContainer.children().not('#welcome-state').remove();
        if (jobPollers && typeof jobPollers.forEach === 'function') {
            jobPollers.forEach(entry => {
                if (entry && entry.timer) {
                    window.clearTimeout(entry.timer);
                }
            });
            jobPollers.clear();
        }
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function buildEndpointUrl(template, jobId) {
        return template.replace('__JOB_ID__', encodeURIComponent(jobId));
    }

    function buildChartCanvas(visualization) {
        return `
            <canvas
                class="chat-chart"
                data-type="${escapeHtml(visualization.chart_type || 'bar')}"
                data-labels='${escapeHtml(JSON.stringify(visualization.labels || []))}'
                data-values='${escapeHtml(JSON.stringify(visualization.values || []))}'
                data-title="${escapeHtml(visualization.title || 'Analysis')}"
                data-unit="${escapeHtml(visualization.unit || '')}"
                data-x-label="${escapeHtml(visualization.x_label || '')}"
                data-y-label="${escapeHtml(visualization.y_label || '')}">
            </canvas>
        `;
    }

    function containsRenderedHtml(value) {
        return /<\s*(canvas|div|button|a|table|ul|ol|li|p|span|section)\b/i.test(String(value || ''));
    }

    function normalizePlainBotMarkdown(value) {
        const raw = String(value ?? '').trim();
        if (!raw || containsRenderedHtml(raw)) {
            return raw;
        }
        if (raw.length < 120 || /\n\s*\n|^\s*(#{1,6}\s|[-*]\s|\d+\.\s)/m.test(raw)) {
            return raw;
        }

        return raw
            .replace(/(\[[\d,\s]+\]\.?)\s+(?=[가-힣A-Za-z0-9])/g, '$1\n\n')
            .replace(/((?:입니다|합니다|됩니다|있습니다|없습니다|했습니다|였습니다|같습니다|권장합니다|필요합니다)(?:\s*\[[\d,\s]+\])?\.?)\s+(?=[가-힣A-Za-z0-9])/g, '$1\n\n')
            .replace(/\n{3,}/g, '\n\n');
    }

    function getSourceCitationNumber(item) {
        const metadata = item && item.metadata ? item.metadata : {};
        const value = metadata.citation_number ?? metadata.citationNumber ?? item?.citation_number;
        const numberValue = Number(value);
        return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
    }

    function formatSourceTag(item) {
        const sourceId = item && item.id ? item.id : 'source';
        const citationNumber = getSourceCitationNumber(item);
        const citationLabel = citationNumber ? `<span class="source-tag-index">[${citationNumber}]</span>` : '';
        const role = item?.metadata?.citation_role || item?.type || '';
        return `
            <span class="source-tag" title="${escapeHtml(role)}">
                ${citationLabel}
                <span>${escapeHtml(sourceId)}</span>
            </span>
        `;
    }

    function stopJobPolling(jobId) {
        const timer = jobPollers.get(jobId);
        if (timer && timer.timer) {
            window.clearTimeout(timer.timer);
            jobPollers.delete(jobId);
        }
    }

    function setRequestBusy(isBusy) {
        btnSend.prop('disabled', isBusy);
        btnStop.toggleClass('is-active', isBusy).prop('disabled', !isBusy);
        input.prop('disabled', isBusy);
    }

    function stopActiveChatRequest() {
        requestStoppedByUser = true;
        if (activeChatRequest && typeof activeChatRequest.abort === 'function') {
            activeChatRequest.abort();
        }
        if (activeLoadingId) {
            $(`#${activeLoadingId}`).remove();
        }
        activeChatRequest = null;
        activeLoadingId = '';
        setRequestBusy(false);
        appendMessage(
            'bot',
            '요청을 중지했습니다. 이미 자동화 실행이 시작된 경우에는 해당 실행 카드의 `실행 중지` 버튼을 사용하세요.'
        );
    }

    function scheduleJobPolling(jobId, pollFn, delayMs) {
        stopJobPolling(jobId);
        const timer = window.setTimeout(pollFn, delayMs);
        jobPollers.set(jobId, { timer, pollFn });
    }

    function formatStatusBadge(status) {
        const map = {
            pending_confirmation: { label: 'Confirmation', classes: 'border-amber-200 bg-amber-50 text-amber-700' },
            queued: { label: 'Queued', classes: 'border-slate-200 bg-slate-100 text-slate-600' },
            running: { label: 'Running', classes: 'border-blue-200 bg-blue-50 text-blue-700' },
            success: { label: 'Completed', classes: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
            failed: { label: 'Failed', classes: 'border-red-200 bg-red-50 text-red-700' },
            canceled: { label: 'Canceled', classes: 'border-slate-200 bg-slate-100 text-slate-600' }
        };
        return map[status] || { label: 'Active', classes: 'border-slate-200 bg-slate-100 text-slate-600' };
    }

    function buildAutomationCard(job, options = {}) {
        if (!job || !job.job_id) {
            return '';
        }

        const badge = formatStatusBadge(job.status);
        const callbackMode = job.callback_mode === 'callback' ? 'Callback' : 'Polling';
        const detailRows = [
            { label: 'Job ID', value: job.job_id },
            { label: 'Action', value: job.action_key || '-' },
            { label: 'Run Mode', value: job.run_mode || '-' },
            { label: 'Pipeline', value: job.pipeline || job.pipeline_id || '-' },
            { label: 'Delivery', value: callbackMode },
        ];

        if (job.plan_execution_id) {
            detailRows.push({ label: 'Execution', value: job.plan_execution_id });
        }
        if (job.stage_name || job.stage_status) {
            detailRows.push({
                label: 'Stage',
                value: `${job.stage_name || '-'} / ${job.stage_status || '-'}`
            });
        }
        if (job.result_summary) {
            detailRows.push({ label: 'Summary', value: job.result_summary });
        }

        const detailsHtml = detailRows.map((row) => `
            <div class="flex items-center justify-between gap-4 text-[11px]">
                <span class="font-bold uppercase tracking-[0.14em] text-slate-400">${escapeHtml(row.label)}</span>
                <span class="max-w-[70%] break-words text-right font-semibold text-slate-700">${escapeHtml(row.value)}</span>
            </div>
        `).join('');

        const canCancel = ['pending_confirmation', 'queued', 'running'].includes(job.status);
        const cancelButtonHtml = canCancel ? `
            <button
                class="cancel-automation-btn inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-xs font-bold text-red-700 transition-colors hover:bg-red-100"
                data-job-id="${escapeHtml(job.job_id)}">
                실행 중지
                <i class="fas fa-stop text-[10px]"></i>
            </button>
        ` : '';
        const consoleLinkHtml = job.execution_url ? `
            <a
                class="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 transition-colors hover:border-primary hover:text-primary"
                href="${escapeHtml(job.execution_url)}"
                target="_blank"
                rel="noreferrer">
                실행 콘솔 열기
                <i class="fas fa-arrow-up-right-from-square text-[10px]"></i>
            </a>
        ` : '';
        const actionHtml = options.confirmationToken ? `
            <div class="mt-4 flex flex-wrap items-center gap-2">
                <button
                    class="confirm-automation-btn inline-flex items-center gap-2 rounded-lg bg-amber-500 px-4 py-2 text-xs font-bold text-white shadow-sm transition-colors hover:bg-amber-600"
                    data-job-id="${escapeHtml(job.job_id)}"
                    data-confirmation-token="${escapeHtml(options.confirmationToken)}">
                    승인 후 실행
                    <i class="fas fa-shield-halved text-[10px]"></i>
                </button>
                ${cancelButtonHtml}
            </div>
        ` : (cancelButtonHtml || consoleLinkHtml) ? `
            <div class="mt-4 flex flex-wrap items-center gap-2">
                ${cancelButtonHtml}
                ${consoleLinkHtml}
            </div>
        ` : '';

        const helperText = options.confirmationToken
            ? '고비용 자동화이므로 최종 승인 후 실행됩니다.'
            : job.status === 'failed'
                ? '실행 요청 또는 파이프라인 처리 중 오류가 발생했습니다. 오류 메시지와 실행 콘솔을 확인하세요.'
            : job.status === 'canceled'
                ? '사용자 요청으로 대화 상태와 자동 상태 확인을 중지했습니다.'
            : options.live
                ? '백엔드 상태를 주기적으로 확인해 완료 시 결과를 이어서 보여줍니다.'
                : '자동화 상태가 업데이트되면 같은 대화 흐름에서 이어서 확인할 수 있습니다.';

        const errorHtml = job.error_message ? `
            <div class="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold leading-5 text-red-700">
                ${escapeHtml(job.error_message)}
            </div>
        ` : '';

        return `
            <div class="automation-card mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div class="flex items-center justify-between gap-3">
                    <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-400">Automation Control</p>
                    <span class="inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${badge.classes}">
                        ${escapeHtml(badge.label)}
                    </span>
                </div>
                <div class="mt-4 space-y-2">
                    ${detailsHtml}
                </div>
                <p class="mt-4 text-xs leading-5 text-slate-500">${escapeHtml(helperText)}</p>
                ${errorHtml}
                ${actionHtml}
            </div>
        `;
    }

    function scrollChatToBottom() {
        const container = chatContainer[0];
        if (!container) {
            return;
        }
        container.scrollTo({
            top: container.scrollHeight,
            behavior: 'smooth',
        });
    }

    function scrollChatToMessageStart(messageElement) {
        const container = chatContainer[0];
        if (!container || !messageElement) {
            return;
        }
        const containerRect = container.getBoundingClientRect();
        const messageRect = messageElement.getBoundingClientRect();
        const top = container.scrollTop + (messageRect.top - containerRect.top) - 24;
        container.scrollTo({
            top: Math.max(top, 0),
            behavior: 'smooth',
        });
    }

    function appendMessage(role, text, provenance = null, advisory_signals = null, options = {}) {
        toggleWelcome(false);
        const isBot = role === 'bot' || role === 'model';
        let formattedText = String(text ?? '');
        const extraHtml = isBot ? String(options.extraHtml || '') : '';
        const contentClass = isBot ? 'bot-msg-content' : 'user-msg-content';
        const scrollMode = options.scrollMode || (isBot ? 'start' : 'bottom');

        if (isBot) {
            formattedText = formattedText.replace(/```html/gi, '').replace(/```/g, '');
            formattedText = normalizePlainBotMarkdown(formattedText);
            formattedText = formattedText.replace(/\[(\d+)\]/g, '<span class="citation-badge" title="Source #$1">$1</span>');
            formattedText = marked.parse(formattedText);
        } else {
            formattedText = escapeHtml(formattedText).replace(/\n/g, '<br>');
        }

        const botIcon = `<div class="w-9 h-9 rounded bg-primary flex items-center justify-center shadow-lg shadow-primary/20 flex-shrink-0"><i class="fas fa-robot text-white text-sm"></i></div>`;
        const userInitial = interface.data('user-initial') || '';
        const userIcon = `<div class="w-9 h-9 rounded bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-slate-700 dark:text-slate-300 font-bold text-xs flex-shrink-0">${userInitial}</div>`;

        let sourceHtml = '';
        if (provenance && provenance.items && provenance.items.length > 0) {
            const tags = provenance.items.map(formatSourceTag).join(' ');
            sourceHtml = `<div class="message-source-block mt-4 flex flex-wrap gap-2 border-t border-slate-100 dark:border-slate-800 pt-4">${tags}</div>`;
        }

        let advisoryHtml = '';
        if (advisory_signals && advisory_signals.length > 0) {
            advisoryHtml = advisory_signals.map(sig => `
                <div class="advisory-card-premium p-4 rounded-lg mt-4 flex items-start gap-3">
                    <i class="fas fa-info-circle text-primary mt-1"></i>
                    <div>
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Expert Advisor Note</p>
                        <p class="text-xs text-slate-700 dark:text-slate-300 font-semibold">${escapeHtml(sig.message)}</p>
                    </div>
                </div>
            `).join('');
        }

        const bubbleClass = isBot
            ? 'bg-white dark:bg-slate-900 border border-harness-border dark:border-slate-800 text-slate-700 dark:text-slate-300'
            : 'bg-primary text-white border border-primary-hover';

        const html = `
            <div class="flex ${isBot ? 'justify-start' : 'justify-end'} animate-in fade-in slide-in-from-bottom-2 duration-300">
                <div class="flex ${isBot ? 'flex-row' : 'flex-row-reverse'} items-start gap-4 max-w-[85%]">
                    ${isBot ? botIcon : userIcon}
                    <div class="flex flex-col ${isBot ? 'items-start' : 'items-end'}">
                        <div class="px-5 py-4 ${bubbleClass} chat-bubble-custom shadow-sm">
                            <div class="${contentClass}">${formattedText}</div>
                            ${extraHtml}
                            ${advisoryHtml}
                            ${sourceHtml}
                        </div>
                        <span class="text-[9px] font-bold text-slate-400 mt-2 px-1">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                </div>
            </div>
        `;
        chatContainer.append(html);
        const appendedMessage = chatContainer.children().last()[0];
        window.requestAnimationFrame(() => {
            if (scrollMode === 'none') {
                return;
            }
            if (scrollMode === 'start') {
                scrollChatToMessageStart(appendedMessage);
                return;
            }
            scrollChatToBottom();
        });
        renderCharts();
    }

    function parseChartArray(rawValue) {
        if (!rawValue) return [];
        try {
            const parsed = JSON.parse(rawValue);
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return String(rawValue).split(',');
        }
    }

    function normalizeChartSeries(labels, values) {
        const normalized = [];
        values.forEach((value, index) => {
            const numericValue = Number(String(value).replace(/[,%원\s]/g, ''));
            if (!Number.isFinite(numericValue)) {
                return;
            }
            normalized.push({
                label: String(labels[index] || `#${index + 1}`),
                value: numericValue,
            });
        });
        return normalized;
    }

    function compactChartLabel(value, maxLength = 14) {
        const text = String(value || '');
        if (text.length <= maxLength) {
            return text;
        }
        return `${text.slice(0, maxLength - 3)}...`;
    }

    function formatChartValue(value) {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue)) {
            return '-';
        }
        const rounded = Math.abs(numericValue) >= 100 ? Math.round(numericValue) : Math.round(numericValue * 10) / 10;
        return rounded.toLocaleString('ko-KR');
    }

    function inferChartUnit(title, explicitUnit = '') {
        const unit = String(explicitUnit || '').trim();
        if (unit) {
            return unit;
        }
        const normalizedTitle = String(title || '').toLowerCase();
        if (/(낙찰률|진행도|비율|rate|percent|r2)/i.test(normalizedTitle)) {
            return '%';
        }
        if (/(시간|소요|duration|분)/i.test(normalizedTitle)) {
            return '분';
        }
        if (/(금액|가격|예산|amount|price|원)/i.test(normalizedTitle)) {
            return '원';
        }
        if (/(건수|현황|공고|문서|결과|count|rows)/i.test(normalizedTitle)) {
            return '건';
        }
        return '';
    }

    function inferXAxisLabel(labels, chartType, explicitLabel = '') {
        const label = String(explicitLabel || '').trim();
        if (label) {
            return label;
        }
        const looksLikePeriod = labels.some((item) => /^\d{4}[-./]\d{1,2}/.test(String(item || '')));
        if (chartType === 'line' || looksLikePeriod) {
            return '기간';
        }
        return '항목';
    }

    function inferYAxisLabel(title, unit, explicitLabel = '') {
        const label = String(explicitLabel || '').trim();
        if (label) {
            return label;
        }
        const normalizedTitle = String(title || '').trim();
        let metric = '값';
        if (/낙찰률|rate/i.test(normalizedTitle)) {
            metric = '낙찰률';
        } else if (/진행도/i.test(normalizedTitle)) {
            metric = '진행도';
        } else if (/시간|소요|duration/i.test(normalizedTitle)) {
            metric = '소요 시간';
        } else if (/금액|가격|예산|amount|price/i.test(normalizedTitle)) {
            metric = '금액';
        } else if (/문서/i.test(normalizedTitle)) {
            metric = '문서 수';
        } else if (/건수|현황|공고|결과|count|rows/i.test(normalizedTitle)) {
            metric = '건수';
        }
        return unit ? `${metric} (${unit})` : metric;
    }

    function formatChartValueWithUnit(value, unit) {
        const formattedValue = formatChartValue(value);
        return unit ? `${formattedValue}${unit}` : formattedValue;
    }

    function resizeChartCard($card, scale) {
        const currentWidth = $card.outerWidth();
        const currentHeight = $card.outerHeight();
        const maxWidth = Math.min(1280, Math.max(340, $(window).width() - 48));
        const nextWidth = Math.max(340, Math.min(Math.round(currentWidth * scale), maxWidth));
        const nextHeight = Math.max(340, Math.min(Math.round(currentHeight * scale), 760));
        $card.css({ width: `${nextWidth}px`, height: `${nextHeight}px` });
        const chart = $card.find('.chat-chart').data('chartInstance');
        if (chart && typeof chart.resize === 'function') {
            window.requestAnimationFrame(() => chart.resize());
        }
    }

    function resetChartCard($card) {
        $card.css({
            width: '',
            height: '',
        });
        const chart = $card.find('.chat-chart').data('chartInstance');
        if (chart && typeof chart.resize === 'function') {
            window.requestAnimationFrame(() => chart.resize());
        }
    }

    function setChartExpanded($card, expanded) {
        $('.chat-chart-card.is-expanded').not($card).each(function() {
            setChartExpanded($(this), false);
        });
        $card.toggleClass('is-expanded', expanded);
        $('body').toggleClass('chart-expanded-open', expanded);
        const $button = $card.find('.chart-zoom-expand');
        $button.toggleClass('is-active', expanded);
        $button.attr('title', expanded ? '확대 닫기' : '화면 확대');
        $button.text(expanded ? '×' : '⛶');
        const chart = $card.find('.chat-chart').data('chartInstance');
        if (chart && typeof chart.resize === 'function') {
            window.requestAnimationFrame(() => chart.resize());
        }
    }

    function observeChartResize($card, chart) {
        if (!window.ResizeObserver || !chart || $card.data('resizeObserved')) {
            return;
        }
        const observer = new ResizeObserver(() => {
            window.requestAnimationFrame(() => chart.resize());
        });
        observer.observe($card[0]);
        $card.data('resizeObserved', true);
        $card.data('resizeObserver', observer);
    }

    function buildChartShell($canvas, title, values) {
        const maxValue = values.length ? Math.max(...values) : 0;
        const unit = inferChartUnit(title, $canvas.attr('data-unit'));
        const summary = values.length ? formatChartValueWithUnit(maxValue, unit) : '-';
        $canvas.wrap('<div class="chat-chart-card mt-6 mb-2"></div>');
        const $card = $canvas.closest('.chat-chart-card');
        $card.prepend(`
            <div class="chat-chart-header">
                <div class="min-w-0">
                    <p class="chat-chart-eyebrow">BIDBOX ANALYTICS</p>
                    <p class="chat-chart-title">${escapeHtml(title)}</p>
                </div>
                <div class="chat-chart-header-actions">
                    <div class="chat-chart-controls" aria-label="차트 크기 조절">
                        <button type="button" class="chat-chart-control-btn chart-zoom-out" title="축소">-</button>
                        <button type="button" class="chat-chart-control-btn chart-zoom-in" title="확대">+</button>
                        <button type="button" class="chat-chart-control-btn chart-zoom-reset" title="크기 초기화">↺</button>
                        <button type="button" class="chat-chart-control-btn chart-zoom-expand" title="화면 확대">⛶</button>
                    </div>
                    <div class="chat-chart-summary">
                        <p class="chat-chart-summary-label">MAX</p>
                        <p class="chat-chart-summary-value">${escapeHtml(summary)}</p>
                    </div>
                </div>
            </div>
        `);
        $card.find('.chart-zoom-out').on('click', () => resizeChartCard($card, 0.86));
        $card.find('.chart-zoom-in').on('click', () => resizeChartCard($card, 1.16));
        $card.find('.chart-zoom-reset').on('click', () => resetChartCard($card));
        $card.find('.chart-zoom-expand').on('click', () => setChartExpanded($card, !$card.hasClass('is-expanded')));
        $canvas.wrap('<div class="chat-chart-body"></div>');
    }

    const CHAT_CHART_BAR_PALETTE = [
        { top: '#2563EB', mid: '#38BDF8', bottom: '#BAE6FD', border: '#1D4ED8' },
        { top: '#059669', mid: '#34D399', bottom: '#BBF7D0', border: '#047857' },
        { top: '#D97706', mid: '#FBBF24', bottom: '#FEF3C7', border: '#B45309' },
        { top: '#7C3AED', mid: '#A78BFA', bottom: '#DDD6FE', border: '#6D28D9' },
        { top: '#E11D48', mid: '#FB7185', bottom: '#FFE4E6', border: '#BE123C' },
        { top: '#0F766E', mid: '#2DD4BF', bottom: '#CCFBF1', border: '#0F766E' },
        { top: '#4F46E5', mid: '#818CF8', bottom: '#E0E7FF', border: '#4338CA' },
        { top: '#475569', mid: '#94A3B8', bottom: '#E2E8F0', border: '#334155' },
    ];

    function hexToRgba(hex, alpha = 1) {
        const normalized = String(hex || '').replace('#', '');
        if (normalized.length !== 6) {
            return `rgba(37, 99, 235, ${alpha})`;
        }
        const value = parseInt(normalized, 16);
        const red = (value >> 16) & 255;
        const green = (value >> 8) & 255;
        const blue = value & 255;
        return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
    }

    function getBarPaletteColor(index) {
        return CHAT_CHART_BAR_PALETTE[index % CHAT_CHART_BAR_PALETTE.length];
    }

    function createBarGradient(ctx, area, index) {
        const color = getBarPaletteColor(index);
        const gradient = ctx.createLinearGradient(0, area.top, 0, area.bottom);
        gradient.addColorStop(0, hexToRgba(color.top, 0.94));
        gradient.addColorStop(0.58, hexToRgba(color.mid, 0.76));
        gradient.addColorStop(1, hexToRgba(color.bottom, 0.72));
        return gradient;
    }

    function createChartGradient(ctx, area, type) {
        const gradient = ctx.createLinearGradient(0, area.top, 0, area.bottom);
        if (type === 'line') {
            gradient.addColorStop(0, 'rgba(0, 115, 230, 0.20)');
            gradient.addColorStop(1, 'rgba(0, 115, 230, 0.02)');
            return gradient;
        }
        gradient.addColorStop(0, 'rgba(37, 99, 235, 0.92)');
        gradient.addColorStop(0.55, 'rgba(14, 165, 233, 0.72)');
        gradient.addColorStop(1, 'rgba(125, 211, 252, 0.62)');
        return gradient;
    }

    const chatChartValueLabelPlugin = {
        id: 'chatChartValueLabel',
        afterDatasetsDraw(chart) {
            const dataset = chart.data.datasets[0];
            if (!dataset || chart.config.type === 'line') {
                return;
            }
            const unit = chart.options.chatChartUnit || '';
            const meta = chart.getDatasetMeta(0);
            const { ctx } = chart;
            ctx.save();
            ctx.font = '700 11px Inter, system-ui, sans-serif';
            ctx.fillStyle = '#334155';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            meta.data.forEach((bar, index) => {
                const y = Math.max(bar.y - 7, chart.chartArea.top + 14);
                ctx.fillText(formatChartValueWithUnit(dataset.data[index], unit), bar.x, y);
            });
            ctx.restore();
        }
    };

    function renderCharts() {
        $('.chat-chart').each(function() {
            if (!$(this).data('rendered')) {
                $(this).data('rendered', true);
                const ctx = this.getContext('2d');
                const requestedType = $(this).attr('data-type') || 'bar';
                const rawLabels = parseChartArray($(this).attr('data-labels'));
                const rawValues = parseChartArray($(this).attr('data-values'));
                const series = normalizeChartSeries(rawLabels, rawValues);
                const labels = series.map((item) => item.label);
                const values = series.map((item) => item.value);
                const type = requestedType === 'line' && values.length < 2 ? 'bar' : requestedType;
                const title = $(this).attr('data-title') || 'Data Analysis';
                const unit = inferChartUnit(title, $(this).attr('data-unit'));
                const xAxisLabel = inferXAxisLabel(labels, type, $(this).attr('data-x-label'));
                const yAxisLabel = inferYAxisLabel(title, unit, $(this).attr('data-y-label'));

                buildChartShell($(this), title, values);

                if (!values.length) {
                    $(this).replaceWith(`
                        <div class="chart-empty-state rounded-lg px-4 py-5 text-center text-xs font-bold">
                            차트로 표시할 수 있는 숫자 데이터가 충분하지 않습니다.
                        </div>
                    `);
                    return;
                }

                const minValue = Math.min(...values);
                const maxValue = Math.max(...values);
                const padding = minValue === maxValue ? Math.max(Math.abs(minValue) * 0.05, 1) : 0;

                const chart = new Chart(ctx, {
                    type: type,
                    data: {
                        labels: labels,
                        datasets: [{
                            label: title,
                            data: values,
                            backgroundColor: (chartContext) => {
                                const area = chartContext.chart.chartArea;
                                if (!area) {
                                    return type === 'line' ? 'rgba(0, 115, 230, 0.12)' : 'rgba(37, 99, 235, 0.78)';
                                }
                                if (type === 'bar') {
                                    return createBarGradient(chartContext.chart.ctx, area, chartContext.dataIndex || 0);
                                }
                                return createChartGradient(chartContext.chart.ctx, area, type);
                            },
                            borderColor: (chartContext) => {
                                if (type === 'line') {
                                    return '#2563EB';
                                }
                                return getBarPaletteColor(chartContext.dataIndex || 0).border;
                            },
                            hoverBackgroundColor: (chartContext) => {
                                if (type === 'line') {
                                    return 'rgba(37, 99, 235, 0.18)';
                                }
                                const color = getBarPaletteColor(chartContext.dataIndex || 0);
                                return hexToRgba(color.top, 0.88);
                            },
                            hoverBorderColor: (chartContext) => {
                                if (type === 'line') {
                                    return '#1D4ED8';
                                }
                                return getBarPaletteColor(chartContext.dataIndex || 0).border;
                            },
                            borderWidth: type === 'line' ? 3 : 1,
                            borderRadius: type === 'bar' ? 8 : 0,
                            borderSkipped: false,
                            maxBarThickness: 72,
                            categoryPercentage: 0.68,
                            barPercentage: 0.82,
                            tension: type === 'line' ? 0.35 : 0,
                            pointRadius: type === 'line' ? 4 : 0,
                            pointHoverRadius: type === 'line' ? 6 : 0,
                            pointBackgroundColor: '#FFFFFF',
                            pointBorderColor: '#2563EB',
                            pointBorderWidth: type === 'line' ? 2.5 : 0,
                            fill: type === 'line',
                            spanGaps: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        chatChartUnit: unit,
                        layout: {
                            padding: { top: type === 'bar' ? 18 : 8, right: 6, bottom: 0, left: 0 }
                        },
                        plugins: {
                            legend: { display: false },
                            title: { display: false },
                            tooltip: {
                                enabled: true,
                                backgroundColor: 'rgba(15, 23, 42, 0.94)',
                                borderColor: 'rgba(148, 163, 184, 0.35)',
                                borderWidth: 1,
                                cornerRadius: 10,
                                displayColors: false,
                                padding: 12,
                                titleColor: '#F8FAFC',
                                bodyColor: '#DBEAFE',
                                titleFont: { size: 12, weight: '800' },
                                bodyFont: { size: 12, weight: '700' },
                                callbacks: {
                                    title: (items) => items[0]?.label || '',
                                    label: (item) => `${title}: ${formatChartValueWithUnit(item.parsed.y, unit)}`
                                }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: type !== 'line',
                                suggestedMin: padding ? minValue - padding : undefined,
                                suggestedMax: padding ? maxValue + padding : undefined,
                                grace: '12%',
                                border: { display: false },
                                grid: {
                                    color: 'rgba(148, 163, 184, 0.16)',
                                    drawTicks: false
                                },
                                ticks: {
                                    color: '#64748B',
                                    font: { size: 10, weight: '700' },
                                    padding: 8,
                                    callback: (value) => formatChartValueWithUnit(value, unit)
                                },
                                title: {
                                    display: true,
                                    text: yAxisLabel,
                                    color: '#334155',
                                    font: { size: 11, weight: '800' },
                                    padding: { top: 0, bottom: 8 }
                                }
                            },
                            x: {
                                border: { display: false },
                                grid: { display: false },
                                ticks: {
                                    color: '#475569',
                                    font: { size: 10, weight: '700' },
                                    maxRotation: 0,
                                    minRotation: 0,
                                    padding: 8,
                                    callback: function(value) {
                                        return compactChartLabel(this.getLabelForValue(value), labels.length > 4 ? 9 : 14);
                                    }
                                },
                                title: {
                                    display: true,
                                    text: xAxisLabel,
                                    color: '#334155',
                                    font: { size: 11, weight: '800' },
                                    padding: { top: 10, bottom: 0 }
                                }
                            }
                        },
                        interaction: {
                            intersect: false,
                            mode: 'index'
                        }
                    },
                    plugins: [chatChartValueLabelPlugin]
                });
                $(this).data('chartInstance', chart);
                observeChartResize($(this).closest('.chat-chart-card'), chart);
            }
        });
    }

    $(document).on('keydown', function(event) {
        if (event.key === 'Escape') {
            const $expandedChart = $('.chat-chart-card.is-expanded').first();
            if ($expandedChart.length) {
                setChartExpanded($expandedChart, false);
            }
        }
    });

    function appendVisualizations(visualizations) {
        if (!Array.isArray(visualizations)) {
            return;
        }
        visualizations.forEach((visualization) => {
            if (visualization.type === 'chart') {
                appendMessage('bot', buildChartCanvas(visualization), null, null, { scrollMode: 'none' });
            }
        });
    }

    function handleBotPayload(data) {
        const answerText = data.answer || data.message || '응답을 받지 못했습니다.';

        if (data.mode === 'confirmation' && data.job) {
            appendMessage(
                'bot',
                answerText,
                data.provenance,
                data.advisory_signals,
                { extraHtml: buildAutomationCard(data.job, { confirmationToken: data.confirmation_token }) }
            );
            return;
        }

        if ((data.mode === 'action' || data.mode === 'progress') && data.job) {
            appendMessage(
                'bot',
                answerText,
                data.provenance,
                data.advisory_signals,
                { extraHtml: buildAutomationCard(data.job, { live: true }) }
            );
            startJobPolling(data.job);
            return;
        }

        if ((data.mode === 'result' || data.mode === 'error') && data.job) {
            stopJobPolling(data.job.job_id);
            appendMessage(
                'bot',
                answerText,
                data.provenance,
                data.advisory_signals,
                { extraHtml: buildAutomationCard(data.job) }
            );
            appendVisualizations(data.visualizations);
            return;
        }

        appendMessage('bot', answerText, data.provenance, data.advisory_signals);
        appendVisualizations(data.visualizations);
    }

    function startJobPolling(job) {
        if (!job || !job.job_id) {
            return;
        }
        if (job.status === 'success' || job.status === 'failed' || job.status === 'canceled' || job.status === 'pending_confirmation') {
            return;
        }

        const pollDelay = resolvePollDelay(Number(job.poll_after_ms) || 5000);
        const pollUrl = buildEndpointUrl(CONFIG.statusUrlTemplate, job.job_id);

        const poll = function() {
            $.ajax({
                url: pollUrl,
                method: 'GET',
                success: function(data) {
                    if (data.status !== 'success') {
                        scheduleJobPolling(job.job_id, poll, resolvePollDelay(pollDelay));
                        return;
                    }

                    if (data.mode === 'result' || data.mode === 'error') {
                        handleBotPayload(data);
                        return;
                    }

                    const nextDelay = resolvePollDelay(Number((data.job || {}).poll_after_ms) || pollDelay);
                    scheduleJobPolling(job.job_id, poll, nextDelay);
                },
                error: function() {
                    scheduleJobPolling(job.job_id, poll, resolvePollDelay(pollDelay));
                }
            });
        };

        scheduleJobPolling(job.job_id, poll, pollDelay);
    }

    window.addEventListener('bidbox:settings-changed', function(event) {
        const nextDelay = Number((event.detail || {}).pollIntervalMs);
        if (!Number.isFinite(nextDelay) || nextDelay <= 0) {
            return;
        }

        jobPollers.forEach(function(entry, jobId) {
            if (!entry || typeof entry.pollFn !== 'function') {
                return;
            }
            window.clearTimeout(entry.timer);
            jobPollers.set(jobId, {
                timer: window.setTimeout(entry.pollFn, nextDelay),
                pollFn: entry.pollFn,
            });
        });
    });

    function sendMessage() {
        const message = input.val().trim();
        if (!message) return;
        if (activeChatRequest) return;

        appendMessage('user', message);
        input.val('');
        requestStoppedByUser = false;
        setRequestBusy(true);

        const loadingId = 'loading-' + Date.now();
        activeLoadingId = loadingId;
        chatContainer.append(`
            <div id="${loadingId}" class="flex justify-start animate-in fade-in duration-300">
                <div class="flex items-start gap-4">
                    <div class="w-9 h-9 rounded bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
                        <span class="loading loading-spinner loading-xs"></span>
                    </div>
                    <div class="px-5 py-4 bg-white dark:bg-slate-900 border border-harness-border dark:border-slate-800 rounded-xl shadow-sm">
                        <div class="flex items-center gap-3">
                            <span class="text-xs font-bold text-slate-500 tracking-widest">AI가 요청을 분석 중입니다</span>
                            <div class="flex gap-1">
                                <div class="typing-dot"></div>
                                <div class="typing-dot"></div>
                                <div class="typing-dot"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `);
        scrollChatToBottom();

        streamMessage(message, loadingId);
    }

    // AbortController 는 jQuery jqXHR 처럼 abort() 를 가지고 있어
    // stopActiveChatRequest 가 그대로 동작합니다.
    function streamMessage(message, loadingId) {
        const controller = new AbortController();
        activeChatRequest = controller;

        const streamId = 'stream-' + Date.now();
        let streamStarted = false;

        function ensureStreamBubble() {
            if (streamStarted) return;
            streamStarted = true;
            $(`#${loadingId}`).remove();
            chatContainer.append(`
                <div id="${streamId}" class="flex justify-start animate-in fade-in duration-300">
                    <div class="flex items-start gap-4">
                        <div class="w-9 h-9 rounded bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
                            <i data-lucide="bot" class="w-5 h-5"></i>
                        </div>
                        <div class="px-5 py-4 bg-white dark:bg-slate-900 border border-harness-border dark:border-slate-800 rounded-xl shadow-sm max-w-3xl">
                            <div class="prose prose-sm max-w-none dark:prose-invert" data-stream-body></div>
                        </div>
                    </div>
                </div>
            `);
            if (window.lucide) { window.lucide.createIcons(); }
        }

        function cleanup() {
            $(`#${loadingId}`).remove();
            $(`#${streamId}`).remove();
            activeChatRequest = null;
            activeLoadingId = '';
            setRequestBusy(false);
        }

        function handleEvent(name, data) {
            if (name === 'stage') {
                $(`#${loadingId}`).find('span.text-xs').text(data.message || 'AI가 요청을 분석 중입니다');
                return;
            }
            if (name === 'token') {
                ensureStreamBubble();
                const body = $(`#${streamId}`).find('[data-stream-body]');
                body.text(body.text() + (data.text || ''));
                scrollChatToBottom();
                return;
            }
            if (name === 'final') {
                cleanup();
                if (data.status === 'success') {
                    handleBotPayload(data);
                } else {
                    appendMessage('bot', '분석 처리 중 오류가 발생했습니다: ' + (data.message || '알 수 없는 오류'));
                }
                return;
            }
            if (name === 'error') {
                cleanup();
                appendMessage('bot', data.message || '응답 생성에 실패했습니다.');
            }
        }

        fetch(CONFIG.streamUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CONFIG.csrfToken },
            body: JSON.stringify({ message: message }),
            signal: controller.signal
        }).then(async function(response) {
            if (!response.ok || !response.body) {
                throw new Error('stream unavailable');
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                // SSE 는 빈 줄로 이벤트를 구분합니다. 마지막 조각은 미완성일 수
                // 있으므로 버퍼에 남겨 다음 청크와 이어붙입니다.
                let boundary = buffer.indexOf('\n\n');
                while (boundary !== -1) {
                    const chunk = buffer.slice(0, boundary);
                    buffer = buffer.slice(boundary + 2);
                    let name = 'message';
                    const dataLines = [];
                    chunk.split('\n').forEach(function(line) {
                        if (line.startsWith('event:')) {
                            name = line.slice(6).trim();
                        } else if (line.startsWith('data:')) {
                            dataLines.push(line.slice(5).trim());
                        }
                    });
                    if (dataLines.length > 0) {
                        try {
                            handleEvent(name, JSON.parse(dataLines.join('\n')));
                        } catch (err) {
                            console.error('SSE 파싱 실패', err);
                        }
                    }
                    boundary = buffer.indexOf('\n\n');
                }
            }
        }).catch(function(err) {
            if (err && err.name === 'AbortError' && requestStoppedByUser) {
                requestStoppedByUser = false;
                return;
            }
            cleanup();
            appendMessage('bot', '서버 통신 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
        });
    }

    btnSend.click(sendMessage);
    btnStop.click(stopActiveChatRequest);
    input.keypress(function(e) { if (e.which === 13) sendMessage(); });
    $('.quick-btn').click(function() {
        input.val($(this).text().trim());
        sendMessage();
    });

    $('#btn-new-chat').click(function() {
        const button = $(this);
        button.prop('disabled', true).addClass('opacity-70');

        $.ajax({
            url: CONFIG.newSessionUrl,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            success: function(data) {
                if (data.status === 'success') {
                    location.href = CONFIG.chatPageUrl || '/chatbot';
                    return;
                }
                button.prop('disabled', false).removeClass('opacity-70');
                appendMessage('bot', '새 분석 세션을 시작하지 못했습니다: ' + (data.message || '알 수 없는 오류'));
            },
            error: function() {
                button.prop('disabled', false).removeClass('opacity-70');
                appendMessage('bot', '새 분석 세션을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.');
            }
        });
    });

    $('.session-item-li').click(function() {
        const item = $(this);
        const sessionKey = item.data('session-key');

        if (!sessionKey) {
            return;
        }

        $('.session-item-li').removeClass('active');
        item.addClass('active');

        clearConversation();
        toggleWelcome(false);
        chatContainer.append(`
            <div class="flex h-full min-h-[240px] items-center justify-center">
                <div class="rounded-2xl border border-slate-200 bg-white px-6 py-5 text-center shadow-sm">
                    <div class="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                        <span class="loading loading-spinner loading-sm"></span>
                    </div>
                    <p class="mt-4 text-sm font-bold tracking-tight text-slate-900">세션 기록을 불러오는 중입니다</p>
                    <p class="mt-2 text-xs text-slate-500">최근 대화와 시각화 결과를 복원합니다.</p>
                </div>
            </div>
        `);

        $.ajax({
            url: CONFIG.chatUrl,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                session_key: sessionKey
            }),
            success: function(data) {
                clearConversation();

                if (data.status !== 'success') {
                    appendMessage('bot', '세션 전환에 실패했습니다: ' + (data.message || '알 수 없는 오류'));
                    return;
                }

                if (Array.isArray(data.history) && data.history.length > 0) {
                    data.history.forEach((item) => {
                        appendMessage(item.role === 'user' ? 'user' : 'bot', item.text || '');
                    });
                    appendVisualizations(data.visualizations);
                    return;
                }

                if (data.last_query || data.answer) {
                    if (data.last_query) {
                        appendMessage('user', data.last_query);
                    }
                    if (data.answer) {
                        appendMessage('bot', data.answer);
                    }
                    appendVisualizations(data.visualizations);
                    return;
                }

                toggleWelcome(true);
            },
            error: function() {
                clearConversation();
                appendMessage('bot', '세션 기록을 가져오지 못했습니다. 다시 시도해 주세요.');
            }
        });
    });

    $(document).on('click', '.confirm-automation-btn', function() {
        const button = $(this);
        const jobId = button.data('job-id');
        const confirmationToken = button.data('confirmation-token');

        button.prop('disabled', true).addClass('opacity-70').text('승인 처리 중...');

        $.ajax({
            url: buildEndpointUrl(CONFIG.confirmUrlTemplate, jobId),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                confirmation_token: confirmationToken
            }),
            success: function(data) {
                button.closest('.automation-card').fadeOut(150, function() {
                    $(this).remove();
                });
                if (data.status === 'success') {
                    handleBotPayload(data);
                } else {
                    appendMessage('bot', '승인 요청 처리에 실패했습니다: ' + (data.message || '알 수 없는 오류'));
                }
            },
            error: function() {
                button.prop('disabled', false).removeClass('opacity-70').text('승인 후 실행');
                appendMessage('bot', '승인 요청 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
            }
        });
    });

    $(document).on('click', '.cancel-automation-btn', function() {
        const button = $(this);
        const jobId = button.data('job-id');
        if (!jobId) {
            return;
        }

        button.prop('disabled', true).addClass('opacity-70').text('중지 중...');
        stopJobPolling(jobId);

        $.ajax({
            url: buildEndpointUrl(CONFIG.cancelUrlTemplate, jobId),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            success: function(data) {
                button.closest('.automation-card').fadeOut(150, function() {
                    $(this).remove();
                });
                if (data.status === 'success') {
                    handleBotPayload(data);
                    return;
                }
                appendMessage('bot', '실행 중지 요청에 실패했습니다: ' + (data.message || '알 수 없는 오류'));
            },
            error: function() {
                button.prop('disabled', false).removeClass('opacity-70').text('실행 중지');
                appendMessage('bot', '실행 중지 요청 중 오류가 발생했습니다. 실행 콘솔에서 상태를 확인해 주세요.');
            }
        });
    });

    let initialMessage = interface.data('initial-message');
    if (typeof initialMessage === 'string') {
        try {
            initialMessage = JSON.parse(initialMessage);
        } catch (e) {
            // keep as string
        }
    }
    if (initialMessage) {
        toggleWelcome(false);
        window.setTimeout(function() {
            setAndSend(initialMessage);
        }, 0);
    }

    // Automatically load the active session history on page load
    const activeSessionItem = $('.session-item-li.active');
    if (activeSessionItem.length > 0) {
        activeSessionItem.click();
    }
});
