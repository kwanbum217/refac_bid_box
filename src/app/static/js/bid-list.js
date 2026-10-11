/* 공고 목록 행 클릭 이동을 담당합니다. 인라인 onclick 을 대체합니다. */
document.addEventListener('click', function(event) {
    const row = event.target.closest('tr.bid-row');
    if (!row || !row.dataset.url) {
        return;
    }
    window.location.href = row.dataset.url;
});
