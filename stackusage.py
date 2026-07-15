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

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(os.path.basename(__file__))

@dataclass(slots=True)
class Function:
    source_file:str
    func_line:int
    func_col:int
    su_func_name:str
    stack_usage:Optional[int]


@dataclass(slots=True)
class CINode:
    title:str
    source_file:str
    func_name:str
    signature:str
    label_func:Optional[str]

@dataclass(slots=True)
class CIEdge:
    source:str
    source_file:str
    source_signature:str
    source_func_name:str
    target:str
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
            cost = sum(node.func.stack_usage for node in path if node.func is not None and node.func.stack_usage is not None)
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
_SU_LINE_REGEX = re.compile(r'^(.+):(\d+):(\d+):([^\t]+)(\t([^\t]+)(\t([^\t]+))?)?$')
_LABEL_FIRST_LINE_FILE_REGEX = re.compile(r'.+:\d+:\d+$')

all_func_per_su_name:Dict[str, List[Function]] = {}
ci_node_per_title:Dict[str, List[CINode]] = {}
ci_node_per_label:Dict[str, List[CINode]] = {}
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
                label = m.group(2).strip()
                label_split_by_lines = label.split('\\n')
                demangled_signature = demangle(signature)
                func_name = get_func_name_from_signature(demangled_signature)

                label_func:Optional[str] = None
                if len(label_split_by_lines) > 0:
                    
                    # Seems like when there is a function name, it's on the first line
                    # if not, the file:line:col is the first line. 
                    # The best I could find.
                    if not _LABEL_FIRST_LINE_FILE_REGEX.match(label_split_by_lines[0]):
                        label_func = label_split_by_lines[0].strip()

                yield CINode(
                    title=title,
                    source_file=source_file, 
                    func_name=func_name, 
                    signature=demangled_signature, 
                    label_func=label_func
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
                    source = source,
                    source_file=source_file, 
                    source_func_name=source_func_name, 
                    source_signature=demangled_source_signature, 

                    target=target,
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
            
            m = _SU_LINE_REGEX.match(line)
            if not m:
                raise RuntimeError(f"Line regex didn't work on {line}")
            
            source_file = m.group(1).strip()
            line_number = int(m.group(2).strip())
            col_number = int(m.group(3).strip())
            su_func_name = m.group(4).strip()
            stack_usage:Optional[int] = None
            if m.group(6):
                stack_usage = int(m.group(6))

            yield Function(
                su_func_name=su_func_name,
                source_file = source_file, 
                func_line = line_number, 
                func_col = col_number, 
                stack_usage = stack_usage
                )

def get_target_ci_node(edge:CIEdge) -> Optional[CINode]:
    if edge.target not in ci_node_per_title:
        return None
    
    for node in ci_node_per_title[edge.target]:
        if node.source_file == edge.target_file:
            return node

    return ci_node_per_title[edge.target][0]

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
    if ci_node.label_func not in all_func_per_su_name:
        return None 
    
    for func in all_func_per_su_name[ci_node.label_func]:
        if func.source_file == ci_node.source_file:
            return func
    
    return all_func_per_su_name[ci_node.label_func][0]


def scan_filesystem_and_init_indexes(root_dir:Path):
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.ci'):
                for node in read_ci_file(Path(dirpath) / filename):
                    if isinstance(node, CINode):
                        if node.title not in ci_node_per_title:
                            ci_node_per_title[node.title] = []                            
                        ci_node_per_title[node.title].append(node)

                    elif isinstance(node, CIEdge):
                        if node.source_signature not in edge_per_source_func_signature:
                            edge_per_source_func_signature[node.source_signature] = []
                        edge_per_source_func_signature[node.source_signature].append(node)
            if filename.endswith('.su'):
                for func in read_stack_usage_file(Path(dirpath) / filename):
                    if func.su_func_name not in all_func_per_su_name:
                        all_func_per_su_name[func.su_func_name] = []
                    all_func_per_su_name[func.su_func_name].append(func)   

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

    start_nodes:List[CINode] = []
    for tile, nodes in ci_node_per_title.items():
        for node in nodes:
            if node.func_name == start_func:
                start_nodes.append(node)
                break

            if node.signature == start_func:
                start_nodes.append(node)
                break
    
    
    if len(start_nodes) == 0:
        logger.error(f"Could not find a node matching: {start_func}")
        root_node = CallTreeNode(func=None, parent=None, problem="No matching func with CI node")
        yield root_node
    else:
        for start_node in start_nodes:
            func = get_matching_func(start_node)
            if func is None:
                logger.error(f"Could not find given start function {start_func}")
                root_node = CallTreeNode(func=None, parent=None, problem="No matching func with CI node")
            else:
                root_node = CallTreeNode(func=func, parent=None)
                edges = get_outgoing_edges(start_node)
                add_children_to_node_recursive(root_node, edges, set([id(start_node)]))
                
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
                assert node.func.stack_usage is not None
                total += node.func.stack_usage
                print(f"    [{node.func.stack_usage:4}] {node.func.su_func_name} ")
            print(f"    [{total:4}] TOTAL")
            print()

if __name__ == '__main__':
    main()