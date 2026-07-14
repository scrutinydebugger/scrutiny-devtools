# This is a home amde script to calculate the stack usage based of GCC output
# It is missing overload handling, but it's enough for now
# author : Pier-Yves Lessard

from dataclasses import dataclass
from pathlib import Path
from typing import *
import logging
import os
import re
import argparse
import subprocess

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(os.path.basename(__file__))

@dataclass(slots=True)
class Function:
    pretty_name:str
    return_type:str
    signature:str
    source_file:str
    func_line:int
    func_col:int
    stack_usage:int

@dataclass(slots=True)
class CINode:
    source_file:str
    func_name:str
    signature:str
    stack_usage_from_label:Optional[int]

@dataclass(slots=True)
class CIEdge:
    source_file:str
    source_signature:str
    source_func_name:str
    target_file:str
    target_signature:str
    target_func_name:str
    label:str

@dataclass(init=False, slots=True)
class CallTreeNode:
    func:Optional[Function]
    parent:Optional["CallTreeNode"]
    children:List["CallTreeNode"]
    problem:Optional[str]

    def __init__(self, 
                 func:Optional[Function], 
                 parent:Optional["CallTreeNode"], 
                 children:Optional[List["CallTreeNode"]] = None, 
                 problem:Optional[str] = None
                 ) -> None:
        self.func = func
        self.parent = parent
        if children is None:
            self.children = []
        else:
            self.children = children

        self.problem = problem


    def walk_leaf(self, node:Optional["CallTreeNode"]=None) -> Generator[List["CallTreeNode"], None, None]:
        if node is None:
            node = self

        if len(node.children) == 0:
            path = [node]
            parent = node.parent
            while parent is not None:
                path.insert(0, parent)
                parent = parent.parent
            yield path
        else:
            for child in node.children:
                yield from self.walk_leaf(node=child)


    def get_heaviest_path(self) -> List["CallTreeNode"]:
        contender:Optional[Tuple[List["CallTreeNode"], int]] = None

        for path in self.walk_leaf():
            if any( node.func is None for node in path ):
                continue
            cost = sum(node.func.stack_usage for node in path if node.func is not None)
            if contender is None or cost>contender[1]:
                contender = (path, cost)
        if contender is None:
            return []
        return contender[0]


def get_file_func(s:str) -> Tuple[str,str]:
    parts = s.split(':')
    if len(parts) == 1:
        return ("", s.strip())
    elif len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    else:
        raise ValueError(f"Unsupported File:Func format. {s}")

def demangle(name:str) -> str:
    p = subprocess.run(['c++filt', name],stdout=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"c+filt failed on {name}")
    return p.stdout.decode('utf8').strip()

_CI_NODE_RE = re.compile(r'^node:\s*\{\s*title:\s*"([^"]*)"\s*label:\s*"([^"]*)"\s*(?:shape\s*:\s*\w+\s*)?\}')
_CI_EDGE_RE = re.compile(r'^edge:\s*\{\s*sourcename:\s*"([^"]*)"\s*targetname:\s*"([^"]*)"\s*label:\s*"([^"]*)"\s*\}')
_STACK_SIZE_REGEX = re.compile(r'^(\d+) bytes?')

_STACK_USAGE_REGEX = re.compile(r'(\d+)\D*$')
_OBJECT_REGEX = re.compile(r'^(.+):(\d+):(\d+):(([^ \(]+) )?(.+)$')
_SIGNATURE_PARSE_REGEX = re.compile(r'^([^\(]+)\(.*\)(.*)$')

all_func_per_name:Dict[str, List[Function]] = {}
ci_node_per_func_name:Dict[str, List[CINode]] = {}
edge_per_source_func_signature:Dict[str, List[CIEdge]] = {}

def read_ci_file(file:Path) -> Generator[Union[CINode, CIEdge], None, None]:

    def get_func_name_from_signature(signature:str) -> str:
        index = signature.find('(')
        func_name = signature
        if index != -1:
            func_name = signature[:index]
        return func_name.strip()

    with open(file, 'r') as f:
        for line in f.readlines():
            line = line.strip()
            m = _CI_NODE_RE.match(line)
            if m:
                title = m.group(1).strip()
                source_file, signature = get_file_func(title)
                stack_usage_from_label:Optional[int] = None
                label = m.group(2).strip()
                label_split_by_lines = label.split('\\n')
                if len(label_split_by_lines) == 3:
                    m = _STACK_SIZE_REGEX.match(label_split_by_lines[-1])
                    if not m:
                        logger.error(f"Did not find stack size in {file}. Line: {line} ")
                        continue
                    stack_usage_from_label = int(m.group(1))
                demangled_signature = demangle(signature)
                func_name = get_func_name_from_signature(demangled_signature)

                yield CINode(
                    source_file=source_file, 
                    func_name=func_name, 
                    signature=demangled_signature, 
                    stack_usage_from_label=stack_usage_from_label
                    )
                continue

            m = _CI_EDGE_RE.match(line)
            if m:
                source = str(m.group(1).strip())
                target =str( m.group(2).strip())
                label = str(m.group(3).strip())

                source_file, source_signature = get_file_func(source)
                target_file, target_signature = get_file_func(target)

                demangled_source_signature = demangle(source_signature)
                source_func_name = get_func_name_from_signature(demangled_source_signature)
                demangled_target_signature = demangle(target_signature)
                target_func_name = get_func_name_from_signature(demangled_target_signature)

                yield CIEdge(
                    source_file=source_file, 
                    source_func_name=source_func_name, 
                    source_signature=demangled_source_signature, 
                   
                    target_file=target_file, 
                    target_func_name=target_func_name, 
                    target_signature=demangled_target_signature,

                    label=label
                )

def read_stack_usage_file(file:Path) -> Generator[Function, None, None]:
    logger.debug(f"Reading {file}")

    with open(file, 'r') as f:  
        for line in f.readlines():
            line = line.strip()
            if len(line) == 0:
                continue
                    
            if not (line.endswith('static') or line.endswith('bounded')):
                logger.debug(f'File {file}. Skipping {line}')
                continue
            
            usage_match = _STACK_USAGE_REGEX.search(line)
            if usage_match is None:
                logger.debug(f'File {file}. No usage_match. Skipping {line}')
                continue
            
            line = line[:usage_match.start()].strip()
            object_match = _OBJECT_REGEX.match(line)
            if not object_match:
                logger.debug(f'File {file}. No object_match. Skipping {line}')
                continue
            
            stack_usage = int(usage_match.group(1))
            source_file = object_match.group(1).strip()
            line_number = int(object_match.group(2))
            col_number = int(object_match.group(3))
            return_type = object_match.group(4).strip()
            signature = object_match.group(6).strip()
            demangled_signature = demangle(signature)
            m = _SIGNATURE_PARSE_REGEX.match(demangled_signature)
            if not m:
                logger.debug(f'Invalid signature in {line}')
                continue

            pretty_name = m.group(1).strip()

            yield Function(
                pretty_name=pretty_name, 
                return_type=return_type,
                signature =demangled_signature,
                source_file = source_file, 
                func_line = line_number, 
                func_col = col_number, 
                stack_usage = stack_usage,
                )

def get_target_ci_node(edge:CIEdge) -> Optional[CINode]:
    if edge.target_func_name not in ci_node_per_func_name:
        return None
    
    nodes = [node for node in ci_node_per_func_name[edge.target_func_name] if node.signature == edge.target_signature]

    if len(nodes) == 0:
        return None
    
    for node in nodes: # Priority to same compile unit for linkage
        if node.source_file == edge.source_file:
            return node
    
    return nodes[0]

def get_outgoing_edges(source_node:CINode) -> Generator[CIEdge, None, None]:
    if source_node.signature not in edge_per_source_func_signature:
        return None
    generated_edges:Set[int] = set()

    for edge in edge_per_source_func_signature[source_node.signature]:
        if id(edge) not in generated_edges:
            if edge.source_file == source_node.source_file:
                generated_edges.add(id(edge))
                yield edge

def get_matching_func(ci_node:CINode) -> Optional[Function]:
    if ci_node.func_name not in all_func_per_name:
        return None 
    
    func_with_correct_signature = [f for f in all_func_per_name[ci_node.func_name] if f.signature == ci_node.signature]
    for func in func_with_correct_signature:
        if func.source_file == ci_node.source_file:
            return func
        
        return func_with_correct_signature[0]

    for func in all_func_per_name[ci_node.func_name]:
        if func.source_file == ci_node.source_file:
            return func
    
    return all_func_per_name[ci_node.func_name][0]


def scan_filesystem_and_init_indexes(root_dir:Path):
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.ci'):
                for node in read_ci_file(Path(dirpath) / filename):
                    if isinstance(node, CINode):
                        if node.func_name not in ci_node_per_func_name:
                            ci_node_per_func_name[node.func_name] = []
                        ci_node_per_func_name[node.func_name].append(node)
                    elif isinstance(node, CIEdge):
                        if node.source_signature not in edge_per_source_func_signature:
                            edge_per_source_func_signature[node.source_signature] = []
                        edge_per_source_func_signature[node.source_signature].append(node)
            if filename.endswith('.su'):
                for func in read_stack_usage_file(Path(dirpath) / filename):
                    if func.pretty_name not in all_func_per_name:
                        all_func_per_name[func.pretty_name] = []
                    all_func_per_name[func.pretty_name].append(func)   

def add_children_to_node_recursive(node:CallTreeNode, edges:Iterable[CIEdge], seen_ci_node:Set[int]) -> None:
    for edge in edges:
        target_node = get_target_ci_node(edge)
        if target_node is None:
            problem = f"Cannot find target node of edge: {edge}"
            logger.warning(problem)
            node.children.append(CallTreeNode(func=None, parent=node, problem=problem))
            continue
        
        if id(target_node) in seen_ci_node:
            problem = f"Seen node {target_node} more than once in {node.func}"
            logger.warning(problem)
            node.children.append(CallTreeNode(func=None, parent=node, problem=problem))
            continue
        
        child_seen_node = seen_ci_node.copy()
        child_seen_node.add(id(target_node))
        target_func = get_matching_func(target_node)
        if target_func is None:
            problem = f"Cannot find matching func to node {target_node}"
            logger.warning(problem)
            node.children.append(CallTreeNode(func=None, parent=node, problem=problem))
            continue
        
        child_node = CallTreeNode(func=target_func, parent=node)
        add_children_to_node_recursive(
            node = child_node, 
            edges = get_outgoing_edges(target_node), 
            seen_ci_node = child_seen_node
        )
        node.children.append(child_node)

def build_func_trees(start_func:str) -> Generator[CallTreeNode, None, None]:
    for ci_node in ci_node_per_func_name.get(start_func, []):
        func = get_matching_func(ci_node)
        if func is None:
            logger.error(f"Could not find given start function {start_func}")
            root_node = CallTreeNode(func=None, parent=None, problem="No matching func with CI node")
        else:
            root_node = CallTreeNode(func=func, parent=None)
            edges = get_outgoing_edges(ci_node)
            add_children_to_node_recursive(root_node, edges, set([id(ci_node)]))
            
        yield root_node


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('root_dir', type=str)
    parser.add_argument('funcs', type=str, nargs='*')
    args = parser.parse_args()

    scan_filesystem_and_init_indexes(Path(args.root_dir))
    
    for func_name in args.funcs:
        for tree in build_func_trees(func_name):
            callstack = tree.get_heaviest_path()
            print(f"- {func_name}")
            total = 0
            for node in callstack:
                assert node.func is not None
                total += node.func.stack_usage
                print(f"    [{node.func.stack_usage:4}] {node.func.signature} ")
            print(f"    [{total:4}] TOTAL")
            print()

if __name__ == '__main__':
    main()