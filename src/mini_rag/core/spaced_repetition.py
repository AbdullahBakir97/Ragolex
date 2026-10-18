"""Spaced repetition: when to review a flashcard again, from how well it was remembered.

A variant of SM-2, the algorithm behind Anki, with its four answers. A new
card is due again after a day ("good"), or four ("easy"); then each good
review multiplies the interval by the card's ease, which "hard" and
"again" lower and "easy" raises. A card forgotten ("again") comes back in
ten minutes and starts over.
"""

from mini_rag.domain.models import ReviewGrade, Schedule

MINUTE = 1 / (24 * 60)
RELEARN_DAYS = 10 * MINUTE
MIN_EASE = 1.3
MAX_INTERVAL_DAYS = 365 * 3


def next_schedule(current: Schedule, grade: ReviewGrade) -> Schedule:
    """The card's schedule after a review graded ``grade``."""
    if grade == "again":
        return Schedule(interval_days=round(RELEARN_DAYS, 6),
                        ease=round(max(MIN_EASE, current.ease - 0.2), 2), repetitions=0,
                        lapses=current.lapses + (1 if current.repetitions else 0))
    if current.repetitions == 0:
        intervals = {"hard": 1.0, "good": 1.0, "easy": 4.0}
    else:
        good = 3.0 if current.repetitions == 1 else current.interval_days * current.ease
        # A card remembered again never comes back sooner than it would have.
        floor = current.interval_days + 1
        good = max(good, floor)
        intervals = {"hard": max(min(current.interval_days * 1.2, good), floor), "good": good,
                     "easy": max(good * 1.3, good + 1)}
    ease = {"hard": max(MIN_EASE, current.ease - 0.15), "good": current.ease,
            "easy": current.ease + 0.15}[grade]
    return Schedule(interval_days=round(min(intervals[grade], MAX_INTERVAL_DAYS), 6),
                    ease=round(ease, 2), repetitions=current.repetitions + 1,
                    lapses=current.lapses)


def previews(current: Schedule) -> dict[ReviewGrade, float]:
    """The interval, in days, each answer would give the card."""
    grades: tuple[ReviewGrade, ...] = ("again", "hard", "good", "easy")
    return {grade: next_schedule(current, grade).interval_days for grade in grades}
