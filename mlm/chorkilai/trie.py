# -*- coding: utf-8 -*
import os
import mmap
import struct
import pdb
import argparse
import csv

from abc import ABC, abstractmethod
from pprint import pprint, pformat
from tqdm import tqdm

import arichuvadi as ari
import chorkilai.utils as utils

XSV_DELIMITER = '\t'
LETTER_FIELD_SIZE = 8

class BaseTrie(ABC):
    @abstractmethod
    def add(self, item):
        """Adds an item to the trie."""
        pass

    @abstractmethod
    def lookup(self, word: str) -> bool:
        """Returns True if the word exists as an exact match."""
        pass

    @abstractmethod
    def prefix_exists_p(self, prefix: str) -> bool:
        """Returns True if the prefix exists in the trie."""
        pass

    def close(self):
        """For backing stores that require cleanup (e.g. mmap)."""
        pass

class Node(object):

    def __repr__(self):
        if self.level < 160:
            return "Node({}, {}, {})\n{} {}".format(
                ''.join(self.value) if self.value else self.value,
                self.count,
                self.is_complete,
                '\t' * self.level,
                self.children,)
        else:
            return ''

    def __str__(self):
        return self.__repr__()

    def __init__(self, value=None, count=1, level=0):
        self.value = value
        self.count = count
        self.children = {}
        self.is_complete = False
        self.level = level


class Trie(BaseTrie):

    def __init__(self):
        self.root = Node(value=None, level=0)

    def __repr__(self):   return self.root.__repr__()
    def __str__(self):    return self.__repr__()

    def add(self, item):
        node, i = self.find_prefix(item)
        if i < len(item):
            #increment count
            j = 0
            tnode = self.root
            while j < i:
                tnode.children[item[j]].count += 1
                tnode = tnode.children[item[j]]
                j += 1

            # add new nodes
            while i < len(item):
                #new_node = Node(item[:i+1], count=1, level=i+1)
                new_node = Node(item[i], count=1, level=i+1)
                node.children[item[i]] = new_node
                node = new_node
                i += 1

            node.is_complete = True

    def lookup(self, word: str) -> bool:
        """Returns True if the complete word is present (i.e. the final node is marked complete)."""
        node = self.root
        for letter in word:
            node = node.children.get(letter)
            if node is None:
                return False
        return node.is_complete

    def find_prefix(self, prefix, default=None):
        i = 0
        prev_node = node = self.root
        while i < len(prefix) and node:
            prev_node = node
            node = node.children.get(prefix[i], None)
            i += 1

        if i <= len(prefix):
            return prev_node, i-1
        else:
            return self.root, 0

    def prefix_exists_p(self, prefix: str) -> bool:
        """Returns True if the prefix exists in the trie."""
        node = self.root
        for letter in prefix:
            node = node.children.get(letter)
            if node is None:
                return False
        return True

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

class OnDiskTrie(BaseTrie):
    import struct
    # Define header sizes and initial capacity.
    # Header now consists of:
    #   record_length (4 bytes), terminal flag (1 byte), child_count (2 bytes), capacity (2 bytes)
    # Total header size = 9 bytes.
    HEADER_SIZE = 9
    INITIAL_NODE_CAPACITY = 10
    CHILD_RECORD_SIZE = 1 + LETTER_FIELD_SIZE + 4  # 1 byte key length, LETTER_FIELD_SIZE bytes key, 4 bytes pointer

    def __init__(self, db_path, new=False):
        from .trie_disk_store import TrieDiskStore
        import struct
        self.store = TrieDiskStore(db_path, new=new)
        if new:
            # Create a fresh root node.
            root = {
                'is_terminal': 0,
                'child_count': 0,
                'capacity': self.INITIAL_NODE_CAPACITY,
                'children': []
            }
            root_data = self._serialize_node(root)
            self.root_offset = self.store.allocate_node(root_data)
            # Update the file header with the new root offset.
            self._update_header()
        else:
            # Read the header and set self.root_offset from the stored value.
            hdr = self.store.mm[:self.store.HEADER_SIZE]
            magic, version, free_list_head, root_offset = struct.unpack(self.store.HEADER_FORMAT, hdr)
            if magic != b"TRIE":
                raise ValueError("Invalid file format")
            self.root_offset = root_offset
            self._root_offset = self.root_offset

    def _node_record_size(self, capacity: int) -> int:
        """Computes node record size given a children capacity."""
        return self.HEADER_SIZE + capacity * self.CHILD_RECORD_SIZE

    def _read_node(self, offset: int) -> dict:
        """Reads the node at the given offset and returns a dictionary representation."""
        data = self.store.read_node(offset)
        if len(data) < self.HEADER_SIZE:
            raise ValueError("Corrupt node record at offset %s" % offset)
        rec_length = self.struct.unpack("<I", data[0:4])[0]
        is_terminal = data[4]
        child_count = self.struct.unpack("<H", data[5:7])[0]
        capacity = self.struct.unpack("<H", data[7:9])[0]
        children = []
        pos = self.HEADER_SIZE
        for i in range(child_count):
            key_len = data[pos]
            pos += 1
            key_bytes = data[pos:pos+LETTER_FIELD_SIZE]
            pos += LETTER_FIELD_SIZE
            child_ptr = self.struct.unpack("<I", data[pos:pos+4])[0]
            pos += 4
            key = key_bytes[:key_len].decode("utf-8", errors="ignore")
            if key_len > 0:
                children.append({'key': key, 'child_ptr': child_ptr})
        return {
            'offset': offset,
            'record_length': rec_length,
            'is_terminal': is_terminal,
            'child_count': child_count,
            'capacity': capacity,
            'children': children
        }

    def _serialize_node(self, node: dict) -> bytes:
        """Serializes a node dictionary into a bytes object with appropriate record size."""
        capacity = node['capacity']
        rec_size = self._node_record_size(capacity)
        ba = bytearray(rec_size)
        # Write header: record length, terminal flag, child_count, capacity.
        ba[0:4] = self.struct.pack("<I", rec_size)
        ba[4] = node['is_terminal']
        ba[5:7] = self.struct.pack("<H", node['child_count'])
        ba[7:9] = self.struct.pack("<H", capacity)
        pos = self.HEADER_SIZE
        for i in range(len(node['children'])):
            child = node['children'][i]
            key_bytes = child['key'].encode("utf-8")
            key_len = len(key_bytes)
            if key_len > LETTER_FIELD_SIZE:
                key_bytes = key_bytes[:LETTER_FIELD_SIZE]
                key_len = LETTER_FIELD_SIZE
            ba[pos] = key_len
            pos += 1
            key_padded = key_bytes.ljust(LETTER_FIELD_SIZE, b'\x00')
            ba[pos:pos+LETTER_FIELD_SIZE] = key_padded
            pos += LETTER_FIELD_SIZE
            ba[pos:pos+4] = self.struct.pack("<I", child['child_ptr'])
            pos += 4
        return bytes(ba
)
    def _create_empty_node(self) -> int:
        """Creates an empty node with initial capacity and returns its offset."""
        node = {
            'is_terminal': 0,
            'child_count': 0,
            'capacity': self.INITIAL_NODE_CAPACITY,
            'children': []
        }
        data = self._serialize_node(node)
        offset = self.store.allocate_node(data)
        return offset

    def _expand_node(self, parent_offset, parent_node, child_key, current_offset, node):
        """
        Expands the node's capacity (double its current capacity) and updates the parent's pointer.
        Returns the new offset for the expanded node.
        """
        old_capacity = node['capacity']
        new_capacity = old_capacity * 2
        node['capacity'] = new_capacity
        # Recompute record size accordingly.
        new_data = self._serialize_node(node)
        # Write new node record; store.write_node will reallocate if new_data is larger than current record.
        new_offset = self.store.write_node(current_offset, new_data)
        # If the node got reallocated, update parent's pointer.
        if new_offset != current_offset:
            if parent_node is None:
                # Root node changed.
                self.root_offset = new_offset
                self._update_header()
            else:
                # Update parent's child pointer for letter child_key.
                for child in parent_node['children']:
                    if child['key'] == child_key:
                        child['child_ptr'] = new_offset
                        break
                parent_data = self._serialize_node(parent_node)
                self.store.write_node(parent_offset, parent_data)
        return new_offset

    def _update_header(self):
        """Update the file header with the current root offset."""
        new_header = struct.pack(self.store.HEADER_FORMAT, b"TRIE", 1, 0, self.root_offset)
        self.store.mm.seek(0)
        self.store.mm.write(new_header)
        self.store.mm.flush()  # flush changes so the header is persisted

    def add(self, item):
        """
        Inserts the word (item) into the on-disk trie.
        This implementation expands a node when its capacity is reached.
        """
        current_offset = self.root_offset
        parent_info = None  # Tuple: (parent_offset, parent_node, letter_key)
        for letter in item:
            node = self._read_node(current_offset)
            found = False
            for child in node['children']:
                if child['key'] == letter:
                    found = True
                    parent_info = (current_offset, node, letter)
                    current_offset = child['child_ptr']
                    break
            if not found:
                # If node is full, expand it.
                if node['child_count'] >= node['capacity']:
                    if parent_info is None:
                        # Expanding root node.
                        current_offset = self._expand_node(self.root_offset, None, letter, current_offset, node)
                        node = self._read_node(current_offset)
                    else:
                        (p_offset, p_node, p_letter) = parent_info
                        current_offset = self._expand_node(p_offset, p_node, p_letter, current_offset, node)
                        node = self._read_node(current_offset)
                # Create new child.
                new_node_offset = self._create_empty_node()
                node['children'].append({'key': letter, 'child_ptr': new_node_offset})
                node['child_count'] += 1
                updated_data = self._serialize_node(node)
                self.store.write_node(current_offset, updated_data)
                parent_info = (current_offset, node, letter)
                current_offset = new_node_offset
        # Mark the final node as terminal.
        final_node = self._read_node(current_offset)
        final_node['is_terminal'] = 1
        final_data = self._serialize_node(final_node)
        self.store.write_node(current_offset, final_data)

    def lookup(self, word: str) -> bool:
        """
        Returns True if the complete word is present in the trie.
        """
        #import pdb; pdb.set_trace()
        current_offset = self.root_offset
        for letter in word:
            node = self._read_node(current_offset)
            found = False
            for child in node['children']:
                if child['key'] == letter:
                    found = True
                    current_offset = child['child_ptr']
                    break
            if not found:
                return False
        final_node = self._read_node(current_offset)
        return bool(final_node['is_terminal'])

    def prefix_exists_p(self, prefix: str) -> bool:
        """
        Returns True if the prefix exists in the trie.
        """
        current_offset = self.root_offset
        for letter in prefix:
            node = self._read_node(current_offset)
            found = False
            for child in node['children']:
                if child['key'] == letter:
                    found = True
                    current_offset = child['child_ptr']
                    break
            if not found:
                return False
        return True

    def find_prefix(self, prefix, default=None):
        """
        Traverse the on-disk trie to find the node corresponding to the given prefix.
        Returns the node dictionary if found, else returns default.
        """
        if self._root_offset == 0:
            return default
        node = self._read_node(self._root_offset)
        for letter in prefix:
            for child in node['children']:
                if child['key'] == letter:
                    found = True
                    child_offset = child['child_ptr']
                    break
            if not found:
                return default
            node = self._read_node(child_offset)
        return node

    def _collect_suffixes(self, node, current_suffix):
        """
        Recursively collect all suffixes from the on-disk trie starting at the given node.
        """
        results = []
        if node.get("is_terminal", False):
            results.append(current_suffix)
        for record in node.get("children", {}):
            letter, child_offset = record.values()
            child_node = self._read_node(child_offset)
            results.extend(self._collect_suffixes(child_node, current_suffix + letter))
        return results

    def get_all_suffixes(self, prefix):
        """
        Returns all suffixes (relative to the given prefix) for words stored in the on-disk trie.
        """
        node = self.find_prefix(prefix)
        if node is None:
            return []
        return self._collect_suffixes(node, "")

    def close(self):
        self.store.close()

def get_trie(use_mmap=False, db_path=None, db_flush=False):
    if use_mmap:
        # Create an on-disk trie and populate it with words.
        trie = OnDiskTrie(db_path, new=db_flush)
    else:
         trie = Trie()
    return trie

def load_files(filepaths, trie, pbarp=False):
    for filepath in filepaths:
        print('loading {}...'.format(filepath))
        if pbarp:
            pbar = tqdm(utils.openfile(filepath), ncols=100)
        else:
            pbar = utils.openfile(filepath)
        for item in csv.reader(pbar, delimiter=XSV_DELIMITER):
            try:
                token, *count = item
                if token:
                    trie.add(ari.get_letters_coding(token))
                    # if pbarp:
                    #     pbar.set_description(token)
            except Exception as e:
                print("Error processing {}: {}".format(item, e))

    return trie

def build_trie(filepaths, use_mmap=False, db_path=None, db_flush=False, pbarp=True):
    trie = get_trie(use_mmap, db_path, db_flush)
    if db_flush:
        trie = load_files(filepaths, trie, pbarp)
    return trie

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Trie CLI: Choose backing store (in-memory or mmap).")
    parser.add_argument("--mmap", action="store_true", help="Use mmap-backed trie instead of in-memory.")
    parser.add_argument("--mmap-flush", action="store_true", help="Delete existing mmap store and create new one")
    parser.add_argument("--db-path", type=str, default="data/tamil_trie_ondisk.db",
                        help="Path to store/read the mmap trie binary file.")
    parser.add_argument("--suffixes", action='store_true',
                        help="prefix for which to list all the exisitng suffixes")
    parser.add_argument('filepaths', nargs='+', help='paths to files that contain words to be loaded')

    args = parser.parse_args()

    use_mmap = args.mmap
    db_path = args.db_path
    db_flush = args.mmap_flush

    print(args.filepaths)

    trie_obj = build_trie(args.filepaths, use_mmap=use_mmap, db_path=db_path, db_flush=db_flush)

    word = input('> ')
    while word:
        try:
            if not word.strip():
                break
            word = ari.TamilStr(word)
            print(word, repr(word))
            if args.suffixes:
                for item in trie_obj.get_all_suffixes(word):
                    print(item)
            else:
                print('இருக்குதா? {}'.format(
                    'இருக்கு' if trie_obj.lookup(word) else 'இல்லை'))
            word = input('> ')
        except KeyboardInterrupt:
            break


    trie_obj.close()
