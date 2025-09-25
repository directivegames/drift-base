def pytest_configure(config):
    return
    #from gevent import monkey
    #monkey.patch_all()

    try:
        from ddtrace import tracer
        from ddtrace.internal.telemetry import telemetry_writer
        telemetry_writer.periodic = lambda *args, **kwargs: None
        tracer._span_aggregator.writer.write = lambda *args: None
    except ImportError:
        pass
