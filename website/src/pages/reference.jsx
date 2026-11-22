import React, { useEffect } from "react";
import Head from "@docusaurus/Head";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import endpoints from "../../.content/api/sidebar";

const endpointIds = new Set(endpoints.flatMap(({ items }) => items.map(({ id }) => id)));
const legacyOperation = /(?:^#|\/)operation\/([a-z0-9_-]+)$/;

export default function ReferenceRedirect() {
  const apiUrl = useBaseUrl("/api/");

  useEffect(() => {
    const operation = legacyOperation.exec(window.location.hash)?.[1];
    const slug = operation?.replaceAll("_", "-");
    const target = endpointIds.has(`api/${slug}`) ? `${apiUrl}${slug}/` : apiUrl;
    window.location.replace(target);
  }, [apiUrl]);

  return (
    <>
      <Head>
        <title>REST API | KeePassBox</title>
        <meta name="robots" content="noindex" />
      </Head>
      <p>Open the <Link to="/api/">KeePassBox REST API</Link>.</p>
    </>
  );
}
