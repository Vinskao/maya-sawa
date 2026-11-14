"""Database modules use the SQLAlchemy 2.x declarative_base location, so importing them raises no MovedIn20Warning."""
import importlib
import sys
import warnings

import pytest
from sqlalchemy.exc import MovedIn20Warning

MODULES = [
    "maya_sawa.databases.article_db",
    "maya_sawa.databases.conversation_db",
    "maya_sawa.databases.git_commit_db",
    "maya_sawa.databases.portfolio_history_db",
]


@pytest.mark.parametrize("name", MODULES)
def test_importing_the_module_emits_no_moved_in_20_warning(name):
    original = sys.modules.pop(name, None)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", MovedIn20Warning)
            module = importlib.import_module(name)
        assert hasattr(module.Base, "metadata")
    finally:
        # Put the already-imported module back so other tests keep sharing one Base.
        if original is not None:
            sys.modules[name] = original
