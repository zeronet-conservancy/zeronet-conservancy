import re
import logging

log = logging.getLogger("SafeRe")



class UnsafePatternError(Exception):
    pass

max_cache_size = 1000
cached_patterns = {}
old_cached_patterns = {}


def isSafePattern(pattern):
    if len(pattern) > 255:
        raise UnsafePatternError("Pattern too long: %s characters in %s" % (len(pattern), pattern))

    unsafe_pattern_match = re.search(r"[^\.][\*\{\+]", pattern)  # Always should be "." before "*{+" characters to avoid ReDoS
    if unsafe_pattern_match:
        raise UnsafePatternError("Potentially unsafe part of the pattern: %s in %s" % (unsafe_pattern_match.group(0), pattern))

    repetitions = re.findall(r"\.[\*\{\+]", pattern)
    if len(repetitions) >= 10:
        raise UnsafePatternError("More than 10 repetitions of %s in %s" % (repetitions[0], pattern))

    return True


def compilePattern(pattern):
    global cached_patterns
    global old_cached_patterns

    cached_pattern = cached_patterns.get(pattern)
    if cached_pattern:
        return cached_pattern

    cached_pattern = old_cached_patterns.get(pattern)
    if cached_pattern:
        del old_cached_patterns[pattern]
        cached_patterns[pattern] = cached_pattern
        return cached_pattern

    if isSafePattern(pattern):
        cached_pattern = re.compile(pattern)
        cached_patterns[pattern] = cached_pattern
        log.debug("Compiled new pattern: %s" % pattern)
        log.debug("Cache size: %d + %d" % (len(cached_patterns), len(old_cached_patterns)))

        if len(cached_patterns) > max_cache_size:
            old_cached_patterns = cached_patterns
            cached_patterns = {}
            log.debug("Size limit reached. Rotating cache.")
            log.debug("Cache size: %d + %d" % (len(cached_patterns), len(old_cached_patterns)))

        return cached_pattern


def match(pattern, *args, **kwargs):
    cached_pattern = compilePattern(pattern)
    return cached_pattern.match(*args, **kwargs)

################################################################################

# TESTS

def testSafePattern(pattern):
    try:
        return isSafePattern(pattern)
    except UnsafePatternError as err:
        return False


# Some real examples to make sure it works as expected
assert testSafePattern('(data/mp4/.*|updater/.*)')
assert testSafePattern('((js|css)/(?!all.(js|css)))|.git')


# Unsafe cases:

# ((?!json).)*$ not allowed, because of ) before the * character. Possible fix: .*(?!json)$
assert not testSafePattern('((?!json).)*$')
assert testSafePattern('.*(?!json)$')

# (.*.epub|.*.jpg|.*.jpeg|.*.png|data/.*.gif|.*.avi|.*.ogg|.*.webm|.*.mp4|.*.mp3|.*.mkv|.*.eot) not allowed, because it has 12 .* repetition patterns. Possible fix: .*(epub|jpg|jpeg|png|data/gif|avi|ogg|webm|mp4|mp3|mkv|eot)
assert not testSafePattern('(.*.epub|.*.jpg|.*.jpeg|.*.png|data/.*.gif|.*.avi|.*.ogg|.*.webm|.*.mp4|.*.mp3|.*.mkv|.*.eot)')
assert testSafePattern('.*(epub|jpg|jpeg|png|data/gif|avi|ogg|webm|mp4|mp3|mkv|eot)')

# FIXME: https://github.com/HelloZeroNet/ZeroNet/issues/2757
#assert not testSafePattern('a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?a?aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')

################################################################################
