"""Centralized selectors for grok.com/imagine UI.

Source: inspector snapshots in CLAUDE.md. Always use prefix matching (`^=`)
for aria-labels because Grok mutates label suffixes (e.g. "Submit prompt"
vs "Submit"). Never hardcode full strings.
"""

# /imagine input page
PROMPT_INPUT = '[contenteditable="true"]'
PROMPT_INPUT_EMPTY = 'p.is-empty.is-editor-empty'
SUBMIT = 'button[aria-label^="Submit"]'
UPLOAD = 'button[aria-label^="Upload"]'

MODE_GROUP = 'div[aria-label^="Generation mode"]'
MODE_IMAGE = 'button[aria-label^="Image"][role="radio"]'
MODE_VIDEO = 'button[aria-label^="Video"][role="radio"]'

QUALITY_RADIO = 'button[role="radio"]'  # filter by text "Speed"/"Quality"

ASPECT_TRIGGER = 'button[aria-label^="Aspect Ratio"]'
ASPECT_OPTION = 'div[role="menuitem"]'  # filter by text prefix

VIDEO_RES_GROUP = 'div[aria-label="Video resolution"]'
VIDEO_DUR_GROUP = 'div[aria-label="Video duration"]'

# Image generation state (in masonry)
MASONRY_PREFIX = '[id^="imagine-masonry-section-"]'
LIST_ITEM_CANVAS = '[role="listitem"] canvas'
LIST_ITEM_READY = '[role="listitem"] img.opacity-1'

# /imagine/post/{uuid} result page
DOWNLOAD = 'button[aria-label^="Download"]'
REDO_IMAGE = 'button[aria-label^="Redo image"]'
MAKE_VIDEO = 'button[aria-label^="Make video"]'
PLAY = 'button[aria-label^="Play"]'
BACK = 'div[aria-label^="Back"]'  # NOTE: <div>, not <button>

# Toasts (errors)
TOAST = '[data-sonner-toast]'
