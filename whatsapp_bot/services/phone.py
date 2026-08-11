import re


def normalize_phone(phone):
    value = re.sub(r"\D+", "", phone or "")
    if value.startswith("00"):
        value = value[2:]
    if value.startswith("0") and len(value) == 11:
        value = "234" + value[1:]
    return value


def is_valid_phone(phone):
    value = normalize_phone(phone)
    return bool(re.fullmatch(r"[1-9]\d{9,14}", value))
