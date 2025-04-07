import json
import re
import logging
from bs4 import BeautifulSoup
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

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
    
    # Priority 5: Extract from application URL directly
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

def update_grants_organizations():
    # Load existing grants
    try:
        with open('c:\\Users\\doug\\Documents\\Cline\\grant_scraper\\grants.json', 'r', encoding='utf-8') as f:
            grants = json.load(f)
        logging.info(f"Loaded {len(grants)} grants from file")
    except Exception as e:
        logging.error(f"Error loading grants: {e}")
        return
    
    updated_count = 0
    
    # Process each grant
    for grant in grants:
        if grant.get('organization') in ["Organization Not Found", None]:
            # No article available for existing grants, so pass None
            new_org = extract_organization(None, grant)
            
            if new_org and new_org != "Unknown Organization":
                # Clean organization name
                new_org = re.sub(r"(https?://|www\.)", "", new_org, flags=re.IGNORECASE)
                new_org = re.sub(r"\b(Trust|Foundation|Fund|Org(a?nization)?|Programme?)\b", "", new_org, flags=re.IGNORECASE)
                new_org = new_org.strip(" -_./")
                
                if len(new_org) >= 3:  # Only use if not too short after cleaning
                    grant['organization'] = new_org
                    updated_count += 1
                    logging.info(f"Updated organization for: {grant['title']} -> {new_org}")
    
    # Save updated grants
    if updated_count > 0:
        try:
            with open('c:\\Users\\doug\\Documents\\Cline\\grant_scraper\\grants.json', 'w', encoding='utf-8') as f:
                json.dump(grants, f, indent=2, ensure_ascii=False)
            logging.info(f"Successfully updated {updated_count} organizations and saved to grants.json")
        except Exception as e:
            logging.error(f"Error saving grants: {e}")
    else:
        logging.info("No organizations were updated")

if __name__ == "__main__":
    update_grants_organizations()