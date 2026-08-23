"use client";

import React, { useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";

export function TerminalPrompt() {
  return (
    <span className="terminal-prompt">
      <span className="terminal-user">user</span>
      <span className="terminal-at">@</span>
      <span className="terminal-host">linux</span>
      <span className="terminal-path">:~</span>
      <span className="terminal-hash">$ </span>
    </span>
  );
}

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
        <span className="window-title">{label}</span>
        <span className="linux-controls" aria-hidden="true">
          <i></i>
          <i></i>
          <i className="close"></i>
        </span>
      </div>
      <pre className="max-w-full min-w-0 overflow-x-auto break-all">
        <TerminalPrompt />
        {displayCommand}
      </pre>
    </div>
  );
}
