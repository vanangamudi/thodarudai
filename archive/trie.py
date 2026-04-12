# -*- coding: utf-8 -*-
import json
from pprint import pprint, pformat
import pdb
from tqdm import tqdm

SLICE_FIRST_REST = slice(1, None, None)
class Node(object):
    __slots__ = ['count', 'is_complete', 'children', 'trie']
    def __init__(self, trie, count=0):
        self.count = count
        self.is_complete = False
        self.children = {}
        self.trie = trie

    def concat(self, seq1, seq2):  raise NotImplementedError
    def split(self, seq1, seq2):  raise NotImplementedError
    def index(self, seq1, seq2):  raise NotImplementedError

    def first_rest(self, sequence):
        return (self.index(sequence, 0),
                self.index(sequence, SLICE_FIRST_REST))

    def add(self, sequence):
        self.count += 1
        if len(sequence) == 0:
            self.is_complete = True
            return

        first, rest = self.first_rest(sequence)
        if first not in self.children:
            self.children[first] = self.trie.node_class(self.trie)
        self.children[first].add(rest)

    def find_prefix(self, prefix, length=0):
        if len(prefix) == 0:
            return self, length

        first, rest = self.first_rest(prefix)
        if first in self.children:
            return self.children[first].find_prefix(rest,length+1)
        else:
            return self, length

    def to_dict(self):
        return {
            'count': self.count,
            'is_complete': self.is_complete,
            'children': {k:v.to_dict()
                         for k,v  in self.children.items()}
        }

    @classmethod
    def from_dict(cls, trie, dictionary):
        node = cls(trie)
        node.count = dictionary['count']
        node.is_complete = dictionary['is_complete']
        node.children = {}
        for k, v in dictionary['children'].items():
            node.children[k] = cls.from_dict(trie, v)

        return node

    def merge(self, other):
        self.count += other.count
        if other.is_complete == True:
            self.is_complete = True

        for k in other.children.keys():
            if k not in self.children:
                self.children[k] = self.trie.node_class(self.trie)
            self.children[k].merge(other.children[k])


    def get_suffixes(self, prefix):
        # TODO: if prefix is not in trie this
        # prepends the whole prefix to all suffixes
        if not prefix:
            return self._get_suffixes()

        prefix_node, length = self.find_prefix(prefix)
        if length == 0:  return []
        return [prefix[:length] + suffix
                for suffix in prefix_node._get_suffixes()]

    def _get_suffixes(self):
        if len(self.children) == 0:
            # this should be a list.
            # since the parent node expects a list of suffixes
            # this whole block can be avoided if
            # we check children's children
            # to be empty within this node as in below block
            # but to me this seems elegant
            return [self.trie.node_class.EMPTY]

        suffixes = []
        for key in self.children:
            suffixes.extend([
                self.concat(key, suffix)
                for suffix in self.children[key]._get_suffixes()
            ])

        return suffixes

    def __repr__(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self):
        return self.__repr__()

class StringNode(Node):
    EMPTY = ''
    def concat(self, seq1, seq2):  return seq1 + seq2
    def split(self, seq): return seq[:]
    def index(self, seq, index): return seq[index]

class Trie(object):

    def __init__(self, node_class):
        self.node_class = node_class
        self.root = self.node_class(self)

    def __repr__(self):   return self.root.__repr__()
    def __str__(self):    return self.__repr__()

    def load_dict(self, dictionary):
        self.root = self.node_class.from_dict(self, dictionary)

    def as_dict(self): return self.root.to_dict()

    def add(self, sequence): self.root.add(sequence)
    def merge(self, other): self.root.merge(other.root)

    def find_prefix(self, prefix, default=None):
        return self.root.find_prefix(prefix)

    def get_all_suffixes(self, prefix):
        suffixes = []
        node, level = self.find_prefix(prefix)
        if len(prefix):
            node = node.children[prefix[-1]]
        branches = list([ ('' + k, v) for k,v in node.children.items()])
        while branches:
            prefix, node = branches.pop(0)
            branches = list([ (prefix + k, v) for k,v in node.children.items()]) + branches
            if node.is_complete:
                suffixes.append(prefix)

        return suffixes

    def words(self):
        return self.get_all_suffixes(self.root)




if __name__ == '__main__':
    trie = Trie(node_class=StringNode)
    trie.add("hell")
#    trie.add("hello")
    trie.add("why")
 #   trie.add("trie")
    pprint (trie)

    trie1 = Trie(node_class=StringNode)
  #  trie1.add("tell")
  #  trie1.add("tall")
    trie1.add("hey")
    trie1.add("bite")
    pprint (trie1)

    trie.merge(trie1)
    pprint(trie)

    import pdb; pdb.set_trace()
    pprint(trie.root.get_suffixes('h'))
