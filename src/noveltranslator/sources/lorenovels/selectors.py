"""Selectors verified against Lorenovels HTML on 2026-09-26.

The source is a WordPress block theme. Selectors intentionally have semantic
fallbacks because the site can change class names without changing content.
"""

NOVEL_TITLE = ("h2.wp-block-heading", "meta[property='og:title']")
AUTHOR = ("h2.wp-block-heading", "[rel='author']")
DESCRIPTION = ("meta[property='og:description']", ".entry-content p")
COVER = ("meta[property='og:image']", "meta[name='twitter:image']")
CHAPTER_LINKS = "a[href]"
CHAPTER_CONTENT = ("div.entry-content.wp-block-post-content", ".entry-content")

REMOVE_SELECTORS = (
    "script", "style", "noscript", "header", "footer", "nav", "form",
    ".site-comments", ".wp-block-comments", ".comments-area", ".sharedaddy",
    ".wp-block-post-navigation-link", ".wp-block-post-navigation", ".related-posts",
    ".wp-block-buttons", ".addtoany_share_save_container",
)
