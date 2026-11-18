/**
 * NanoTrace Feedback Client - Ultra-lightweight embeddable feedback library (< 2KB).
 * Enables 1-line integration of customer ratings and sentiment directly mapped to trace IDs.
 */
(function(window) {
  'use strict';

  const NanoTraceFeedback = {
    endpoint: '/api/feedback',

    /**
     * Send feedback rating directly via API.
     * @param {Object} options
     * @param {string} options.traceId - Associated trace ID
     * @param {number} options.score - Rating score (+1.0 positive, -1.0 negative, 0 neutral)
     * @param {string} [options.comment] - Optional user comment
     * @param {string} [options.spanId] - Optional specific span ID
     * @param {string} [options.userId] - Optional user identifier
     * @param {Object} [options.metadata] - Optional arbitrary metadata
     * @returns {Promise<Object>}
     */
    send: async function(options) {
      if (!options || !options.traceId) {
        throw new Error('NanoTraceFeedback.send requires a traceId');
      }

      const res = await fetch(this.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_id: options.traceId,
          score: options.score !== undefined ? options.score : 1.0,
          comment: options.comment || null,
          span_id: options.spanId || null,
          user_id: options.userId || null,
          metadata: options.metadata || {}
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to record feedback' }));
        throw new Error(err.detail || 'Feedback submission failed');
      }

      return await res.json();
    },

    /**
     * Mount an interactive feedback widget (Thumbs Up / Down + Comment) into any DOM element.
     * @param {string|HTMLElement} container - DOM element or selector
     * @param {Object} config - { traceId, onSubmitted, theme }
     */
    mount: function(container, config) {
      const el = typeof container === 'string' ? document.querySelector(container) : container;
      if (!el) return;

      const traceId = config.traceId || '';
      const widgetId = 'nt-fb-' + Math.random().toString(36).substring(2, 9);

      el.innerHTML = `
        <div class="nanotrace-feedback-widget" id="${widgetId}" style="display:inline-flex; align-items:center; gap:8px; font-family:system-ui,sans-serif; font-size:13px;">
          <span style="color:#64748b; font-size:12px;">Was this helpful?</span>
          <button type="button" class="nt-fb-btn nt-fb-up" data-score="1" style="cursor:pointer; background:transparent; border:1px solid #cbd5e1; border-radius:4px; padding:3px 8px; font-size:14px; transition:all 0.15s ease;">👍</button>
          <button type="button" class="nt-fb-btn nt-fb-down" data-score="-1" style="cursor:pointer; background:transparent; border:1px solid #cbd5e1; border-radius:4px; padding:3px 8px; font-size:14px; transition:all 0.15s ease;">👎</button>
          <span class="nt-fb-status" style="display:none; color:#10b981; font-weight:600; font-size:12px;">✓ Recorded</span>
        </div>
      `;

      const widget = document.getElementById(widgetId);
      const buttons = widget.querySelectorAll('.nt-fb-btn');
      const status = widget.querySelector('.nt-fb-status');

      buttons.forEach(btn => {
        btn.addEventListener('click', async () => {
          const score = parseFloat(btn.getAttribute('data-score'));
          buttons.forEach(b => {
            b.disabled = true;
            b.style.opacity = '0.5';
          });
          btn.style.background = score > 0 ? '#dcfce7' : '#fee2e2';
          btn.style.borderColor = score > 0 ? '#10b981' : '#ef4444';

          try {
            const result = await NanoTraceFeedback.send({
              traceId: traceId,
              score: score
            });
            status.style.display = 'inline';
            if (config.onSubmitted) config.onSubmitted(result);
          } catch (err) {
            console.error('Failed to submit NanoTrace feedback:', err);
          }
        });
      });
    }
  };

  window.NanoTraceFeedback = NanoTraceFeedback;
})(window);
