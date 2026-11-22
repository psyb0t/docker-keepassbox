import React from "react";
import CodeBlock from "@theme/CodeBlock";

export default function ApiExplorer({ item }) {
  return (item["x-codeSamples"] ?? []).map(({ lang, label, source }) => (
    <CodeBlock key={source} language={lang === "curl" ? "bash" : lang} title={label ?? lang}>
      {source}
    </CodeBlock>
  ));
}
