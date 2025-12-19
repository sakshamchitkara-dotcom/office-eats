from office_eats.http import HttpError
from office_eats.models import Venue
from office_eats.websites import add_menu_links, find_menu_link, robots_allows

HOME = """<html><body><nav>
<a href="mailto:hi@x.test">Email menu</a>
<a href="/order-online">Order</a>
<a href="/food/lunch-menu.pdf">Our <b>Lunch</b> Menu</a>
</nav></body></html>"""


def test_find_menu_prefers_menu_over_order():
    assert find_menu_link(HOME, "https://x.test/") == "https://x.test/food/lunch-menu.pdf"
    assert find_menu_link('<a href="/o">Order now</a>', "https://x.test") == "https://x.test/o"
    assert find_menu_link("<p>nothing</p>", "https://x.test") is None


def test_robots_disallow_blocks_fetch(fake_http):
    http = fake_http({"robots.txt": "User-agent: *\nDisallow: /\n"})
    v = Venue("node/1", "x", 0, 0, website="https://blocked.test/")
    add_menu_links([v], http)
    assert v.menu_url is None
    assert [u for u, _ in http.calls] == ["https://blocked.test/robots.txt"]


def test_robots_allow_then_fetch(fake_http):
    http = fake_http({"robots.txt": "User-agent: *\nDisallow: /admin\n", "ok.test": HOME})
    v = Venue("node/1", "x", 0, 0, website="ok.test")
    add_menu_links([v], http)
    assert v.menu_url == "https://ok.test/food/lunch-menu.pdf"


def test_robots_status_semantics(fake_http):
    def raise_(status):
        def f(url, data):
            raise HttpError("boom", status)
        return f
    assert robots_allows("https://a.test/", fake_http({"robots.txt": raise_(404)})) is True
    assert robots_allows("https://a.test/", fake_http({"robots.txt": raise_(503)})) is False
    assert robots_allows("https://a.test/", fake_http({"robots.txt": raise_(None)})) is False
