"""A call plan routes the three legacy inputs to one ordinary instance method."""
from dataclasses import dataclass
import inspect
from itertools import combinations, permutations

INPUTS = ("lane", "request", "parcel")


@dataclass(frozen=True)
class CallPlan:
    method: str
    positional: tuple  # legacy fields; None uses the target’s default at this position
    keywords: tuple    # (target parameter, legacy field) pairs

    def invoke(self, target, lane, request, parcel):
        values = dict(zip(INPUTS, (lane, request, parcel)))
        method = getattr(target, self.method)
        args = [values[source] if source is not None else None for source in self.positional]
        if None in self.positional:
            # A later positional-only value needs an earlier slot filled.
            fields = tuple(inspect.signature(method).parameters.values())
            for i, source in enumerate(self.positional):
                if source is None:
                    args[i] = fields[i].default
        return method(
            *args,
            **{key: values[source] for key, source in self.keywords},
        )


def plans_for(name, function):
    if not inspect.isfunction(function):
        return
    p = inspect.Parameter
    params = tuple(inspect.signature(function).parameters.values())
    if not params or params[0].kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
        return
    fields = params[1:]
    if any(f.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
           for f in fields):
        return
    required = [f.name for f in fields if f.default is p.empty]
    optional = [f.name for f in fields if f.default is not p.empty]
    needed = len(INPUTS) - len(required)
    if not 0 <= needed <= len(optional):
        return
    for extra in combinations(optional, needed):
        for order in permutations(INPUTS):
            sources = dict(zip((*required, *extra), order))
            positional = [sources.get(f.name) for f in fields if f.kind == p.POSITIONAL_ONLY]
            while positional and positional[-1] is None:
                positional.pop()
            keywords = tuple((f.name, sources[f.name]) for f in fields
                             if f.kind != p.POSITIONAL_ONLY and f.name in sources)
            yield CallPlan(name, tuple(positional), keywords)


def adapted(factory, plan):
    class CompatibleDesk(factory):
        def dispatch(self, lane, request, parcel):
            # Resolve the underlying method even if it is still named dispatch.
            return plan.invoke(super(), lane, request, parcel)
    return CompatibleDesk
