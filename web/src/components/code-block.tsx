"use client";

import React, { useState, useEffect } from "react";
import dynamic from "next/dynamic";

type SyntaxHighlighterStyle = Record<string, React.CSSProperties>;

type SyntaxHighlighterProps = {
  children: string;
  language: string;
  style: SyntaxHighlighterStyle;
  className: string;
  customStyle?: React.CSSProperties;
  wrapLongLines: boolean;
};

// Lazy load syntax highlighter to reduce initial bundle size (~84KB savings)
const SyntaxHighlighter = dynamic<SyntaxHighlighterProps>(
  () =>
    import("react-syntax-highlighter").then(
      (mod) => mod.default as React.ComponentType<SyntaxHighlighterProps>,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="subpage-terminal p-4 text-sm">
        <pre className="whitespace-pre-wrap">Loading...</pre>
      </div>
    ),
  },
);

interface CodeBlockProps {
  language: string;
  children: string;
  className?: string;
  customStyle?: React.CSSProperties;
  wrapLongLines?: boolean;
}

export function CodeBlock({
  language,
  children,
  className = "",
  customStyle,
  wrapLongLines = false,
}: CodeBlockProps) {
  const [style, setStyle] = useState<SyntaxHighlighterStyle | null>(null);

  useEffect(() => {
    // Lazy load the style
    import("react-syntax-highlighter/dist/esm/styles/hljs").then((mod) => {
      setStyle(mod.atomOneDark as SyntaxHighlighterStyle);
    });
  }, []);

  if (!style) {
    return (
      <div
        className={`subpage-terminal p-4 text-sm ${className}`}
        style={customStyle}
      >
        <pre className="whitespace-pre-wrap text-green-400">{children}</pre>
      </div>
    );
  }

  return (
    <SyntaxHighlighter
      language={language}
      style={style}
      className={className}
      customStyle={customStyle}
      wrapLongLines={wrapLongLines}
    >
      {children}
    </SyntaxHighlighter>
  );
}
