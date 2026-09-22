/**
 * Resync Showcase Interactive Logic
 * Single-Page Web App Controller
 */

document.addEventListener('DOMContentLoaded', () => {
  initMobileNav();
  initHoloSpotlight();
  initTerminalTabs();
  initCopyButtons();
  initPlatformTabs();
  initMcpPlayground();
  initDashboardActions();
  initBenchmarkAnimations();
});

/* --------------------------------------------------------------------------
   0. Mobile Navigation Drawer & Hamburger Toggle
   -------------------------------------------------------------------------- */
function initMobileNav() {
  const toggleBtn = document.getElementById('mobile-toggle-btn');
  const drawer = document.getElementById('mobile-nav-drawer');
  if (!toggleBtn || !drawer) return;

  const toggle = (force) => {
    const shouldOpen = typeof force === 'boolean' ? force : !drawer.classList.contains('open');
    if (shouldOpen) {
      toggleBtn.classList.add('active');
      drawer.classList.add('open');
      toggleBtn.setAttribute('aria-expanded', 'true');
    } else {
      toggleBtn.classList.remove('active');
      drawer.classList.remove('open');
      toggleBtn.setAttribute('aria-expanded', 'false');
    }
  };

  toggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    toggle();
  });

  const links = drawer.querySelectorAll('.mobile-nav-link, .mobile-drawer-cta a');
  links.forEach((link) => {
    link.addEventListener('click', () => {
      toggle(false);
    });
  });

  document.addEventListener('click', (e) => {
    if (drawer.classList.contains('open') && !drawer.contains(e.target) && !toggleBtn.contains(e.target)) {
      toggle(false);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer.classList.contains('open')) {
      toggle(false);
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 860 && drawer.classList.contains('open')) {
      toggle(false);
    }
  });
}

/* --------------------------------------------------------------------------
   0.1 Holographic Spotlight Interactive Tracking
   -------------------------------------------------------------------------- */
function initHoloSpotlight() {
  const holoCards = document.querySelectorAll('.holo-card');
  if (!holoCards.length) return;

  holoCards.forEach((card) => {
    const handleMove = (e) => {
      const rect = card.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      const x = ((clientX - rect.left) / rect.width) * 100;
      const y = ((clientY - rect.top) / rect.height) * 100;
      card.style.setProperty('--spotlight-x', `${x.toFixed(2)}%`);
      card.style.setProperty('--spotlight-y', `${y.toFixed(2)}%`);
    };

    card.addEventListener('mousemove', handleMove, { passive: true });
    card.addEventListener('touchmove', handleMove, { passive: true });

    card.addEventListener('mouseleave', () => {
      card.style.setProperty('--spotlight-x', '50%');
      card.style.setProperty('--spotlight-y', '50%');
    });
  });
}

/* --------------------------------------------------------------------------
   0.2 Interactive Hero Terminal Simulator Tabs
   -------------------------------------------------------------------------- */
function initTerminalTabs() {
  const tabBtns = document.querySelectorAll('.terminal-tab-btn');
  const panels = document.querySelectorAll('.terminal-panel');
  if (!tabBtns.length) return;

  tabBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tabId = btn.getAttribute('data-tab');
      if (!tabId) return;

      tabBtns.forEach((b) => b.classList.remove('active'));
      panels.forEach((p) => p.classList.remove('active'));

      btn.classList.add('active');
      const targetPanel = document.getElementById(`terminal-panel-${tabId}`);
      if (targetPanel) {
        targetPanel.classList.add('active');
      }
    });
  });
}

/* --------------------------------------------------------------------------
   1. Copy-to-Clipboard Functionality
   -------------------------------------------------------------------------- */
async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      // Fallback below
    }
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let successful = false;
  try {
    successful = document.execCommand('copy');
  } catch (err) {
    successful = false;
  }
  document.body.removeChild(textarea);
  return successful;
}

function initCopyButtons() {
  const copyButtons = document.querySelectorAll('.copy-btn');

  copyButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const targetText = btn.getAttribute('data-clipboard-text') ||
        btn.closest('.copy-box, .code-window')?.querySelector('code, pre')?.innerText;

      if (!targetText) return;

      const success = await copyToClipboard(targetText.trim());
      if (!success) return;

      const originalHtml = btn.innerHTML;
      btn.classList.add('copied');
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        Copied!
      `;

      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = originalHtml;
      }, 2200);
    });
  });
}

/* --------------------------------------------------------------------------
   2. Platform Installation Tabs
   -------------------------------------------------------------------------- */
function initPlatformTabs() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const panes = document.querySelectorAll('.platform-pane');

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetPlatform = btn.getAttribute('data-platform');

      tabButtons.forEach((b) => b.classList.remove('active'));
      panes.forEach((p) => p.classList.remove('active'));

      btn.classList.add('active');
      const activePane = document.getElementById(`pane-${targetPlatform}`);
      if (activePane) {
        activePane.classList.add('active');
      }
    });
  });
}

/* --------------------------------------------------------------------------
   3. MCP Tools Interactive Playground Data & Switcher
   -------------------------------------------------------------------------- */
const MCP_TOOLS = {
  verify_package: {
    name: 'verify_package',
    latency: '< 180ms',
    tag: 'Real-Time Gate',
    desc: 'Checks if an agent-invoked package name exists on the registry (PyPI/npm/crates.io) and verifies active OSV.dev advisories before the agent touches your lockfile.',
    scenario: 'AI agent hallucinated `transformers-quant-v2` during refactoring. Resync intercepts and halts execution before code is committed.',
    request: `{\n  "method": "tools/call",\n  "params": {\n    "name": "verify_package",\n    "arguments": {\n      "package": "transformers-quant-v2",\n      "ecosystem": "pypi"\n    }\n  }\n}`,
    response: `{\n  "outcome": "package_not_found",\n  "detail": "transformers-quant-v2 was not found on PyPI registry.",\n  "risk_assessment": "CRITICAL: Potential AI hallucination / slopsquatting vector."\n}`
  },
  check_symbol_exists: {
    name: 'check_symbol_exists',
    latency: '< 45ms',
    tag: 'In-Memory LanceDB',
    desc: 'Validates imported symbols against known breaking changes and PEP 440 version specifiers in the repository knowledge store.',
    scenario: 'AI agent calls `transformers.PreTrainedModel.from_pretrained(..., use_auth_token=...)`. Resync flags the deprecated parameter.',
    request: `{\n  "method": "tools/call",\n  "params": {\n    "name": "check_symbol_exists",\n    "arguments": {\n      "fully_qualified_symbol": "transformers.PreTrainedModel.from_pretrained",\n      "pinned_version": "4.35.0"\n    }\n  }\n}`,
    response: `{\n  "outcome": "parameter_renamed",\n  "detail": "use_auth_token was deprecated in v4.32.0 and removed in v5.0.0. Renamed to token.",\n  "suggested_replacement_raw": "token"\n}`
  },
  verify_patch_equivalence: {
    name: 'verify_patch_equivalence',
    latency: '< 120ms',
    tag: 'AST Validation',
    desc: 'Performs non-speculative deterministic AST checks on agent-drafted code rewrites before the file is saved to disk.',
    scenario: 'Agent proposes an AST rename of `use_auth_token` to `token`. Resync confirms structural equivalence against known taxonomy.',
    request: `{\n  "method": "tools/call",\n  "params": {\n    "name": "verify_patch_equivalence",\n    "arguments": {\n      "fully_qualified_symbol": "transformers.AutoModel.from_pretrained",\n      "old_source": "AutoModel.from_pretrained('bert-base', use_auth_token=key)",\n      "new_source": "AutoModel.from_pretrained('bert-base', token=key)",\n      "pinned_version": "4.35.0"\n    }\n  }\n}`,
    response: `{\n  "outcome": "verified_equivalent",\n  "rule_type": "rename",\n  "confidence": 1.0,\n  "detail": "Structural parameter rename verified against ground truth."\n}`
  },
  explain_change: {
    name: 'explain_change',
    latency: '< 60ms',
    tag: 'Trust Scoring',
    desc: 'Provides a human- and agent-readable root-cause breakdown of an API change, including 4-tier decomposed trust ratings.',
    scenario: 'Developer or agent requests the upstream citation and testing evidence for a breaking change in transformers.',
    request: `{\n  "method": "tools/call",\n  "params": {\n    "name": "explain_change",\n    "arguments": {\n      "target": "transformers.PreTrainedModel.from_pretrained"\n    }\n  }\n}`,
    response: `{\n  "symbol": "transformers.PreTrainedModel.from_pretrained",\n  "trust_score": {\n    "rule_match": 1.0,\n    "test_suite_passed": true,\n    "differential_equivalence": true,\n    "source_citation": "huggingface/transformers#24874"\n  },\n  "remediation": ["Apply mechanical AST patch", "Freeze via resync.toml pin"]\n}`
  },
  get_compatibility_report: {
    name: 'get_compatibility_report',
    latency: '< 190ms',
    tag: 'Repository Audit',
    desc: 'Generates a full compatibility matrix across all declared dependencies in the target workspace.',
    scenario: 'Agent or CI inspects all repository manifests to produce an executive compatibility rating before release.',
    request: `{\n  "method": "tools/call",\n  "params": {\n    "name": "get_compatibility_report",\n    "arguments": {\n      "repo_root": "."\n    }\n  }\n}`,
    response: `{\n  "total_dependencies": 42,\n  "compatible": 40,\n  "actionable_deprecations": 2,\n  "provenance_verified_percent": 95.2,\n  "recommended_action": "Run resync sync --tier mechanical --apply"\n}`
  }
};

function initMcpPlayground() {
  const toolButtons = document.querySelectorAll('.tool-btn');
  const codeReqEl = document.getElementById('playground-req');
  const codeResEl = document.getElementById('playground-res');
  const toolNameEl = document.getElementById('playground-tool-name');
  const toolDescEl = document.getElementById('playground-tool-desc');
  const toolLatencyEl = document.getElementById('playground-tool-latency');

  if (!codeReqEl || !codeResEl) return;

  toolButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const toolKey = btn.getAttribute('data-tool');
      const data = MCP_TOOLS[toolKey];
      if (!data) return;

      toolButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      if (toolNameEl) toolNameEl.innerText = data.name;
      if (toolDescEl) toolDescEl.innerText = `${data.desc} ${data.scenario}`;
      if (toolLatencyEl) toolLatencyEl.innerText = data.latency;

      codeReqEl.textContent = data.request;
      codeResEl.textContent = data.response;
    });
  });
}

/* --------------------------------------------------------------------------
   4. AST Diff Review Dashboard Interactive Triggers
   -------------------------------------------------------------------------- */
function initDashboardActions() {
  const actionButtons = document.querySelectorAll('.btn-action');
  const statusBadge = document.getElementById('dash-status-badge');

  actionButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const actionName = btn.innerText.trim();
      const originalBadgeText = statusBadge ? statusBadge.innerText : '';

      if (statusBadge) {
        statusBadge.innerText = `Executed: ${actionName}`;
        statusBadge.style.background = 'var(--accent-green-bg)';
        statusBadge.style.color = 'var(--accent-green)';

        setTimeout(() => {
          statusBadge.innerText = originalBadgeText || 'Pending Review (1 Actionable Change)';
          statusBadge.style.background = 'var(--accent-ice)';
          statusBadge.style.color = 'var(--accent-blue-deep)';
        }, 3000);
      }
    });
  });
}

/* --------------------------------------------------------------------------
   5. Benchmark Bar Animations on Scroll
   -------------------------------------------------------------------------- */
function initBenchmarkAnimations() {
  const bars = document.querySelectorAll('.bar-fill');
  if (!bars.length) return;

  const originalWidths = [];
  bars.forEach((bar, idx) => {
    originalWidths[idx] = bar.style.width || '100%';
    bar.style.width = '0%';
    bar.style.transition = 'width 1.2s cubic-bezier(0.16, 1, 0.3, 1)';
  });

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          bars.forEach((bar, idx) => {
            setTimeout(() => {
              bar.style.width = originalWidths[idx];
            }, idx * 120);
          });
          observer.disconnect();
        }
      });
    },
    { threshold: 0.2 }
  );

  const benchmarkCard = document.querySelector('.benchmark-card');
  if (benchmarkCard) {
    observer.observe(benchmarkCard);
  }
}
