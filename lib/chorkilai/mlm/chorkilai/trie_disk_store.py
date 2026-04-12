import os
import mmap
import struct

class TrieDiskStore:
    HEADER_FORMAT = "<4sIQQ"  # Magic (4s), version (32b), free_list_head (64b), root_offset (64b)
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, filename, new=False):
        self.filename = filename
        if new or not os.path.exists(filename):
            # Create new file and write header
            with open(filename, "wb") as f:
                # Initialize header: magic b"TRIE", version=1, free_list_head=0, root_offset=0
                header = struct.pack(self.HEADER_FORMAT, b"TRIE", 1, 0, 0)
                f.write(header)
            self.fd = open(filename, "r+b")
            self.fd.truncate(self.HEADER_SIZE)
        else:
            self.fd = open(filename, "r+b")
        self.mm = mmap.mmap(self.fd.fileno(), 0)

    def close(self):
        self.mm.flush()
        self.mm.close()
        self.fd.close()

    def allocate_node(self, node_data: bytes) -> int:
        """
        Allocates space for a node record (node_data should include its length as the first 4 bytes)
        by looking in the free list or appending at the end.
        Returns the offset where the node was written.
        """
        # For simplicity, this example always appends.
        offset = self.mm.size()
        self.mm.resize(offset + len(node_data))
        self.mm.seek(offset)
        self.mm.write(node_data)
        self.mm.flush()  # flush allocated node data
        return offset

    def read_node(self, offset: int) -> bytes:
        self.mm.seek(offset)
        # First 4 bytes: record length
        len_bytes = self.mm.read(4)
        if not len_bytes:
            return None
        (record_len,) = struct.unpack("<I", len_bytes)
        self.mm.seek(offset)
        return self.mm.read(record_len)

    def write_node(self, offset: int, node_data: bytes) -> int:
        """
        Overwrites a node record at offset. Node_data should exactly match the record length
        stored in its header. Otherwise, a reallocation is required.
        """
        self.mm.seek(offset)
        curr_len_bytes = self.mm.read(4)
        (curr_len,) = struct.unpack("<I", curr_len_bytes)
        if len(node_data) > curr_len:
            # Not enough room: need to reallocate.
            new_offset = self.allocate_node(node_data)
            # Caller must update the parent's pointer to use new_offset.
            # Optionally, add the old offset to the free list.
            return new_offset
        else:
            # If node_data is smaller, pad with zeros.
            self.mm.seek(offset)
            self.mm.write(node_data.ljust(curr_len, b'\x00'))
            self.mm.flush()
            return offset
