"""AOS Baton: Director's Cut.

Central question: "Did the agent actually do it?" Baton takes one
interrupted job (an input bundle of events, artifacts, receipts, approvals),
runs deterministic checks over it, extracts a source-linked recovery record,
persists it in SQLite, and exports a handoff for the next session.

Session 1: local scaffold. Extraction is stubbed (deterministic, offline);
the real Nebius/Nemotron adapter plugs into the Extractor interface later.
"""

__version__ = "0.1.0"
