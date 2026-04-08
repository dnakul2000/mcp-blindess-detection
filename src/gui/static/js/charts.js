/* Chart.js initialization helpers */

document.addEventListener('DOMContentLoaded', function() {
  // Set Chart.js defaults
  if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#52525b';
    Chart.defaults.plugins.legend.position = 'bottom';
    Chart.defaults.plugins.legend.labels.padding = 16;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
  }

  initCharts();
});

// Re-init charts after HTMX swaps
document.addEventListener('htmx:afterSwap', function() {
  initCharts();
});

function initCharts() {
  document.querySelectorAll('[data-chart]').forEach(function(el) {
    if (el._chartInstance) {
      el._chartInstance.destroy();
    }
    var config = JSON.parse(el.getAttribute('data-chart'));
    el._chartInstance = new Chart(el, config);
  });
}

/* Compliance color mapping */
var complianceColors = {
  full_execution: '#dc2626',
  partial_compliance: '#d97706',
  instruction_leakage: '#ca8a04',
  silent_refusal: '#16a34a'
};

var complianceBgColors = {
  full_execution: '#fef2f2',
  partial_compliance: '#fffbeb',
  instruction_leakage: '#fefce8',
  silent_refusal: '#f0fdf4'
};
