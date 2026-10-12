"""Profile-scoped plugin diagnostic RPC."""
import logging
from .method_ctx import HandlerRegistry, bind_module
logger = logging.getLogger(__name__)
_registry = HandlerRegistry()
method = _registry.method
_profile_scoped = _registry.profile_scoped

@method("plugin.inspect")
@_profile_scoped
def _plugin_inspect(rid, params: dict) -> dict:
    plugin = str(params.get("plugin") or "").strip()
    if not plugin:
        return _err(rid, 4000, "plugin required")
    try:
        from hermes_cli.plugins import _ensure_plugins_discovered
        manager = _ensure_plugins_discovered()
        return _ok(rid, manager.inspect_plugin(plugin, {
            key: value for key, value in params.items() if key not in {"plugin", "profile", "session_id"}
        }))
    except KeyError:
        return _err(rid, 4040, f"plugin inspector not found: {plugin}")
    except Exception as exc:
        logger.exception("Plugin inspector failed: %s", plugin)
        return _err(rid, 5033, str(exc))


def register(server):
    bind_module(globals(), server)
