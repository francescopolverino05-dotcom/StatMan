/** Shared StatMan app chrome — Matches-first nav (EnjoyFootball-style shell). */

const PRIMARY = [
  { href: "/", id: "home", label: "Matches" },
  { href: "/match", id: "match", label: "Workspace" },
];

const LABS = [
  { href: "/demo", id: "demo", label: "Open-data demo" },
  { href: "/season", id: "season", label: "Season" },
  { href: "/video", id: "video", label: "Film tags" },
  { href: "/review", id: "review", label: "Review" },
  { href: "/import", id: "import", label: "Import" },
  { href: "/api/docs", id: "api", label: "API" },
];

/**
 * Replace or fill `#app-nav` with the product shell.
 * @param {{ active?: string }} opts active link id
 */
export function mountAppNav({ active = "home" } = {}) {
  const host = document.getElementById("app-nav");
  if (!host) return;

  const primary = PRIMARY.map(
    (l) =>
      `<a href="${l.href}" class="${l.id === active ? "is-active" : ""}">${l.label}</a>`
  ).join("");

  const labs = LABS.map(
    (l) =>
      `<a href="${l.href}" class="${l.id === active ? "is-active" : ""}">${l.label}</a>`
  ).join("");

  host.innerHTML = `
    <nav class="topnav topnav--app" aria-label="StatMan">
      <a class="topnav__brand" href="/">StatMan</a>
      <div class="topnav__links">${primary}</div>
      <details class="topnav__labs">
        <summary>Labs</summary>
        <div class="topnav__labs-menu">${labs}</div>
      </details>
    </nav>
  `;
}

/** Common document head bits for installable / mobile feel. */
export function applyAppMeta() {
  const head = document.head;
  if (!head) return;
  if (!document.querySelector('meta[name="theme-color"]')) {
    const m = document.createElement("meta");
    m.name = "theme-color";
    m.content = "#1f6b3a";
    head.appendChild(m);
  }
  if (!document.querySelector('meta[name="apple-mobile-web-app-capable"]')) {
    const m = document.createElement("meta");
    m.name = "apple-mobile-web-app-capable";
    m.content = "yes";
    head.appendChild(m);
  }
  if (!document.querySelector('link[rel="manifest"]')) {
    const link = document.createElement("link");
    link.rel = "manifest";
    link.href = "/static/manifest.webmanifest";
    head.appendChild(link);
  }
}
