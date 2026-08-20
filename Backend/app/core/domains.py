"""Approved source domains for web search.

Every domain here was reachability-checked during design. Two separate lists:

* ``LEGAL_INFO_DOMAINS`` — used by the /chat flow for legal *information*.
  Official government / statutory sources only.
* ``JUDICIAL_RECORD_DOMAINS`` — used by the /legal-assistance flow to find
  publicly indexed judicial documents naming advocates. Includes
  ``indiankanoon.org``, which is a private aggregator rather than an official
  source; results from it are always presented with the originating court and
  case citation as the verification reference.

Deliberately absent: the CAPTCHA-gated eCourts search endpoints
(``services.ecourts.gov.in``, ``judgments.ecourts.gov.in``, ``njdg.ecourts.gov.in``).
We link users to those to complete manually — we never query them.
"""

from urllib.parse import urlparse

# --- Official sources for legal information (/chat) -------------------------
LEGAL_INFO_DOMAINS: list[str] = [
    "indiacode.nic.in",
    "www.indiacode.nic.in",
    "sci.gov.in",
    "www.sci.gov.in",
    "nalsa.gov.in",
    "doj.gov.in",
    "legalaffairs.gov.in",
    "lawmin.gov.in",
    "egazette.gov.in",
    "prsindia.org",
    "meity.gov.in",
    "cybercrime.gov.in",
    "consumeraffairs.nic.in",
    "ncdrc.nic.in",
    "labour.gov.in",
    "epfindia.gov.in",
    "incometax.gov.in",
    "rera.gov.in",
    "wcd.nic.in",
    "ncw.nic.in",
    "tele-law.in",
    "nyayabandhu.gov.in",
    "data.gov.in",
    "india.gov.in",
    "pib.gov.in",
]

# --- Sources for publicly indexed judicial records (/legal-assistance) ------
JUDICIAL_RECORD_DOMAINS: list[str] = [
    "indiankanoon.org",
    "sci.gov.in",
    "main.sci.gov.in",
    "ncdrc.nic.in",
    "nclt.gov.in",
    "nclat.nic.in",
    "mhc.tn.gov.in",
    "delhihighcourt.nic.in",
    "bombayhighcourt.nic.in",
    "allahabadhighcourt.in",
    "karnatakajudiciary.kar.nic.in",
    "hckerala.gov.in",
    "calcuttahighcourt.gov.in",
    "gujarathighcourt.nic.in",
    "hcraj.nic.in",
    "patnahighcourt.gov.in",
    "cdnbbsr.s3waas.gov.in",  # NIC CDN hosting official DLSA/SLSA panel documents
    "nalsa.gov.in",
]

# Official pages we link users to but never query programmatically (CAPTCHA-gated).
ECOURTS_ADVOCATE_SEARCH_URL = "https://services.ecourts.gov.in/ecourtindia_v6/"
ECOURTS_JUDGMENT_SEARCH_URL = "https://judgments.ecourts.gov.in/pdfsearch/"

# Domains that are aggregators rather than official government sources.
# Results from these are labelled so the frontend can show them differently.
UNOFFICIAL_AGGREGATORS: frozenset[str] = frozenset({"indiankanoon.org"})


def hostname_of(url: str) -> str:
    """Lowercase hostname for *url*, without a leading ``www.``."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_allowed(url: str, whitelist: list[str]) -> bool:
    """True if *url*'s host is in *whitelist*, or is a subdomain of an entry.

    This runs on every result *after* the search API returns, so an off-list URL
    cannot reach the model even if the provider ignores our domain filter.
    """
    host = hostname_of(url)
    if not host:
        return False
    for entry in whitelist:
        allowed = entry.lower()
        allowed = allowed[4:] if allowed.startswith("www.") else allowed
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def is_official(url: str) -> bool:
    """True if *url* is an official government/court source (not an aggregator)."""
    host = hostname_of(url)
    if host in UNOFFICIAL_AGGREGATORS:
        return False
    return host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".in")


def source_name(url: str) -> str:
    """Human-readable source label for a URL, for display in citations."""
    host = hostname_of(url)
    known = {
        "indiacode.nic.in": "India Code",
        "sci.gov.in": "Supreme Court of India",
        "main.sci.gov.in": "Supreme Court of India",
        "nalsa.gov.in": "NALSA",
        "doj.gov.in": "Department of Justice",
        "legalaffairs.gov.in": "Department of Legal Affairs",
        "lawmin.gov.in": "Ministry of Law and Justice",
        "egazette.gov.in": "Gazette of India",
        "prsindia.org": "PRS Legislative Research",
        "meity.gov.in": "Ministry of Electronics and IT",
        "cybercrime.gov.in": "National Cyber Crime Reporting Portal",
        "consumeraffairs.nic.in": "Department of Consumer Affairs",
        "ncdrc.nic.in": "NCDRC",
        "labour.gov.in": "Ministry of Labour and Employment",
        "indiankanoon.org": "Indian Kanoon",
        "nclt.gov.in": "NCLT",
        "mhc.tn.gov.in": "Madras High Court",
        "delhihighcourt.nic.in": "Delhi High Court",
        "cdnbbsr.s3waas.gov.in": "Government of India (NIC)",
    }
    if host in known:
        return known[host]
    return host or "Unknown source"
