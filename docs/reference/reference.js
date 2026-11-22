if (window.Redoc) {
  window.Redoc.init("openapi.json", {
    hideDownloadButton: true,
    nativeScrollbars: true,
    sanitize: true,
    sortRequiredPropsFirst: true,
    pathInMiddlePanel: true,
    theme: {
      spacing: { sectionHorizontal: 24, sectionVertical: 28 },
      typography: {
        fontSize: "15px",
        fontFamily: "system-ui, sans-serif",
        headings: { fontFamily: "system-ui, sans-serif" },
        links: { color: "#6b329d", hover: "#4c2371" }
      },
      colors: {
        primary: { main: "#673a8f" },
        text: { primary: "#252334", secondary: "#534e60" }
      },
      sidebar: { backgroundColor: "#f1ecf5", textColor: "#262136" },
      rightPanel: { backgroundColor: "#1e1e2e", textColor: "#cdd6f4" }
    }
  }, document.getElementById("reference"));
} else {
  document.querySelector("#reference > p").firstChild.textContent =
    "The reference could not load. ";
}
