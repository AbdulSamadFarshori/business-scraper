from sales_website_extract import (
    fetch_html,
    extract_contacts_and_links,
    extract_schema_contacts,
    extract_website_contacts,
)


if __name__ == "__main__":
    url = "https://bondifamilydentist.com/"

    print(f"=== Testing URL: {url} ===\n")

    # 1. Fetch HTML (now returns a tuple)
    html, body_text, mailto_emails = fetch_html(url)
    print(f"[fetch_html] HTML length: {len(html)} chars")
    print(f"[fetch_html] Body text length: {len(body_text)} chars")
    print(f"[fetch_html] Mailto emails from DOM: {mailto_emails}\n")

    if not html:
        print("ERROR: fetch_html returned empty HTML. Exiting.")
        raise SystemExit(1)

    # 2. Extract structured data (schema.org / JSON-LD)
    schema = extract_schema_contacts(html)
    print(f"[schema] Emails: {schema['schema_emails']}")
    print(f"[schema] Phones: {schema['schema_phones']}")
    print(f"[schema] Social: {schema['schema_social_links']}\n")

    # 3. Extract contacts & links with BeautifulSoup
    page_data = extract_contacts_and_links(html, url, body_text=body_text)
    print(f"[BS4] Emails: {page_data['emails']}")
    print(f"[BS4] Phones: {page_data['phones']}")
    print(f"[BS4] Contact pages: {page_data['contact_pages']}")
    print(f"[BS4] Social links: {page_data['social_links']}\n")

    # 4. Full extraction pipeline (homepage + contact pages)
    print("--- Running full extract_website_contacts ---")
    result = extract_website_contacts(url)
    print(f"Emails:        {result['emails']}")
    print(f"Phones:        {result['phones_from_website']}")
    print(f"Contact pages: {result['contact_pages']}")
    print(f"Social links:  {result['social_links']}")
    print(f"Sources:       {result['extracted_from']}")