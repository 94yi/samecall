"""A call plan routes the three legacy inputs to one ordinary instance method."""
from dataclasses import dataclass
import inspect
from itertools import permutations

INPUTS = ("lane", "request", "parcel")


@dataclass(frozen=True)
class CallPlan:
    method: str
    positional: tuple  # legacy field names, in target positional-only order
    keywords: tuple    # (target parameter, legacy field) pairs

    def invoke(self, target, lane, request, parcel):
        values = dict(zip(INPUTS, (lane, request, parcel)))
        return getattr(target, self.method)(
            *(values[source] for source in self.positional),
            **{key: values[source] for key, source in self.keywords},
        )


def plans_for(name, function):
    if not inspect.isfunction(function):
        return
    p = inspect.Parameter
    params = tuple(inspect.signature(function).parameters.values())
    if len(params) != len(INPUTS) + 1 or params[0].kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
        return
    fields = params[1:]
    if any(f.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
           or f.default is not p.empty for f in fields):
        return
    for order in permutations(INPUTS):
        pairs = tuple(zip(fields, order))
        yield CallPlan(name,
                       tuple(source for f, source in pairs if f.kind == p.POSITIONAL_ONLY),
                       tuple((f.name, source) for f, source in pairs if f.kind != p.POSITIONAL_ONLY))


def adapted(factory, plan):
    class CompatibleDesk(factory):
        def dispatch(self, lane, request, parcel):
            # Resolve the underlying method even if it is still named dispatch.
            return plan.invoke(super(), lane, request, parcel)
    return CompatibleDesk
