import pytest

from mini_rag.core.spaced_repetition import (
    MAX_INTERVAL_DAYS,
    MIN_EASE,
    RELEARN_DAYS,
    next_schedule,
    previews,
)
from mini_rag.domain.models import Schedule

NEW = Schedule()


def review(*grades, start=NEW):
    schedule = start
    for grade in grades:
        schedule = next_schedule(schedule, grade)
    return schedule


def test_a_new_card_comes_back_in_a_day_or_four_when_easy():
    assert previews(NEW) == {"again": round(RELEARN_DAYS, 6), "hard": 1.0, "good": 1.0,
                             "easy": 4.0}


def test_good_reviews_space_out_by_the_ease():
    assert [review(*["good"] * n).interval_days for n in (1, 2, 3, 4)] == [1.0, 3.0, 7.5, 18.75]


def test_forgetting_brings_a_card_back_soon_and_starts_over():
    learnt = review("good", "good", "good")

    forgotten = next_schedule(learnt, "again")

    assert forgotten.interval_days == pytest.approx(10 / (24 * 60), abs=1e-6)
    assert (forgotten.repetitions, forgotten.lapses) == (0, 1)
    assert forgotten.ease == pytest.approx(learnt.ease - 0.2)
    # Forgetting a card never learnt is not a lapse.
    assert next_schedule(NEW, "again").lapses == 0


def test_hard_and_easy_change_the_ease():
    assert review("hard").ease == pytest.approx(2.35)
    assert review("easy").ease == pytest.approx(2.65)
    assert review(*["again"] * 10).ease == MIN_EASE


@pytest.mark.parametrize("grades", [(), ("good",), ("good", "good"), ("good", "hard", "good"),
                                    ("easy", "easy"), ("good", "again", "good")])
def test_harder_answers_never_give_longer_intervals(grades):
    intervals = previews(review(*grades))

    assert intervals["again"] < intervals["hard"] <= intervals["good"] < intervals["easy"]


def test_a_review_never_brings_a_learnt_card_back_sooner():
    learnt = review("good", "good", "good")

    assert all(next_schedule(learnt, grade).interval_days > learnt.interval_days
               for grade in ("hard", "good", "easy"))


def test_intervals_have_a_ceiling():
    assert review(*["easy"] * 30).interval_days == MAX_INTERVAL_DAYS
