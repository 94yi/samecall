"""The packaged adapter keeps the original caller-facing method."""
from binding import PLAN
from call_plan import adapted
from service import CurrentDesk

ParcelDesk = adapted(CurrentDesk, PLAN)
