/* 등급확인서 PDF 에서 신용평가등급과 평가일을 읽어 입력칸을 미리 채웁니다.
   폼을 제출하거나 저장하지 않으며, 서버가 돌려준 문자열은 textContent 로만 넣습니다. */
(function () {
    'use strict';

    var EXTRACT_ENDPOINT = '/api/v1/documents/extract';
    var MAX_FILE_BYTES = 5 * 1024 * 1024;
    var CONFIDENCE_LABELS = { high: '높음', medium: '보통', low: '낮음' };
    var UNRECOGNIZED_MESSAGE = '문서에서 등급을 찾지 못했습니다. 직접 입력하십시오.';
    var DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

    function createElement(tagName, className, text) {
        var element = document.createElement(tagName);
        if (className) {
            element.className = className;
        }
        if (text !== undefined && text !== null) {
            element.textContent = text;
        }
        return element;
    }

    function clear(element) {
        while (element.firstChild) {
            element.removeChild(element.firstChild);
        }
    }

    function setStatus(statusNode, message, tone) {
        if (!statusNode) {
            return;
        }
        statusNode.textContent = message || '';
        statusNode.classList.remove('text-slate-500', 'text-red-500', 'text-emerald-600');
        if (tone === 'error') {
            statusNode.classList.add('text-red-500');
        } else if (tone === 'ok') {
            statusNode.classList.add('text-emerald-600');
        } else {
            statusNode.classList.add('text-slate-500');
        }
    }

    function appendEvidence(parent, evidence) {
        var items = Array.isArray(evidence) ? evidence : evidence ? [evidence] : [];
        var list = createElement('ul', 'mt-1 space-y-0.5');
        items.forEach(function (item) {
            if (!item) {
                return;
            }
            var prefix = item.page === undefined || item.page === null ? '' : 'p.' + item.page + ' ';
            var text = (prefix + (item.text || '')).trim();
            if (text) {
                list.appendChild(createElement('li', 'text-[10px] text-slate-400', text));
            }
        });
        if (list.firstChild) {
            parent.appendChild(list);
        }
    }

    function renderField(container, field, filled, reason) {
        if (!container) {
            return;
        }
        clear(container);
        container.hidden = false;

        if (!field) {
            container.appendChild(
                createElement('p', 'text-[10px] text-slate-400', '문서에서 이 항목을 찾지 못했습니다.')
            );
            return;
        }

        if (filled) {
            var badge = createElement(
                'span',
                'inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-600'
            );
            badge.appendChild(createElement('i', 'fas fa-triangle-exclamation'));
            badge.appendChild(document.createTextNode(' 확인 필요'));
            var meta = createElement(
                'span',
                'ml-2 text-[10px] text-slate-400',
                '신뢰도 ' + (CONFIDENCE_LABELS[field.confidence] || field.confidence || '알 수 없음')
            );
            var header = createElement('p', 'flex items-center');
            header.appendChild(badge);
            header.appendChild(meta);
            container.appendChild(header);
            appendEvidence(container, field.evidence);
            return;
        }

        container.appendChild(
            createElement('p', 'text-[10px] text-slate-400', reason || '자동 입력하지 않았습니다.')
        );
        appendEvidence(container, field.evidence);
    }

    function fillCreditGrade(field) {
        var select = document.getElementById('id_credit_grade');
        var container = document.getElementById('doc-autofill-result-credit_grade');
        var filled = false;
        var reason = '';
        if (field && field.confidence === 'low') {
            reason = '신뢰도가 낮아 자동 입력하지 않았습니다.';
        } else if (field && field.value) {
            var matched =
                select &&
                Array.prototype.some.call(select.options, function (option) {
                    return option.value === field.value;
                });
            if (matched) {
                select.value = field.value;
                filled = true;
            } else {
                reason = '선택지에 없는 등급이라 자동 입력하지 않았습니다.';
            }
        }
        renderField(container, field, filled, reason);
    }

    function fillEvaluatedOn(field) {
        var input = document.getElementById('id_credit_evaluated_on');
        var container = document.getElementById('doc-autofill-result-credit_evaluated_on');
        var filled = false;
        var reason = '';
        if (field && field.confidence === 'low') {
            reason = '신뢰도가 낮아 자동 입력하지 않았습니다.';
        } else if (field && typeof field.value === 'string' && DATE_PATTERN.test(field.value)) {
            if (input) {
                input.value = field.value;
                filled = true;
            }
        } else if (field && field.value) {
            reason = '날짜 형식이 아니라 자동 입력하지 않았습니다.';
        }
        renderField(container, field, filled, reason);
    }

    function fileProblem(file) {
        if (!file) {
            return 'PDF 파일을 선택하십시오.';
        }
        if (file.size > MAX_FILE_BYTES) {
            return '파일 크기가 5MB 를 넘습니다. 더 작은 파일을 고르십시오.';
        }
        var looksLikePdf =
            file.type === 'application/pdf' || (!file.type && /\.pdf$/i.test(file.name || ''));
        if (!looksLikePdf) {
            return 'PDF 파일만 올릴 수 있습니다.';
        }
        return '';
    }

    function parseError(payload, status) {
        if (payload && typeof payload.detail === 'string' && payload.detail) {
            return payload.detail;
        }
        return '문서를 읽지 못했습니다. (오류 ' + status + ')';
    }

    function init() {
        var root = document.querySelector('[data-doc-autofill]');
        if (!root) {
            return;
        }
        var fileInput = root.querySelector('#doc-autofill-file');
        var runButton = root.querySelector('#doc-autofill-run');
        var status = root.querySelector('#doc-autofill-status');
        if (!fileInput || !runButton) {
            return;
        }

        runButton.addEventListener('click', function () {
            var file = fileInput.files && fileInput.files[0];
            var problem = fileProblem(file);
            if (problem) {
                setStatus(status, problem, 'error');
                return;
            }

            runButton.disabled = true;
            setStatus(status, '문서를 읽는 중입니다...', 'info');
            fetch(EXTRACT_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/pdf' },
                body: file,
                credentials: 'same-origin',
            })
                .then(function (response) {
                    return response
                        .json()
                        .catch(function () {
                            return null;
                        })
                        .then(function (payload) {
                            return { response: response, payload: payload };
                        });
                })
                .then(function (result) {
                    if (!result.response.ok) {
                        setStatus(status, parseError(result.payload, result.response.status), 'error');
                        return;
                    }
                    var payload = result.payload || {};
                    if (payload.status === 'unrecognized') {
                        setStatus(status, UNRECOGNIZED_MESSAGE, 'error');
                        return;
                    }
                    var fields = payload.fields || {};
                    fillCreditGrade(fields.credit_grade);
                    fillEvaluatedOn(fields.credit_evaluated_on);
                    setStatus(
                        status,
                        payload.notice || '문서에서 읽은 값을 채웠습니다. 저장 전에 직접 확인하십시오.',
                        'ok'
                    );
                })
                .catch(function () {
                    setStatus(status, '문서를 읽는 중 문제가 생겼습니다. 잠시 후 다시 시도하십시오.', 'error');
                })
                .then(function () {
                    runButton.disabled = false;
                });
        });
    }

    document.addEventListener('DOMContentLoaded', init);
})();
