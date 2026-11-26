from app.database import engine


def test_engine_pings_pooled_connections_before_use():
    # Without this, the first request after a postgres restart can fail on a
    # pooled connection the restart already closed.
    assert engine.pool._pre_ping is True
