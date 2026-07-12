"""Build the public website (docs/) from the in-app landing page.

Run `python3 make_site.py` after changing LANDING_HTML in app.py, then commit
docs/. GitHub Pages serves docs/ from main.
"""
import os
import re

src = open("app.py").read()

m = re.search(r'LANDING_HTML = """(.*?)"""\n\n\n', src, re.S)
assert m, "LANDING_HTML not found"
page = m.group(1)

LOGO = ('<svg class="logo-mark" width="21" height="21" viewBox="0 0 24 24" fill="none">'
        '<path d="M4 9V6a2 2 0 0 1 2-2h3M15 4h3a2 2 0 0 1 2 2v3M20 15v3a2 2 0 0 1-2 2h-3M9 20H6a2 2 0 0 1-2-2v-3" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
        '<circle cx="12" cy="12" r="3" fill="#3ecf8e"/></svg>')


def svg(inner, size=17):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')


APPLE = svg('<path d="M12 20.94c1.5 0 2.75 1.06 4 1.06 3 0 6-8 6-12.22A4.91 4.91 0 0 0 17 5c-2.22 0-4 1.44-5 2-1-.56-2.78-2-5-2a4.9 4.9 0 0 0-5 4.78C2 14 5 22 8 22c1.25 0 2.5-1.06 4-1.06Z"/><path d="M10 2c1 .5 2 2 2 5"/>')
WIN = svg('<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>')
TUX = svg('<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>')

REPO = "https://github.com/Param077s/phone-detector"
SITE = "https://param077s.github.io/phone-detector/"
# Stable "latest release" asset URLs — always point at the newest published release.
DMG = "https://github.com/Param077s/phone-detector/releases/latest/download/Vigil.dmg"
ZIP = "https://github.com/Param077s/phone-detector/releases/latest/download/Vigil.zip"

page = page.replace("__LOGO__", LOGO)
page = page.replace('href="/favicon.svg"', 'href="favicon.svg"')
page = page.replace('<a class="btn btn-grn" href="/login">Open dashboard</a>',
                    '<a class="btn btn-grn" href="#get">Download free</a>')
page = page.replace('<a href="#privacy">Privacy</a><a href="#faq">FAQ</a>',
                    '<a href="#get">Download</a><a href="#privacy">Privacy</a><a href="#faq">FAQ</a>')
page = page.replace('<a class="btn btn-grn" href="/login">Open the dashboard →</a>',
                    '<a class="btn btn-grn" href="#get">Download Vigil free ↓</a>')
page = page.replace('<a class="btn btn-ghost" href="#how">See how it works</a>',
                    '<a class="btn btn-ghost" href="#get">See how it installs</a>')
page = page.replace('Sign in to your control room, or set Vigil up on the computer in the room you want to watch.',
                    'Download it onto the computer in the room you want to watch — free, no account, nothing leaves the machine.')
page = page.replace('<a href="/login">Sign in</a>', '<a href="#get">Download</a>')
page = page.replace('<link rel="icon" href="favicon.svg">',
                    f'<link rel="canonical" href="{SITE}">\n<link rel="icon" href="favicon.svg">\n'
                    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"SoftwareApplication",'
                    '"name":"Vigil","operatingSystem":"macOS, Windows, Linux","applicationCategory":"SecurityApplication",'
                    '"description":"Local AI phone detection: watches your camera feeds on-device and raises alerts with photo evidence the moment a phone appears. For exams, testing centres and secure spaces.",'
                    f'"offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}},"url":"{SITE}","downloadUrl":"{ZIP}"}}</script>')

GET = f'''
  <section id="get">
    <span class="sec-kicker reveal">Download</span>
    <h2 class="reveal" style="--d:.05s">Get Vigil on your computer.</h2>
    <p class="sec-sub reveal" style="--d:.08s">Free, no account. On Mac it installs like any app —
      drag it into Applications and open it. The first launch sets up its AI components once
      (~2&nbsp;GB); every launch after that is instant.</p>
    <div class="ctas reveal" style="--d:.1s; margin-top:26px; display:flex; gap:12px; flex-wrap:wrap">
      <a class="btn btn-grn" href="{DMG}">{APPLE} Download for Mac</a>
      <a class="btn btn-ghost" href="{ZIP}">{WIN} Windows &amp; Linux (.zip)</a>
    </div>
    <div class="setups" style="margin-top:30px">
      <div class="setup-c reveal"><span class="ico">{APPLE}</span><h3>Mac — drag &amp; drop</h3>
        <p>Open the downloaded <code>Vigil.dmg</code> and drag <b>Vigil</b> into your
        <b>Applications</b> folder — just like any Mac app. Double-click to open. First time only:
        right-click → <b>Open</b> → <b>Open</b> (macOS checks new apps once). Your browser opens to
        Vigil — create an admin account and you're watching.</p></div>
      <div class="setup-c reveal" style="--d:.08s"><span class="ico">{WIN}</span><h3>Windows</h3>
        <p>Unzip the download and double-click <code>Vigil-Windows.bat</code>. If SmartScreen warns,
        choose <b>More info → Run anyway</b>. If it asks for Python, install it with
        <b>"Add Python to PATH"</b> ticked, then run it again.</p></div>
      <div class="setup-c reveal" style="--d:.16s"><span class="ico">{TUX}</span><h3>Linux</h3>
        <p>Unzip and run <code>./Vigil-Linux.sh</code> in a terminal — it sets itself up on the first
        run and opens the dashboard when ready.</p></div>
    </div>
  </section>
'''
page = page.replace('  <section id="privacy" class="privacy">', GET + '\n  <section id="privacy" class="privacy">')

os.makedirs("docs", exist_ok=True)
open("docs/index.html", "w").write(page)

open("docs/favicon.svg", "w").write(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
    '<rect width="24" height="24" rx="6" fill="#0e1116"/>'
    '<path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10'
    'M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" '
    'stroke="#7a8595" stroke-width="1.8" stroke-linecap="round"/>'
    '<circle cx="12" cy="12" r="2.6" fill="#3ecf8e"/></svg>')

ok = "/login" not in page and "#get" in page and "ld+json" in page
print(f"docs/index.html written ({len(page)} bytes), checks pass: {ok}")
assert ok
