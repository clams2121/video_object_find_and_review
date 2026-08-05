import datetime as dt

from app.worker.scanner import _find_or_create_event


def test_overlapping_clips_from_different_cameras_join_same_event(db_session):
    t0 = dt.datetime(2026, 8, 4, 19, 37, 0)
    ev1 = _find_or_create_event(db_session, t0, t0 + dt.timedelta(seconds=30), tolerance_seconds=5)
    db_session.flush()

    # camera2 clip starts a few seconds after camera1's clip started, well within tolerance
    ev2 = _find_or_create_event(
        db_session, t0 + dt.timedelta(seconds=10), t0 + dt.timedelta(seconds=40), tolerance_seconds=5
    )

    assert ev1.id == ev2.id
    assert ev2.end_time == t0 + dt.timedelta(seconds=40)


def test_non_overlapping_clips_get_separate_events(db_session):
    t0 = dt.datetime(2026, 8, 4, 19, 37, 0)
    ev1 = _find_or_create_event(db_session, t0, t0 + dt.timedelta(seconds=10), tolerance_seconds=5)
    db_session.flush()

    far_later = t0 + dt.timedelta(minutes=5)
    ev2 = _find_or_create_event(db_session, far_later, far_later + dt.timedelta(seconds=10), tolerance_seconds=5)

    assert ev1.id != ev2.id
