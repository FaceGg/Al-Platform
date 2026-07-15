import importlib
import inspect
import pkgutil
import unittest

import app


class TestBackendModuleImports(unittest.TestCase):
    def test_all_application_modules_import(self):
        module_names = sorted(
            module.name
            for module in pkgutil.walk_packages(app.__path__, prefix="app.")
        )

        self.assertGreaterEqual(len(module_names), 70)
        for module_name in module_names:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_imports_do_not_use_removed_pydantic_or_asyncio_patterns(self):
        from app.api import runs
        from app.schemas import project, run, workflow

        for module in (project, run, workflow):
            with self.subTest(module=module.__name__):
                self.assertNotIn("class Config", inspect.getsource(module))
        self.assertNotIn("get_event_loop(", inspect.getsource(runs))


if __name__ == "__main__":
    unittest.main()
