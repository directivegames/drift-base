print("CONFTEST")
def pytest_configure(config):
    print(f"CONFTEST: pytest_configure {config}")
    from gevent import monkey
    monkey.patch_all()
