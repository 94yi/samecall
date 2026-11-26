"""Compare direct forwards to the example's receipt writer, without calling it."""
import ast
import inspect
import textwrap
from types import SimpleNamespace

from catalog import methods_of
from service import Desk


def projection(factory, function):
    """Compile only a single direct return to the unchanged three-column writer."""
    if (inspect.getattr_static(factory, "_deliver", None) is not Desk._deliver
            or factory.__init__ is not Desk.__init__
            or factory.__getattribute__ is not object.__getattribute__):
        return None
    try:
        body = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    except (OSError, TypeError, SyntaxError):
        return None
    if not isinstance(body, ast.FunctionDef) or body.decorator_list or len(body.body) != 1:
        return None
    stmt = body.body[0]
    call = stmt.value if isinstance(stmt, ast.Return) else None
    sig = inspect.signature(function)
    names = tuple(sig.parameters)
    if not (names and isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == names[0]
            and call.func.attr == "_deliver" and not call.keywords and len(call.args) == 3):
        return None
    for arg in call.args:
        if not (isinstance(arg, ast.Name) and arg.id in names[1:] or
                isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            return None
    sig = sig.replace(parameters=list(sig.parameters.values())[1:])

    def project(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return tuple(bound.arguments[a.id] if isinstance(a, ast.Name) else a.value
                     for a in call.args)
    project.__signature__ = sig  # CallPlan can read omitted positional-only defaults.
    return project


def sample_filter(old, current, old_example, new_example=None):
    legacy = projection(old, old.dispatch)
    if legacy is None:
        return lambda plan: True
    targets = {name: project for name, fn in methods_of(current).items()
               if (project := projection(current, fn)) is not None}
    samples = []

    def record(lane, request, parcel):
        args = (lane, request, parcel)
        samples.append((args, legacy(*args)))

    old_example(SimpleNamespace(dispatch=record))
    # A new call supplies a second witness via the writer's known column order.
    # Do not infer parameter identities by matching incidental example literals.
    if new_example is not None:
        def capture(project):
            def run(*args, **kwargs):
                row = project(*args, **kwargs)
                if legacy(*row) == row:
                    samples.append((row, row))
            return run
        desk = SimpleNamespace(**{n: capture(targets[n]) if n in targets else lambda *a, **k: None
                                  for n in methods_of(current)})
        new_example(desk)

    def compatible(plan):
        if plan.method not in targets:
            return True
        desk = SimpleNamespace(**{plan.method: targets[plan.method]})
        return all(plan.invoke(desk, *args) == row for args, row in samples)
    return compatible
