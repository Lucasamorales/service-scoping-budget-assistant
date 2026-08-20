"""Deterministic tools that propose facts for the orchestrator.

Reads go through ``app.store``. Side effects (mail send) only run after an
explicit Yes in chat — never from the model inventing a recipient or price.
"""
