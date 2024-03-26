def pytest_configure(config):
    from gevent import monkey
    monkey.patch_all()
