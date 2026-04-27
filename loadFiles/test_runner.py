from django.test.runner import DiscoverRunner


class ProductionDatabaseTestRunner(DiscoverRunner):
    """
    Test runner that skips test database creation and destruction.
    Runs tests against the real database — required for validation tests
    that check production data integrity against external sources.
    """

    def setup_databases(self, **kwargs):
        return []

    def teardown_databases(self, old_config, **kwargs):
        pass
