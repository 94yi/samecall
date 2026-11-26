"""Evaluate a small, side-effect-free subset of source on concrete example calls."""
import ast
import inspect
import textwrap
from functools import lru_cache
from types import SimpleNamespace

from catalog import methods_of
from service import Desk

UNKNOWN = object()


class Unsupported(Exception):
    """This sample provides no evidence about the selected path."""


def projection(factory, function, direct_only=False):
    if (inspect.getattr_static(factory, "_deliver", None) is not Desk._deliver
            or factory.__init__ is not Desk.__init__
            or factory.__getattribute__ is not object.__getattribute__):
        return None

    @lru_cache(None)
    def definition(fn):
        if not inspect.isfunction(fn) or inspect.isgeneratorfunction(fn):
            return None
        try:
            body = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
        except (OSError, TypeError, SyntaxError):
            return None
        if not isinstance(body, ast.FunctionDef) or body.decorator_list:
            return None
        sig = inspect.signature(fn)
        params = tuple(sig.parameters.values())
        if not params or params[0].kind not in (inspect.Parameter.POSITIONAL_ONLY,
                                                inspect.Parameter.POSITIONAL_OR_KEYWORD):
            return None
        return params[0].name, sig.replace(parameters=params[1:]), body.body

    def run(fn, args, kwargs, depth):
        spec = definition(fn)
        if spec is None:
            raise Unsupported
        receiver, sig, statements = spec
        try:
            bound = sig.bind(*args, **kwargs)
        except TypeError:
            raise Unsupported
        bound.apply_defaults()
        env = bound.arguments

        def scalar(node):
            if isinstance(node, ast.Name):
                value = env.get(node.id, UNKNOWN)
            elif isinstance(node, ast.Constant):
                value = node.value
            else:
                raise Unsupported
            # Don't invoke user-defined equality or truthiness.
            if type(value) not in (str, bool, int, type(None)):
                raise Unsupported
            return value

        def condition(node):
            if (isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], (ast.Eq, ast.NotEq))):
                equal = scalar(node.left) == scalar(node.comparators[0])
                return equal if isinstance(node.ops[0], ast.Eq) else not equal
            return bool(scalar(node))

        def returned(node):
            if not isinstance(node, ast.Call):
                return scalar(node)
            target = node.func
            if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == receiver and all(k.arg for k in node.keywords)):
                raise Unsupported
            values = [scalar(a) for a in node.args]
            keys = {k.arg: scalar(k.value) for k in node.keywords}
            if target.attr == "_deliver" and not keys and len(values) == 3:
                return tuple(values)
            if depth or direct_only or target.attr in ("dispatch", "_deliver", "db") or target.attr.startswith("__"):
                raise Unsupported
            helper = inspect.getattr_static(factory, target.attr, None)
            if not inspect.isfunction(helper):
                raise Unsupported
            return run(helper, values, keys, depth + 1)

        def block(nodes):
            for stmt in nodes:
                if isinstance(stmt, ast.Return):
                    return returned(stmt.value)
                if direct_only:
                    raise Unsupported
                if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id != receiver):
                    value = returned(stmt.value)
                    if isinstance(value, tuple):  # a write before the final return
                        raise Unsupported
                    env[stmt.targets[0].id] = value
                elif isinstance(stmt, ast.If):
                    result = block(stmt.body if condition(stmt.test) else stmt.orelse)
                    if result is not UNKNOWN:
                        return result
                else:
                    raise Unsupported
            return UNKNOWN  # this block fell through

        if direct_only and len(statements) != 1:
            raise Unsupported
        result = block(statements)
        if result is UNKNOWN:
            raise Unsupported
        return result

    info = definition(function)
    if info is None:
        return None

    def project(*args, **kwargs):
        try:
            result = run(function, args, kwargs, 0)
        except Unsupported:
            return UNKNOWN
        return result if isinstance(result, tuple) else UNKNOWN
    project.__signature__ = info[1]
    return project


def sample_filter(old, current, old_example, new_example=None, *, direct_only=False):
    legacy = projection(old, old.dispatch, direct_only)
    if legacy is None:
        return lambda plan: True
    targets = {name: project for name, fn in methods_of(current).items()
               if (project := projection(current, fn, direct_only)) is not None}
    samples = []

    def record(lane, request, parcel):
        args = (lane, request, parcel)
        row = legacy(*args)
        if row is not UNKNOWN:
            samples.append((args, row))

    old_example(SimpleNamespace(dispatch=record))
    # A new call supplies a second witness via the writer's known column order.
    # Do not infer parameter identities by matching incidental example literals.
    if new_example is not None:
        def capture(project):
            def run(*args, **kwargs):
                row = project(*args, **kwargs)
                if row is not UNKNOWN and legacy(*row) == row:
                    samples.append((row, row))
            return run
        desk = SimpleNamespace(**{n: capture(targets[n]) if n in targets else lambda *a, **k: None
                                  for n in methods_of(current)})
        new_example(desk)

    def compatible(plan):
        if plan.method not in targets:
            return True
        desk = SimpleNamespace(**{plan.method: targets[plan.method]})
        for args, row in samples:
            projected = plan.invoke(desk, *args)
            if projected is not UNKNOWN and projected != row:
                return False
        return True
    return compatible
