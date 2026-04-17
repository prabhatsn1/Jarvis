import logging
import importlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError

log = logging.getLogger("jarvis.actions")

ACTION_TIMEOUT = 5  # seconds


class ActionExecutor:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._modules = {}

    def _get_action(self, action_path):
        """Resolve 'apps.open_app' → callable function."""
        module_name, func_name = action_path.rsplit(".", 1)
        full_module = f"jarvis.actions.{module_name}"

        if full_module not in self._modules:
            try:
                self._modules[full_module] = importlib.import_module(full_module)
            except ImportError as e:
                log.error(f"Cannot import action module '{full_module}': {e}")
                return None

        module = self._modules[full_module]
        func = getattr(module, func_name, None)
        if func is None:
            log.error(f"Action not found: {action_path}")
        return func

    def execute(self, action_path, slots):
        """Execute an action with timeout. Returns result string or None."""
        func = self._get_action(action_path)
        if not func:
            return None

        log.info(f"Executing: {action_path}({slots})")

        try:
            future = self._pool.submit(func, **slots)
            result = future.result(timeout=ACTION_TIMEOUT)
            log.info(f"Action completed: {result}")
            return result
        except TimeoutError:
            log.error(f"Action timed out: {action_path}")
            return None
        except Exception as e:
            log.error(f"Action failed: {action_path}: {e}")
            return None
