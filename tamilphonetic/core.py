#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: tamil_phonetic
Provides transliteration logic for Tamil phonetic input.
This module maps basic Latin characters (as on QWERTY keyboards) to Tamil script.
For example purposes only; the mapping should be extended to cover full phonetic needs.
"""

import string
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

def transliterate(text):
    """
    Transliterates romanized input using a scheme modeled on the Emacs Tamil ITRANS
    input method. It greedily matches vowel and consonant tokens and attaches vowel diacritics
    to a pending consonant. If no vowel follows a consonant, a pulli is appended.
    """
    output = []
    pending = None
    i = 0

    def match_vowel_at(j):
        for vt in VOWEL_TOKENS:
            if text[j:j+len(vt)].lower() == vt:
                return vt
        return None

    def match_consonant_at(j):
        for ct in CONSONANT_TOKENS:
            cand = text[j:j+len(ct)]
            if cand == ct:
                return ct
            if cand.lower() == ct.lower():
                if cand and ct and cand[0].islower() and ct[0].islower():
                    return ct
        return None

    def flush_pending_with_vowel(vt):
        nonlocal pending
        if pending is not None:
            output.append(pending + VOWEL_DIACRITICS[vt])
            pending = None
        else:
            output.append(PHONETIC_VOWELS[vt])

    def flush_pending_pulli():
        nonlocal pending
        if pending is not None:
            output.append(pending + PULLI)
            pending = None

    def flush_pending_raw():
        nonlocal pending
        if pending is not None:
            output.append(pending)
            pending = None

    while i < len(text):
        vt = match_vowel_at(i)
        if vt is not None:
            flush_pending_with_vowel(vt)
            i += len(vt)
            continue

        ct = match_consonant_at(i)
        if ct is not None:
            if pending is not None:
                output.append(pending + PULLI)
            pending = CONSONANTS[ct]
            i += len(ct)
            continue

        ch = text[i]
        if ch in string.whitespace or ch in string.punctuation:
            flush_pending_pulli()
            output.append(ch)
            i += 1
        else:
            flush_pending_raw()
            output.append(ch)
            i += 1

    if pending is not None:
        output.append(pending + PULLI)
    return ''.join(output)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
        print(transliterate(input_text))
    else:
        print("Usage: {} <text>".format(sys.argv[0]))
