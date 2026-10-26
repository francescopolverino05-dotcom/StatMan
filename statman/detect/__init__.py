"""Local, free event-moment detection from match video (auto-tagger rebuild, phase 1).

Code finds *when* something happens (ball touches, possession changes); a model
only labels those moments later (phase 2). Nothing here calls a paid API.

Pipeline: ``extract`` (YOLO persons + ball per sampled frame, kit colours)
-> ``teams`` (kit-colour clustering) -> ``ball`` (ball track) -> ``moments``
(candidate touch / possession-change moments). ``evaluate`` scores the
candidates against hand tags. Not wired into the live tagging path.
"""
