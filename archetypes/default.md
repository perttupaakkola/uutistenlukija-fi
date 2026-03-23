+++
date = '{{ .Date }}'
draft = true
title = '{{ replace .File.ContentBaseName "-" " " | title }}'
+++

# Optional frontmatter fields:
# 
# journalist_note: |
#   Editorial note from the journalist (Markdown supported).
#   Appears in a styled box at the end of the article.
#
# content_type: "article" | "analysis" | "opinion"
#   Default: "article"
#   "analysis" uses a different layout optimized for in-depth content
#   with multi-column layout and prominent author byline.
#
# editorial_reviewed: true
#   Set to true if the editorial team has reviewed/fact-checked this piece.
#   Only shown for content_type: "analysis" articles.
#
# author_image: /path/to/image.jpg
#   Photo of the author, shown in author box at bottom of article.
#
# author_title: "Title or expertise area"
#   Role/title shown in author byline (e.g., "Science Editor", "Political Correspondent").
#
# author_bio: "Short bio"
#   Brief biography shown in author box at end of article.
