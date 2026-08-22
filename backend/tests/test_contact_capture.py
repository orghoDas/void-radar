from app.services.contact_capture import extract_phones


def test_extract_phones_labels_non_email_contacts() -> None:
    contacts = extract_phones(
        '<a href="tel:+441234567890">Call</a>',
        page_url="https://example.com/contact",
    )

    assert len(contacts) == 1
    assert contacts[0].phone == "+441234567890"
    assert contacts[0].contact_kind == "unknown"
    assert contacts[0].deliverability == "no_email"
    assert contacts[0].source_url == "https://example.com/contact"
