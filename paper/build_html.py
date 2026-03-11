#!/usr/bin/env python3
"""
Build a unified HTML version of the white paper from markdown chapters.
Includes all charts, diagrams, and conceptual images.
"""
import os
import re

PAPER_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(PAPER_DIR, "assets")
OUTPUT = os.path.join(PAPER_DIR, "paper.html")

# Chapter files in order
CHAPTERS = [
    "00-index.md",
    "01-introduction.md",
    "02-related-work.md",
    "03-design-principles.md",
    "04-architecture.md",
    "05-cryptographic-identity.md",
    "06-transport-layer.md",
    "07-experimental-design.md",
    "08-results.md",
    "09-cross-model-communication.md",
    "10-discussion.md",
    "11-conclusion.md",
    "12-references.md",
]

# Map chapter numbers to images/charts to insert
MEDIA_INSERTIONS = {
    "00-index.md": [
        ("after_title", "hero-mailbox.png", "The Mailbox Principle — where simplicity meets infrastructure"),
    ],
    "02-related-work.md": [
        ("end", "chart-protocol-comparison.png", "Figure 1. Protocol feature comparison across AgentAZAll, MCP, A2A, and ACP"),
    ],
    "04-architecture.md": [
        ("after_heading:4.4", "diagram-architecture.png", "Figure 2. System architecture overview"),
        ("after_heading:4.6", "heterogeneous-endpoints.png", "Figure 3. Heterogeneous endpoints — identical protocol, diverse services"),
    ],
    "05-cryptographic-identity.md": [
        ("end", "crypto-signature.png", "Figure 4. Cryptographic identity travels with the message, not the transport"),
    ],
    "06-transport-layer.md": [
        ("after_heading:6.5", "transport-agnostic.png", "Figure 5. Three transports, one destination"),
    ],
    "08-results.md": [
        ("after_heading:8.1", "chart-messages-per-round.png", "Figure 6. Message volume by transport round"),
        ("after_heading:8.2", "chart-per-bot-total.png", "Figure 7. Per-bot message output across all rounds"),
        ("after_heading:8.3", "chart-latency-comparison.png", "Figure 8. Inference latency by bot and transport"),
        ("after:Finding 2", "chart-transport-scaling.png", "Figure 9. Transport latency vs. message throughput"),
        ("after:Finding 4", "chart-gpu-contention.png", "Figure 10. GPU contention: dedicated vs. shared inference"),
        ("after:8.4", "chart-overhead-pie.png", "Figure 11. Time budget per message cycle"),
    ],
    "09-cross-model-communication.md": [
        ("after_heading:9.3", "multi-model-conversation.png", "Figure 12. Four architecturally distinct models in autonomous conversation"),
    ],
}


def md_to_html(md_text):
    """Convert markdown to HTML (simple converter, no external deps)."""
    lines = md_text.split("\n")
    html_parts = []
    in_code = False
    in_table = False
    in_list = False
    table_rows = []
    list_items = []

    def flush_table():
        nonlocal table_rows, in_table
        if not table_rows:
            return ""
        result = '<table class="data-table">\n'
        for i, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|") if c.strip() != ""]
            if i == 0:
                result += "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead>\n<tbody>\n"
            elif all(set(c.strip()) <= set("-: ") for c in cells):
                continue  # separator row
            else:
                result += "<tr>" + "".join(f"<td>{inline_format(c)}</td>" for c in cells) + "</tr>\n"
        result += "</tbody></table>\n"
        table_rows = []
        in_table = False
        return result

    def flush_list():
        nonlocal list_items, in_list
        if not list_items:
            return ""
        result = "<ul>\n" + "".join(f"<li>{inline_format(li)}</li>\n" for li in list_items) + "</ul>\n"
        list_items = []
        in_list = False
        return result

    def inline_format(text):
        """Apply inline formatting: bold, italic, code, links."""
        # Code spans
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        # Bold
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        return text

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith("```"):
            if in_table:
                html_parts.append(flush_table())
            if in_list:
                html_parts.append(flush_list())
            if in_code:
                html_parts.append("</code></pre>\n")
                in_code = False
            else:
                lang = line.strip()[3:].strip()
                html_parts.append(f'<pre><code class="language-{lang}">')
                in_code = True
            i += 1
            continue

        if in_code:
            html_parts.append(line.replace("<", "&lt;").replace(">", "&gt;") + "\n")
            i += 1
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            if in_list:
                html_parts.append(flush_list())
            in_table = True
            table_rows.append(line)
            i += 1
            continue
        elif in_table:
            html_parts.append(flush_table())

        # List items
        if re.match(r'^[-*]\s+', line.strip()):
            if in_table:
                html_parts.append(flush_table())
            in_list = True
            list_items.append(re.sub(r'^[-*]\s+', '', line.strip()))
            i += 1
            continue
        elif re.match(r'^\d+\.\s+', line.strip()):
            if in_table:
                html_parts.append(flush_table())
            in_list = True
            list_items.append(re.sub(r'^\d+\.\s+', '', line.strip()))
            i += 1
            continue
        elif in_list and line.strip() == "":
            html_parts.append(flush_list())
            i += 1
            continue
        elif in_list and line.startswith("   "):
            list_items[-1] += " " + line.strip()
            i += 1
            continue
        elif in_list:
            html_parts.append(flush_list())

        # Headings
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            text = inline_format(m.group(2).strip())
            slug = re.sub(r'[^a-z0-9]+', '-', m.group(2).lower()).strip('-')
            html_parts.append(f'<h{level} id="{slug}">{text}</h{level}>\n')
            i += 1
            continue

        # Horizontal rules
        if line.strip() in ("---", "***", "___") and not line.startswith("From:"):
            html_parts.append("<hr>\n")
            i += 1
            continue

        # Empty lines
        if line.strip() == "":
            i += 1
            continue

        # Paragraphs
        para_lines = [line]
        while i + 1 < len(lines) and lines[i+1].strip() and not lines[i+1].startswith("#") \
              and not lines[i+1].strip().startswith("```") and not lines[i+1].strip().startswith("|") \
              and not re.match(r'^[-*]\s+', lines[i+1].strip()) \
              and not re.match(r'^\d+\.\s+', lines[i+1].strip()) \
              and lines[i+1].strip() not in ("---", "***", "___"):
            i += 1
            para_lines.append(lines[i])

        text = inline_format(" ".join(l.strip() for l in para_lines))
        # Skip navigation links
        if text.startswith("<em>Next:") or text.startswith("<em>Return to"):
            i += 1
            continue
        html_parts.append(f"<p>{text}</p>\n")
        i += 1

    if in_table:
        html_parts.append(flush_table())
    if in_list:
        html_parts.append(flush_list())
    if in_code:
        html_parts.append("</code></pre>\n")

    return "".join(html_parts)


def insert_media(html, chapter_file, media_list):
    """Insert images/charts at specified positions in the HTML."""
    for position, filename, caption in media_list:
        filepath = f"assets/{filename}"
        if not os.path.exists(os.path.join(PAPER_DIR, filepath)):
            # Try SVG
            svg = filepath.replace(".png", ".svg")
            if os.path.exists(os.path.join(PAPER_DIR, svg)):
                filepath = svg

        img_html = f'''
<figure class="paper-figure">
    <img src="{filepath}" alt="{caption}" loading="lazy">
    <figcaption>{caption}</figcaption>
</figure>
'''
        if position == "after_title":
            # Insert after first h2
            html = re.sub(r'(</h2>)', r'\1' + img_html, html, count=1)
        elif position == "end":
            html += img_html
        elif position.startswith("after_heading:"):
            section = position.split(":")[1]
            pattern = rf'(<h\d[^>]*id="[^"]*{re.escape(section.replace(".", "-").lower())}[^"]*"[^>]*>.*?</h\d>)'
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                insert_pos = m.end()
                html = html[:insert_pos] + img_html + html[insert_pos:]
        elif position.startswith("after:"):
            marker = position.split(":", 1)[1]
            idx = html.find(marker)
            if idx >= 0:
                # Find end of containing paragraph/section
                end_p = html.find("</p>", idx)
                if end_p >= 0:
                    insert_pos = end_p + 4
                    html = html[:insert_pos] + img_html + html[insert_pos:]

    return html


def build():
    """Build the unified HTML paper."""
    # Read all chapters
    chapter_html = []
    for ch_file in CHAPTERS:
        path = os.path.join(PAPER_DIR, ch_file)
        if not os.path.exists(path):
            print(f"  [WARN] Missing: {ch_file}")
            continue

        with open(path, "r", encoding="utf-8") as f:
            md = f.read()

        html = md_to_html(md)

        # Insert media
        if ch_file in MEDIA_INSERTIONS:
            html = insert_media(html, ch_file, MEDIA_INSERTIONS[ch_file])

        chapter_id = ch_file.replace(".md", "")
        chapter_html.append(f'<section id="{chapter_id}" class="chapter">\n{html}\n</section>')

    body = "\n\n".join(chapter_html)

    full_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Mailbox Principle — Filesystem-First Communication for Autonomous AI Agents</title>
<style>
:root {{
    --bg: #ffffff;
    --text: #1a1a2e;
    --text-secondary: #4a4a6a;
    --accent: #2563eb;
    --accent-light: #dbeafe;
    --border: #e2e8f0;
    --code-bg: #f1f5f9;
    --table-stripe: #f8fafc;
    --figure-bg: #fafbfc;
    --max-width: 820px;
    --font-serif: "Georgia", "Times New Roman", serif;
    --font-sans: "Segoe UI", system-ui, -apple-system, sans-serif;
    --font-mono: "Cascadia Code", "Fira Code", "Consolas", monospace;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: var(--font-serif);
    font-size: 17px;
    line-height: 1.75;
    color: var(--text);
    background: var(--bg);
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 40px 24px 80px;
}}

/* Headings */
h1 {{
    font-family: var(--font-sans);
    font-size: 2.4em;
    font-weight: 800;
    line-height: 1.2;
    margin: 0 0 0.3em;
    color: var(--text);
    letter-spacing: -0.02em;
}}

h2 {{
    font-family: var(--font-sans);
    font-size: 1.6em;
    font-weight: 700;
    line-height: 1.3;
    margin: 2.5em 0 0.6em;
    color: var(--text);
    padding-bottom: 0.3em;
    border-bottom: 2px solid var(--accent);
}}

h3 {{
    font-family: var(--font-sans);
    font-size: 1.25em;
    font-weight: 600;
    margin: 2em 0 0.5em;
    color: var(--text);
}}

h4 {{
    font-family: var(--font-sans);
    font-size: 1.1em;
    font-weight: 600;
    margin: 1.5em 0 0.4em;
    color: var(--text-secondary);
}}

/* Paragraphs */
p {{
    margin: 0 0 1.2em;
    text-align: justify;
    hyphens: auto;
}}

/* Links */
a {{
    color: var(--accent);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.2s;
}}
a:hover {{ border-bottom-color: var(--accent); }}

/* Code */
code {{
    font-family: var(--font-mono);
    font-size: 0.88em;
    background: var(--code-bg);
    padding: 2px 6px;
    border-radius: 4px;
    color: #c7254e;
}}

pre {{
    background: #0f172a;
    color: #e2e8f0;
    padding: 20px 24px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 1.5em 0;
    line-height: 1.5;
}}

pre code {{
    background: none;
    color: inherit;
    padding: 0;
    font-size: 0.85em;
}}

/* Tables */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1.5em 0;
    font-family: var(--font-sans);
    font-size: 0.9em;
}}

.data-table th {{
    background: var(--accent);
    color: white;
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
    font-size: 0.9em;
}}

.data-table td {{
    padding: 9px 14px;
    border-bottom: 1px solid var(--border);
}}

.data-table tbody tr:nth-child(even) {{
    background: var(--table-stripe);
}}

.data-table tbody tr:hover {{
    background: var(--accent-light);
}}

/* Lists */
ul, ol {{
    margin: 0.8em 0 1.2em 1.8em;
}}
li {{ margin: 0.3em 0; }}

/* Figures */
.paper-figure {{
    margin: 2em 0;
    text-align: center;
    background: var(--figure-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
}}

.paper-figure img {{
    max-width: 100%;
    height: auto;
    border-radius: 4px;
}}

.paper-figure figcaption {{
    font-family: var(--font-sans);
    font-size: 0.85em;
    color: var(--text-secondary);
    margin-top: 12px;
    font-style: italic;
}}

/* Chapter sections */
.chapter {{
    margin-bottom: 3em;
}}

#\\30 0-index {{
    text-align: center;
    margin-bottom: 4em;
}}

#\\30 0-index h1 {{
    font-size: 2.8em;
    margin-bottom: 0.1em;
}}

#\\30 0-index h2 {{
    border: none;
    font-size: 1.3em;
    font-weight: 400;
    color: var(--text-secondary);
    margin-top: 0;
}}

#\\30 0-index h3 {{
    font-size: 1.1em;
    font-weight: 400;
    color: var(--text-secondary);
}}

/* Horizontal rules */
hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 3em 0;
}}

/* Strong in paragraphs (finding labels) */
p > strong:first-child {{
    color: var(--accent);
}}

/* Table of Contents */
#\\30 0-index ol, #\\30 0-index ul {{
    list-style: none;
    margin: 1em 0;
    padding: 0;
}}

#\\30 0-index li {{
    padding: 0.3em 0;
}}

/* Print styles */
@media print {{
    body {{
        font-size: 11pt;
        max-width: none;
        padding: 0;
    }}
    .paper-figure {{
        break-inside: avoid;
    }}
    .chapter {{
        break-before: page;
    }}
    pre {{
        background: #f5f5f5 !important;
        color: #333 !important;
        border: 1px solid #ddd;
    }}
}}

/* Responsive */
@media (max-width: 768px) {{
    body {{
        font-size: 15px;
        padding: 20px 16px 60px;
    }}
    h1 {{ font-size: 1.8em; }}
    h2 {{ font-size: 1.3em; }}
    .data-table {{ font-size: 0.8em; }}
    .data-table td, .data-table th {{ padding: 6px 8px; }}
}}
</style>
</head>
<body>

{body}

<footer style="text-align: center; margin-top: 4em; padding: 2em 0; border-top: 1px solid var(--border); font-family: var(--font-sans); font-size: 0.85em; color: var(--text-secondary);">
    <p>&copy; 2026 Gregor H. Max Koch, MSc. All rights reserved.</p>
    <p>Correspondence: <a href="https://github.com/cronos3k/AgentAZAll">github.com/cronos3k/AgentAZAll</a></p>
</footer>

</body>
</html>'''

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"\n  HTML paper written to: {OUTPUT}")
    print(f"  Size: {os.path.getsize(OUTPUT) // 1024}KB")


if __name__ == "__main__":
    print("Building unified HTML paper...")
    build()
