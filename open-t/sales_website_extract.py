import html as html_module
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import serpapi
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


app = Flask(__name__)
CORS(app)

# ---------- shared browser (reuse across requests) ----------
_browser_instance = None
_playwright_instance = None


def _get_browser():
    """Return a shared Chromium browser, launching it once on first call."""
    global _browser_instance, _playwright_instance
    if _browser_instance is None or not _browser_instance.is_connected():
        if _playwright_instance is None:
            _playwright_instance = sync_playwright().start()
        _browser_instance = _playwright_instance.chromium.launch(headless=True)
    return _browser_instance


def api_keys(*keys):
    """Return cleaned API keys, preserving order for failover usage."""
    return [key.strip() for key in keys if key and key.strip()]

def get_coordinates(city, country):
    print(f"  [get_coordinates] Looking up {city}, {country} ...")
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{city}, {country}",
        "format": "json",
        "limit": 1
    }
    headers = {"User-Agent": "sales-website-extractor/1.0"}
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError(f"Could not find coordinates for '{city}, {country}'")
    return data[0]["lat"], data[0]["lon"]


def _get_searches_left(api_key):
    """Return total_searches_left for a SerpAPI key, or 0 on failure."""
    try:
        resp = requests.get(
            "https://serpapi.com/account",
            params={"api_key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        return int(resp.json().get("total_searches_left", 0))
    except Exception:
        return 0


def search_local_businesses(query, api_key, city, country):
    print(f"\n[search_local_businesses] query='{query}', city='{city}', country='{country}'")
    lat, lon = get_coordinates(city, country)
    pages = [0, 20, 40, 60, 80, 100]
    all_results = []

    left = _get_searches_left(api_key)
    if left <= 0:
        raise RuntimeError("API key quota exhausted (0 searches left). Please use a different key.")
    print(f"Key {api_key[:6]}... has {left} searches left. Starting pagination...")

    for start in pages:
        try:
            client = serpapi.Client(api_key=api_key)
            results = client.search({
                "engine": "google_maps",
                "q": query,
                "lat": lat,
                "lon": lon,
                "z": "14",
                "start": str(start),
            })

            error = str(results.get("error", "")).lower()
            if error:
                if "limit" in error or "quota" in error or "rate" in error:
                    print(f"Key {api_key[:6]}... quota exhausted at start={start}. Returning results collected so far.")
                    break
                raise RuntimeError(results.get("error"))

            page_results = results.get("local_results", [])
            if not page_results:
                break
            all_results.extend(page_results)
            print(f"Page start={start}: got {len(page_results)} results (total: {len(all_results)})")
        except RuntimeError:
            raise
        except Exception as exc:
            print(f"Error at start={start}: {exc}")
            break

    return all_results


def normalize_url(url):
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        return "https://" + url
    return url


_COMMON_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _fetch_html_fast(url, timeout=15):
    """Try fetching HTML with requests (no browser). Returns (html, body_text, mailto_emails) or None if JS rendering is likely needed."""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": _COMMON_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None

        html = resp.text or ""
        if len(html) < 100:
            return None

        # Parse with BeautifulSoup to extract body text and mailto emails.
        decoded_html = html_module.unescape(html)
        soup = BeautifulSoup(decoded_html, "html.parser")

        # Remove script/style for clean visible text.
        for tag in soup(["script", "style"]):
            tag.decompose()
        body_tag = soup.find("body")
        body_text = body_tag.get_text(separator=" ", strip=True) if body_tag else ""

        # If visible text is too short, the page likely needs JS rendering.
        if len(body_text) < 50:
            return None

        # Extract mailto emails from anchor tags.
        mailto_emails = []
        for a_tag in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
            addr = a_tag["href"].split(":", 1)[1].split("?")[0].strip()
            if addr:
                mailto_emails.append(addr)

        return html, body_text, mailto_emails
    except Exception:
        return None


def fetch_html(url, timeout=30):
    """Fetch a page: try fast requests first, fall back to Playwright if needed."""
    # --- Fast path: plain HTTP request (no browser) ---
    fast = _fetch_html_fast(url, timeout=15)
    if fast is not None:
        html, body_text, mailto_emails = fast
        print(f"  [fetch_html] (fast/requests) {url} => {len(html)} chars, {len(mailto_emails)} mailto links", flush=True)
        return html, body_text, mailto_emails

    # --- Slow path: Playwright browser ---
    print(f"  [fetch_html] falling back to Playwright for {url}", flush=True)
    try:
        browser = _get_browser()
        context = browser.new_context(
            user_agent=_COMMON_UA,
            locale="en-US",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        html = page.content() or ""

        # Get clean visible text (no tags/scripts) from the live DOM.
        try:
            body_text = page.inner_text("body") or ""
        except Exception:
            body_text = ""

        # Extract mailto emails directly from the live DOM (catches JS-injected links).
        try:
            mailto_emails = page.eval_on_selector_all(
                'a[href^="mailto:"]',
                "els => els.map(e => e.href.replace('mailto:', '').split('?')[0])",
            )
        except Exception:
            mailto_emails = []

        context.close()
        print(f"  [fetch_html] (playwright) {url} => {len(html)} chars, {len(mailto_emails)} mailto links", flush=True)
        return html, body_text, mailto_emails
    except Exception as exc:
        print(f"  [fetch_html] FAILED {url}: {exc}", flush=True)
        return "", "", []


def _safe_json_loads(value):
    try:
        return json.loads(value)
    except Exception:
        return None


def _normalize_email(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if any(token in cleaned for token in ("example.com", "domain.com", "your@email", "u003e", "u003c")):
        return None
    if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
        return cleaned
    return None


def _normalize_phone(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    digits = re.sub(r"\D", "", cleaned)

    # Keep only likely real phone numbers; this removes most random IDs.
    if not (10 <= len(digits) <= 15):
        return None
    if not any(ch in cleaned for ch in (" ", "-", ".", "(", ")", "+")):
        return None

    return re.sub(r"\s+", " ", cleaned)


def _to_slug(value):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "unknown"


def extract_schema_contacts(html):
    print(f"  [extract_schema_contacts] Parsing JSON-LD blocks ...")
    contacts = {
        "schema_emails": set(),
        "schema_phones": set(),
        "schema_social_links": set(),
    }

    json_ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def walk(node):
        if isinstance(node, dict):
            email = node.get("email")
            phone = node.get("telephone")
            same_as = node.get("sameAs")
            if isinstance(email, str):
                normalized_email = _normalize_email(email)
                if normalized_email:
                    contacts["schema_emails"].add(normalized_email)
            if isinstance(phone, str):
                normalized_phone = _normalize_phone(phone)
                if normalized_phone:
                    contacts["schema_phones"].add(normalized_phone)
            if isinstance(same_as, list):
                contacts["schema_social_links"].update(
                    item.strip() for item in same_as if isinstance(item, str)
                )
            elif isinstance(same_as, str):
                contacts["schema_social_links"].add(same_as.strip())

            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in json_ld_blocks:
        parsed = _safe_json_loads(block.strip())
        if parsed is not None:
            walk(parsed)

    return contacts


def extract_contacts_and_links(html, base_url, body_text=""):
    """Use BeautifulSoup to parse HTML and extract emails, phones, and links."""
    print(f"  [extract_contacts_and_links] Parsing {base_url} with BS4 ...")
    email_pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    phone_pattern = (
        r"(?:\+?\d{1,3}[\s.\-]?)?"
        r"(?:\(?\d{2,4}\)?[\s.\-]?)?"
        r"\d{3}[\s.\-]\d{4}(?:\s*(?:x|ext\.?)[\s:]*\d{1,5})?"
    )

    # Decode HTML entities (&#64; → @, etc.) before parsing.
    decoded_html = html_module.unescape(html)
    soup = BeautifulSoup(decoded_html, "html.parser")

    # Remove <script> and <style> so get_text() is clean.
    for tag in soup(["script", "style"]):
        tag.decompose()

    visible_text = soup.get_text(separator=" ")

    emails = set()
    phones = set()
    contact_pages = set()
    social_links = set()

    # --- EMAIL EXTRACTION (4 methods) ---

    # 1. mailto: links via BS4
    for a_tag in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        addr = a_tag["href"].split(":", 1)[1].split("?")[0]
        normalized = _normalize_email(addr)
        if normalized:
            emails.add(normalized)

    # 2. Regex scan on visible text
    for match in re.findall(email_pattern, visible_text):
        normalized = _normalize_email(match)
        if normalized:
            emails.add(normalized)

    # 3. Deobfuscate [at]/(at)/[dot]/(dot) in visible text
    deobfuscated = re.sub(r'\s*[\[\(]\s*at\s*[\]\)]\s*', '@', visible_text, flags=re.IGNORECASE)
    deobfuscated = re.sub(r'\s*[\[\(]\s*dot\s*[\]\)]\s*', '.', deobfuscated, flags=re.IGNORECASE)
    for match in re.findall(email_pattern, deobfuscated):
        normalized = _normalize_email(match)
        if normalized:
            emails.add(normalized)

    # 4. Scan Playwright body_text (catches JS-rendered text invisible in raw HTML)
    if body_text:
        for match in re.findall(email_pattern, body_text):
            normalized = _normalize_email(match)
            if normalized:
                emails.add(normalized)

    # --- PHONE EXTRACTION (2 methods) ---

    # 1. tel: links via BS4
    for a_tag in soup.find_all("a", href=re.compile(r"^tel:", re.I)):
        phone_val = a_tag["href"].split(":", 1)[1]
        normalized = _normalize_phone(phone_val)
        if normalized:
            phones.add(normalized)

    # 2. Regex scan on visible text
    for match in re.findall(phone_pattern, visible_text):
        normalized = _normalize_phone(match)
        if normalized:
            phones.add(normalized)

    # --- LINK EXTRACTION via BS4 ---
    contact_keywords = (
        "contact", "about", "support", "help",
        "enquiry", "enquire", "get-in-touch", "reach-us",
        "connect", "feedback", "info",
    )
    social_domains = (
        "facebook.com", "instagram.com", "linkedin.com",
        "x.com", "twitter.com", "youtube.com", "tiktok.com",
    )

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        lower = absolute.lower()

        if any(kw in lower for kw in contact_keywords):
            contact_pages.add(absolute)
        if any(site in lower for site in social_domains):
            social_links.add(absolute)

    return {
        "emails": emails,
        "phones": phones,
        "contact_pages": contact_pages,
        "social_links": social_links,
    }


def extract_website_contacts(website, max_contact_pages=3):
    print(f"\n  [extract_website_contacts] START {website}")
    website = normalize_url(website)
    empty_result = {
        "emails": [],
        "phones_from_website": [],
        "contact_pages": [],
        "social_links": [],
        "extracted_from": [],
    }
    if not website:
        return empty_result

    html, body_text, mailto_emails = fetch_html(website)
    if not html:
        return empty_result

    schema_data = extract_schema_contacts(html)
    page_data = extract_contacts_and_links(html, website, body_text=body_text)

    sources = set()
    if schema_data["schema_emails"] or schema_data["schema_phones"]:
        sources.add("schema.org")
    if page_data["emails"] or page_data["phones"]:
        sources.add("homepage")

    contact_pages = set(page_data["contact_pages"])
    social_links = set(page_data["social_links"]) | set(schema_data["schema_social_links"])
    emails = set(page_data["emails"]) | set(schema_data["schema_emails"])
    phones = set(page_data["phones"]) | set(schema_data["schema_phones"])

    # Merge mailto emails captured from the live DOM by Playwright.
    for addr in mailto_emails:
        normalized = _normalize_email(addr)
        if normalized:
            emails.add(normalized)

    # Crawl only top contact-like pages to keep it fast and focused.
    for page_url in list(contact_pages)[:max_contact_pages]:
        cp_html, cp_body, cp_mailtos = fetch_html(page_url)
        if not cp_html:
            continue

        extra_schema = extract_schema_contacts(cp_html)
        extra_page_data = extract_contacts_and_links(cp_html, page_url, body_text=cp_body)

        if extra_schema["schema_emails"] or extra_schema["schema_phones"]:
            sources.add("schema.org:contact-page")
        if extra_page_data["emails"] or extra_page_data["phones"]:
            sources.add("contact-page")

        emails.update(extra_schema["schema_emails"])
        emails.update(extra_page_data["emails"])
        phones.update(extra_schema["schema_phones"])
        phones.update(extra_page_data["phones"])
        social_links.update(extra_schema["schema_social_links"])
        social_links.update(extra_page_data["social_links"])

        for addr in cp_mailtos:
            normalized = _normalize_email(addr)
            if normalized:
                emails.add(normalized)

    print(f"  [extract_website_contacts] {website} => {len(emails)} emails, {len(phones)} phones", flush=True)

    return {
        "emails": sorted(emails),
        "phones_from_website": sorted(phones),
        "contact_pages": sorted(contact_pages),
        "social_links": sorted(social_links),
        "extracted_from": sorted(sources),
    }

def extract_business_info(local_results):
    print(f"\n[extract_business_info] Processing {len(local_results or [])} businesses ...")
    businesses = []
    local_results = local_results or []
    for i, result in enumerate(local_results):
        website = result.get("website")
        website_data = {
            "emails": [],
            "phones_from_website": [],
            "contact_pages": [],
            "social_links": [],
            "extracted_from": [],
        }

        if website:
            print(f"  [{i+1}/{len(local_results)}] Scraping {website} ...", flush=True)
            website_data = extract_website_contacts(website)

        business = {
            "name": result.get("title"),
            "address": result.get("address"),
            "phone": result.get("phone"),
            "website": website,
            "type": result.get("type"),
            "emails": website_data["emails"],
            "phones_from_website": website_data["phones_from_website"],
            "social_links": website_data["social_links"]
        }
        businesses.append(business)
    return businesses


def _build_business_report(type_of_business, city, country, api_key):
    """Fetch businesses and return normalized report payload."""
    print(f"\n[_build_business_report] type='{type_of_business}', city='{city}', country='{country}'")
    key = (api_key or "").strip() if isinstance(api_key, str) else ""
    if not key:
        raise ValueError("API key is required.")

    local_results = search_local_businesses(type_of_business, key, city, country)
    businesses = extract_business_info(local_results)

    file_name = f"{_to_slug(type_of_business)}_{_to_slug(city)}_{_to_slug(country)}.xlsx"
    output_path = os.path.join(os.getcwd(), file_name)

    return {
        "businesses": businesses,
        "file_name": file_name,
        "output_path": output_path,
        "city": city,
        "country": country,
    }


def _write_businesses_to_excel(businesses, output_path, city, country):
    """Write normalized businesses list to an Excel workbook."""

    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required to export Excel. Install it with: pip install openpyxl"
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "businesses"

    headers = [
        "country",
        "city",
        "name",
        "address",
        "phone",
        "website",
        "type",
        "emails",
        "phones_from_website",
        "contact_pages",
        "social_links",
        "extracted_from",
    ]
    sheet.append(headers)

    for business in businesses:
        sheet.append([
            country or "",
            city or "",
            business.get("name") or "",
            business.get("address") or "",
            business.get("phone") or "",
            business.get("website") or "",
            business.get("type") or "",
            ", ".join(business.get("emails", [])),
            ", ".join(business.get("phones_from_website", [])),
            ", ".join(business.get("contact_pages", [])),
            ", ".join(business.get("social_links", [])),
            ", ".join(business.get("extracted_from", [])),
        ])

    workbook.save(output_path)
    print(f"  [_write_businesses_to_excel] Saved {len(businesses)} rows to {output_path}")


def save_businesses_to_excel(type_of_business, city, country, api_key):
    """Single entry point: fetch businesses, enrich website data, and save to Excel."""
    report = _build_business_report(
        type_of_business=type_of_business,
        city=city,
        country=country,
        api_key=api_key,
    )
    _write_businesses_to_excel(
        report["businesses"],
        report["output_path"],
        report["city"],
        report["country"],
    )
    return report["output_path"]


@app.get("/api/health")
def health_check():
    print('yes')
    return jsonify({"status": "ok"})


@app.post("/api/check-quota")
def check_quota_api():
    payload = request.get_json(silent=True) or {}
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "api_key is required."}), 400
    left = _get_searches_left(api_key)
    return jsonify({"total_searches_left": left})


@app.post("/api/extract")
def extract_businesses_api():
    print(f"\n=== /api/extract HIT ===", flush=True)
    payload = request.get_json(silent=True) or {}
    print(f"  Payload: {payload}", flush=True)
    type_of_business = (payload.get("type_of_business") or "").strip()
    city = (payload.get("city") or "").strip()
    country = (payload.get("country") or "").strip()
    api_key = payload.get("api_key")

    if not type_of_business or not city or not country:
        return jsonify({"error": "type_of_business, city, and country are required."}), 400

    try:
        report = _build_business_report(
            type_of_business=type_of_business,
            city=city,
            country=country,
            api_key=api_key,
        )
        _write_businesses_to_excel(
            report["businesses"],
            report["output_path"],
            report["city"],
            report["country"],
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "message": "Extraction completed successfully.",
            "file_name": report["file_name"],
            "file_url": f"/api/download/{report['file_name']}",
            "business_count": len(report["businesses"]),
            "businesses": report["businesses"],
        }
    )

@app.get("/api/download/<path:file_name>")
def download_report(file_name):
    safe_name = os.path.basename(file_name)
    return send_from_directory(os.getcwd(), safe_name, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)