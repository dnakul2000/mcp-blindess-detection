/* Message trace interactivity */

document.addEventListener('htmx:afterSwap', function() {
  initMessageTrace();
});

document.addEventListener('DOMContentLoaded', function() {
  initMessageTrace();
});

function initMessageTrace() {
  // Toggle message detail on click
  document.querySelectorAll('.message-row[hx-get]').forEach(function(row) {
    row.addEventListener('click', function() {
      var detailDiv = this.nextElementSibling;
      if (detailDiv && detailDiv.id && detailDiv.id.startsWith('msg-detail-')) {
        if (detailDiv.style.display === 'none') {
          detailDiv.style.display = '';
          // Trigger HTMX load if empty
          if (!detailDiv.innerHTML.trim()) {
            htmx.trigger(row, 'click');
          }
        } else {
          detailDiv.style.display = 'none';
        }
      }
    });
  });
}
