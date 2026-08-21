from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.llm_client import LlmError
from app.services.parser_generation import (
    PageSample,
    ParserSelectors,
    apply_selectors,
    generate_and_validate,
    load_active_parser,
    selectors_from_payload,
    validate_selectors,
)

CAREERS_HTML = """
<html><body>
  <div class="jobs">
    <div class="job"><a href="/jobs/1"><h3>Senior Backend Engineer</h3></a>
      <span class="loc">Berlin</span><span class="dept">Engineering</span></div>
    <div class="job"><a href="/jobs/2"><h3>Product Manager</h3></a>
      <span class="loc">Remote</span><span class="dept">Product</span></div>
  </div>
</body></html>
"""

GOOD_SELECTORS = {
    "job_container": "div.job",
    "title": "h3",
    "url": "a",
    "location": "span.loc",
    "department": "span.dept",
}


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                create table parser_versions (
                    id text primary key,
                    source_key text not null,
                    schema_version text not null,
                    selectors text not null,
                    generated_at timestamp not null,
                    validated_at timestamp,
                    success_rate numeric,
                    sample_size integer not null default 0,
                    status text not null default 'candidate',
                    notes text,
                    created_at timestamp not null,
                    updated_at timestamp not null
                )
                """
            )
        )
    return sessionmaker(bind=engine)()


class FakeLlm:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls += 1
        return self.payload


def samples(count: int) -> list[PageSample]:
    return [PageSample(url=f"https://example.com/careers/{i}", html=CAREERS_HTML) for i in range(count)]


def test_apply_selectors_extracts_jobs_and_resolves_relative_urls() -> None:
    jobs = apply_selectors(
        selectors_from_payload(GOOD_SELECTORS),
        CAREERS_HTML,
        base_url="https://example.com/careers",
    )
    assert len(jobs) == 2
    assert jobs[0]["title"] == "Senior Backend Engineer"
    assert jobs[0]["url"] == "https://example.com/jobs/1"
    assert jobs[0]["location"] == "Berlin"


def test_working_selectors_are_persisted_as_active() -> None:
    db = make_session()
    result = generate_and_validate(
        db,
        FakeLlm(GOOD_SELECTORS),
        source_key="careers_page",
        schema_version="v1",
        samples=samples(6),
    )
    assert result["status"] == "active"
    assert result["success_rate"] == 1.0
    assert load_active_parser(db, "careers_page") is not None


def test_selectors_that_match_nothing_are_stored_as_failed_not_active() -> None:
    """Model output that does not work is recorded, never used for extraction."""
    db = make_session()
    result = generate_and_validate(
        db,
        FakeLlm({**GOOD_SELECTORS, "job_container": "div.nonexistent"}),
        source_key="careers_page",
        schema_version="v1",
        samples=samples(6),
    )
    assert result["status"] == "failed"
    assert result["success_rate"] == 0.0
    assert load_active_parser(db, "careers_page") is None


def test_too_few_samples_cannot_activate_a_parser() -> None:
    db = make_session()
    result = generate_and_validate(
        db,
        FakeLlm(GOOD_SELECTORS),
        source_key="careers_page",
        schema_version="v1",
        samples=samples(2),
    )
    assert result["status"] == "failed"
    assert load_active_parser(db, "careers_page") is None


def test_incomplete_model_output_is_rejected_before_persistence() -> None:
    db = make_session()
    try:
        generate_and_validate(
            db,
            FakeLlm({"title": "h3", "url": "a"}),
            source_key="careers_page",
            schema_version="v1",
            samples=samples(6),
        )
    except LlmError as error:
        assert "job_container" in str(error)
    else:
        raise AssertionError("expected LlmError for missing job_container")

    rows = db.execute(text("select count(*) from parser_versions")).scalar()
    assert rows == 0


def test_activating_a_new_parser_retires_the_previous_one() -> None:
    db = make_session()
    generate_and_validate(
        db, FakeLlm(GOOD_SELECTORS), source_key="careers_page",
        schema_version="v1", samples=samples(6),
    )
    generate_and_validate(
        db, FakeLlm(GOOD_SELECTORS), source_key="careers_page",
        schema_version="v2", samples=samples(6),
    )
    statuses = dict(
        db.execute(
            text("select schema_version, status from parser_versions")
        ).all()
    )
    assert statuses == {"v1": "retired", "v2": "active"}


def test_invalid_selector_syntax_is_recorded_as_page_error() -> None:
    result = validate_selectors(
        ParserSelectors(job_container="div[", title="h3", url="a"),
        samples(5),
    )
    assert result.success_rate == 0.0
    assert all(page.error for page in result.page_results)


def test_condense_html_strips_noise_so_job_markup_survives_the_budget() -> None:
    """Naive truncation fed the model <head> and scripts, so it found nothing."""
    from app.services.parser_generation import condense_html_for_prompt

    noisy = (
        "<html><head>" + "<style>.a{color:red}</style>" * 400 + "</head>"
        "<body><script>" + "var x=1;" * 400 + "</script>"
        '<div class="job" data-reactid="xyz" style="color:red">'
        "<a href='/jobs/1'><h3>Backend Engineer</h3></a></div></body></html>"
    )
    condensed = condense_html_for_prompt(noisy, budget=4000)

    assert "Backend Engineer" in condensed
    assert "<script" not in condensed
    assert "<style" not in condensed
    assert "data-reactid" not in condensed
