def pytest_configure(config):
    from gevent import monkey
    monkey.patch_all()

    try:
        # ddtrace will be imported before we get here, courtesy of it having an entry point in its package, which means
        # the tracer instance and all its dependencies will be loaded before we get here.
        from ddtrace import tracer
        # so, lets block the agent writer from starting up for real, as there's almost no way to get it to shut down
        #  in less than 30-40 seconds once it has something to report.
        tracer._writer.start = lambda *args: None
        # Also unregister the exit handler since that will try to flush all processors/workers, with retries and
        # timeouts etc, also consuming about 30 seconds. We don't want that.
        from ddtrace.internal import atexit
        from ddtrace.internal.telemetry import telemetry_writer
        atexit.unregister(telemetry_writer.app_shutdown)
    except ImportError:
        pass
