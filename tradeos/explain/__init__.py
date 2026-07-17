"""Explanation layer: turns a computed cluster into plain language.

The model explains, it never measures (Decision 10). A deterministic template is always
available and is the default; optional Gemini/Anthropic providers rephrase it, but every
model output passes a numbers guard (no figure the computation didn't produce) and a
directive-language guard (no advice) before it is ever shown — else the template renders.
"""
