/*
 * 메인 '모델 정확도' 카드의 실측 그래프 두 개입니다.
 *
 * 왼쪽은 오차 범위별 적중 비율 가로 막대, 오른쪽은 예측 대 실제 낙찰률
 * 산점도입니다. 값은 서버가 사이드카의 distribution 에서 읽어 JSON 스크립트
 * 태그로 넘기므로 이 파일에는 지표 수치를 두지 않습니다. distribution 이
 * 없으면 서버가 chart.visible=false 로 내려 카드가 그래프를 숨깁니다.
 */
(function () {
    'use strict';

    var BAND_CANVAS_ID = 'home-accuracy-band-chart';
    var SCATTER_CANVAS_ID = 'home-accuracy-scatter-chart';
    var PAYLOAD_ID = 'home-accuracy-chart-data';

    function readPayload() {
        var node = document.getElementById(PAYLOAD_ID);
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
            muted: dark ? '#94a3b8' : '#64748b',
            grid: dark ? 'rgba(148, 163, 184, 0.16)' : 'rgba(148, 163, 184, 0.28)',
            bar: dark ? '#60a5fa' : '#2563eb',
            barSoft: dark ? 'rgba(96, 165, 250, 0.28)' : 'rgba(37, 99, 235, 0.18)',
            point: dark ? 'rgba(96, 165, 250, 0.45)' : 'rgba(37, 99, 235, 0.40)',
            pointHover: dark ? 'rgba(147, 197, 253, 0.9)' : 'rgba(29, 78, 216, 0.9)',
            band: dark ? 'rgba(96, 165, 250, 0.10)' : 'rgba(37, 99, 235, 0.08)',
            diagonal: dark ? 'rgba(226, 232, 240, 0.55)' : 'rgba(71, 85, 105, 0.55)'
        };
    }

    function percentText(value) {
        var number = Number(value);
        if (!isFinite(number)) {
            return '';
        }
        return (Math.round(number * 10) / 10).toString() + '%';
    }

    /* 막대 끝에 값을 적습니다. 넘치면 막대 안쪽 오른쪽에 붙입니다. */
    var barValueLabels = {
        id: 'homeAccuracyBarValueLabels',
        afterDatasetsDraw: function (chart) {
            var colors = themeColors();
            var meta = chart.getDatasetMeta(0);
            var dataset = chart.data.datasets[0] || { data: [] };
            var area = chart.chartArea;
            var ctx = chart.ctx;
            ctx.save();
            ctx.font = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.textBaseline = 'middle';
            (meta.data || []).forEach(function (bar, index) {
                var value = dataset.data[index];
                if (value === null || value === undefined) {
                    return;
                }
                var text = percentText(value);
                var width = ctx.measureText(text).width;
                var x = bar.x + 6;
                ctx.textAlign = 'left';
                if (x + width > area.right) {
                    x = bar.x - 6;
                    ctx.textAlign = 'right';
                }
                ctx.fillStyle = colors.text;
                ctx.fillText(text, x, bar.y);
            });
            ctx.restore();
        }
    };

    /* 정확히 맞힘 대각선(y=x)과 ±2%p 띠를 점보다 먼저 그립니다. */
    var perfectBand = {
        id: 'homeAccuracyPerfectBand',
        beforeDatasetsDraw: function (chart) {
            var options = chart.options.plugins || {};
            var scatter = options.homeAccuracyPerfectBand;
            if (!scatter) {
                return;
            }
            var colors = themeColors();
            var xScale = chart.scales.x;
            var yScale = chart.scales.y;
            var area = chart.chartArea;
            var band = Math.abs(Number(scatter.band_pp)) || 0;
            var min = Number(scatter.axis_min);
            var max = Number(scatter.axis_max);
            var ctx = chart.ctx;

            function px(value) {
                return xScale.getPixelForValue(value);
            }
            function py(value) {
                return yScale.getPixelForValue(value);
            }

            ctx.save();
            ctx.beginPath();
            ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
            ctx.clip();

            if (band > 0) {
                ctx.beginPath();
                ctx.moveTo(px(min), py(min - band));
                ctx.lineTo(px(max), py(max - band));
                ctx.lineTo(px(max), py(max + band));
                ctx.lineTo(px(min), py(min + band));
                ctx.closePath();
                ctx.fillStyle = colors.band;
                ctx.fill();
            }

            ctx.beginPath();
            ctx.moveTo(px(min), py(min));
            ctx.lineTo(px(max), py(max));
            ctx.strokeStyle = colors.diagonal;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([5, 4]);
            ctx.stroke();
            ctx.restore();
        }
    };

    function axisTicks(value) {
        return percentText(value).replace('%', '');
    }

    function buildBandChart(canvas, payload) {
        if (!window.Chart || !canvas || !payload || !Array.isArray(payload.bands)) {
            return null;
        }
        if (payload.bands.length === 0) {
            return null;
        }
        var colors = themeColors();
        var labels = payload.bands.map(function (band) {
            return band.label;
        });
        var values = payload.bands.map(function (band) {
            return band.percent;
        });
        var shares = payload.bands.map(function (band) {
            return band.share;
        });

        var chart = new window.Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '적중 비율',
                        data: values,
                        backgroundColor: colors.bar,
                        hoverBackgroundColor: colors.bar,
                        borderRadius: 4,
                        borderSkipped: false,
                        barPercentage: 0.62,
                        categoryPercentage: 0.82
                    }
                ]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                layout: { padding: { right: 34 } },
                animation: { duration: 300 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (item) {
                                var share = shares[item.dataIndex];
                                var ratio = isFinite(Number(share)) ? Number(share) : null;
                                var text = percentText(item.parsed.x);
                                if (ratio !== null) {
                                    text += ' (검증 표본의 ' + percentText(ratio * 100) + ')';
                                }
                                return text;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        min: 0,
                        max: 100,
                        grid: { color: colors.grid },
                        border: { display: false },
                        ticks: {
                            color: colors.muted,
                            font: { size: 11 },
                            callback: axisTicks
                        }
                    },
                    y: {
                        grid: { display: false },
                        border: { display: false },
                        ticks: { color: colors.text, font: { size: 11, weight: '600' } }
                    }
                }
            },
            plugins: [barValueLabels]
        });
        return chart;
    }

    function buildScatterChart(canvas, payload) {
        var scatter = payload && payload.scatter;
        if (!window.Chart || !canvas || !scatter || !Array.isArray(scatter.points)) {
            return null;
        }
        if (scatter.points.length === 0) {
            return null;
        }
        var colors = themeColors();
        var points = scatter.points.map(function (point) {
            return { x: Number(point[0]), y: Number(point[1]) };
        });
        var axisMin = Number(scatter.axis_min);
        var axisMax = Number(scatter.axis_max);

        var chart = new window.Chart(canvas.getContext('2d'), {
            type: 'scatter',
            data: {
                datasets: [
                    {
                        label: '공고',
                        data: points,
                        backgroundColor: colors.point,
                        borderColor: 'transparent',
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: colors.pointHover
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 300 },
                layout: { padding: 4 },
                plugins: {
                    legend: { display: false },
                    homeAccuracyPerfectBand: scatter,
                    tooltip: {
                        callbacks: {
                            label: function (item) {
                                var point = item.raw || {};
                                return '예측 ' + percentText(point.x) + ' · 실제 ' + percentText(point.y);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: axisMin,
                        max: axisMax,
                        grid: { color: colors.grid },
                        border: { display: false },
                        ticks: {
                            color: colors.muted,
                            font: { size: 11 },
                            maxTicksLimit: 6,
                            callback: axisTicks
                        }
                    },
                    y: {
                        type: 'linear',
                        min: axisMin,
                        max: axisMax,
                        grid: { color: colors.grid },
                        border: { display: false },
                        ticks: {
                            color: colors.muted,
                            font: { size: 11 },
                            maxTicksLimit: 6,
                            callback: axisTicks
                        }
                    }
                }
            },
            plugins: [perfectBand]
        });
        return chart;
    }

    function build(payload) {
        var bandCanvas = document.getElementById(BAND_CANVAS_ID);
        var scatterCanvas = document.getElementById(SCATTER_CANVAS_ID);
        return [
            bandCanvas ? buildBandChart(bandCanvas, payload) : null,
            scatterCanvas ? buildScatterChart(scatterCanvas, payload) : null
        ].filter(Boolean);
    }

    function init() {
        var payload = readPayload();
        if (!payload || !payload.visible) {
            return;
        }
        var charts = build(payload);
        if (charts.length === 0) {
            return;
        }
        var bandCanvas = document.getElementById(BAND_CANVAS_ID);
        var scatterCanvas = document.getElementById(SCATTER_CANVAS_ID);
        new MutationObserver(function () {
            charts.forEach(function (chart) {
                chart.destroy();
            });
            charts = [];
            if (bandCanvas) {
                var bandChart = buildBandChart(bandCanvas, payload);
                if (bandChart) {
                    charts.push(bandChart);
                }
            }
            if (scatterCanvas) {
                var scatterChart = buildScatterChart(scatterCanvas, payload);
                if (scatterChart) {
                    charts.push(scatterChart);
                }
            }
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
