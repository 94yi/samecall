"""The packaged adapter keeps the original caller-facing method."""
from binding import PLAN, TargetDesk
from call_plan import adapted

ParcelDesk = adapted(TargetDesk, PLAN)
