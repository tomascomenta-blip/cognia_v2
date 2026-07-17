
import re

def is_allowed_specific_char(s):
    pattern = r'^[a-zA-Z0-9]+$'
    return bool(re.match(pattern, s))

assert is_allowed_specific_char("ABCDEFabcdef123450") == True
assert is_allowed_specific_char("*&%@#!}{") == False
assert is_allowed_specific_char("HELLOhowareyou98765") == True