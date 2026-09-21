def test_package_imports():
    import mail_organizer
    import mail_organizer.providers

    assert mail_organizer.providers is not None
