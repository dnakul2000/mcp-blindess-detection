/* SSE handler for live experiment monitoring */

function startSSE(experimentId) {
  var logOutput = document.getElementById('log-output');
  var progressFill = document.getElementById('progress-fill');
  var statusDot = document.getElementById('status-dot');

  if (!logOutput) return;

  // Set global status to running
  if (statusDot) statusDot.classList.add('running');

  var source = new EventSource('/sse/experiment/' + experimentId);

  source.onmessage = function(event) {
    var line = document.createElement('div');
    line.className = 'log-line';
    var text = event.data;

    // Color-code based on content
    if (text.indexOf('OK') !== -1) {
      line.className += ' success';
    } else if (text.indexOf('FAILED') !== -1 || text.indexOf('ERROR') !== -1) {
      line.className += ' error';
    } else if (text.indexOf('Starting') !== -1 || text.indexOf('Run ') !== -1) {
      line.className += ' info';
    }

    line.textContent = text;
    logOutput.appendChild(line);
    logOutput.scrollTop = logOutput.scrollHeight;

    // Update progress from "Run N/M" lines
    var match = text.match(/Run (\d+)\/(\d+)/);
    if (match && progressFill) {
      var pct = (parseInt(match[1]) / parseInt(match[2])) * 100;
      progressFill.style.width = pct + '%';
    }
  };

  source.addEventListener('done', function(event) {
    source.close();
    if (statusDot) statusDot.classList.remove('running');

    var data = JSON.parse(event.data);
    var doneDiv = document.createElement('div');
    doneDiv.className = 'mt-4';
    doneDiv.innerHTML = '<a href="/results" class="btn btn-primary">View Results</a>';
    logOutput.parentNode.appendChild(doneDiv);
  });

  source.onerror = function() {
    source.close();
    if (statusDot) statusDot.classList.remove('running');
    var errLine = document.createElement('div');
    errLine.className = 'log-line error';
    errLine.textContent = 'SSE connection lost.';
    logOutput.appendChild(errLine);
  };
}
