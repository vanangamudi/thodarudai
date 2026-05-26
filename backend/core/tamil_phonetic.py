#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: tamil_phonetic
Provides transliteration logic for Tamil phonetic input.
This module maps basic Latin characters (as on QWERTY keyboards) to Tamil script.
For example purposes only; the mapping should be extended to cover full phonetic needs.
"""

import string
import logging
logger = logging.getLogger("tamil_phonetic")
# Transliteration mappings

# Standalone vowels mapping (for when vowels appear with no preceding consonant)
PHONETIC_VOWELS = {
    'a': 'அ',
    'aa': 'ஆ',
    'i': 'இ',
    'ii': 'ஈ',
    'u': 'உ',
    'uu': 'ஊ',
    'e': 'எ',
    'ee': 'ஏ',
    'ai': 'ஐ',
    'o': 'ஒ',
    'oo': 'ஓ',
    'au': 'ஔ',
}

# Diacritics to be attached when a vowel follows a consonant.
# For the inherent vowel 'a' no diacritic is needed.
VOWEL_DIACRITICS = {
    'a': '',
    'aa': 'ா',
    'i': 'ி',
    'ii': 'ீ',
    'u': 'ு',
    'uu': 'ூ',
    'e': 'ெ',
    'ee': 'ே',
    'ai': 'ை',
    'o': 'ொ',
    'oo': 'ோ',
    'au': 'ௌ',
}

CONSONANTS = {
    # க் row
    'k': 'க',
    'g': 'க',   # both k and g yield க
    # ங் row
    'ng': 'ங',
    # ச் row
    'ch': 'ச',
    's': 'ச',
    # ஞ் row
    'nj': 'ஞ',
    # ட் row (note: these are one set)
    't': 'ட',
    'd': 'ட',
    # ண் row
    'N': 'ண',
    #த் row (different from the t-row)
    'th': 'த',
    'dh': 'த',
    # ந் row (using the key for this row)
    'nh': 'ந',
    # ப் row
    'p': 'ப',
    # ம் row
    'm': 'ம',
    # ய் row
    'y': 'ய',
    # ர் row
    'r': 'ர',
    # ல் row
    'l': 'ல',
    # வ் row
    'v': 'வ',
    # ழ் row
    'z': 'ழ',
    'zh': 'ழ',
    # ள் row
    'L': 'ள',
    # ற் row
    'rh': 'ற',
    # ன் row
    'n': 'ன',
    # ஜ் row
    'j': 'ஜ',
    # ஸ் row
    'S': 'ஸ',
    # ஷ் row
    'sh': 'ஷ',
    # ஹ் row
    'h': 'ஹ',
    # க்ஷ் row (optional; add if needed)
    'ksH': 'க்ஷ',
    #க்‌ஷ் row
    'ksh': 'க்‌ஷ',
    # ஶ் row
    'Z': 'ஶ',
}

PULLI = "்"  # used to suppress the inherent vowel (for pure consonants)
# Prepare sorted tokens (longer strings first) for greedy matching.
VOWEL_TOKENS = sorted(PHONETIC_VOWELS.keys(), key=len, reverse=True)
CONSONANT_TOKENS = sorted(CONSONANTS.keys(), key=len, reverse=True)

def match_vowel_at(text, j):
    for vt in VOWEL_TOKENS:
        if text[j:j+len(vt)].lower() == vt:
            return vt
    return None

def match_consonant_at(text, j):
    for ct in CONSONANT_TOKENS:
        cand = text[j:j+len(ct)]
        if cand == ct:
            return ct
        if cand.lower() == ct.lower():
            if cand and ct and cand[0].islower() and ct[0].islower():
                return ct
    return None

def flush_pending_with_vowel(output, pending, vowel_token):
    if pending is not None:
        output.append(pending + VOWEL_DIACRITICS[vowel_token])
        return None
    else:
        output.append(PHONETIC_VOWELS[vowel_token])
        return None

def flush_pending_pulli(output, pending):
    if pending is not None:
        output.append(pending + PULLI)
        return None
    return pending

def flush_pending_raw(output, pending):
    if pending is not None:
        output.append(pending)
        return None
    return pending

def process_vowel(text, i, pending, output):
    vt = match_vowel_at(text, i)
    if vt is None:
        return False, i, pending
    logger.debug("phonetic: vowel token=%r at i=%d (had_pending=%s)", vt, i, pending is not None)
    pending = flush_pending_with_vowel(output, pending, vt)
    return True, i + len(vt), pending

def process_consonant(text, i, pending, output):
    ct = match_consonant_at(text, i)
    if ct is None:
        return False, i, pending
    logger.debug("phonetic: consonant token=%r at i=%d (had_pending=%s)", ct, i, pending is not None)
    if pending is not None:
        output.append(pending + PULLI)
    pending = CONSONANTS[ct]
    return True, i + len(ct), pending

def process_other_char(text, i, pending, output):
    ch = text[i]
    logger.debug("phonetic: other char=%r at i=%d (whsp/punct=%s had_pending=%s)", ch, i, (ch in string.whitespace or ch in string.punctuation), pending is not None)
    if ch in string.whitespace or ch in string.punctuation:
        pending = flush_pending_pulli(output, pending)
        output.append(ch)
        return i + 1, pending
    pending = flush_pending_raw(output, pending)
    output.append(ch)
    return i + 1, pending


def transliterate(text):
    """
    Transliterates romanized input using a scheme modeled on the Emacs Tamil ITRANS
    input method. It greedily matches vowel and consonant tokens and attaches vowel
diacritics
    to a pending consonant. If no vowel follows a consonant, a pulli is appended.
    """
    logger.debug("phonetic: transliterate IN=%r", text)
    output = []
    pending = None
    i = 0
    while i < len(text):
        did_vowel, i2, pending = process_vowel(text, i, pending, output)
        if did_vowel:
            i = i2
            continue
        did_cons, i2, pending = process_consonant(text, i, pending, output)
        if did_cons:
            i = i2
            continue
        i, pending = process_other_char(text, i, pending, output)
    if pending is not None:
        output.append(pending + PULLI)
    res = ''.join(output)
    logger.debug("phonetic: transliterate OUT=%r", res)
    return res

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
        print(transliterate(input_text))
    else:
        print("Usage: {} <text>".format(sys.argv[0]))
