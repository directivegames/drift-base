import pkgutil
import importlib

def import_all_models() -> None:
    """
    This is just for alembic to find all the model files, so I can use it to generate a diff between the models and my
    chosen db.
    """
    for modinfo in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
        name = modinfo.name
        if name.rsplit(".", 1)[-1].startswith("_"):
            continue
        importlib.import_module(name)
