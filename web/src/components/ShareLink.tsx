"use client";

import { useEffect, useState } from "react";

/**
 * Hands a link on: the phone's share sheet where there is one (how a link
 * actually gets to someone at the table — a chat app), else the clipboard.
 * The URL is also on the button as data-url, for tests.
 */
export default function ShareLink({
  url,
  title,
  label = "Share",
  testId,
  className,
}: {
  url: string;
  title?: string;
  label?: string;
  testId: string;
  className: string;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  async function share() {
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ url, title });
        return;
      } catch (e) {
        // Dismissing the sheet isn't a failure to fall back from.
        if (e instanceof DOMException && e.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // No clipboard either (insecure origin, denied): show it to copy by hand.
      window.prompt("Copy this link", url);
    }
  }

  return (
    <button type="button" onClick={share} data-testid={testId} data-url={url} className={className}>
      {copied ? "Copied" : label}
    </button>
  );
}
