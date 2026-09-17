# =============================================================================
# File        : markdown_converter.py
# Description : Converts an agent-produced reply's own Markdown-ish formatting into Telegram-safe HTML, deterministically.
# Author      : SorinoSSK
# Created On  : 2026-09-16
#
# Features    :
#   - to_telegram_html() - the one public entry point, escaping every HTML-special character then converting fenced/inline code, headers, bullet lists, bold, and italic into Telegram's own supported HTML tags.
#
# Notes       :
#   - Exists because bot_sanctuary's persona writes ordinary CommonMark-style Markdown, which matches neither of Telegram's own Markdown parse_mode dialects - see README.md for the full rationale.
#   - Every substitution only ever emits a matched, balanced tag pair, so an unmatched/stray delimiter degrades gracefully to a literal character instead of causing Telegram to reject the whole send.
#   - Code spans are extracted into opaque placeholders before any other conversion runs, so formatting characters inside them are never reinterpreted, and are restored verbatim at the end.
#   - Bold/italic patterns exclude '<' and newlines from their own capture groups, guarding against matching across a tag an earlier step already inserted, or spanning multiple lines.
#   - Italic conversion is deliberately guarded against matching inside a snake_case identifier.
#
# =============================================================================
# I M P O R T   H E A D E R

import re
import html

# =============================================================================
# G L O B A L   V A R I A B L E

# Fenced code block - ```<optional language>\n...\n``` - captured before anything else so its own content is
# never reinterpreted as bold/italic/header/bullet formatting. DOTALL so '.' spans the block's own newlines.
_FENCED_CODE_PATTERN = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)

# Inline code - `...` - captured next, same reasoning as the fenced pattern above, one line at a time.
_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+?)`")

# A Markdown header line - one or more leading '#' followed by a space - converted to a bold lead-in line
# instead, since Telegram's HTML mode has no header tag of its own. re.MULTILINE so '^' matches per line.
_HEADER_PATTERN = re.compile(r"^#{1,6}[ \t]+(.+)$", re.MULTILINE)

# A Markdown bullet list marker ('-' or '*' followed by a space, at the start of a line) - converted to a plain
# '•' character, which Telegram renders as-is with no escaping/tag needed. Deliberately run before the bold/
# italic patterns below, so a leading '*' used as a list marker is never mistaken for an opening bold delimiter.
_BULLET_PATTERN = re.compile(r"^[ \t]*[-*][ \t]+", re.MULTILINE)

# Bold - '**text**' (CommonMark, what the model actually writes by default) matched before single-asterisk bold,
# so a double-asterisk pair is never left with one asterisk over from a greedy single-asterisk match instead.
# The capture group excludes '<'/'\n' - see "Nesting guard" in this module's own header Notes for why: without
# it, this pattern (and the two below) could match straight across a tag boundary an *earlier* step in this
# same conversion already inserted (e.g. a header's own '<b>...</b>'), producing invalid overlapping HTML that
# Telegram's parser rejects outright rather than the intended graceful degrade-to-literal-text.
_BOLD_DOUBLE_PATTERN = re.compile(r"\*\*([^<\n]+?)\*\*")

# Bold - '*text*' (Telegram's own native syntax, in case the model uses it directly instead of/alongside '**').
# Same '<'/'\n' exclusion as _BOLD_DOUBLE_PATTERN above, same reason.
_BOLD_SINGLE_PATTERN = re.compile(r"\*([^<\n]+?)\*")

# Italic - '_text_' - guarded on both sides against a word character immediately outside the underscore pair,
# so "SESSION_ID_MARKER" (underscores flanked by word characters throughout) is never matched, while " _mm..._ "
# (underscores flanked by whitespace/punctuation) is. This mirrors CommonMark's own "flanking" emphasis rule,
# applied narrowly enough to protect snake_case identifiers without needing a full CommonMark implementation.
# Same '<'/'\n' exclusion as _BOLD_DOUBLE_PATTERN above, same reason - this pattern runs last, so it's the one
# most exposed to matching across a '<b>'/'</b>' a preceding header or bold substitution just inserted.
_ITALIC_PATTERN = re.compile(r"(?<!\w)_(?!_)([^<\n]+?)(?<!_)_(?!\w)")

_CODE_PLACEHOLDER = "\x00CODE{index}\x00"

# =============================================================================

def _extract_code_spans(text: str) -> tuple[str, list[str]]:
    """
    Replaces every fenced/inline code span in text with an opaque placeholder, returning both the placeholder'd
    text and the list of already-converted <pre>/<code> HTML each placeholder stands in for.

    Args:
        text (str):
            Already HTML-escaped text - code span content is therefore already safe to wrap in a tag verbatim, with no further escaping needed here.

    Returns:
        tuple[str, list[str]]:
            (text with every code span replaced by a placeholder, the ordered list of converted HTML each placeholder maps to - restored by _restore_code_spans() once every other substitution has run).

    Notes:
        - Fenced blocks are extracted before inline spans, so nothing inside a fenced block is separately matched as inline code.
        - A fenced block's optional language identifier is preserved as an HTML class on <code>, per Telegram's own syntax-highlighting convention.
    """
    spans: list[str] = []

    def _store(html_content: str) -> str:
        spans.append(html_content)
        return _CODE_PLACEHOLDER.format(index=len(spans) - 1)

    def _replace_fenced(match: re.Match) -> str:
        language, code = match.group(1), match.group(2)
        code = code.strip("\n")
        opening = f'<pre><code class="language-{language}">' if language else "<pre><code>"
        return _store(f"{opening}{code}</code></pre>")

    def _replace_inline(match: re.Match) -> str:
        return _store(f"<code>{match.group(1)}</code>")

    text = _FENCED_CODE_PATTERN.sub(_replace_fenced, text)
    text = _INLINE_CODE_PATTERN.sub(_replace_inline, text)
    return text, spans

def _restore_code_spans(text: str, spans: list[str]) -> str:
    """
    Substitutes every \\x00CODE<index>\\x00 placeholder in text back for its converted HTML.

    Args:
        text (str):
            Text produced by _extract_code_spans(), with every other conversion already applied.

        spans (list[str]):
            The list returned alongside text by _extract_code_spans().

    Returns:
        str:
            text with every placeholder replaced by its original converted HTML.
    """
    for index, converted in enumerate(spans):
        text = text.replace(_CODE_PLACEHOLDER.format(index=index), converted)
    return text

def to_telegram_html(text: str) -> str:
    """
    Converts text's own Markdown-ish formatting into Telegram-safe HTML, deterministically.

    Args:
        text (str):
            A reply's raw text content, as produced by the agent - ordinary CommonMark-style Markdown assumed, not yet valid for any Telegram parse_mode.

    Returns:
        str:
            text with every HTML-special character escaped and every recognised Markdown construct converted to Telegram's own supported HTML tags - ready to send with parse_mode="HTML".

    Notes:
        - See this module's own header Notes for the design/safety reasoning behind the conversion ordering.
        - Never raises - a construct this module doesn't recognise is left as literal, already-escaped text.
    """
    escaped = html.escape(text, quote=False)
    without_code, code_spans = _extract_code_spans(escaped)

    converted = _HEADER_PATTERN.sub(lambda match: f"<b>{match.group(1)}</b>", without_code)
    converted = _BULLET_PATTERN.sub("• ", converted)
    converted = _BOLD_DOUBLE_PATTERN.sub(lambda match: f"<b>{match.group(1)}</b>", converted)
    converted = _BOLD_SINGLE_PATTERN.sub(lambda match: f"<b>{match.group(1)}</b>", converted)
    converted = _ITALIC_PATTERN.sub(lambda match: f"<i>{match.group(1)}</i>", converted)

    return _restore_code_spans(converted, code_spans)

# =============================================================================
