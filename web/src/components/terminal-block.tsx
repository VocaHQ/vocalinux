"use client";

import React, { useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";

export function TerminalBlock({
  command,
  displayCommand,
  label = "terminal",
}: {
  command: string;
  displayCommand: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }, [command]);

  return (
    <div className="terminal-panel min-w-0">
      <div className="terminal-chrome">
        <span className="window-title">{label}</span>
        <button
          type="button"
          onClick={handleCopy}
          title={copied ? "Copied" : "Copy"}
          className={`terminal-copy${copied ? " is-copied" : ""}`}
          aria-label={copied ? "Copied to clipboard" : "Copy to clipboard"}
        >
          {copied ? (
            <Check className="h-4 w-4" strokeWidth={2} />
          ) : (
            <Copy className="h-4 w-4" strokeWidth={1.75} />
          )}
        </button>
      </div>
      <pre className="max-w-full min-w-0 overflow-x-auto break-all">
        <span className="terminal-prompt">$ </span>
        {displayCommand}
      </pre>
    </div>
  );
}
