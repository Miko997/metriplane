// Shared Metriplane view switcher.
// App shells get navigation inside their existing rail/sidebar so it never floats
// over controls. Plain scrollable pages get an in-flow top rail.
(function () {
  const LINKS = [
    ["command_center_live.html", "Command Center"],
    ["operator.html", "Operator Setup"],
    ["runtime.html", "Runtime Console"],
    ["index.html", "System Dashboard"],
  ];

  const here = (location.pathname.split("/").pop() || "index.html").toLowerCase();

  function activeFor(href) {
    return here === href.toLowerCase() ||
      (here === "command_center.html" && href === "command_center_live.html");
  }

  function addStyles() {
    if (document.getElementById("mp-shared-nav-style")) return;
    const style = document.createElement("style");
    style.id = "mp-shared-nav-style";
    style.textContent = `
      .mp-shared-nav {
        width: 100%;
        min-height: 48px;
        padding: 0 24px;
        display: flex;
        align-items: center;
        gap: 12px;
        background: rgba(2, 6, 12, 0.985);
        border-bottom: 1px solid var(--mp-border, rgba(100, 222, 214, 0.18));
        color: var(--mp-text-secondary, #D1D6D8);
        font-family: var(--mp-font-ui, "Inter", "Segoe UI", sans-serif);
        position: sticky;
        top: 0;
        z-index: 80;
      }
      .mp-shared-nav-brand {
        color: var(--mp-primary-bright, #64DED6);
        font-family: var(--mp-font-brand, "Sora", "Inter", sans-serif);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0;
        white-space: nowrap;
      }
      .mp-shared-nav-links {
        display: flex;
        align-items: center;
        gap: 4px;
        min-width: 0;
        overflow-x: auto;
        scrollbar-width: none;
      }
      .mp-shared-nav-links::-webkit-scrollbar { display: none; }
      .mp-shared-nav-link {
        min-height: 30px;
        padding: 6px 10px;
        border-radius: 7px;
        color: var(--mp-text-muted, #8EA3A8);
        text-decoration: none;
        font-size: 12px;
        font-weight: 650;
        white-space: nowrap;
        border: 1px solid transparent;
        transition: color 0.14s ease, background 0.14s ease, border-color 0.14s ease;
      }
      .mp-shared-nav-link:hover {
        color: var(--mp-text, #FBFBFB);
        background: rgba(64, 204, 196, 0.08);
      }
      .mp-shared-nav-link.active {
        color: var(--mp-primary-bright, #64DED6);
        background: rgba(64, 204, 196, 0.10);
        border-color: rgba(100, 222, 214, 0.28);
      }
      .mp-nav-sidebar-section {
        border-top: 1px solid var(--mp-border, rgba(100, 222, 214, 0.18));
      }
      .mp-nav-sidebar-section .nav-item .nav-icon {
        color: var(--mp-primary-bright, #64DED6);
        font-size: 13px;
        line-height: 1;
      }
      .cc-view-list {
        display: grid;
        gap: 5px;
      }
      .cc-view-link {
        min-height: 31px;
        padding: 7px 8px;
        border: 1px solid transparent;
        border-radius: 7px;
        color: var(--mp-text-muted, #8EA3A8);
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 12px;
        font-weight: 750;
        text-decoration: none;
      }
      .cc-view-link::after {
        content: "";
        width: 5px;
        height: 5px;
        border-radius: 999px;
        background: transparent;
      }
      .cc-view-link:hover {
        color: var(--mp-text, #FBFBFB);
        background: rgba(64, 204, 196, 0.06);
      }
      .cc-view-link.active {
        color: var(--mp-primary-bright, #64DED6);
        background: rgba(64, 204, 196, 0.08);
        border-color: rgba(100, 222, 214, 0.20);
      }
      .cc-view-link.active::after {
        background: var(--mp-primary-bright, #64DED6);
        box-shadow: 0 0 10px rgba(100, 222, 214, 0.5);
      }
      .vt-landing-page .lp-nav-ctas .mp-landing-extra {
        display: inline-flex;
        align-items: center;
      }
      @media (max-width: 720px) {
        .mp-shared-nav {
          align-items: flex-start;
          flex-direction: column;
          gap: 6px;
          padding: 10px 16px;
        }
        .mp-shared-nav-links {
          width: 100%;
          flex-wrap: wrap;
          overflow-x: visible;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function makeRailLink(href, label) {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    a.className = "mp-shared-nav-link" + (activeFor(href) ? " active" : "");
    return a;
  }

  function mountRail() {
    const bar = document.createElement("nav");
    bar.id = "mp-shared-nav";
    bar.className = "mp-shared-nav";
    bar.setAttribute("aria-label", "Metriplane views");

    const brand = document.createElement("span");
    brand.className = "mp-shared-nav-brand";
    brand.textContent = "Metriplane";
    bar.appendChild(brand);

    const links = document.createElement("div");
    links.className = "mp-shared-nav-links";
    for (const [href, label] of LINKS) links.appendChild(makeRailLink(href, label));
    bar.appendChild(links);

    document.body.prepend(bar);
  }

  function mountSidebar(sidebar) {
    if (document.getElementById("mp-shared-nav")) return;
    const section = document.createElement("div");
    section.id = "mp-shared-nav";
    section.className = "sidebar-section mp-nav-sidebar-section";

    const label = document.createElement("div");
    label.className = "sidebar-section-label";
    label.textContent = "Views";
    section.appendChild(label);

    for (const [href, text] of LINKS) {
      const a = document.createElement("a");
      a.href = href;
      a.className = "nav-item" + (activeFor(href) ? " active" : "");

      const icon = document.createElement("span");
      icon.className = "nav-icon";
      icon.textContent = activeFor(href) ? ">" : "-";
      a.appendChild(icon);

      a.appendChild(document.createTextNode(text));
      section.appendChild(a);
    }

    const cta = sidebar.querySelector(".sidebar-cta");
    if (cta) sidebar.insertBefore(section, cta);
    else sidebar.appendChild(section);
  }

  function mountCommandRail(rail) {
    if (document.getElementById("mp-shared-nav")) return;
    const section = document.createElement("div");
    section.id = "mp-shared-nav";
    section.className = "cc-rail-section";

    const label = document.createElement("div");
    label.className = "cc-rail-label";
    label.textContent = "Views";
    section.appendChild(label);

    const list = document.createElement("div");
    list.className = "cc-view-list";
    for (const [href, text] of LINKS) {
      const a = document.createElement("a");
      a.href = href;
      a.textContent = text;
      a.className = "cc-view-link" + (activeFor(href) ? " active" : "");
      list.appendChild(a);
    }
    section.appendChild(list);

    const afterBrand = rail.querySelector(".cc-rail-brand");
    if (afterBrand && afterBrand.nextSibling) rail.insertBefore(section, afterBrand.nextSibling);
    else rail.appendChild(section);
  }

  function patchLandingNav() {
    const ctas = document.querySelector(".lp-nav-ctas");
    if (
      !ctas ||
      ctas.querySelector(".mp-landing-extra") ||
      ctas.querySelector('a[href="command_center_live.html"]')
    ) return;
    const a = document.createElement("a");
    a.href = "command_center_live.html";
    a.className = "lp-nav-link mp-landing-extra";
    a.textContent = "Command Center";
    ctas.insertBefore(a, ctas.firstChild);
  }

  function mount() {
    addStyles();
    const body = document.body;

    if (body.classList.contains("vt-landing-page")) {
      patchLandingNav();
      return;
    }

    const commandRail = body.classList.contains("vt-cc-page")
      ? document.querySelector(".cc-rail")
      : null;

    const sidebar = body.classList.contains("vt-runtime-page")
      ? document.querySelector(".sidebar")
      : body.classList.contains("vt-operator-page")
        ? document.querySelector(".op-sidebar")
        : null;

    if (commandRail) mountCommandRail(commandRail);
    else if (sidebar) mountSidebar(sidebar);
    else mountRail();
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
