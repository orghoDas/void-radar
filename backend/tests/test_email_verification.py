from app.services.email_verification import (
    VerificationResult,
    check_email,
)


def fake_mx(hosts: tuple[str, ...]):
    def _lookup(domain: str) -> tuple[str, ...]:
        return hosts
    return _lookup


def test_valid_business_address_with_mx_is_deliverable() -> None:
    check = check_email("jane@example.com", mx_lookup=fake_mx(("mx1.example.com",)))
    assert check.result is VerificationResult.DELIVERABLE_DOMAIN
    assert check.sendable is True


def test_domain_without_mx_cannot_receive_mail() -> None:
    check = check_email("jane@example.com", mx_lookup=fake_mx(()))
    assert check.result is VerificationResult.NO_MX_RECORD
    assert check.sendable is False


def test_role_address_is_sendable_but_labelled() -> None:
    check = check_email("careers+hn@example.com", mx_lookup=fake_mx(("mx1.example.com",)))
    assert check.result is VerificationResult.ROLE_ADDRESS
    assert check.sendable is True


def test_free_mail_and_disposable_are_rejected() -> None:
    assert check_email("x@gmail.com").result is VerificationResult.FREE_MAIL_DOMAIN
    assert check_email("x@mailinator.com").result is VerificationResult.DISPOSABLE_DOMAIN


def test_malformed_addresses_are_rejected_without_dns() -> None:
    def explode(domain: str):
        raise AssertionError("DNS must not be queried for malformed input")

    assert check_email("+hn@example.com", mx_lookup=explode).result is VerificationResult.INVALID_SYNTAX
    assert check_email("not-an-email", mx_lookup=explode).result is VerificationResult.INVALID_SYNTAX


def test_dns_failure_is_reported_not_treated_as_deliverable() -> None:
    import dns.exception

    def failing(domain: str):
        raise dns.exception.Timeout()

    check = check_email("jane@example.com", mx_lookup=failing)
    assert check.result is VerificationResult.DNS_ERROR
    assert check.sendable is False
