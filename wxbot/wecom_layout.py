"""Read-only WeCom light-theme layout detection in window-relative pixels.

No saved machine coordinates or OCR/model download is needed. Ambiguous frames
(login, empty workspace, modal overlays) return None instead of guessed clicks.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class WeComLayout:
    nav_right: int
    chat_left: int
    chat_right: int
    header_bottom: int
    input_top: int
    input_bottom: int
    scale: float

    def rows(self, image):
        """Locate avatar bands, comparing against each row's own list colour.

        Using a row-local background keeps the selected blue row detectable.
        Return name-line anchors (not an assumed fixed row pitch).
        """
        a = np.asarray(image.convert("RGB"), dtype=np.int16)
        s = self.scale
        x0, x1 = round(18*s), round(52*s)
        if a.shape[1] < round(120*s):
            return []
        reference = np.median(a[:, round(110*s):, :], axis=1)
        ink = (np.abs(a[:, x0:x1] - reference[:, None, :]).sum(2) > 28).mean(1) > .48
        ink[:self.header_bottom + round(8*s)] = False
        # Fill small holes inside photo avatars, not gaps between conversations.
        for lo, hi in _runs(~ink):
            if lo > 0 and hi < len(ink) and hi-lo <= round(5*s):
                ink[lo:hi] = True
        return [lo + round((17 if hi-lo > 50*s else 4)*s) for lo, hi in _runs(ink)
                if round(24*s) <= hi-lo <= round(75*s)
                and hi + round(5*s) < a.shape[0]]


def _runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def detect_wecom_layout(image: Image.Image):
    a = np.asarray(image.convert("RGB"), dtype=np.int16)
    h, w = a.shape[:2]
    if w < 500 or h < 350:
        return None
    # The large white editor near the bottom is distinct from light grey chat
    # and sidebar backgrounds. Its extent also excludes the customer sidebar.
    white = (a.min(2) >= 250) & (a.max(2) - a.min(2) <= 6)
    candidates = [(lo, hi) for lo, hi in _runs(white[round(h*.88):round(h*.96)].mean(0) > .75)
                  if hi-lo >= max(180, w*.18) and 40 < lo < w*.65
                  and hi > w*.50]
    if len(candidates) != 1:
        return None
    ix0, ix1 = candidates[0]
    # Find the header's horizontal separator across the inner chat pane.
    strip = a[:min(round(h*.22), 240), ix0+10:ix1-10]
    med = np.median(strip, axis=1)
    flat = (np.abs(strip - med[:, None, :]).sum(2) < 6).mean(1)
    contrast = np.abs(med[1:] - med[:-1]).sum(1)
    lines = np.flatnonzero((contrast > 12) & (flat[1:] > .80)) + 1
    lines = lines[(lines >= 35) & (lines <= min(200, h*.2))]
    if not len(lines):
        return None
    header = int(lines[0] + 1)
    scale = header / 64.0
    if not .7 <= scale <= 3.2:
        return None
    # Chat/list separator is a continuous line just before the editor inset.
    left_limit = max(0, ix0-round(32*scale))
    right_limit = ix0-round(6*scale)
    sample = a[round(h*.25):round(h*.70):3]
    delta = np.abs(sample[:, 1:] - sample[:, :-1]).sum(2)
    score = np.median(delta, axis=0)
    edges = np.flatnonzero(score[left_limit:right_limit] > 12) + left_limit + 1
    if not len(edges):
        return None
    chat_left = int(edges[-1])
    # A separator plus an editor inset establishes the right pane boundary.
    near = min(w-1, ix1 + round(32*scale))
    edges = np.flatnonzero(score[ix1:near] > 12) + ix1 + 1
    chat_right = int(edges[0]) if len(edges) else w
    if chat_right - ix1 > round(35*scale):
        return None
    # Header height gives UI scale, then locate the navigation divider nearby.
    lo, hi = round(40*scale), min(chat_left-round(120*scale), round(100*scale))
    if hi <= lo:
        return None
    nav_edges = np.flatnonzero(score[lo:hi] > 12) + lo + 1
    if not len(nav_edges):
        return None
    nav = int(nav_edges[np.argmin(abs(nav_edges - 60*scale))])
    content = white[:, ix0+round(15*scale):ix1-round(15*scale)].mean(1) > .80
    for lo, hi in _runs(~content):
        if lo > h*.55 and hi < h and hi-lo <= round(40*scale):
            content[lo:hi] = True
    editor = [(lo, hi) for lo, hi in _runs(content)
              if lo > h*.45 and hi > h*.9 and hi-lo > 45*scale]
    if len(editor) != 1:
        return None
    top, bottom = editor[0]
    if not (nav < chat_left < ix0 < ix1 <= chat_right <= w):
        return None
    return WeComLayout(nav, chat_left, chat_right, header, int(top), int(bottom), scale)
