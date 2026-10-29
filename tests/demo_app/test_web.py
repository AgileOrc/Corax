import json
import re
from pathlib import Path

WEB = Path(__file__).parents[2] / "demo" / "web"
SOURCES = sorted(p for p in (WEB / "src").rglob("*") if p.suffix in (".js", ".jsx"))


def test_the_page_never_builds_html_from_strings():
    # React escapes every string it renders; these would bypass that
    raw_html = re.compile(r"dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write")

    found = [f"{p.relative_to(WEB)}:{i}" for p in SOURCES for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if raw_html.search(line)]

    assert SOURCES and found == []


def test_the_page_has_no_inline_script_or_style():
    # nginx sends script-src 'self' and style-src 'self', so the built page loads only files
    html = (WEB / "index.html").read_text(encoding="utf-8")
    nginx = (WEB / "nginx.conf").read_text(encoding="utf-8")

    assert re.findall(r"<script[^>]*>", html) == ['<script type="module" src="/src/main.jsx">']
    assert "<style" not in html and "style=" not in html
    assert "script-src 'self'" in nginx and "style-src 'self'" in nginx
    assert not [p for p in SOURCES if re.search(r"\bstyle=\{", p.read_text(encoding="utf-8"))]


def test_packages_are_pinned_to_exact_versions():
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    versions = {**package["dependencies"], **package["devDependencies"]}

    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions.values()), versions
    assert (WEB / "package-lock.json").exists()


def test_the_dev_server_sends_every_api_call_to_the_gateway():
    called = {m.group(1) for p in SOURCES for m in re.finditer(r'api\("[A-Z]+", [`"](/[a-z-]+)', p.read_text(encoding="utf-8"))}
    proxied = set(re.findall(r'"(/[a-z-]+)"', (WEB / "vite.config.js").read_text(encoding="utf-8")))

    assert called and called <= proxied
