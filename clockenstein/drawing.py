import math


def draw_circle(cr, color, x, y, radius):
    cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
    cr.arc(x, y, radius, 0, math.tau)
    cr.fill()


def draw_centered_circle(widget, cr, color):
    allocation = widget.get_allocation()
    draw_circle(
        cr, color, allocation.width / 2, allocation.height / 2,
        min(allocation.width, allocation.height) / 2,
    )
    return False
