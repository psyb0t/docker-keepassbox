const repository = "https://github.com/psyb0t/docker-keepassbox";

export default {
  title: "KeePassBox",
  tagline: "KeePass vaults over REST and MCP",
  url: "https://psyb0t.github.io",
  baseUrl: "/docker-keepassbox/",
  trailingSlash: true,
  future: { faster: { rspackBundler: true, swcJsLoader: true } },
  organizationName: "psyb0t",
  projectName: "docker-keepassbox",
  onBrokenLinks: "throw",
  markdown: { hooks: { onBrokenMarkdownLinks: "throw" } },
  staticDirectories: ["static", ".assets"],
  presets: [
    ["classic", {
      blog: false,
      docs: {
        path: ".content",
        routeBasePath: "/",
        sidebarPath: "./sidebars.js",
        docItemComponent: "@theme/ApiItem",
        editUrl: repository + "/edit/main/docs/",
      },
    }],
  ],
  plugins: [
    ["docusaurus-plugin-openapi-docs", {
      id: "api",
      docsPluginId: "classic",
      config: {
        keepassbox: {
          specPath: ".assets/reference/openapi.json",
          outputDir: ".content/api",
          showInfoPage: false,
          hideSendButton: true,
          sidebarOptions: { groupPathsBy: "tag" },
        },
      },
    }],
  ],
  themes: [
    "docusaurus-theme-openapi-docs",
    ["@easyops-cn/docusaurus-search-local", {
      docsDir: ".content",
      docsRouteBasePath: "/",
      indexBlog: false,
      hashed: true,
    }],
  ],
  themeConfig: {
    navbar: {
      title: "KeePassBox",
      items: [
        { href: repository, label: "GitHub", position: "right" },
        { href: repository + "/blob/main/CHANGELOG.md", label: "Changelog", position: "right" },
      ],
    },
    colorMode: { defaultMode: "dark", respectPrefersColorScheme: true },
    api: {
      schemaExpansion: { enabled: true, default: 1 },
    },
  },
};
