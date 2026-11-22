const endpoints = require("./.content/api/sidebar").default;

module.exports = {
  docs: [
    "index",
    "install",
    {
      type: "category",
      label: "REST API",
      link: { type: "doc", id: "api" },
      items: endpoints,
    },
    "mcp",
  ],
};
