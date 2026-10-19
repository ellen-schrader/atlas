"""How Atlas introduces itself to the public APIs it calls (Crossref, NCBI,
Europe PMC, ClinicalTrials.gov), which ask for a contact address."""

CONTACT_EMAIL = "hello@labatlas.app"
API_USER_AGENT = f"paper-radar/0.1 (mailto:{CONTACT_EMAIL})"
