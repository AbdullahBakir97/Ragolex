"""How documents are split by default: for uploads, website pages and evaluations.

Chosen with `mini-rag tune` on the handbook dataset; see docs/evaluation.md.
"""

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP_SIZE = 200
