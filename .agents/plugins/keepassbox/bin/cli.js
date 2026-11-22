#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const token = process.env.KEEPASSBOX_TOKEN ?? "";
let url;
try {
  url = new URL(process.env.KEEPASSBOX_URL);
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    !(url.protocol === "https:" || (loopback && url.protocol === "http:")) ||
    url.username || url.password || url.search || url.hash ||
    !/^[!-~]{32,256}$/.test(token)
  ) {
    throw new Error("Invalid KeePassBox connection settings");
  }
} catch {
  console.error("Configure KEEPASSBOX_URL and KEEPASSBOX_TOKEN for your trusted instance.");
  process.exit(1);
}
url.pathname = url.pathname.replace(/\/+$/, "") + "/mcp";
const proxy = require.resolve("mcp-remote/dist/proxy.js");
const args = [proxy, url.href, "--transport", "http-only", "--header",
  "Authorization: Bearer ${KEEPASSBOX_TOKEN}"];
if (url.protocol === "http:") {
  args.push("--allow-http");
}
const result = spawnSync(process.execPath, args, { stdio: "inherit" });
process.exit(result.status ?? 1);
