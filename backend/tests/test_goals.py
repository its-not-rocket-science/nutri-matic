import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.goals import attach_goals, goal_keys_of, goal_weight, load_goal_keys, load_goal_keys_batch, replace_goals
from app.models import Profile, ProfileGoal, User


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


_email_counter = [0]


def make_profile(db, **kwargs):
    _email_counter[0] += 1
    user = User(email=f"user{_email_counter[0]}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    defaults = dict(user_id=user.id, name="Me", is_account_owner=True)
    defaults.update(kwargs)
    profile = Profile(**defaults)
    db.add(profile)
    db.flush()
    return profile


def test_replace_goals_writes_ordered_priority_rows(db):
    profile = make_profile(db)
    replace_goals(db, profile, ["nutrient_gaps", "budget", "exploring"])
    db.commit()

    rows = db.query(ProfileGoal).filter(ProfileGoal.profile_id == profile.id).order_by(ProfileGoal.priority).all()
    assert [(r.goal, r.priority) for r in rows] == [
        ("nutrient_gaps", 1), ("budget", 2), ("exploring", 3),
    ]


def test_replace_goals_mirrors_priority_one_into_legacy_goal_column(db):
    profile = make_profile(db)
    replace_goals(db, profile, ["weight_loss", "budget"])
    assert profile.goal == "weight_loss"


def test_replace_goals_empty_list_clears_legacy_goal_column(db):
    profile = make_profile(db, goal="budget")
    replace_goals(db, profile, ["budget"])
    replace_goals(db, profile, [])
    assert profile.goal is None
    assert load_goal_keys(db, profile) == []


def test_replace_goals_overwrites_previous_set_not_appends(db):
    profile = make_profile(db)
    replace_goals(db, profile, ["budget", "exploring"])
    db.commit()
    replace_goals(db, profile, ["weight_loss"])
    db.commit()

    assert load_goal_keys(db, profile) == ["weight_loss"]


def test_replace_goals_dedupes_preserving_first_occurrence(db):
    profile = make_profile(db)
    replace_goals(db, profile, ["budget", "exploring", "budget"])
    db.commit()
    assert load_goal_keys(db, profile) == ["budget", "exploring"]


def test_load_goal_keys_batch_covers_multiple_profiles_and_empty_ones(db):
    profile_a = make_profile(db, name="A")
    profile_b = make_profile(db, name="B")
    profile_c = make_profile(db, name="C")
    replace_goals(db, profile_a, ["budget"])
    replace_goals(db, profile_b, ["exploring", "nutrient_gaps"])
    db.commit()

    result = load_goal_keys_batch(db, [profile_a.id, profile_b.id, profile_c.id])
    assert result[profile_a.id] == ["budget"]
    assert result[profile_b.id] == ["exploring", "nutrient_gaps"]
    assert result[profile_c.id] == []


def test_load_goal_keys_batch_empty_input_returns_empty_dict(db):
    assert load_goal_keys_batch(db, []) == {}


def test_attach_goals_sets_transient_goals_attribute(db):
    profile = make_profile(db)
    replace_goals(db, profile, ["protein_quality"])
    db.commit()

    attach_goals(db, profile)
    assert profile.goals == ["protein_quality"]


def test_goal_keys_of_uses_attached_goals_when_present(db):
    profile = make_profile(db, goal="budget")
    profile.goals = ["weight_loss", "budget"]  # simulates attach_goals() having run
    assert goal_keys_of(profile) == ["weight_loss", "budget"]


def test_goal_keys_of_falls_back_to_legacy_goal_column_when_never_attached(db):
    """A Profile built directly (e.g. in another test's fixture), never
    routed through attach_goals() — must not silently look goal-less."""
    profile = make_profile(db, goal="exploring")
    assert goal_keys_of(profile) == ["exploring"]


def test_goal_keys_of_falls_back_to_empty_list_when_no_legacy_goal_either(db):
    profile = make_profile(db, goal=None)
    assert goal_keys_of(profile) == []


def test_goal_keys_of_respects_attached_empty_list_over_stale_legacy_column(db):
    """An attached (real, queried) empty goal set must win even if the
    legacy column happens to still hold a value — attach_goals() having
    run at all means the ProfileGoal table is authoritative."""
    profile = make_profile(db, goal="budget")
    profile.goals = []
    assert goal_keys_of(profile) == []


@pytest.mark.parametrize(
    "rank,expected",
    [(1, 1.0), (2, 0.5), (3, pytest.approx(1 / 3)), (4, 0.25)],
)
def test_goal_weight_is_one_over_rank(rank, expected):
    assert goal_weight(rank) == expected
