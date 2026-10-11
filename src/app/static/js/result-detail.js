/* 낙찰 결과 상세의 인쇄·뒤로가기 버튼을 담당합니다. 인라인 onclick 을 대체합니다. */
document.addEventListener('click', function(event) {
    if (event.target.closest('[data-print-page]')) {
        window.print();
        return;
    }
    if (event.target.closest('[data-history-back]')) {
        window.history.back();
    }
});
