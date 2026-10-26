"""How documents are split by default: for uploads, website pages and evaluations.

Measured with `ragolex tune` on the handbook dataset, and kept: see
docs/evaluation.md for the results and why. The web app keeps a copy
(DEFAULT_PROCESS_OPTIONS in frontend/src/api/types.ts), checked against
the API's schema.
"""

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP_SIZE = 200
