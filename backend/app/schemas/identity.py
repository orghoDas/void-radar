from pydantic import BaseModel


class IdentityResolutionResult(BaseModel):
    source: str
    scanned: int
    companies_created: int
    companies_matched: int
    aliases_created: int
    review_items_created: int
    skipped_already_linked: int

