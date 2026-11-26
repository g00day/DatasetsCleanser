from decimal import Decimal


SCORE_FORMULA_VERSION = 1


def quality_score(checked_rows, affected_rows):
    if not checked_rows or affected_rows is None:
        return None
    percent = Decimal(100) * (checked_rows - affected_rows) / checked_rows
    return percent.quantize(Decimal("0.0001"))
