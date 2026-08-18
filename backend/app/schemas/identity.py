from pydantic import BaseModel


class IdentityResolutionResult(BaseModel):
    source: str
    scanned: int
    companies_created: int
    companies_matched: int
    aliases_created: int
    source_identities_created: int
    founders_created: int
    founder_links_created: int
    founder_profiles_created: int
    review_items_created: int
    skipped_already_linked: int
