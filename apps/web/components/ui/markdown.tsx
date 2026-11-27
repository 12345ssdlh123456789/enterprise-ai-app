'use client';

import React from 'react';

interface MarkdownProps {
  content: string;
  className?: string;
}

const elements: Record<string, React.ComponentType<any>> = {
  h1: ({ children, ...props }) => <h1 className="text-2xl font-bold mt-4 mb-2" {...props}>{children}</h1>,
  h2: ({ children, ...props }) => <h2 className="text-xl font-bold mt-4 mb-2" {...props}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 className="text-lg font-bold mt-3 mb-1" {...props}>{children}</h3>,
  h4: ({ children, ...props }) => <h4 className="text-base font-bold mt-3 mb-1" {...props}>{children}</h4>,
  p: ({ children, ...props }) => <p className="my-2" {...props}>{children}</p>,
  a: ({ children, href, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline hover:text-primary/80" {...props}>
      {children}
    </a>
  ),
  ul: ({ children, ...props }) => <ul className="list-disc list-inside my-2 space-y-1" {...props}>{children}</ul>,
  ol: ({ children, ...props }) => <ol className="list-decimal list-inside my-2 space-y-1" {...props}>{children}</ol>,
  li: ({ children, ...props }) => <li className="ml-4" {...props}>{children}</li>,
  blockquote: ({ children, ...props }) => (
    <blockquote className="border-l-4 border-primary/50 pl-4 italic my-2 text-muted-foreground" {...props}>
      {children}
    </blockquote>
  ),
  code: ({ children, className, ...props }) => {
    // Check if it's inline code (no newlines)
    const isInline = !String(children).includes('\n');
    if (isInline) {
      return <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono" {...props}>{children}</code>;
    }
    return null; // Handled by pre
  },
  pre: ({ children, ...props }) => {
    const code = React.Children.only(children);
    const language = code.props.className?.replace('language-', '') || '';
    return (
      <div className="relative my-3 rounded-lg bg-muted overflow-hidden" {...props}>
        <div className="flex items-center justify-between p-2 border-b border-border bg-muted/50">
          <span className="text-xs text-muted-foreground font-mono">{language}</span>
          <CopyCodeButton code={String(code.props.children)} />
        </div>
        <pre className="p-4 overflow-x-auto"><code className={cn('font-mono text-sm', code.props.className)}>{code.props.children}</code></pre>
      </div>
    );
  },
  strong: ({ children, ...props }) => <strong className="font-semibold" {...props}>{children}</strong>,
  em: ({ children, ...props }) => <em className="italic" {...props}>{children}</em>,
  del: ({ children, ...props }) => <del className="line-through" {...props}>{children}</del>,
  hr: ({ ...props }) => <hr className="my-4 border-border" {...props} />,
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-4">
      <table className="w-full border-collapse" {...props}>{children}</table>
    </div>
  ),
  thead: ({ children, ...props }) => <thead className="bg-muted/50" {...props}>{children}</thead>,
  tbody: ({ children, ...props }) => <tbody {...props}>{children}</tbody>,
  tr: ({ children, ...props }) => <tr className="border-b border-border" {...props}>{children}</tr>,
  th: ({ children, ...props }) => <th className="px-3 py-2 text-left font-semibold border border-border" {...props}>{children}</th>,
  td: ({ children, ...props }) => <td className="px-3 py-2 border border-border" {...props}>{children}</td>,
};

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="text-xs text-muted-foreground hover:text-foreground transition-colors"
    >
      {copied ? '已复制' : '复制'}
    </button>
  );
}

function cn(...classes: (string | undefined | null | false)[]) {
  return classes.filter(Boolean).join(' ');
}

export function Markdown({ content, className }: MarkdownProps) {
  // Simple markdown-like parsing for common elements
  // For production, consider using react-markdown or similar

  const paragraphs = content.split('\n\n').filter(p => p.trim());

  return (
    <div className={cn('prose prose-sm max-w-none', className)}>
      {paragraphs.map((paragraph, i) => {
        // Code blocks
        if (paragraph.startsWith('```')) {
          const lines = paragraph.split('\n');
          const language = lines[0].slice(3).trim();
          const codeContent = lines.slice(1, -1).join('\n');
          return (
            <div key={i} className="relative my-3 rounded-lg bg-muted overflow-hidden">
              <div className="flex items-center justify-between p-2 border-b border-border bg-muted/50">
                <span className="text-xs text-muted-foreground font-mono">{language || 'text'}</span>
                <CopyCodeButton code={codeContent} />
              </div>
              <pre className="p-4 overflow-x-auto"><code className="font-mono text-sm">{codeContent}</code></pre>
            </div>
          );
        }

        // Headings
        if (paragraph.startsWith('# ')) {
          return <h1 key={i} className="text-2xl font-bold mt-4 mb-2">{paragraph.slice(2)}</h1>;
        }
        if (paragraph.startsWith('## ')) {
          return <h2 key={i} className="text-xl font-bold mt-4 mb-2">{paragraph.slice(3)}</h2>;
        }
        if (paragraph.startsWith('### ')) {
          return <h3 key={i} className="text-lg font-bold mt-3 mb-1">{paragraph.slice(4)}</h3>;
        }

        // Blockquote
        if (paragraph.startsWith('> ')) {
          return (
            <blockquote key={i} className="border-l-4 border-primary/50 pl-4 italic my-2 text-muted-foreground">
              {paragraph.slice(2)}
            </blockquote>
          );
        }

        // List items
        if (paragraph.startsWith('- ') || paragraph.startsWith('* ')) {
          const items = paragraph.split('\n').map(line => line.replace(/^[-*]\s+/, ''));
          return (
            <ul key={i} className="list-disc list-inside my-2 space-y-1">
              {items.map((item, idx) => <li key={idx} className="ml-4">{item}</li>)}
            </ul>
          );
        }

        // Numbered list
        if (/^\d+\.\s/.test(paragraph)) {
          const items = paragraph.split('\n').map(line => line.replace(/^\d+\.\s+/, ''));
          return (
            <ol key={i} className="list-decimal list-inside my-2 space-y-1">
              {items.map((item, idx) => <li key={idx} className="ml-4">{item}</li>)}
            </ol>
          );
        }

        // Horizontal rule
        if (paragraph.trim() === '---' || paragraph.trim() === '***') {
          return <hr key={i} className="my-4 border-border" />;
        }

        // Regular paragraph with inline formatting
        return (
          <p key={i} className="my-2 leading-relaxed">
            {parseInline(paragraph)}
          </p>
        );
      })}
    </div>
  );
}

function parseInline(text: string): React.ReactNode {
  // Simple inline parsing: **bold**, *italic*, `code`, [link](url)
  const parts = text.split(/(\*\*.*?\*\*|\*.*?\*|`.*?`|\[.*?\]\(.*?\))/);

  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*') && !part.startsWith('**')) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono">{part.slice(1, -1)}</code>;
    }
    // Link: [text](url)
    const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
    if (linkMatch) {
      return (
        <a key={i} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-primary underline hover:text-primary/80">
          {linkMatch[1]}
        </a>
      );
    }
    return <span key={i}>{part}</span>;
  });
}