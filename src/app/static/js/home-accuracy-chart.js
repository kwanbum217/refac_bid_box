/*
 * 메인 '모델 정확도' 카드의 승격 세대별 오차 추이 그래프입니다.
 *
 * 값은 서버가 세대 metadata.json 의 source_metrics 에서 읽어 JSON 스크립트
 * 태그로 넘깁니다. 이 파일에는 지표 수치를 두지 않습니다. 세대가 두 개
 * 미만이면 서버가 chart.visible=false 로 내려 카드가 그래프를 숨깁니다.
 */
(function () {
    'use strict';

    var PALETTE = ['rmse', 'mape'];

    function readPayload() {
        var node = document.getElementById('home-accuracy-chart-data');
        if (!node) {
            return null;
        }
        try {
            return JSON.parse(node.textContent || '{}');
        } catch (error) {
            return null;
        }
    }

    function isDark() {
        return document.documentElement.classList.contains('dark');
    }

    function themeColors() {
        var dark = isDark();
        return {
            text: dark ? '#cbd5e1' : '#475569',
            grid: dark ? 'rgba(148, 163, 184, 0.16)' : 'rgba(148, 163, 184, 0.28)',
            rmse: dark ? '#60a5fa' : '#2563eb',
            mape: dark ? '#34d399' : '#059669'
        };
    }

    function lineColor(key, colors) {
        return colors[key] || colors.rmse;
    }

    function buildChart(canvas, payload) {
        if (!window.Chart || !canvas || !payload || !payload.visible) {
            return null;
        }
        if (!Array.isArray(payload.series) || payload.series.length === 0) {
            return null;
        }
        var colors = themeColors();
        var datasets = payload.series.map(function (series) {
            var color = lineColor(PALETTE.indexOf(series.key) >= 0 ? series.key : 'rmse', colors);
            return {
                label: series.label,
                data: series.data,
                borderColor: color,
                backgroundColor: color,
                borderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBorderWidth: 0,
                tension: 0.3,
                spanGaps: false,
                fill: false
            };
        });

        return new window.Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: payload.labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            usePointStyle: true,
                            boxWidth: 8,
                            boxHeight: 8,
                            padding: 16,
                            font: { size: 11, weight: '600' }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            afterTitle: function (items) {
                                if (!items.length || !Array.isArray(payload.versions)) {
                                    return '';
                                }
                                return payload.versions[items[0].dataIndex] || '';
                            },
                            label: function (item) {
                                var series = payload.series[item.datasetIndex] || {};
                                var value = Number(item.parsed.y);
                                if (!isFinite(value)) {
                                    return item.dataset.label + ' 값 없음';
                                }
                                return item.dataset.label + ' ' + value.toFixed(2) + (series.unit || '');
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text, font: { size: 11 } }
                    },
                    y: {
                        beginAtZero: false,
                        grid: { color: colors.grid },
                        ticks: {
                            color: colors.text,
                            font: { size: 11 },
                            callback: function (value) {
                                return Number(value).toFixed(2);
                            }
                        }
                    }
                }
            }
        });
    }

    function init() {
        var payload = readPayload();
        var canvas = document.getElementById('home-accuracy-chart');
        if (!payload || !canvas) {
            return;
        }
        var chart = buildChart(canvas, payload);
        if (!chart) {
            return;
        }
        new MutationObserver(function () {
            chart.destroy();
            chart = buildChart(canvas, payload);
        }).observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['class', 'data-theme']
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
