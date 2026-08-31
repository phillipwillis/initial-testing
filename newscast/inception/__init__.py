"""Inception CMS adapter (§9, §10.6).

§9 asks for a thin adapter so the scripting and validation layers never learn
how Inception is being driven. `frames.py` is the part of that with no Selenium
in it: describing where in the frame tree an operation belongs, so the driving
code never has to track where it currently is.
"""

from newscast.inception.frames import (
    FrameSpec,
    FrameDescriptor,
    by_title,
    by_src,
    by_id_prefix,
    matches,
    resolve,
)

__all__ = [
    "FrameSpec",
    "FrameDescriptor",
    "by_title",
    "by_src",
    "by_id_prefix",
    "matches",
    "resolve",
]
