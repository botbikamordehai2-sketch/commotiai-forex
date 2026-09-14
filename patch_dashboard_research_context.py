from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD = BASE_DIR / "dashboard.html"

html = DASHBOARD.read_text(encoding="utf-8")

if 'id="research-context"' in html:
    raise SystemExit("Research Context is already present; no change made.")

section = """
    <section class="section">
      <h2>Research Context</h2>
      <div id="research-context" class="grid"></div>
    </section>

    <section class="section">
      <h2>Manual Research Notes</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Event time UTC</th>
              <th>Currency / Pair</th>
              <th>Category</th>
              <th>Severity</th>
              <th>Window</th>
              <th>Summary</th>
              <th>Verified by</th>
            </tr>
          </thead>
          <tbody id="research-notes"></tbody>
        </table>
      </div>
    </section>
"""

anchor = """
    <section class="section">
      <div class="notice">
        Hermes role: Read-only auditor and analyst. Classification is not a trade instruction.
        Status: RESEARCH ONLY. No threshold change authorized.
      </div>
    </section>
"""

if anchor not in html:
    raise SystemExit("Dashboard anchor was not found; no change made.")

html = html.replace(anchor, section + anchor)

helpers_anchor = """
    function render(snapshot) {
"""

helpers = """
    async function loadResearchContext() {
      try {
        const response = await fetch(
          `research_context.json?t=${Date.now()}`,
          { cache: 'no-store' }
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const context = await response.json();
        renderResearchContext(context);
      } catch {
        $('research-context').innerHTML = `
          <div class="card">
            <div class="label">Research Context</div>
            <p>Context file is unavailable. Run build_research_context.py.</p>
          </div>
        `;
        $('research-notes').innerHTML = `
          <tr><td colspan="7" class="empty">Manual context unavailable</td></tr>
        `;
      }
    }

    function renderResearchContext(context) {
      const freshness = Object.entries(context.timeframe_freshness || {})
        .map(([label, value]) => `${label}: ${value}`)
        .join(' · ') || 'No timeframe data';

      const flags = context.data_quality_flags || [];
      const flagText = flags.length
        ? flags.map(flag => flag.flag).join(' · ')
        : 'No data-quality flags';

      $('research-context').innerHTML = `
        <div class="card">
          <div class="label">Market session (UTC)</div>
          <div class="value">${escapeHtml(context.market_session_utc || 'N/A')}</div>
          <p>Generated: ${escapeHtml(context.generated_at_utc || 'N/A')}</p>
        </div>
        <div class="card">
          <div class="label">Data freshness</div>
          <div class="value">${badge(
            flags.length ? 'CHECK FLAGS' : 'CLEAR',
            flags.length ? 'yellow' : 'green'
          )}</div>
          <p>${escapeHtml(freshness)}</p>
        </div>
        <div class="card">
          <div class="label">Research mode</div>
          <div class="value">${badge(
            context.research_only ? 'RESEARCH ONLY' : 'UNKNOWN',
            context.research_only ? 'blue' : 'gray'
          )}</div>
          <p>${escapeHtml(context.purpose || '')}</p>
        </div>
      `;

      const notes = context.manual_notes || [];

      $('research-notes').innerHTML = notes.map(note => {
        const subject = [note.currency, note.pair]
          .filter(Boolean)
          .join(' / ') || 'GENERAL';

        return `
          <tr>
            <td>${escapeHtml(note.event_time_utc || '—')}</td>
            <td>${escapeHtml(subject)}</td>
            <td>${escapeHtml(note.category || '—')}</td>
            <td>${badge(
              escapeHtml(note.severity || 'LOW'),
              note.severity === 'HIGH'
                ? 'red'
                : note.severity === 'MEDIUM'
                  ? 'yellow'
                  : 'gray'
            )}</td>
            <td>${escapeHtml(note.event_window || '—')}</td>
            <td>${escapeHtml(note.summary || '—')}</td>
            <td>${escapeHtml(note.verified_by || '—')}</td>
          </tr>
        `;
      }).join('') || `
        <tr><td colspan="7" class="empty">No active manual research notes</td></tr>
      `;
    }

"""

if helpers_anchor not in html:
    raise SystemExit("Dashboard script anchor was not found; no change made.")

html = html.replace(helpers_anchor, helpers + helpers_anchor)

startup = """
    loadDefault();
"""

if startup not in html:
    raise SystemExit("Dashboard startup anchor was not found; no change made.")

html = html.replace(startup, """
    loadDefault();
    loadResearchContext();
""")

DASHBOARD.write_text(html, encoding="utf-8")
print("Patched dashboard.html with Research Context.")