#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Build all possible graphs using a Randomised Stepwise Addition Order Algorithm w/ Branch and Bound.
# Usage...
# python -u permute_qpgraph.py 1> permute-std.log 2> permute-err.log

import xml.etree.ElementTree as ElemTree
import re
import sys

# use the Pathos library for improved multi-processing
import pathos.multiprocessing as mp

# import the custom modules
from pipeline_utils import *

from cStringIO import StringIO
from Bio import Phylo

# shoud we use multi-threading to speed up the graph search
MULTITHREADED_SEARCH = True

# how many outliers should we allow before pruning a branch in graph space
MAX_OUTLIER_THRESHOLD = 0

# print PDFs for graphs with (N - offset) nodes
REMAINING_PRINT_OFFSET = 0

# should we try all possible graphs, or should we stop when we find something reasonable
EXHAUSTIVE_SEARCH = False
# EXHAUSTIVE_SEARCH = True

# TODO improve parsimony...
# on first pass, only allow non-admix insertion
# if can't be added, then send to back of list
# if it fails admix insertion (when it's turn comes up again)
# then throw


class PermuteQpgraph:

    def __init__(self, par_file, dot_path, pdf_path, nodes, outgroup):
        """
        Initialise the object attributes 
        """
        self.par_file = par_file
        self.dot_path = dot_path
        self.pdf_path = pdf_path

        if outgroup in nodes:
            nodes.remove(outgroup)

        self.nodes = nodes
        self.outgroup = outgroup

        self.root_node = 'R'
        self.problem_nodes = []
        self.tested_graphs = set()
        self.solutions = set()

    def recurse_tree(self, root_tree, new_tag, remaining, depth=0):
        """
        Permute all possible new trees, by adding the new node to all branches.
    
        If no resulting tree passes the outlier threshold then try adding the node to all possible pairs of branches.
        """
        new_trees = []

        # get all the nodes in the tree (skip the outgroup)
        target_nodes = [node for node in root_tree.findall('.//*') if node.tag != self.outgroup]

        # add the new node to every branch in the tree
        for target_node in target_nodes:

            # clone the current tree and add the new node
            new_tree = copy.deepcopy(root_tree)
            self.insert_node(new_tree, target_node, new_tag)
            new_trees.append(new_tree)

        # test all the trees
        results = self.test_trees(new_trees, depth)

        # process the results
        node_placed = self.check_results(results, remaining, depth)

        # test all the admixture possibilities
        if not node_placed:

            admix_trees = []

            # permute all the two parent admixture possibilities
            pairs = list(itertools.combinations(target_nodes, 2))

            for target1, target2 in pairs:
                # skip duplicate targets (this happens when there is already an admixture node in the tree)
                if target1.tag == target2.tag:
                    continue

                # clone the current tree
                new_tree = copy.deepcopy(root_tree)

                # make a new intermediate node
                admix_label = self.new_label(new_tree, admix=True)

                # add two admix nodes as the children of both targets
                admix_nodes = [
                    self.insert_node(new_tree, target1, admix_label, attrs={'internal': '1', 'admix': '1', 'side': 'l'}),
                    self.insert_node(new_tree, target2, admix_label, attrs={'internal': '1', 'admix': '1', 'side': 'r'})
                ]

                # choose the actual parent based on the sort order of the tag name (needed for unique tree hashing)
                admix_node = admix_nodes[0] if target1.tag < target2.tag else admix_nodes[1]

                # add the new node as the child of the preferred admix node
                self.insert_node(new_tree, admix_node, new_tag, append=True)

                admix_trees.append(new_tree)

            # test all the admixture trees
            results = self.test_trees(admix_trees, depth)

            # process the results
            node_placed = self.check_results(results, remaining, depth)

        if not node_placed:

            # we could not place the node via either method :(
            if new_tag not in self.problem_nodes and remaining and not EXHAUSTIVE_SEARCH:
                print "WARNING: Unable to place node '%s' at this time." % new_tag

                self.problem_nodes.append(new_tag)

                # add the problem node to end of the list, as we may be able to add it later on
                remaining.append(new_tag)

                # try and add the other nodes
                self.recurse_tree(root_tree, remaining[0], remaining[1:], depth)

            else:
                raise NodeUnplaceable("ERROR: Cannot place node '%s' in the graph." % new_tag)

    def test_trees(self, new_trees, depth):
        """
        Run qpGraph on a list of trees
        """
        if MULTITHREADED_SEARCH:
            # we need to buffer the results to use multi-threading
            pool = mp.ProcessingPool(MAX_CPU_CORES)
            results = pool.map(self.run_qpgraph, itertools.izip(new_trees, itertools.repeat(depth)))
        else:
            # test the trees without multi-threading
            results = []
            for new_tree in new_trees:
                result = self.run_qpgraph((new_tree, depth))
                results.append(result)

        return results

    def check_results(self, results, remaining, depth):
        """
        Check the results from qpGraph
        """
        # were we able to place the new node
        placed_node = False

        for new_tree, outliers, graph_name in results:

            # add this graph to the list of those we've tested
            self.tested_graphs.add(graph_name)

            # did our new trees pass the threshold
            if len(outliers) <= MAX_OUTLIER_THRESHOLD:

                # recursively add any remaining nodes
                if remaining:
                    self.recurse_tree(new_tree, remaining[0], remaining[1:], depth + 1)
                else:
                    print "SUCCESS: Placed all nodes on a graph without outliers!"

                    # add this graph to the list of solutions
                    self.solutions.add(graph_name)

                # we successfully placed the new node!
                placed_node = True

        return placed_node

    def insert_node(self, new_tree, target_node, new_tag, attrs=None, append=False):
        """
        Helper function to add a new node on the branch leading to the target node.
        """
        # get the target node in the new tree
        target_xpath = './/' + target_node.tag

        if target_node.get('side'):
            target_xpath += '[@side="%s"]' % target_node.get('side')

        target_node = new_tree.find(target_xpath)

        if append:
            # append the new node directly to the target
            parent_node = target_node

        else:
            # get the parent of the target
            parent_node = new_tree.find(target_xpath + '/..')

            # does the target node have a sibling
            if len(parent_node) > 1:
                label = self.new_label(new_tree)
                parent_node.remove(target_node)

                # add an intermediate node, to act as the parent for the new node
                parent_node = ElemTree.SubElement(parent_node, label)
                parent_node.set('internal', '1')

                # re add the target node
                # ElemTree.SubElement(parent_node, target_node.tag)
                parent_node.append(target_node)

        # add the new node as a sibling to the target
        new_node = ElemTree.SubElement(parent_node, new_tag)

        if attrs:
            # add any node attributes
            for key, value in attrs.iteritems():
                new_node.set(key, value)

        return new_node

    def run_qpgraph(self, args):
        """
        Run qpGraph on the given tree 
        """
        # extract the tuple of arguments
        new_tree, depth = args

        # convert the tree to newick format
        newick = self.print_newick_tree(new_tree)

        # get unique names for the output files
        graph_name = self.hash_text(newick)
        grp_file = self.dot_path + '-{name}.graph'.format(name=graph_name)
        dot_file = self.dot_path + '-{name}.dot'.format(name=graph_name)
        log_file = self.dot_path + '-{name}.log'.format(name=graph_name)
        xml_file = self.dot_path + '-{name}.xml'.format(name=graph_name)

        try:
            # if the log file exists then we've run the analysis already
            with open(log_file, 'r') as fin:
                log = fin.read()

        except IOError:
            # save the xml file
            new_tree.write(xml_file)

            # convert the tree to qpGraph format
            graph = self.export_qpgraph(new_tree)

            # save the graph file
            with open(grp_file, 'w') as fout:
                fout.write(graph)

            # run qpGraph
            log = run_cmd(["qpGraph", "-p", self.par_file, "-g", grp_file, "-d", dot_file], verbose=False)

            # save the log file
            with open(log_file, 'w') as fout:
                fout.write(log)

        # parse the log and extract the outliers
        outliers, worst_fstat = self.extract_outliers(log.splitlines())

        # count the leaf nodes
        all_nodes = new_tree.findall('.//*')
        num_nodes = len([node for node in all_nodes if node.get('internal') != '1'])
        num_admix = len([node for node in all_nodes if node.get('admix') == '1']) / 2
        num_outliers = len(outliers)

        # only print PDFs for graphs that pass the threshold
        if num_outliers <= MAX_OUTLIER_THRESHOLD and num_nodes > (len(self.nodes) - REMAINING_PRINT_OFFSET):

            # embed some useful metadata info in the PDF name
            pdf_file = self.pdf_path + '-n{nodes}-o{out}-a{admix}-{name}.pdf'.format(nodes=num_nodes,
                                                                                     out=num_outliers,
                                                                                     admix=num_admix,
                                                                                     name=graph_name)

            # pretty print the qpGraph dot file
            pprint_qpgraph(dot_file, pdf_file)

        # output some summary stats
        print "{padding}{tree} \tnodes={nodes}\t admix={admix}\t outliers={out}\t worst={worst}\t {name}".format(
            padding="  "*depth, name=graph_name, tree=newick.ljust(80), nodes=num_nodes, admix=num_admix,
            out=len(outliers), worst=worst_fstat[-1])

        return new_tree, outliers, graph_name

    @staticmethod
    def extract_outliers(log):
        """
        Parse the log file and extract the outliers
        """
        outliers = []
        read_log = False
        worst_fstat = []

        for line in log:
            if 'outliers' in line:
                read_log = True
                continue
            elif 'worst f-stat' in line:
                worst_fstat = line.split()
                read_log = False
                continue

            if read_log and len(line.strip()) > 0:
                # save all the outliers
                outliers.append(line.split())

        return outliers, worst_fstat

    def export_qpgraph(self, root_tree):
        """
        Convert the ElementTree into qpGraph format
        """
        # clone the tree because this process is destructive
        local_tree = copy.deepcopy(root_tree)

        graph = "root\t{root}\n".format(root=self.root_node)

        # get all the nodes
        nodes = local_tree.findall('.//*')

        for node in nodes:
            # skip non-leaf nodes
            if len(node) == 0 and node.get('admix') != '1':
                graph += "label\t{node}\t{node}\n".format(node=node.tag)

        # build the list of edges
        graph += self.export_qpgraph_node(local_tree)

        return graph

    def export_qpgraph_node(self, root_tree, parent_node=None):
        """
        Recursively export all the edges in the graph
        """
        graph = ""

        if parent_node is None:
            parent_node = root_tree.getroot()

        for child_node in list(parent_node):

            if child_node.get('printed') != '1':

                # is this an admixture node or a normal node
                matches = root_tree.findall('.//' + child_node.tag + '/..')

                if len(matches) > 1:
                    # admixture branch
                    parent1, parent2 = matches

                    middle1 = child_node.tag + 'a'
                    middle2 = child_node.tag + 'b'
                    code1 = self.hash_text(middle1)
                    code2 = self.hash_text(middle2)

                    # don't admix from a bifurcating node; intermediate nodes to accommodate drift
                    graph += "edge\t{code}\t{parent}\t{middle}\n".format(code=code1, parent=parent1.tag, middle=middle1)
                    graph += "edge\t{code}\t{parent}\t{middle}\n".format(code=code2, parent=parent2.tag, middle=middle2)

                    # now admix from the two middle nodes
                    graph += "admix\t{child}\t{parent1}\t{parent2}\t50\t50\n".format(parent1=middle1, parent2=middle2,
                                                                                     child=child_node.tag)

                    # flag both nodes so we don't export them twice
                    parent1.find(child_node.tag).set('printed', '1')
                    parent2.find(child_node.tag).set('printed', '1')

                else:
                    # regular branch
                    code = self.hash_text(child_node.tag)
                    graph += "edge\t{code}\t{parent}\t{child}\n".format(code=code, parent=parent_node.tag,
                                                                        child=child_node.tag)

            # leaf nodes
            if len(child_node) > 0:
                # now convert the children
                graph += self.export_qpgraph_node(root_tree, child_node)

        return graph

    @staticmethod
    def hash_text(text, length=7):
        """
        Generate a unique key by hashing a string
        """
        return hashlib.sha1(text).hexdigest()[0:length]

    @staticmethod
    def new_label(root_tree, admix=False):
        """
        Return a new label for a node
        """
        all_nodes = root_tree.findall('.//*')

        if admix:
            num = len([node for node in all_nodes if node.get('admix') == '1']) / 2
        else:
            num = len([node for node in all_nodes if node.get('internal') == '1' and node.get('admix') != '1'])

        return '{pre}{num}'.format(pre='a' if admix else 'n', num=num+1)

    def print_newick_tree(self, root_tee):
        """
        Convert an ElementTree into a ladderized Newick tree.
        """
        newick = self.export_newick_tree(root_tee.getroot())

        # load into Phylo so we can sort the tree (i.e. ladderize)
        tree = Phylo.read(StringIO(newick), 'newick')
        tree.ladderize()

        # export the tree back to a string
        fout = StringIO()
        Phylo.write(tree, fout, 'newick')

        return fout.getvalue().replace(':0.00000', '').strip()

    def export_newick_tree(self, parent_node):
        """
        Convert an ElementTree tree into Newick format
        """
        if len(parent_node) == 0:
            return parent_node.tag
        else:
            children = [(child_node.tag, self.export_newick_tree(child_node)) for child_node in parent_node]
            children.sort()
            tag_name = '' if re.match('n[0-9]+|R', parent_node.tag) else parent_node.tag
            return '(' + ','.join(node for tag, node in children) + ')%s' % tag_name

    def find_graph(self):
        """
        Build and test all possible trees and graphs
        """

        print 'INFO: Starting list %s' % self.nodes

        # setup a simple 2-node tree
        root_node = ElemTree.Element(self.root_node)
        root_tree = ElemTree.ElementTree(root_node)

        ElemTree.SubElement(root_node, self.outgroup)
        ElemTree.SubElement(root_node, self.nodes[0])

        # recursively add all the other nodes
        self.recurse_tree(root_tree, self.nodes[1], self.nodes[2:])


def permute_qpgraph(par_file, dot_path, pdf_path, nodes, outgroup):
    """
    Find the best fitting graph for a given set of nodes, by permuting all possible graphs.
    """

    # instantiate the class
    qp = PermuteQpgraph(par_file, dot_path, pdf_path, nodes, outgroup)

    # get all the permutations of possible node orders
    all_nodes_perms = list(itertools.permutations(nodes, len(nodes)))

    print "INFO: There are %s possible starting orders for the given nodes." % len(all_nodes_perms)

    # keep looping until we find a solution
    while not qp.solutions or EXHAUSTIVE_SEARCH:

        try:
            # perform the analysis
            qp.find_graph()

        except NodeUnplaceable as error:
            # log the error
            print error

        try:
            # try starting with a different node order
            qp.nodes = list(all_nodes_perms.pop())

        except IndexError:
            # we've run out of node orders to try
            if not qp.solutions:
                print "ERROR: Cannot resolve the graph from any permutation of the given nodes."

            break

    print "FINISHED: Found %s unique solution(s) from a total of %s unique graphs!" % \
          (len(qp.solutions), len(qp.tested_graphs))

    return len(qp.solutions) > 0


class NodeUnplaceable(Exception):
    """
    Node cannot be placed in the graph without exceeding outlier threshold
    """
    pass


if __name__ == "__main__":

    # # simulated test data...
    # par_file = "permute/simulated.par"
    # dot_path = 'permute/graphs/sim'
    # pdf_path = 'permute/pdf/sim'
    # nodes = ['A', 'B', 'C', 'X']
    # outgroup = 'Out'

    # # test scenarios...
    # group = 'qpgraph-pops'
    # dataset = 'merged_v2_hq2_nomex_ctvt'
    # nodes = QPGRAPH_POPS
    # outgroup = 'COY'

    group = 'simple-pops'
    dataset = 'merged_v2_hq2_nomex_ctvt'
    nodes = SIMPLE_POPS
    outgroup = 'WAM'

    par_file = 'qpgraph/{0}.{1}.permute.par'.format(group, dataset)
    dot_path = 'qpgraph/{0}.{1}.permute'.format(group, dataset)
    pdf_path = 'pdf/{0}.{1}.qpg-permute'.format(group, dataset)

    permute_qpgraph(par_file, dot_path, pdf_path, nodes, outgroup)

    pass