document.addEventListener('DOMContentLoaded', () => {
  const payload = window.chartPayload || window.STOCK_DASHBOARD_DATA;
  if (!payload) return;
  const monthlyCanvas = document.getElementById('monthlyChart');
  const stockCanvas = document.getElementById('stockChart');

  if (monthlyCanvas) {
    new Chart(monthlyCanvas, {
      type: 'bar',
      data: {
        labels: payload.monthly_labels,
        datasets: [
          { label: '매수', data: payload.monthly_buy },
          { label: '매도', data: payload.monthly_sell },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
  }

  if (stockCanvas) {
    new Chart(stockCanvas, {
      type: 'pie',
      data: {
        labels: payload.stock_labels,
        datasets: [{ data: payload.stock_counts }],
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
  }
});
