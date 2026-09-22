"""Verify Showcase Website Assets and HTML Parity."""

import re
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent

    # 1. Parity between root and docs/
    for name in ["index.html", "style.css", "app.js"]:
        root_file = root / name
        docs_file = root / "docs" / name
        assert root_file.exists(), f"Missing root file: {root_file}"
        assert docs_file.exists(), f"Missing docs file: {docs_file}"
        assert root_file.read_text(encoding="utf-8") == docs_file.read_text(encoding="utf-8"), (
            f"Mismatch between {root_file} and {docs_file}"
        )
        print(f"Parity verified: {name}")

    # 2. HTML Validation
    html_content = (root / "docs" / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_content))
    hrefs = set(re.findall(r'href=["\']#([^"\']+)["\']', html_content))

    missing = [h for h in hrefs if h and h not in ids]
    if missing:
        raise ValueError(f"Missing anchor targets in index.html: {missing}")
    print(f"All {len(hrefs)} internal anchor links verified against valid IDs!")

    # 3. Check required interactive elements
    required_ids = [
        "mobile-toggle-btn",
        "mobile-nav-drawer",
        "terminal-panel-check",
        "terminal-panel-mcp",
        "terminal-panel-doctor",
        "playground-req",
        "playground-res",
        "playground-tool-name",
        "dash-status-badge",
    ]
    for req_id in required_ids:
        assert req_id in ids, f"Required element ID '{req_id}' missing in HTML"
    print("All required interactive element IDs present!")

    # 4. Check CSS holo tokens and aurora classes
    css_content = (root / "docs" / "style.css").read_text(encoding="utf-8")
    required_css_tokens = [
        "--accent-crimson",
        "--accent-coral",
        "--accent-rose-glow",
        "--grad-aurora",
        "--grad-holo-border",
        "--shadow-holo",
        ".holo-card",
        ".btn-glow-aurora",
        ".mobile-nav-drawer",
        ".ambient-aurora-wrap",
        ".aurora-orb",
        "@keyframes holoBorderShimmer",
        "@keyframes pulseConnector",
    ]
    for token in required_css_tokens:
        assert token in css_content, f"Required CSS token/class '{token}' missing in style.css"
    print("All required CSS tokens and keyframe animations verified!")

    # 5. Check JS controllers
    js_content = (root / "docs" / "app.js").read_text(encoding="utf-8")
    required_js_funcs = [
        "initMobileNav",
        "initHoloSpotlight",
        "initTerminalTabs",
        "initCopyButtons",
        "initPlatformTabs",
        "initMcpPlayground",
        "initDashboardActions",
        "initBenchmarkAnimations",
    ]
    for func in required_js_funcs:
        assert func in js_content, f"Required JS function '{func}' missing in app.js"
    print("All required JavaScript controllers verified!")

    print("\nSUCCESS: All Showcase website verifications passed cleanly!")


if __name__ == "__main__":
    main()
