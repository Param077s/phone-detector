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


APPLE = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
         '<path d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014'
         '-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 '
         '3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 '
         '1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-'
         '2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zm3.378-3.066c.843-1.012 1.4-2.427 1.245-3.83'
         '-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.56-1.702z"/></svg>')
WIN = svg('<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>')
TUX = svg('<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>')

REPO = "https://github.com/Param077s/vigil"
SITE = "https://phone-detector-one.vercel.app/"
# Stable "latest release" asset URLs — public 'vigil' repo hosts the app builds
# (source stays in the private phone-detector repo).
DMG = "https://github.com/Param077s/vigil/releases/latest/download/Vigil.dmg"
ZIP = "https://github.com/Param077s/vigil/releases/latest/download/Vigil.zip"

page = page.replace("__LOGO__", LOGO)
page = page.replace('href="/favicon.svg"', 'href="favicon.svg"')
page = page.replace('<a class="btn btn-grn" href="/login">OPEN DASHBOARD</a>',
                    f'<a class="btn btn-grn js-dl" href="{DMG}">DOWNLOAD FREE</a>')
page = page.replace('<a href="#privacy">PRIVACY</a><a href="#faq">FAQ</a>',
                    f'<a class="js-dl" href="{DMG}">DOWNLOAD</a><a href="#privacy">PRIVACY</a><a href="#faq">FAQ</a>')
page = page.replace('<a class="btn btn-grn" href="/login">OPEN THE DASHBOARD</a>',
                    f'<a class="btn btn-grn js-dl" href="{DMG}">DOWNLOAD VIGIL FREE</a>')
page = page.replace('Sign in to your control room, or set Vigil up on the computer in the room you want to watch.',
                    'Download it onto the computer in the room you want to watch — free, no account, nothing leaves the machine.')
page = page.replace('<a href="/login">SIGN IN</a>',
                    f'<a class="js-dl" href="{DMG}">DOWNLOAD</a>'
                    '<a href="privacy.html">PRIVACY POLICY</a><a href="terms.html">TERMS</a>')
# renumber sections after the injected ACCESS section
page = page.replace('04 / PRIVACY DOCTRINE', '05 / PRIVACY DOCTRINE')
page = page.replace('05 / QUESTIONS', '06 / QUESTIONS')
page = page.replace('<link rel="icon" href="favicon.svg">',
                    f'<link rel="canonical" href="{SITE}">\n<link rel="icon" href="favicon.svg">\n'
                    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"SoftwareApplication",'
                    '"name":"Vigil","operatingSystem":"macOS, Windows, Linux","applicationCategory":"SecurityApplication",'
                    '"description":"Local AI phone detection: watches your camera feeds on-device and raises alerts with photo evidence the moment a phone appears. For exams, testing centres and secure spaces.",'
                    f'"offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}},"url":"{SITE}","downloadUrl":"{ZIP}"}}</script>')

GET = f'''
  <section id="get">
    <div class="sec-head reveal"><span class="sec-no">04 / ACCESS</span></div>
    <h2 class="reveal" style="--d:.05s">Get Vigil on<br>your computer.</h2>
    <p class="sec-sub reveal" style="--d:.08s">Free, no account. On Mac it installs like any app — drag it
      into Applications and open it. The first launch sets up its AI components once (~2&nbsp;GB); every
      launch after that is instant.</p>
    <div class="ctas reveal" style="--d:.1s; margin-top:30px; display:flex; gap:12px; flex-wrap:wrap">
      <a class="btn btn-grn" href="{DMG}" download>{APPLE} DOWNLOAD FOR MAC</a>
      <a class="btn btn-ghost" href="{ZIP}" download>{WIN} WINDOWS &amp; LINUX (.ZIP)</a>
    </div>
    <div class="setups">
      <div class="setup-c reveal"><span class="ico">{APPLE}</span><h3>Mac — drag &amp; drop</h3>
        <p>Open <code>Vigil.dmg</code> and drag <b>Vigil</b> into <b>Applications</b>. Double-click to open.
        First time only: right-click → <b>Open</b> → <b>Open</b>. Your browser opens to Vigil — create the
        admin account and you're watching.</p></div>
      <div class="setup-c reveal" style="--d:.08s"><span class="ico">{WIN}</span><h3>Windows</h3>
        <p>Unzip and double-click <code>Vigil-Windows.bat</code>. If SmartScreen warns, choose
        <b>More info → Run anyway</b>. If asked, install Python with <b>"Add Python to PATH"</b> ticked,
        then run it again.</p></div>
      <div class="setup-c reveal" style="--d:.16s"><span class="ico">{TUX}</span><h3>Linux</h3>
        <p>Unzip and run <code>./Vigil-Linux.sh</code> — it sets itself up on the first run and opens the
        dashboard when ready.</p></div>
    </div>
  </section>
'''
page = page.replace('  <section id="privacy" class="doctrine">', GET + '\n  <section id="privacy" class="doctrine">')

DLSWAP = ("<script>(function(){var w=/Win|Linux/.test(navigator.platform)&&!/Mac/.test(navigator.platform);"
          f"if(w)document.querySelectorAll('.js-dl').forEach(function(a){{a.href='{ZIP}';}});}})();</script>")
page = page.replace('</body></html>', DLSWAP + '\n</body></html>')

os.makedirs("docs", exist_ok=True)
open("docs/index.html", "w").write(page)

# ---- Privacy & Terms pages ----
def legal_page(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — {title}</title><link rel="icon" href="favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{ --bg:#07090c; --line:rgba(255,255,255,.07); --txt:#e8ebf1; --mut:#8b95a3; --dim:#525c6b; --grn:#3ecf8e;
    --mono:'JetBrains Mono',monospace; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--txt); font-family:'Inter',sans-serif; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:64px 28px 100px; }}
  .k {{ font-family:var(--mono); font-size:10.5px; letter-spacing:2.2px; color:var(--grn); }}
  .k::before {{ content:'// '; color:var(--dim); }}
  h1 {{ font-family:'Space Grotesk',sans-serif; font-size:clamp(30px,4vw,44px); letter-spacing:-0.02em; margin:16px 0 8px; }}
  .upd {{ font-family:var(--mono); font-size:10.5px; color:var(--dim); letter-spacing:1px; }}
  h2 {{ font-family:'Space Grotesk',sans-serif; font-size:19px; margin:42px 0 10px; }}
  p, li {{ font-size:14.5px; line-height:1.75; color:var(--mut); }}
  ul {{ padding-left:20px; margin:8px 0; }}
  b {{ color:var(--txt); }}
  a {{ color:var(--grn); text-decoration:none; }}
  .back {{ font-family:var(--mono); font-size:11px; letter-spacing:1.4px; display:inline-block; margin-bottom:40px; color:var(--mut); }}
  .back:hover {{ color:var(--txt); }}
  hr {{ border:none; border-top:1px solid var(--line); margin:48px 0 0; }}
</style></head><body><div class="wrap">
<a class="back" href="index.html">← VIGIL</a>
{body}
<hr><p style="margin-top:18px; font-family:var(--mono); font-size:10.5px; letter-spacing:1px; color:var(--dim)">
VIGIL — ON-PREMISE VISION INTELLIGENCE · <a href="privacy.html">PRIVACY</a> · <a href="terms.html">TERMS</a></p>
</div></body></html>"""

PRIVACY_BODY = """
<span class="k">PRIVACY POLICY</span>
<h1>Privacy, by architecture.</h1>
<p class="upd">LAST UPDATED — 12 JULY 2026</p>
<h2>The short version</h2>
<p>Vigil is software you download and run on <b>your own computer</b>. We do not operate servers that
receive your camera feeds, photos, or evidence. We cannot see your footage — by design, not by promise.</p>
<h2>What the Vigil app processes</h2>
<ul>
<li><b>Camera feeds</b> are analyzed on the machine running Vigil. Frames stay in memory; nothing is streamed to us.</li>
<li><b>Evidence photos and logs</b> (detections, timestamps, reviewer decisions) are stored in a local folder and database on that same machine. Deleting them is up to you.</li>
<li><b>Accounts</b> (admin/invigilator logins) exist only inside your installation.</li>
</ul>
<h2>What leaves your machine</h2>
<ul>
<li><b>Nothing, by default.</b> Vigil runs fully offline after the one-time component download.</li>
<li><b>Optional Telegram alerts:</b> if you configure them, detection photos are sent to the chat IDs you chose, via Telegram's service, under Telegram's terms.</li>
<li><b>Downloads &amp; updates</b> are fetched from GitHub when you request them.</li>
</ul>
<h2>This website</h2>
<p>This site is a static page. It sets no cookies and runs no analytics or trackers. It loads fonts from
Google Fonts and serves downloads from GitHub; those services may see standard request data (like your IP
address) under their own policies.</p>
<h2>Your responsibilities as an operator</h2>
<p>You are the data controller for footage and evidence captured by your installation. Follow your local
laws on CCTV use, signage and consent, and your institution's policies.</p>
<h2>Contact</h2>
<p>Questions? Open an issue on our <a href="https://github.com/Param077s/vigil">GitHub repository</a>.</p>
"""

TERMS_BODY = """
<span class="k">TERMS OF USE</span>
<h1>Plain terms.</h1>
<p class="upd">LAST UPDATED — 12 JULY 2026</p>
<h2>What Vigil is</h2>
<p>Vigil is on-premise software that analyzes camera feeds you control and flags configured objects
(such as phones) for <b>human review</b>. It is a detection aid — not a judge. Alerts are suggestions;
decisions and their consequences belong to the people operating it.</p>
<h2>License</h2>
<p>Vigil is provided free of charge for use at your own site. You may install and use it on machines you
control. You may not resell it, misrepresent its origin, or remove attribution.</p>
<h2>Acceptable use</h2>
<ul>
<li>Use Vigil only where you have the <b>legal right to operate cameras</b>, with any required signage or consent.</li>
<li>Give affected people a route to contest AI-assisted findings; keep a human in the loop for every enforcement decision.</li>
<li>Do not use Vigil to harass, unlawfully surveil, or discriminate.</li>
</ul>
<h2>No warranty</h2>
<p>Vigil is provided <b>"as is", without warranty of any kind</b>. Detection accuracy varies with cameras,
lighting, distance and configuration. False positives and missed detections will occur. You are responsible
for validating the system in your environment (we recommend the pilot protocol) before relying on it.</p>
<h2>Limitation of liability</h2>
<p>To the maximum extent permitted by law, the makers of Vigil are not liable for any indirect, incidental
or consequential damages — including decisions made from alerts, lost data, or misuse of the software.</p>
<h2>Changes</h2>
<p>We may update these terms and the software. Material changes will be reflected on this page with a new
"last updated" date.</p>
<h2>Contact</h2>
<p>Questions? Open an issue on our <a href="https://github.com/Param077s/vigil">GitHub repository</a>.</p>
"""

open("docs/privacy.html","w").write(legal_page("Privacy Policy", PRIVACY_BODY))
open("docs/terms.html","w").write(legal_page("Terms of Use", TERMS_BODY))

open("docs/favicon.svg", "w").write(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
    '<rect width="24" height="24" rx="6" fill="#0e1116"/>'
    '<path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10'
    'M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" '
    'stroke="#7a8595" stroke-width="1.8" stroke-linecap="round"/>'
    '<circle cx="12" cy="12" r="2.6" fill="#3ecf8e"/></svg>')

ok = "/login" not in page and 'id="get"' in page and "ld+json" in page and "js-dl" in page
print(f"docs/index.html written ({len(page)} bytes), checks pass: {ok}")
assert ok
