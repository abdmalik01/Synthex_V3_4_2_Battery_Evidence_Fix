from __future__ import annotations
import sys
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text
from synthex_platform.extraction import DomainRouter

if len(sys.argv) < 2:
    raise SystemExit('Usage: python smoke_route.py "path/to/paper.pdf"')
text = pages_to_marked_text(extract_pages(sys.argv[1]))
route = DomainRouter().route_text(text)
print("Domain:", route.domain)
print("Confidence:", route.confidence)
print("Paper types:", ", ".join(route.paper_types) if route.paper_types else "-")
print("Matched terms:", route.matched_terms.get(route.domain, []))
