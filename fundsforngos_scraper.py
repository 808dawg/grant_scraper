import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import json
import re
import time # Import time module
import logging
# Add urllib.parse import here for urljoin
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_date(date_str):
    import locale
    formats = [
        "%d-%b-%y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
        "%d/%m/%y", "%d/%m/%Y", "%m/%d/%y", "%m/%d/%Y",
        "%Y-%m-%d", "%d %B %Y", "%d %b %Y"
    ]
    
    # Normalize input
    cleaned = re.sub(r'(\d+)(th|st|nd|rd)\b', r'\1', date_str.strip())
    cleaned = re.sub(r'[\u200B-\u200D\uFEFF]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Try standard formats first
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    
    # Try locale-specific parsing
    original_locale = locale.getlocale(locale.LC_TIME)
    try:
        for lang in ['en_US', 'fr_FR', 'es_ES']:
            try:
                locale.setlocale(locale.LC_TIME, f'{lang}.UTF-8')
                dt = datetime.strptime(cleaned, "%d %b %Y")
                locale.setlocale(locale.LC_TIME, original_locale)
                return dt
            except:
                continue
    finally:
        locale.setlocale(locale.LC_TIME, original_locale)
    
    # Final fallback to dateutil
    try:
        from dateutil.parser import parse
        return parse(cleaned)
    except Exception as e:
        logging.error(f"Date parsing failed for '{date_str}': {str(e)}")
    
    logging.warning(f"All date parsing attempts failed for: {date_str}")
    return None


# Option E: Return tuple (amount_int, currency_str) - Corrected Group Capturing
def extract_amount(text):
    """
    Extracts a grant amount and currency from text.
    Prioritizes ranges, then 'up to', then single amounts.
    Handles currency symbols, codes (USD/EUR/GBP), commas, and multipliers.
    Returns a tuple (max_amount_int, currency_string) or (None, None).
    """
    # Define base patterns with non-capturing groups for internal use
    currency_symbols_nc = r'(?:[$€£])'
    currency_codes_nc = r'(?:USD|EUR|GBP)'
    currency_pattern_nc = rf'(?:{currency_symbols_nc}|{currency_codes_nc})'
    number_pattern_nc = r'(?:\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)'
    multiplier_pattern_nc = r'(?:\s*(?:k|thousand|million)\b)'

    # Define patterns with specific capturing groups for extraction
    currency_capture = rf'({currency_symbols_nc}|{currency_codes_nc})' # Captures the specific symbol/code
    number_capture = rf'({number_pattern_nc})' # Captures the number string
    multiplier_capture = r'(\s*(?:k|thousand|million)\b)' # Fixed: Added parentheses around the entire pattern

    # --- Helper Function ---
    def clean_and_convert(num_str, multiplier_str=None):
        if num_str is None: return None
        try:
            # Remove currency symbols and commas for calculation
            cleaned_num = re.sub(rf'{currency_symbols_nc}|,', '', num_str).strip()
            value = float(cleaned_num)
            multiplier = 1
            if multiplier_str:
                multi_lower = multiplier_str.lower()
                if multi_lower == 'k' or multi_lower == 'thousand': multiplier = 1000
                elif multi_lower == 'million': multiplier = 1000000
            return int(value * multiplier)
        except (ValueError, TypeError):
            logging.warning(f"Could not convert '{num_str}' with multiplier '{multiplier_str}' to number.")
            return None

    # --- Regex Patterns (with corrected capturing groups) ---
    # 1. Mangled Range (e.g., 025 - 203) - Assume thousands, no currency info usually
    # Groups: (num1), (num2)
    mangled_range_pattern = re.compile(r'\b(0?\d{1,3})\s*-\s*(\d{1,3})\b')

    # 2. Standard Range (e.g., $1,000 - $5,000 or 10k - 20k euros)
    # Groups: (cur1)?, (num1), (mult1)?, (cur2)?, (num2), (mult2)?, (cur3)?
    # Corrected: Removed '?' after number_capture groups as numbers are required in a range.
    # Fixed regex pattern with proper grouping and escaping
    try:
        standard_range_pattern = re.compile(
            rf'(?:{currency_capture})?\s*{number_capture}(?:\s*{multiplier_capture})?\s*(?:-|to)\s*(?:{currency_capture})?\s*{number_capture}(?:\s*{multiplier_capture})?',
            re.IGNORECASE
        )
    except re.error as e:
        logging.error(f"Regex compilation error: {str(e)}")
        return None, None

    # 3. Up To / Maximum (e.g., up to $10,000, maximum of 5 million EUR)
    # Groups: (cur1)?, (num), (mult)?, (cur2)?
    upto_pattern = re.compile(
        rf'(?:up to|maximum of|upto)\s+(?:{currency_capture})?\s*{number_capture}(?:{multiplier_capture})?\s*(?:{currency_capture})?',
        re.IGNORECASE
    )

    # 4. Single Amount (Prefers explicit keywords or currency symbols/codes)
    # Stricter: Requires keywords like 'grant of', 'prize of', 'amount:', 'USD', etc.
    # Groups: (cur1)?, (num), (mult)?, (cur2)?
    strict_single_pattern = re.compile(
        rf'(?:grants? of|prize of|award of|funding of|amount:)\s*{currency_capture}?\s*{number_capture}\s*{multiplier_capture}?\s*{currency_capture}?',
        re.IGNORECASE
    )
    # Currency Code specific
    # Groups: (code), (num), (mult)?
    code_single_pattern = re.compile(
        rf'({currency_codes_nc})\s*{number_capture}\s*{multiplier_capture}?', # Capture code, num, mult
        re.IGNORECASE
    )
    # Currency Symbol specific
    # Groups: (symbol), (num), (mult)?
    symbol_single_pattern = re.compile(
        rf'({currency_symbols_nc})\s*{number_capture}\s*{multiplier_capture}?', # Capture symbol, num, mult
        re.IGNORECASE
    )

    # --- Search Logic ---
    found_amount = None
    found_currency = None

    # 1. Check Mangled Range (Assume thousands, no currency)
    mangled_match = mangled_range_pattern.search(text)
    if mangled_match:
        num1_str, num2_str = mangled_match.groups() # Expects 2 groups
        val1 = clean_and_convert(num1_str, 'thousand')
        val2 = clean_and_convert(num2_str, 'thousand')
        if val1 is not None and val2 is not None:
            found_amount = max(val1, val2)
            found_currency = "$" # Default to $ for mangled ranges
            logging.info(f"Found mangled range amount: {mangled_match.group(0)} -> {found_amount} (Currency: {found_currency})")
            return f"{found_currency}{found_amount}", None
        else:
            logging.warning(f"Found mangled range '{mangled_match.group(0)}' but failed conversion.")

    # 2. Check Standard Range
    range_match = standard_range_pattern.search(text)
    if range_match:
        # Expects 7 groups: cur1, num1, mult1, cur2, num2, mult2, cur3
        cur1, num1_str, mult1, cur2, num2_str, mult2, cur3 = range_match.groups()
        mult2 = mult2 or mult1 # Use first multiplier if second is missing
        val1 = clean_and_convert(num1_str, mult1)
        val2 = clean_and_convert(num2_str, mult2)
        if val1 is not None and val2 is not None:
            found_amount = max(val1, val2)
            # Determine currency: prioritize currency next to max value, then other currency, then None
            max_val_cur = cur2 if val2 >= val1 else cur1
            # Safely get currency values with fallbacks
            found_currency = next((c for c in [max_val_cur, cur3, cur1, cur2] if c), "$")
            logging.info(f"Found standard range amount: {range_match.group(0)} -> {found_amount} (Currency: {found_currency})")
            return f"{found_currency}{found_amount}", None
        else:
            logging.warning(f"Found standard range '{range_match.group(0)}' but failed conversion.")

    # 3. Check "Up to X" / "Maximum of X"
    upto_match = upto_pattern.search(text)
    if upto_match:
        # Expects 4 groups: cur1, num, mult, cur2
        cur1, num_str, mult_str, cur2 = upto_match.groups()
        try:
            val = clean_and_convert(num_str, mult_str)
        except Exception as e:
            logging.warning(f"Amount conversion failed: {str(e)}")
            val = None
        if val is not None:
            found_amount = val
            found_currency = cur1 or cur2 or "$" # Prioritize currency before number, default to $
            logging.info(f"Found 'up to/maximum' amount: {upto_match.group(0)} -> {found_amount} (Currency: {found_currency})")
            return f"{found_currency}{found_amount}", None

    # 4. Check Single Amounts (Strict keywords, codes, then symbols)
    potential_matches = [] # Store tuples of (value, currency, original_match_string)
    patterns_to_check = [
        (strict_single_pattern, 4), # cur1, num, mult, cur2
        (code_single_pattern, 3),   # code, num, mult
        (symbol_single_pattern, 3)  # symbol, num, mult
    ]

    for pattern, expected_groups in patterns_to_check:
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) != expected_groups:
                logging.error(f"Regex pattern {pattern.pattern} returned {len(groups)} groups, expected {expected_groups}. Match: {match.group(0)}")
                continue # Skip this match if group count is wrong

            num_str, mult_str, currency = None, None, None

            try:
                if pattern == strict_single_pattern:
                    cur1, num_str, mult_str, cur2 = groups
                    currency = cur1 or cur2
                elif pattern == code_single_pattern:
                    currency, num_str, mult_str = groups
                elif pattern == symbol_single_pattern:
                    currency, num_str, mult_str = groups
            except ValueError as e:
                 logging.error(f"Error unpacking groups for pattern {pattern.pattern} on match '{match.group(0)}': {e}")
                 continue


            val = clean_and_convert(num_str, mult_str)
            if val is not None:
                 is_year = (1990 <= val <= 2050 and mult_str is None and '.' not in num_str)
                 if not is_year:
                     potential_matches.append((val, currency, match.group(0)))
                     logging.debug(f"Potential single amount: {match.group(0)} -> {val} (Currency: {currency})")

    if potential_matches:
        # Sort by value descending, return the largest amount and its currency
        potential_matches.sort(key=lambda x: x[0], reverse=True)
        found_amount, found_currency, match_str = potential_matches[0]
        logging.info(f"Found single amount(s), selected max: {match_str} -> {found_amount} (Currency: {found_currency})")
        return found_amount, found_currency

    # Fallback: No reliable amount found
    logging.info(f"No clear amount pattern found in text: '{text[:100]}...'")
    return None, None


# Change the output path to use grants.json in the current directory
base_url = "https://www2.fundsforngos.org/tag/funding-opportunities-and-resources-in-kenya/page/{}/"
# Hardcoded to April 2nd 2025 per user requirements
from datetime import date
deadline_cutoff = date(2025, 4, 2)  # Year, Month, Day fixed values
logging.info(f"CONFIRMED CUTOFF: {deadline_cutoff.strftime('%d-%b-%Y')}")
output_path = 'c:\\Users\\doug\\Documents\\Cline\\grant_scraper\\grants.json'  # Fixed variable name
# Remove this line that's overriding the output_path
# output_path = 'grantsource/grantopportunities.json' # Define output path earlier

# --- Load existing grants ---
existing_grants = []
existing_grant_urls = set()
try:
    import os
    # Ensure directory exists before trying to read
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'r', encoding='utf-8') as f:
        existing_grants = json.load(f)
        if isinstance(existing_grants, list):
            for grant in existing_grants:
                if isinstance(grant, dict) and 'applicationUrl' in grant:
                    existing_grant_urls.add(grant['applicationUrl'])
            logging.info(f"Loaded {len(existing_grants)} existing grants from {output_path}")
        else:
            logging.warning(f"Existing file {output_path} does not contain a valid JSON list. Starting fresh.")
            existing_grants = [] # Reset if format is wrong
except FileNotFoundError:
    logging.info(f"Initializing new output file {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump([], f)
    existing_grants = []
except json.JSONDecodeError:
    logging.error(f"Error decoding JSON from {output_path}. Starting fresh.")
    existing_grants = []
except Exception as e:
    logging.error(f"Unexpected error loading existing grants: {e}")
    existing_grants = []

# Initialize grants list with existing data
grants = existing_grants
processed_urls = set() # Keep track of URLs processed in *this* run to avoid duplicate work

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}

for page in range(1, 11):
    logging.info(f"Processing page {page}...")
    page_url = base_url.format(page)
    try:
        response = requests.get(page_url, headers=headers, timeout=30)
        response.raise_for_status()
        time.sleep(2)

        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all('article', class_=re.compile(r'post-\d+'))

        if not articles:
            logging.info(f"No articles found on page {page}, stopping.")
            break

        page_has_valid_grants = False

        for article in articles:
            # Initialize grant dictionary with defaults
            grant = {'deadline': None, 'title': None, 'applicationUrl': None, 'organization': None,
                     'description': None, 'amount': None, 'status': 'active', 
                     'eligibility': 'See official guidelines', 'category': 'General'}
            try:
                title_tag = article.find('h2', class_='entry-title')
                link_tag = title_tag.find('a') if title_tag else None

                if not title_tag or not link_tag or not link_tag.has_attr('href'):
                    logging.warning(f"  Skipping article - missing title/URL")
                    continue

                # First, let's add the clean_text function that's missing
                def clean_text(text):
                    """Clean and normalize text content"""
                    if not text:
                        return text
                        
                    # Replace common Unicode characters
                    text = text.replace('\u2019', "'")
                    text = text.replace('\u2018', "'")
                    text = text.replace('\u201c', '"')
                    text = text.replace('\u201d', '"')
                    text = text.replace('\u2013', '-')
                    text = text.replace('\u2014', '-')
                    text = text.replace('\u00a0', ' ')
                    
                    # Remove excessive whitespace
                    text = re.sub(r'\s+', ' ', text).strip()
                    
                    return text
                
                # Add a function to clean amount values
                def clean_amount_value(amount_str):
                    """Clean and standardize amount values"""
                    if not amount_str:
                        return None
                        
                    # Handle Unicode characters
                    if isinstance(amount_str, str):
                        amount_str = amount_str.replace('\u00a3', '£')
                    
                    # Add missing currency symbol if it's just a number
                    if isinstance(amount_str, (int, float)):
                        return f"${amount_str:,}"
                        
                    # If it's a string with just digits, add $ symbol
                    if isinstance(amount_str, str) and amount_str.isdigit():
                        return f"${int(amount_str):,}"
                        
                    # If it already has a currency symbol, format it properly
                    if isinstance(amount_str, str) and amount_str.startswith(('$', '£', '€')):
                        currency = amount_str[0]
                        try:
                            value = float(re.sub(r'[^\d.]', '', amount_str))
                            return f"{currency}{value:,.0f}"
                        except:
                            return amount_str
                            
                    return amount_str
                
                # Define the extract_organization function properly
                def extract_organization(article, grant):
                    """Enhanced organization name extraction from multiple sources"""
                    # Priority 1: Check if organization is mentioned in title pattern
                    title = grant.get('title', '')
                    org_patterns = [
                        r"(?:by|from|at|for)\s+([A-Z][A-Za-z\s&'-]+?(?=\s+(Grant|Award|Program|Prize|Fellowship)))",
                        r"(?:by|from|at|for)\s+([A-Z][A-Za-z\s&'-]+?(?=\.|$))",
                        r"(?:presented by|sponsored by|supported by)\s+([A-Z][A-Za-z\s&'-]+)"
                    ]
                    
                    for pattern in org_patterns:
                        match = re.search(pattern, title, re.IGNORECASE)
                        if match:
                            org = next((g for g in match.groups() if g), None)
                            if org:
                                return clean_text(org.strip("'s").strip())
                    
                    # Priority 2: Extract from URL domain
                    url = grant.get('applicationUrl', '')
                    if url:
                        try:
                            domain = url.split('/')[2] if len(url.split('/')) > 2 else ''
                            domain_parts = [p for p in domain.split('.') 
                                          if p.lower() not in {'com','org','net','gov','edu','co','ac','uk','www'}]
                            if domain_parts:
                                org = max(domain_parts, key=len)
                                return clean_text(org.replace('-', ' ').title())
                        except Exception as e:
                            logging.debug(f"Error extracting org from URL: {e}")
                    
                    # Priority 3: Extract from description first sentence
                    desc = grant.get('description', '')
                    if desc:
                        first_sentence = desc.split('.')[0] if '.' in desc else desc
                        org_patterns = [
                            r"(?:The|A|An)\s+([A-Z][A-Za-z\s&'-]+?(?=\s+(is|has|announces|offers)))",
                            r"([A-Z][A-Za-z\s&'-]+?(?=\s+(Grant|Award|Program|Initiative)))",
                            r"(?:funded by|sponsored by)\s+([A-Z][A-Za-z\s&'-]+)"
                        ]
                        for pattern in org_patterns:
                            match = re.search(pattern, first_sentence, re.IGNORECASE)
                            if match:
                                org = next((g for g in match.groups() if g), None)
                                if org:
                                    return clean_text(org.strip("'s").strip())
                    
                    # Priority 4: Check article metadata (if available)
                    if article:
                        org_tag = article.find('span', class_='author') or \
                         article.find('span', class_='organization') or \
                         article.find('div', class_='org-name')
                        if org_tag and org_tag.text.strip():
                            return clean_text(org_tag.text.strip())
                    
                    # Priority 5: Extract from application URL directly
                    if url:
                        url_org_patterns = [
                            r"https?://(?:www\.)?([a-zA-Z0-9-]+)\.",
                            r"https?://(?:www\.)?[a-zA-Z0-9-]+\.([a-zA-Z0-9-]+)\."
                        ]
                        for pattern in url_org_patterns:
                            match = re.search(pattern, url)
                            if match and match.group(1) and match.group(1).lower() not in {'com','org','net','gov','edu','co','ac','uk','www'}:
                                return clean_text(match.group(1).replace('-', ' ').title())
                    
                    # Fallback: Try to extract organization from the application URL hostname
                    if url:
                        try:
                            from urllib.parse import urlparse
                            hostname = urlparse(url).netloc
                            if hostname:
                                # Remove www. and common TLDs
                                org_name = re.sub(r'^www\.', '', hostname)
                                org_name = re.sub(r'\.(com|org|net|gov|edu|co|ac|uk)$', '', org_name)
                                if org_name:
                                    return clean_text(org_name.split('.')[0].replace('-', ' ').title())
                        except Exception as e:
                            logging.debug(f"Error parsing URL: {e}")
                    
                    # Fallback: Return a more specific "Unknown" rather than "Not Found"
                    return "Unknown Organization"
                
                # Make sure to add this code where you process each grant
                # This should be in your main scraping loop where you process each article
                grant['organization'] = extract_organization(article, grant)
                
                # Clean organization name if needed
                if grant['organization'] and grant['organization'] not in ["Unknown Organization", "Organization Not Found"]:
                    grant['organization'] = re.sub(r"(https?://|www\.)", "", grant['organization'], flags=re.IGNORECASE)
                    grant['organization'] = re.sub(r"\b(Trust|Foundation|Fund|Org(a?nization)?|Programme?)\b", "", grant['organization'], flags=re.IGNORECASE)
                    grant['organization'] = grant['organization'].strip(" -_./")
                    if len(grant['organization']) < 3:  # If too short after cleaning
                        grant['organization'] = "Unknown Organization"
                
                # Apply this function to extract amount from description if not already set
                if not grant['amount'] or grant['amount'] == 'null':
                    extracted_amount = extract_amount_from_text(full_description_text)
                    if extracted_amount:
                        grant['amount'] = extracted_amount
                
                # --- Fix text encoding issues ---
                # Add this before saving the grants
                def clean_text(text):
                    """Clean and normalize text content"""
                    if not text:
                        return text
                        
                    # Replace common Unicode characters
                    text = text.replace('\u2019', "'")
                    text = text.replace('\u2018', "'")
                    text = text.replace('\u201c', '"')
                    text = text.replace('\u201d', '"')
                    text = text.replace('\u2013', '-')
                    text = text.replace('\u2014', '-')
                    text = text.replace('\u00a0', ' ')
                    
                    # Remove excessive whitespace
                    text = re.sub(r'\s+', ' ', text).strip()
                    
                    return text
                
                # Apply text cleaning to all text fields
                for field in ['title', 'description', 'eligibility']:
                    if field in grant and grant[field]:
                        grant[field] = clean_text(grant[field])

                logging.info(f"  Fetching details for: {grant['title'][:50]}...")
                detail_resp = requests.get(grant['applicationUrl'], headers=headers, timeout=30)
                detail_resp.raise_for_status()
                time.sleep(2)
                detail_soup = BeautifulSoup(detail_resp.content, 'html.parser')

                content_div = detail_soup.find('div', class_='entry-content')
                full_description_text = ""
                cleaned_description = "Description not found."
                deadline_str_extracted = None
                external_application_url = grant['applicationUrl'] # Default

                if content_div:
                    full_description_text = ' '.join(content_div.stripped_strings)
                    cleaned_description = full_description_text

                    # --- Find the external application link ---
                    info_para = None
                    key_phrases = ["For more information, visit", "More information is available at", "Visit the website for details"]
                    for p in content_div.find_all('p'):
                        p_text = p.get_text()
                        for phrase in key_phrases:
                            if phrase.lower() in p_text.lower():
                                info_para = p
                                break
                        if info_para: break
                    if info_para:
                        link_tag = info_para.find('a', href=True)
                        if link_tag:
                            external_application_url = urljoin(grant['applicationUrl'], link_tag['href'])
                            logging.info(f"  Found external application URL: {external_application_url}")
                        else: logging.warning(f"  Found 'For more info' paragraph but no link inside.")
                    else: logging.warning(f"  Could not find 'For more info' paragraph.")
                    # --- End of external link finding ---

                    # --- START: Extract Eligibility ---
                    eligibility_summary = "See official guidelines" # Default
                    eligibility_keywords = ["Eligibility Criteria", "Who can apply?", "Eligible Applicants", "Eligibility"]
                    eligibility_start_index = -1
                    found_keyword = None
                    keyword_search_text = full_description_text.lower()

                    for keyword in eligibility_keywords:
                        try:
                            # Use regex to find keyword at start of line or after punctuation/space
                            # This helps ensure it's likely a heading
                            match = re.search(rf'(?:^|[\s.:;])\s*({re.escape(keyword)})\b', full_description_text, re.IGNORECASE | re.MULTILINE)
                            if match:
                                eligibility_start_index = match.start(1) # Start index of the keyword itself
                                found_keyword = match.group(1) # Get the actual matched keyword casing
                                logging.info(f"  Found potential eligibility keyword: '{found_keyword}' at index {eligibility_start_index}")
                                break
                        except Exception as e_regex:
                            logging.error(f"Regex error searching for eligibility keyword '{keyword}': {e_regex}")
                            continue

                    if eligibility_start_index != -1:
                        start_pos = eligibility_start_index + len(found_keyword)
                        eligibility_text = full_description_text[start_pos:].strip()
                        eligibility_text = re.sub(r'^[:\s]+', '', eligibility_text) # Clean leading punctuation

                        # Find end point (e.g., next common heading or max length)
                        end_markers = ["Funding Information", "How to Apply", "Application Process", "Award Information", "Prize Information", "Focus Areas", "Thematic Areas", "Objectives", "Benefits"]
                        end_pos = len(eligibility_text)
                        for marker in end_markers:
                            try:
                                # Find marker, ensuring it's likely a heading
                                marker_match = re.search(rf'(?:^|[\s.:;])\s*({re.escape(marker)})\b', eligibility_text, re.IGNORECASE | re.MULTILINE)
                                if marker_match:
                                    end_pos = min(end_pos, marker_match.start())
                            except Exception as e_marker:
                                logging.error(f"Regex error searching for end marker '{marker}': {e_marker}")
                                continue

                        eligibility_text_segment = eligibility_text[:end_pos].strip()
                        max_len = 300 # Max length for summary
                        if len(eligibility_text_segment) > max_len:
                            # Try to cut at a sentence boundary nicely
                            cutoff_point = eligibility_text_segment.rfind('.', 0, max_len)
                            if cutoff_point != -1 and cutoff_point > max_len * 0.5: # Ensure cut is not too early
                                eligibility_summary = eligibility_text_segment[:cutoff_point+1]
                            else:
                                # Force cut if no good sentence end found
                                eligibility_summary = eligibility_text_segment[:max_len].strip() + "..."
                        elif len(eligibility_text_segment) > 5: # Require a bit more text to be considered valid
                            eligibility_summary = eligibility_text_segment
                        else:
                            logging.warning(f"  Found eligibility keyword '{found_keyword}' but extracted text too short.")

                        if eligibility_summary != "See official guidelines":
                             logging.info(f"  Extracted eligibility summary: '{eligibility_summary[:50]}...'")
                             grant['eligibility'] = eligibility_summary
                        else:
                             logging.warning(f"  Found eligibility keyword '{found_keyword}' but extracted summary was not suitable.")
                    else:
                        logging.warning(f"  Could not find eligibility section keywords.")
                    # --- END: Extract Eligibility ---


                    # Attempt to extract deadline from detail page text FIRST
                    deadline_match = re.search(r'Deadline\s*:\s*([\w\s,-]+?\d{4}|\d{1,2}[-/][A-Za-z]{3,}[-/]\d{2,4})', full_description_text, re.IGNORECASE)
                    if deadline_match:
                        deadline_str_extracted = deadline_match.group(1).strip()
                        deadline_dt = parse_date(deadline_str_extracted)
                        if deadline_dt and deadline_dt.date() > deadline_cutoff:
                            grant['deadline'] = deadline_dt.strftime("%d-%b-%y")
                            page_has_valid_grants = True
                            # Remove the extracted deadline pattern from the description for cleanliness
                            cleaned_description = re.sub(r'Deadline\s*:\s*' + re.escape(deadline_str_extracted), '', cleaned_description, flags=re.IGNORECASE).strip()
                            logging.info(f"  Extracted deadline: {grant['deadline']}")
                        elif deadline_dt:
                             logging.info(f"  Skipping grant - deadline {deadline_str_extracted} is before cutoff {deadline_cutoff.strftime('%d-%b-%y')}")
                             processed_urls.add(grant['applicationUrl'])
                             continue

                # Fallback deadline extraction from listing page
                if grant['deadline'] is None:
                    deadline_tag_list = article.find('strong', string=re.compile(r'Deadline', re.I))
                    if deadline_tag_list:
                         deadline_str_list = deadline_tag_list.find_parent('p').get_text(strip=True).split(':')[-1].strip()
                         deadline_dt_list = parse_date(deadline_str_list)
                         if deadline_dt_list and deadline_dt_list.date() > deadline_cutoff:
                             grant['deadline'] = deadline_dt_list.strftime("%d-%b-%y")
                             page_has_valid_grants = True
                             deadline_str_extracted = deadline_str_list
                             # Attempt to remove this pattern too if found in description
                             cleaned_description = re.sub(r'Deadline\s*:\s*' + re.escape(deadline_str_extracted), '', cleaned_description, flags=re.IGNORECASE).strip()
                             logging.info(f"  Extracted deadline (fallback): {grant['deadline']}")
                         elif deadline_dt_list:
                             logging.info(f"  Skipping grant (listing page) - deadline {deadline_str_list} is before cutoff {deadline_cutoff.strftime('%d-%b-%y')}")
                             processed_urls.add(grant['applicationUrl'])
                             continue

                # Final deadline check
                if grant['deadline'] is None:
                    logging.warning(f"  Skipping grant - could not find valid deadline after {deadline_cutoff.strftime('%d-%b-%y')}")
                    processed_urls.add(grant['applicationUrl'])
                    continue

                # Validate required fields before saving
                if not all([grant.get('title'), grant.get('applicationUrl'), grant.get('deadline')]):
                    logging.warning(f"Skipping incomplete grant: {grant.get('title', 'Untitled')}")
                    continue
                
                # Validate deadline format
                try:
                    if datetime.strptime(grant['deadline'], "%d-%b-%y").date() <= deadline_cutoff:
                        logging.info(f"Skipping grant with deadline {grant['deadline']}")
                        continue
                except ValueError as e:
                    logging.error(f"Invalid deadline format {grant['deadline']}: {str(e)}")
                    continue

                # Set final description
                grant['description'] = cleaned_description[:500].strip() + ("..." if len(cleaned_description) > 500 else "")
                # Extract amount and currency from ORIGINAL full text
                # Corrected tuple assignment syntax
                amount_with_currency, _ = extract_amount(full_description_text)
                grant['amount'] = amount_with_currency
                # Remove the currency field - it's now combined with amount
                if 'currency' in grant:
                    del grant['currency']
                grant['applicationUrl'] = external_application_url
                # grant['eligibility'] is set within the eligibility block above

                # --- Check if grant already exists before appending ---
                if grant['applicationUrl'] in existing_grant_urls:
                    logging.info(f"  Grant '{grant['title'][:50]}...' already exists in {output_path}. Skipping append.")
                else:
                    # Fix the logging statement - 'currency' key no longer exists
                    logging.info(f"  Successfully processed NEW grant: {grant['title']} (Amount: {grant['amount']})")
                    grants.append(grant) # Append only if it's new
                    existing_grant_urls.add(grant['applicationUrl']) # Add to existing URLs set immediately

                processed_urls.add(grant['applicationUrl']) # Add the original fundsforngos URL to avoid re-processing list items *in this run*

            except requests.exceptions.RequestException as req_e:
                 logging.error(f"HTTP Error processing grant {grant.get('title', 'Unknown')}: {str(req_e)}")
                 time.sleep(5)
                 continue
            except Exception as e:
                logging.error(f"General error processing grant {grant.get('title', 'Unknown')}: {str(e)}", exc_info=True)
                continue

        if not page_has_valid_grants:
            logging.info(f"No grants with deadlines after {deadline_cutoff.strftime('%d-%b-%y')} found on page {page}. Stopping scrape.")
            break

    except requests.exceptions.RequestException as req_e:
        logging.error(f"HTTP Error processing page {page}: {str(req_e)}")
        if isinstance(req_e, requests.exceptions.HTTPError) and req_e.response.status_code == 429:
            logging.warning("Rate limit hit. Stopping script.")
            break
        time.sleep(10)
        continue
    except Exception as e:
        logging.error(f"General error processing page {page}: {str(e)}", exc_info=True)
        continue

# --- After loop ---
# Calculate how many grants were newly added in this run
new_grants_count = len(grants) - len(existing_grants)

if new_grants_count > 0:
    logging.info(f"Added {new_grants_count} new grants.")
    # Optionally log the first few new grants
    # logging.info("First few new grants added:")
    # new_grants_list = [g for g in grants if g['applicationUrl'] not in existing_grant_urls_before_run] # Need to capture state before run if needed
    # for i, g in enumerate(new_grants_list[:3]):
    #     logging.info(f"New Grant {i+1}: {json.dumps(g, indent=2)}")
elif not grants: # No indent
    logging.warning("No grants found in the file and no new grants were added.") # 4 spaces indent
else: # No indent
    logging.info("No new grants were added in this run.") # 4 spaces indent


# At the end of the script, add more robust saving logic
# Replace the existing save code with this:
try:
    # Make sure the directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Clean up any problematic entries before saving
    for grant in grants:
        # Ensure all required fields exist
        for field in ['deadline', 'title', 'applicationUrl', 'organization', 'description', 'amount', 'status', 'eligibility', 'category']:
            if field not in grant or grant[field] is None:
                if field == 'amount':
                    grant[field] = None
                elif field == 'organization' and (field not in grant or grant[field] == "Organization Not Found"):
                    grant[field] = "Unknown Organization"
                else:
                    grant[field] = ""
        
        # Clean text fields
        for field in ['title', 'description', 'eligibility']:
            if grant[field]:
                grant[field] = clean_text(grant[field])
        
        # Clean amount field
        if grant['amount']:
            grant['amount'] = clean_amount_value(grant['amount'])
    
    # Save the file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(grants, f, indent=2, ensure_ascii=False)
    
    logging.info(f"Successfully saved {len(grants)} grants to {output_path}")
    
except Exception as e:
    logging.error(f"Error saving grants to {output_path}: {str(e)}")


# --- Add this at the end of the script, before saving the grants ---
# Update existing grants with better organization names

# First, define a function to extract organization from URL
def extract_org_from_url(url):
    url_parts = url.split('/')
    if len(url_parts) > 2:
        domain = url_parts[2]
        # Extract organization name from domain
        domain_parts = domain.split('.')
        if len(domain_parts) >= 2:
            # Get the main part of the domain (e.g., "unesco" from "unesco.org")
            org_name = domain_parts[-2]
            # Clean up the organization name
            if org_name.lower() not in ['com', 'org', 'net', 'gov', 'edu', 'co', 'ac']:
                # Convert to title case and replace hyphens with spaces
                org_name = org_name.replace('-', ' ').title()
                return org_name
            else:
                # If it's a common TLD, use the part before it
                if len(domain_parts) > 2:
                    org_name = domain_parts[-3].replace('-', ' ').title()
                    return org_name
                else:
                    return domain
        else:
            return domain
    return None

# Update all grants with "Organization Not Found"
for grant in grants:
    if grant['organization'] == "Organization Not Found":
        # Try to extract from URL
        org_from_url = extract_org_from_url(grant['applicationUrl'])
        if org_from_url:
            grant['organization'] = org_from_url
        else:
            # Try to extract from title
            if grant['title']:
                # Look for organization patterns in the title
                org_patterns = [
                    r"([\w\s&\-',.]+?)(?:'s|s'|s) (?:Grant|Award|Prize|Program|Programme|Initiative|Fund)",
                    r"(?:by|from|sponsored by|offered by|from the|by the) ([\w\s&\-',.]+)"
                ]
                for pattern in org_patterns:
                    org_match = re.search(pattern, grant['title'])
                    if org_match:
                        potential_org = org_match.group(1).strip()
                        # Validate it's not too long or too short
                        if 3 < len(potential_org) < 50:
                            grant['organization'] = potential_org
                            break
            
            # If still not found, use a generic name based on the grant type
            if grant['organization'] == "Organization Not Found":
                if "UN" in grant['title'] or "United Nations" in grant['title']:
                    grant['organization'] = "United Nations"
                elif "UNESCO" in grant['title']:
                    grant['organization'] = "UNESCO"
                elif "WHO" in grant['title']:
                    grant['organization'] = "World Health Organization"
                elif "EU" in grant['title'] or "European Union" in grant['title']:
                    grant['organization'] = "European Union"
                elif "Foundation" in grant['title']:
                    foundation_match = re.search(r"([\w\s&\-',.]+Foundation)", grant['title'])
                    if foundation_match:
                        grant['organization'] = foundation_match.group(1)
                    else:
                        grant['organization'] = "Foundation Grant"
                elif "Award" in grant['title']:
                    grant['organization'] = "Award Program"
                elif "Prize" in grant['title']:
                    grant['organization'] = "Prize Program"
                elif "Scholarship" in grant['title']:
                    grant['organization'] = "Scholarship Program"
                elif "Fellowship" in grant['title']:
                    grant['organization'] = "Fellowship Program"
                else:
                    # Use domain as last resort
                    url_parts = grant['applicationUrl'].split('/')
                    if len(url_parts) > 2:
                        domain = url_parts[2]
                        grant['organization'] = domain
