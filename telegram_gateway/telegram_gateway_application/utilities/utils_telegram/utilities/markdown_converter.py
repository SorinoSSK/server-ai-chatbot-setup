# =============================================================================
# File        : markdown_converter.py
# Description : Converts an agent-produced reply's own Markdown-ish formatting into Telegram-safe HTML, deterministically.
# Author      : SorinoSSK
# Created On  : 2026-09-16
#
# Features    :
#   - to_telegram_html() - the one public entry point. Escapes every HTML-special character first, then converts
#     fenced/inline code, headers, bullet lists, bold, and italic into Telegram's own supported HTML tags.
#
# Notes       :
#   - Exists because bot_sanctuary's own persona (libraries/claude/chat.json) writes ordinary CommonMark-style
#     Markdown (**bold**, # headers, - bullets) - the convention essentially every LLM defaults to - which does
#     not match either of Telegram's own Markdown parse_mode dialects (both use a single *asterisk* for bold,
#     support no headers/bullet lists at all, and MarkdownV2 additionally demands escaping over a dozen reserved
#     characters). Rather than depending on the persona consistently hand-writing Telegram-specific syntax turn
#     after turn (already shown unreliable in practice), this module accepts whatever Markdown-ish text the
#     model naturally writes and converts it deterministically - the persona's own wording is left untouched.
#   - Telegram's HTML parse_mode only requires escaping '&'/'<'/'>' - see
#     https://core.telegram.org/bots/api#html-style - far less fragile than MarkdownV2's escaping requirements,
#     and forgiving of an unmatched/stray formatting character (see the "degrades gracefully" Note below).
#   - Ordering is deliberate and safety-critical, in _convert(): the entire raw text is HTML-escaped exactly
#     once, first, before any tag is ever inserted - a tag is only ever introduced by this module's own
#     substitutions afterwards, so neither the model's own text nor a user's original message content (echoed
#     back, if ever) can inject an unintended tag. Fenced/inline code spans are then pulled out into opaque
#     placeholders *before* header/bullet/bold/italic conversion runs, so formatting characters that happen to
#     appear inside a code span (e.g. `**kwargs` in a Python snippet) are never themselves reinterpreted as
#     Telegram formatting - restored verbatim at the very end.
#   - Degrades gracefully by construction, unlike relying on Telegram's own parser directly: every substitution
#     here only ever emits a matched, balanced tag pair - an unmatched/stray delimiter (e.g. one lone trailing
#     '*' with no closing partner) simply never matches any pattern and is left as a harmless literal character,
#     rather than causing Telegram's own parser to reject the whole send with a 400 "can't parse entities" error.
#   - Nesting guard: _BOLD_DOUBLE_PATTERN/_BOLD_SINGLE_PATTERN/_ITALIC_PATTERN's own capture groups all exclude
#     '<' and '\n'. Without this, a bold/italic span could match straight across a tag boundary an *earlier*
#     step in the same conversion already inserted (a header's own '<b>...</b>', or an earlier bold pass, ahead
#     of the italic pass that runs last) - e.g. "**bold and _italic** text_" would otherwise convert to
#     "<b>bold and <i>italic</b> text</i>", invalid overlapping tags Telegram rejects outright, not the graceful
#     degradation described above. Excluding '<' stops a match the instant it would cross an already-inserted
#     tag, leaving the outer delimiters as harmless literal text instead; excluding '\n' additionally stops
#     emphasis from ever spanning multiple lines/paragraphs, which shrinks the blast radius of any stray
#     unmatched delimiter still further (it can no longer swallow the rest of a long, multi-paragraph reply
#     looking for its missing partner).
#   - Italic (_underscore_) conversion is deliberately guarded against matching inside an identifier like
#     "SESSION_ID_MARKER" - see _ITALIC_PATTERN's own comment. bot_sanctuary's persona is explicitly a
#     technology-focused one (see chat.json's own "Technology Interests" section) and routinely discusses
#     snake_case identifiers; a naive '_(.+?)_' pattern would otherwise mangle those into italics.
#   - Deliberately narrow scope - only the constructs the persona actually produces (bold, italic, inline/fenced
#     code, headers, bullet lists) are handled. Telegram HTML also supports <u>/<s>/<tg-spoiler>/<blockquote>,
#     none of which are converted here since nothing in the persona's own instructions asks for them.
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
            Already HTML-escaped text (see _convert()) - code span content is therefore already safe to wrap
            in a tag verbatim, with no further escaping needed here.

    Returns:
        tuple[str, list[str]]:
            (text with every code span replaced by a \\x00CODE<index>\\x00 placeholder, the ordered list of
            converted HTML each placeholder maps to - restored by _restore_code_spans() once every other
            substitution has run).

    Notes:
        - Fenced blocks are extracted before inline spans, so a fenced block's own backticks (there are none by
          definition, but any inline-code-looking content inside it) are never separately matched as inline code.
        - A fenced block's optional language identifier (```python) is preserved as an HTML class on <code>, per
          Telegram's own documented syntax-highlighting convention - harmless if Telegram's client doesn't
          recognise the language, still renders as a plain code block either way.
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
            A reply's raw text content, as produced by the agent - ordinary CommonMark-style Markdown assumed,
            not yet valid for any Telegram parse_mode.

    Returns:
        str:
            text with every HTML-special character escaped and every recognised Markdown construct (fenced/
            inline code, headers, bullet lists, bold, italic) converted to Telegram's own supported HTML tags -
            ready to send with parse_mode="HTML".

    Notes:
        - See this module's own header Notes for the full design/safety reasoning behind the ordering below.
        - Never raises - a construct this module doesn't recognise is simply left as literal text, already
          HTML-escaped and therefore always safe to send regardless.
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
