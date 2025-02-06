# * imports
# ** standard library
import os
import json
import logging
import random

from collections import Counter
from pprint import pprint, pformat

# ** third party
import psutil
from tqdm import tqdm

# ** custom
import arichuvadi as ari

# ** project specific
import trie

# * Globals
WORDS_FILEPATH = '/home/vanangamudi/code/ilakkani/words.clean.tsv'
ARICHUVADI_INDEX = {k:i for i,k in enumerate(ari.ARICHUVADI)}

logging.basicConfig()

# * Functions
def process_memory():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return mem_info.rss

def get_list_letters(filepath):
    counter = Counter()
    error_count = 0
    error_file = open('errored_words.txt', 'w')
    with open(filepath) as f:
        for line in f:
            line, _ = line.split('\t')
            try:
                counter.update(ari.get_letters_coding(line))
            except:
                #import pdb; pdb.set_trace()
                error_count += 1
                print(f'{line}\t{list(i for i in line)}', file=error_file)

    error_file.close()
    return list(counter.keys()), error_count

class SuffixTrieNode:
    def __init__(self):
        self.children = [None] * ari.ARICHUVADI_NEELAM
        self.indexes = []

    def insert_suffix(self, suffix, index):
        self.indexes.append(index)
        if suffix:
            c_index = ARICHUVADI_INDEX[suffix[0]]
            if not self.children[c_index]:
                self.children[c_index] = SuffixTrieNode()
            self.children[c_index].insert_suffix(suffix[1:], index + 1)

    def search(self, pat):
        if not pat:
            return self.indexes
        c_index = ARICHUVADI_INDEX[pat[0]]
        if self.children[c_index]:
            return self.children[c_index].search(pat[1:])
        return None

class SuffixTrie:
    def __init__(self, txt):
        self.root = SuffixTrieNode()
        for i in range(len(txt)):
            self.root.insert_suffix(txt[i:], i)

    def search(self, pat):
        result = self.root.search(pat)
        if not result:
            return None
        else:
            pat_len = len(pat)
            #for i in result:
            #    print(f"Pattern found at position {i - pat_len}")
            return [(i - pat_len) for i in result]

def read_words(filepath):
    words = []
    with open(filepath) as f:
        for line in f:
            word, freq = line.split('\t')
            words.append(word)

    return words



def suffix_trie_test():
    words = read_words(WORDS_FILEPATH)
    words = sorted(words, key=lambda x: (x,len(x)))
    words = sorted(words)
    words = [w for w in words if len(w)>4 and len(w)<40]
    for word in words:
        try:
            #print(word)
            word_letters = ari.get_letters_coding(word)
            st = SuffixTrie(word_letters)
            if len(word_letters) < 3:
                continue
            print(f'-- {word}')
            for wordp in words:
                #print('*', word, wordp)
                try:
                    wordp_letters = ari.get_letters_coding(wordp)
                    if len(wordp_letters) >= len(word_letters):
                        continue
                    pos = st.search(wordp_letters)
                    if pos:

                        print('\t', wordp, pos)
                except:
                    pass
        except KeyboardInterrupt:
            print(word)
            raise KeyboardInterrupt
        except:
            continue
            logging.exception(word)


class TamilAlphabetNode(trie.Node):
    EMPTY = []
    def concat(self, seq1, seq2):  return [seq1] + seq2
    def split(self, seq): return seq[:]
    def index(self, seq, index): return seq[index]


def trie_test():
    words = read_words(WORDS_FILEPATH)
    words = sorted(words, key=lambda i: len(i), reverse=False)
    words = [w for w in words if len(w)>4 and len(w)<40]
    words_pbar = tqdm(words, desc='starting...', ncols=100)
    memory_consumed = process_memory()
    ftrie = trie.Trie(node_class=TamilAlphabetNode)
    btrie = trie.Trie(node_class=TamilAlphabetNode)
    baseline_memory = process_memory()
    for i, word in enumerate(words_pbar):
        #if i > 100000: break
        if i % 1000:
            memory_consumed = process_memory()
            memory_consumed = (memory_consumed-baseline_memory)//(1000*1000)
        try:
            #print(word)
            words_pbar.set_description(
                f'[{memory_consumed}MB-{i//1000}k] {word}')
            word_letters = ari.get_letters_coding(word)
            ftrie.add(word_letters)
            btrie.add(list(reversed(word_letters)))
        except KeyboardInterrupt:
            print(word)
            words_pbar.close()
            return ftrie, btrie
            #raise KeyboardInterrupt
        except:
            continue
            logging.exception(word)

    words_pbar.close()
    return ftrie, btrie

if __name__ == '__main__':

    # ftrie, btrie = trie_test()
    # with open('ftrie.json', 'w') as f:
    #     json.dump(ftrie.as_dict(), f, indent=2, ensure_ascii=False)
    # with open('btrie.json', 'w') as f:
    #     json.dump(btrie.as_dict(), f, indent=2, ensure_ascii=False)

    logging.info('loading ftrie')
    ftrie = trie.Trie(TamilAlphabetNode)
    ftrie.load_dict(json.load(open('ftrie.json')))

    logging.info('loading btrie')
    btrie = trie.Trie(TamilAlphabetNode)
    btrie.load_dict(json.load(open('btrie.json')))

    logging.info('checking ')
    suffixes = ftrie.root.get_suffixes(ari.get_letters_coding('அகராதித்து'))
    suffixes = [''.join(i) for i in suffixes]
    pprint(suffixes)
