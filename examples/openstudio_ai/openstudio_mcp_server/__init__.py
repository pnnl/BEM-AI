__all__ = ["create_server", "serve"]


def __getattr__(name):
    if name in __all__:
        from examples.openstudio_ai.openstudio_mcp_server.server import (
            create_server,
            serve,
        )

        return {"create_server": create_server, "serve": serve}[name]
    raise AttributeError(name)
