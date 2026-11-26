"""Ordinary calls on the two unannotated editions; no field mapping table."""
def old_example(desk):
    return desk.dispatch("blue", "blue", "paper kite")


def new_example(desk):
    return desk.dispatch_v2("tin bird", z="lane-gold", y="order-B")
