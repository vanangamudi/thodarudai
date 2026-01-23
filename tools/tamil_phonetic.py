#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: tamil_phonetic
Provides transliteration logic for Tamil phonetic input.
This module maps basic Latin characters (as on QWERTY keyboards) to Tamil script.
For example purposes only; the mapping should be extended to cover full phonetic needs.
"""

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
    'n': 'ன்',
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

def transliterate(text):
    """
    Transliterates romanized input using a scheme modeled on the Emacs Tamil ITRANS
    input method. It greedily matches vowel and consonant tokens (using the provided
    dictionaries) and attaches vowel diacritics to a pending consonant. If no vowel
    follows a consonant (i.e. at the end), a pulli is appended.
    """
    pulli = "்"  # used to suppress the inherent vowel (for pure consonants)
    # Prepare sorted tokens (longer strings first) for greedy matching.
    vowel_tokens = sorted(PHONETIC_VOWELS.keys(), key=len, reverse=True)
    consonant_tokens = sorted(CONSONANTS.keys(), key=len, reverse=True)

    output = []
    pending = None  # holds a pending consonant letter (plain form from CONSONANTS)
    i = 0
    while i < len(text):
        # First try to match a vowel token.
        matched_token = None
        for vt in vowel_tokens:
            if text[i:i+len(vt)].lower() == vt:
                matched_token = vt
                break
        if matched_token is not None:
            if pending is not None:
                # If the vowel is 'a' (inherent) then do not add a diacritic;
                # otherwise attach the diacritic corresponding to the matched vowel.
                output.append(pending + VOWEL_DIACRITICS[matched_token])
                pending = None
            else:
                output.append(PHONETIC_VOWELS[matched_token])
            i += len(matched_token)
            continue

        # Next try to match a consonant token.
        matched_token = None
        for ct in consonant_tokens:
            if text[i:i+len(ct)].lower() == ct.lower():
                matched_token = ct
                break
        if matched_token is not None:
            if pending is not None:
                output.append(pending + pulli)
            pending = CONSONANTS[matched_token]
            i += len(matched_token)
            continue

        if pending is not None:
            output.append(pending)
            pending = None
        output.append(text[i])
        i += 1

    if pending is not None:
        output.append(pending + pulli)

    return ''.join(output)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
        print(transliterate(input_text))
    else:
        print("Usage: {} <text>".format(sys.argv[0]))
