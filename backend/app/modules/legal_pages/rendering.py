"""Server-rendered public policy: no login, JavaScript, trackers or editable HTML."""

from html import escape

STYLE = """body{margin:0;background:#f5f7fb;color:#17243b;font:17px/1.75 system-ui,-apple-system,sans-serif}main{max-width:850px;margin:40px auto;padding:42px;background:white;border:1px solid #e1e7f0;border-radius:20px}h1{font-size:2.3rem;line-height:1.2}h2{font-size:1.3rem;margin-top:32px;color:#153d74}.brand{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#4266a0}.meta{color:#5b6b80;font-size:14px}p{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1752aa}nav{padding:20px;background:#f5f8ff;border-radius:12px}nav a{display:inline-block;margin:4px 15px 4px 0}.apps{padding:16px 20px;border-left:3px solid #2463eb;background:#f5f8ff}footer{margin-top:36px;border-top:1px solid #e1e7f0;padding-top:20px}@media(max-width:600px){main{margin:0;padding:25px 20px;border-radius:0;border:0}h1{font-size:1.9rem}}"""


def render_policy(policy, revision=None, published_at=None, preview=False):
    e = escape
    app_names = [policy.customer_app_name, policy.merchant_app_name, policy.rider_app_name]
    sections = list(policy.sections)
    from app.modules.legal_pages.schemas import Section

    location = {
        "UNCONFIRMED": "Location details are awaiting confirmation before publication.",
        "FOREGROUND_ONLY": "The Rider app collects precise location when you use location-enabled delivery features while the app is in use, such as starting or verifying an assigned delivery. Location helps check arrival, verify delivery addresses and coordinate delivery work. The Rider app does not collect location in the background. You can manage location permission in device settings; refusing it may prevent location-dependent delivery checks.",
        "FOREGROUND_AND_BACKGROUND": "The Rider app collects precise location during active delivery work, including when the app is in the background or not visible, to support delivery tracking, route and arrival coordination, and delivery-location verification. This processing requires the applicable location permissions and in-app disclosure. You can manage or revoke location permission in device settings. Refusing it may limit location-dependent delivery features. Location must not be collected for unrelated purposes.",
    }[policy.background_location]
    sections.insert(4, Section(heading="Location information", body=location))
    if policy.sdk_disclosure:
        sections.append(
            Section(heading="Service providers and mobile SDKs", body=policy.sdk_disclosure)
        )
    nav = "".join(f'<a href="#section-{i}">{e(s.heading)}</a>' for i, s in enumerate(sections))
    body = "".join(
        f'<section id="section-{i}"><h2>{e(s.heading)}</h2><p>{e(s.body)}</p></section>'
        for i, s in enumerate(sections)
    )
    contact = ""
    if policy.contact_email:
        contact += f'<p>Email: <a href="mailto:{e(policy.contact_email, quote=True)}">{e(policy.contact_email)}</a></p>'
    if policy.contact_url:
        contact += f'<p><a href="{e(policy.contact_url, quote=True)}" rel="noopener noreferrer">Contact us about privacy or account deletion</a></p>'
    banner = (
        '<p class="apps"><strong>Private draft preview — this content is not published.</strong></p>'
        if preview
        else ""
    )
    version = f" · Version {revision}" if revision else ""
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="{"noindex,nofollow" if preview else "index,follow"}"><title>{e(policy.title)} | {e(policy.publisher_name)}</title><style>{STYLE}</style></head><body><main><div class="brand">{e(policy.publisher_name)}</div>{banner}<h1>{e(policy.title)}</h1><p class="meta">Effective date: {policy.effective_date.isoformat()}{version}</p><div class="apps"><strong>This policy covers</strong><ul>{"".join(f"<li>{e(name)}</li>" for name in app_names)}</ul></div><p>Operated by {e(policy.publisher_name)}.</p><nav aria-label="Policy contents">{nav}<a href="#privacy-contact">Privacy contact</a></nav>{body}<footer id="privacy-contact"><h2>Privacy contact and deletion requests</h2>{contact}<p>When contacting us, identify the relevant app and your account. Do not send your password or login OTP.</p></footer></main></body></html>'
