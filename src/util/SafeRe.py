import re


class UnsafePatternError(Exception):
    pass

cached_patterns = {}


def guard(pattern):
    '''Checks if pattern is safe and raises exception if it isn't'''
    if len(pattern) > 255:
        raise UnsafePatternError("Pattern too long: %s characters in %s" % (len(pattern), pattern))

    unsafe_pattern_match = re.search(r"[^\.][\*\{\+]", pattern)  # Always should be "." before "*{+" characters to avoid ReDoS
    if unsafe_pattern_match:
        raise UnsafePatternError("Potentially unsafe part of the pattern: %s in %s" % (unsafe_pattern_match.group(0), pattern))

    repetitions1 = re.findall(r"\.[\*\{\+]", pattern)
    repetitions2 = re.findall(r"[^(][?]", pattern)
    if len(repetitions1) + len(repetitions2) >= 10:
        raise UnsafePatternError("More than 10 repetitions in %s" % pattern)


def match(pattern, *args, **kwargs):
    '''Guard for safety, compile, cache and match regexp'''
    cached_pattern = cached_patterns.get(pattern)
    if cached_pattern:
        return cached_pattern.match(*args, **kwargs)
    else:
        guard(pattern)
        cached_patterns[pattern] = re.compile(pattern)
        return cached_patterns[pattern].match(*args, **kwargs)
