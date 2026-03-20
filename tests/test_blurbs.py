from office_eats.blurbs import apply_deterministic, deterministic_blurb
from office_eats.models import Venue
from office_eats.scoring import Scored


def test_blurb_content():
    v = Venue("node/1", "Taq", 0, 0, kind="fast_food", cuisine=["mexican"], diets={"vegan", "vegetarian"},
              price_level=1, walk_min=4.2, open_now=True, group_size=6)
    b = deterministic_blurb(Scored(v, 80, []), "lunch")
    assert b == "Budget-friendly mexican counter-service spot, 4 min on foot; open when you need it; vegan/vegetarian options; can likely seat ~6."


def test_catering_blurb_and_apply():
    v = Venue("node/1", "X", 0, 0, tags={"catering": "yes"}, walk_min=12)
    items = [Scored(v, 70, [])]
    assert apply_deterministic(items, "catering") == "deterministic"
    assert items[0].blurb.startswith("Mid-priced restaurant, 12 min") and "does catering" in items[0].blurb


def test_diet_names_are_readable():
    v = Venue("node/1", "X", 0, 0, diets={"gluten_free"}, walk_min=2)
    assert "gluten-free options" in deterministic_blurb(Scored(v, 50, []), "lunch")
