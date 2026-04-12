package main

import (
	"encoding/json"
	"fmt"
)

type Node struct {
	Count      int               `json:"count"`
	IsComplete bool              `json:"is_complete"`
	Children   map[string]*Node  `json:"children"`
	Trie       *Trie             `json:"-"`
}

type Trie struct {
	Root *Node
}

func NewNode(trie *Trie) *Node {
	return &Node{
		Count:      0,
		IsComplete: false,
		Children:   make(map[string]*Node),
		Trie:       trie,
	}
}

func NewTrie() *Trie {
	trie := &Trie{}
	trie.Root = NewNode(trie)
	return trie
}

func (n *Node) Add(sequence string) {
	n.Count++
	if len(sequence) == 0 {
		n.IsComplete = true
		return
	}

	first := string(sequence[0])
	rest := sequence[1:]
	if _, exists := n.Children[first]; !exists {
		n.Children[first] = NewNode(n.Trie)
	}
	n.Children[first].Add(rest)
}

func (n *Node) FindPrefix(prefix string, length int) (*Node, int) {
	if len(prefix) == 0 {
		return n, length
	}

	first := string(prefix[0])
	rest := prefix[1:]
	if child, exists := n.Children[first]; exists {
		return child.FindPrefix(rest, length+1)
	}
	return n, length
}

func (t *Trie) Add(sequence string) {
	t.Root.Add(sequence)
}

func (n *Node) ToDict() map[string]interface{} {
	childrenDict := make(map[string]interface{})
	for k, v := range n.Children {
		childrenDict[k] = v.ToDict()
	}
	return map[string]interface{}{
		"count":      n.Count,
		"is_complete": n.IsComplete,
		"children":   childrenDict,
	}
}

func (n *Node) Merge(other *Node) {
	n.Count += other.Count
	if other.IsComplete {
		n.IsComplete = true
	}
	for k, v := range other.Children {
		if _, exists := n.Children[k]; !exists {
			n.Children[k] = NewNode(n.Trie)
		}
		n.Children[k].Merge(v)
	}
}

func (t *Trie) Merge(other *Trie) {
	t.Root.Merge(other.Root)
}

func (t *Trie) FindPrefix(prefix string) (*Node, int) {
	return t.Root.FindPrefix(prefix, 0)
}

func (t *Trie) GetAllSuffixes(prefix string) []string {
	suffixes := []string{}
	node, length := t.FindPrefix(prefix)
	if length == 0 {
		return suffixes
	}

	var collectSuffixes func(n *Node, current string)
	collectSuffixes = func(n *Node, current string) {
		if n.IsComplete {
			suffixes = append(suffixes, current)
		}
		for k, v := range n.Children {
			collectSuffixes(v, current+k)
		}
	}

	collectSuffixes(node, "")
	return suffixes
}

func main() {
	trie1 := NewTrie()
	trie1.Add("hell")
	trie1.Add("why")

	trie2 := NewTrie()
	trie2.Add("hey")
	trie2.Add("bite")

	trie1.Merge(trie2)

	trieJson, _ := json.MarshalIndent(trie1.Root.ToDict(), "", "  ")
	fmt.Println(string(trieJson))

	fmt.Println("Suffixes for 'h':", trie1.GetAllSuffixes("h"))
}
