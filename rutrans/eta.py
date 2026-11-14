"""Time-left estimate for a translation job.

Why the old estimate jumped: it split the bar 60/40 between OCR and translation whatever the
real split was, and it measured translation in sentences that were processed short-to-long.

This model counts work in the units that actually cost time:
    remaining = scanned pages left x seconds per page  +  characters left x seconds per char
Both rates start from what this PC measured on earlier jobs (saved in speed.json), and are
blended with the live measurements as the job runs (the more work done, the more the live
rate counts). The text on scanned pages is unknown until OCR has read them, so it is
estimated from the characters per page read so far.

Countdown smooths what is shown: it counts down every second, and new estimates are eased in
(faster when the estimate drops than when it rises), so the number does not bounce.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {                     # cautious first guesses; replaced by what this PC measures
    "ocr_s_per_page": 8.0,       # 4-core laptop, dense A4 page, 2 parallel OCR engines
    "mt_s_per_char": 0.0007,     # ~1400 characters per second
    "chars_per_scan_page": 1500,
}
LIMITS = {
    "ocr_s_per_page": (0.5, 120.0),
    "mt_s_per_char": (0.00005, 0.02),
    "chars_per_scan_page": (100, 8000),
}
OVERHEAD_S = 1.0                 # opening, saving, building the preview


def _path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "RuEnTranslator" / "speed.json"


def load_rates() -> dict:
    rates = dict(DEFAULTS)
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
        for k, (lo, hi) in LIMITS.items():
            if isinstance(saved.get(k), (int, float)) and lo <= saved[k] <= hi:
                rates[k] = float(saved[k])
    except (OSError, ValueError):
        pass
    return rates


def save_rates(rates: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rates, indent=2), encoding="utf-8")
    except OSError:
        pass


class TimeLeft:
    """Work-based estimate of the seconds left. Feed it progress with update()."""

    def __init__(self, scan_pages: int, text_chars: int, now: float, rates: dict | None = None,
                 workers: int | None = None):
        self.r = dict(rates or load_rates())
        if workers is None:
            try:
                from .ocr import WORKERS as workers
            except Exception:  # noqa: BLE001
                workers = 1
        self.workers = workers                # pages OCR'd at the same time
        self.mt_step = 3000                   # characters per translation report (updated live)
        self.scan_total, self.scan_done = scan_pages, 0
        self.text_chars = text_chars          # typed text, known before starting
        self.ocr_chars = 0                    # characters OCR has read so far
        self.mt_total, self.mt_done = None, 0
        self.t_start = now
        self.ocr_start = now
        self.mt_start = None
        self.last_event = now
        self.ocr_elapsed = 0.0
        self.mt_elapsed = 0.0
        self.ocr_events: list[tuple[int, float]] = []   # (pages done, seconds since start)

    # ---- live rates, shrunk towards the remembered ones while there is little evidence
    def _ocr_fit(self):
        """(seconds per page, start-up seconds). Pages finish in groups (several are OCR'd at
        once), so the pace is the slope of a line fitted through the completion times; the
        intercept absorbs the start-up delay. Shrunk towards the remembered pace."""
        prior, k = self.r["ocr_s_per_page"], 1.5
        pts = self.ocr_events
        if self.scan_done == 0:
            return prior, 0.0
        # Recent pages count more (half-life 4 pages): laptops slow down as they warm up.
        last = pts[-1][0]
        w = [0.5 ** ((last - d) / 4.0) for d, _ in pts]
        sw = sum(w)
        mean_d = sum(wi * d for wi, (d, _) in zip(w, pts)) / sw
        mean_t = sum(wi * t for wi, (_, t) in zip(w, pts)) / sw
        var = sum(wi * (d - mean_d) ** 2 for wi, (d, _) in zip(w, pts))
        span = pts[-1][1] - pts[0][1]
        if len(pts) >= 3 and var > 0 and span > 1.0:
            slope = sum(wi * (d - mean_d) * (t - mean_t) for wi, (d, t) in zip(w, pts)) / var
            evidence = pts[-1][0] - pts[0][0]
            rate = (prior * k + max(slope, 0.0) * evidence) / (k + evidence)
            # Line through the recent points: finish time = start-up + rate x pages.
            return rate, max(mean_t - rate * mean_d, 0.0)
        rate = (prior * k + self.ocr_elapsed) / (k + self.scan_done)
        return rate, 0.0

    def _slowdown(self) -> float:
        """How much slower (>1) or faster (<1) this PC runs right now than it usually does,
        judged from the OCR pace; used to adjust the translation estimate too."""
        if self.scan_done < 2:
            return 1.0
        f = self.ocr_rate() / self.r["ocr_s_per_page"]
        return min(max(f, 0.6), 2.0)

    def ocr_rate(self) -> float:
        return self._ocr_fit()[0]

    def mt_rate(self) -> float:
        k = 1500.0                            # "worth" of the prior, in characters
        prior = self.r["mt_s_per_char"] * self._slowdown()
        return (prior * k + self.mt_elapsed) / (k + self.mt_done)

    def chars_per_scan_page(self) -> float:
        k = 1.0
        return (self.r["chars_per_scan_page"] * k + self.ocr_chars) / (k + self.scan_done)

    def update(self, stage: str, done: int, total: int, now: float, chars: int | None = None):
        self.last_event = now
        if stage == "ocr":
            if done > self.scan_done:
                self.ocr_events.append((done, now - self.ocr_start))
            self.scan_total, self.scan_done = total, done
            if chars is not None:
                self.ocr_chars = chars
            self.ocr_elapsed = now - self.ocr_start
        else:
            if self.mt_start is None:
                self.mt_start = now
            if done > self.mt_done:
                self.mt_step = done - self.mt_done
            self.mt_total, self.mt_done = total, done
            self.mt_elapsed = now - self.mt_start

    def remaining(self, now: float) -> float:
        """Seconds left = estimated total time of the current step - time spent on it, plus
        later steps. If the step is taking longer than expected, its rate is raised right away
        (at most `done + in flight` units can be finished by now), so the estimate grows
        smoothly instead of running down to zero and then jumping back up."""
        if self.mt_total is None:             # reading scanned pages (or not started yet)
            ocr_left = 0.0
            if self.scan_total and self.scan_done < self.scan_total:
                spent = now - self.ocr_start
                rate, startup = self._ocr_fit()
                floor = spent / (self.scan_done + self.workers)   # can't be faster than this
                if floor > rate:
                    rate, startup = floor, 0.0
                ocr_left = max(startup + self.scan_total * rate - spent, 0.0)
            chars = self.text_chars + self.chars_per_scan_page() * self.scan_total
            return ocr_left + chars * self.mt_rate() + OVERHEAD_S
        spent = now - self.mt_start
        rate = max(self.mt_rate(), spent / (self.mt_done + self.mt_step))
        return max(self.mt_total * rate - spent, 0.0) + OVERHEAD_S

    def total_estimate(self) -> float:
        return self.remaining(self.t_start)

    def finish(self, now: float) -> None:
        """Remember how fast this PC was, for better first estimates next time."""
        r = dict(self.r)
        if self.scan_total and self.scan_done == self.scan_total and self.ocr_elapsed > 0:
            pace = self.ocr_elapsed / self.scan_total if self.scan_total < 3 else self.ocr_rate()
            r["ocr_s_per_page"] = 0.5 * r["ocr_s_per_page"] + 0.5 * pace
            r["chars_per_scan_page"] = (0.5 * r["chars_per_scan_page"]
                                        + 0.5 * self.ocr_chars / self.scan_total)
        if self.mt_total and self.mt_total >= 2000 and self.mt_elapsed > 0:
            # Store the pace at this PC's usual speed (undo a temporary slowdown).
            pace = self.mt_elapsed / self.mt_total / self._slowdown()
            r["mt_s_per_char"] = 0.5 * r["mt_s_per_char"] + 0.5 * pace
        for k, (lo, hi) in LIMITS.items():
            r[k] = min(max(r[k], lo), hi)
        save_rates(r)


class Countdown:
    """What the user sees: counts down each second; new estimates are eased in."""

    def __init__(self, seconds: float, now: float):
        self.shown = seconds
        self.t = now

    def tick(self, target: float, now: float) -> float:
        dt = max(now - self.t, 0.0)
        self.t = now
        self.shown = max(self.shown - dt, 0.0)
        diff = target - self.shown
        per_second = 0.35 if diff < 0 else 0.2     # drops quickly, rises more gently
        a = 1 - (1 - per_second) ** max(dt, 0.25)
        self.shown = max(self.shown + diff * a, 0.0)
        return self.shown
