############################################################################
# Copyright 2018 Anthony Ma & Stanford University                          #
#                                                                          #
# Licensed under the Apache License, Version 2.0 (the "License");          #
# you may not use this file except in compliance with the License.         #
# You may obtain a copy of the License at                                  #
#                                                                          #
#     http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                          #
# Unless required by applicable law or agreed to in writing, software      #
# distributed under the License is distributed on an "AS IS" BASIS,        #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. #
# See the License for the specific language governing permissions and      #
# limitations under the License.                                           #
############################################################################

############################################################################
# Imports
############################################################################

from vmd import *
import numpy as np
import math
import re
import sys
import os
from contextlib import contextmanager


def atoi(text):
    return int(text) if text.isdigit() else text


def natural_keys(text):
    return [atoi(c) for c in re.split('(\d+)', text)]


def get_file_type(file_name):
    """
    Determine file type by extracting suffix of file_name
    """
    if file_name is None:
        return None
    file_type = file_name.split(".")[-1].strip()
    if file_type == "nc":
        file_type = "netcdf"
    if file_type == "prmtop":
        file_type = "parm7"
    if file_type == "cms":
        file_type = "mae"
    return file_type


@contextmanager
def suppress_stdout():
    """
    Temporarily suppresses stdout.

    From: https://stackoverflow.com/questions/4178614/suppressing-output-of-module-calling-outside-library

    Example
    =======
        with suppress_stdout():
            print "You cannot see this"
    """
    with open('/dev/null', "w") as devnull:
        old_stdout = os.dup(sys.stdout.fileno())
        os.dup2(devnull.fileno(), 1)
        try:
            yield
        finally:
            os.dup2(old_stdout, 1)


def load_traj(top, traj, beg_frame, end_frame, stride):
    """
    Loads in topology and trajectory into VMD

    Parameters
    ----------
    top: MD Topology
    traj: MD Trajectory
    beg_frame: int
    end_frame: int
    stride: int

    Returns
    -------
    trajid: int
        simulation molid object
    """
    with suppress_stdout():
        top_file_type = get_file_type(top)
        traj_file_type = get_file_type(traj)
        trajid = molecule.load(top_file_type, top)
        molecule.delframe(trajid)  # Ensure topology doesn't count as a frame
        if traj is not None:
            molecule.read(trajid, traj_file_type, traj, beg=beg_frame, end=end_frame, skip=stride, waitfor=-1)
        else:
            molecule.read(trajid, top_file_type, top, beg=beg_frame, end=end_frame, skip=stride, waitfor=-1)

    return trajid


def simulation_length(top, traj):
    """
    Computes the simulation length efficiently
    """

    trajid = load_traj(top, traj, 0, -1, 100)
    num_frags = molecule.numframes(trajid)

    # There are between (num_frags-1)*100 and num_frags*100 frames.
    # Read all frames of the last fragment to determine the exact amount
    trajid = load_traj(top, traj, (num_frags-1)*100, -1, 1)
    last_frag_frames = molecule.numframes(trajid)
    return (num_frags - 1) * 100 + last_frag_frames


def get_atom_selection_labels(selection_id):
    """
    Returns list of atom labels for each atom in selection_id
    """
    chains, resnames, resids, names, indices = get_atom_selection_properties(selection_id)
    atom_labels = []
    for idx in range(len(chains)):
        chain, resname, resid, name, index = chains[idx], resnames[idx], resids[idx], names[idx], indices[idx]
        atom_labels.append("%s:%s:%s:%s:%s" % (chain, resname, resid, name, index))

    return atom_labels


def get_atom_selection_properties(selection_id):
    """
    After executing an evaltcl atom selection command, this function
    is called to retrieve the chain, resname, resid, name, and index
    of each atom in the selection

    Parameters
    ----------
    selection_id: string
        Denotes the atom selection identifier

    Returns
    -------
    chains: list of strings
        Chain identifier for each atom ["A", "B", "A", ...]
    resnames: list of strings
        Resname for each atom ["ASP", "GLU", "TYR", ...]
    resids: list of strings
        Residue index for each atom ["12", "45", ...]
    names: list of strings
        Atom name of each atom ["NZ", "CA", "N", ...]
    indices: list of strings
        VMD based index for each atom ["12304", "1231", ...]
    """
    chains = list(map(str, evaltcl("$%s get chain" % selection_id).split(" ")))
    resnames = list(map(str, evaltcl("$%s get resname" % selection_id).split(" ")))
    resids = list(map(str, evaltcl("$%s get resid" % selection_id).split(" ")))
    names = list(map(str, evaltcl("$%s get name" % selection_id).split(" ")))
    indices = list(map(str, evaltcl("$%s get index" % selection_id).split(" ")))
    if chains == [''] or resnames == [''] or resids == [''] or names == [''] or indices == ['']:
        return [], [], [], [], []
    return chains, resnames, resids, names, indices


def gen_index_to_atom_label(top, traj):
    """
    Read in first frame of simulation and generate mapping from VMD index to atom labels

    Parameters
    ----------
    top: MD Topology
    traj: MD Trajectory

    Returns
    -------
    index_to_label: dict mapping int to string
        Maps VMD atom index to label "chain:resname:resid:name:index"
        {11205: "A:ASP:114:CA:11205, ...}

    """
    # Select all atoms from first frame of trajectory
    trajid = load_traj(top, traj, 1, 2, 1)
    all_atom_sel = "set all_atoms [atomselect %s \" all \" frame %s]" % (trajid, 0)
    evaltcl(all_atom_sel)
    chains, resnames, resids, names, indices = get_atom_selection_properties("all_atoms")
    evaltcl('$all_atoms delete')

    # Generate mapping
    index_to_label = {}
    for idx, index in enumerate(indices):
        chain = chains[idx]
        resname = resnames[idx]
        resid = resids[idx]
        name = names[idx]
        atom_label = "%s:%s:%s:%s:%s" % (chain, resname, resid, name, index)
        index_key = int(index)
        index_to_label[index_key] = atom_label

    molecule.delete(trajid)
    return index_to_label


def get_anion_atoms(traj_frag_molid, frame_idx, sele_id):
    """
    Get list of anion atoms that can form salt bridges

    Returns
    -------
    anion_list: list of strings
        List of atom labels for atoms in ASP or GLU that
        can form salt bridges
    """
    anion_list = []

    if sele_id is None:
        evaltcl("set ASP [atomselect %s \" "
                "(resname ASP) and (name OD1 OD2) \" frame %s]" % (traj_frag_molid, frame_idx))
        evaltcl("set GLU [atomselect %s \" "
                "(resname GLU) and (name OE1 OE2) \" frame %s]" % (traj_frag_molid, frame_idx))
    else:
        evaltcl("set ASP [atomselect %s \" "
                "(resname ASP) and (name OD1 OD2) and (%s) \" frame %s]" % (traj_frag_molid, sele_id, frame_idx))
        evaltcl("set GLU [atomselect %s \" "
                "(resname GLU) and (name OE1 OE2) and (%s) \" frame %s]" % (traj_frag_molid, sele_id, frame_idx))

    anion_list += get_atom_selection_labels("ASP")
    anion_list += get_atom_selection_labels("GLU")

    evaltcl('$ASP delete')
    evaltcl('$GLU delete')
    return anion_list


def get_cation_atoms(traj_frag_molid, frame_idx, sele_id):
    """
    Get list of cation atoms that can form salt bridges or pi cation contacts

    Returns
    -------
    cation_list: list of strings
        List of atom labels for atoms in LYS, ARG, HIS that
        can form salt bridges
    """
    cation_list = []
    if sele_id is None:
        evaltcl("set LYS [atomselect %s \" (resname LYS) and (name NZ) \" frame %s]" %
                (traj_frag_molid, frame_idx))
        evaltcl("set ARG [atomselect %s \" (resname ARG) and (name NH1 NH2) \" frame %s]" %
                (traj_frag_molid, frame_idx))
        evaltcl("set HIS [atomselect %s \" (resname HIS HSD HSE HSP HIE HIP HID) and (name ND1 NE2) \" frame %s]" %
                (traj_frag_molid, frame_idx))
    else:
        evaltcl("set LYS [atomselect %s \" (resname LYS) and (name NZ) and (%s) \" frame %s]" %
                (traj_frag_molid, sele_id, frame_idx))
        evaltcl("set ARG [atomselect %s \" (resname ARG) and (name NH1 NH2) and (%s) \" frame %s]" %
                (traj_frag_molid, sele_id, frame_idx))
        evaltcl("set HIS [atomselect %s \" (resname HIS HSD HSE HSP HIE HIP HID) and (name ND1 NE2) and (%s) \" "
                "frame %s]" % (traj_frag_molid, sele_id, frame_idx))

    cation_list += get_atom_selection_labels("LYS")
    cation_list += get_atom_selection_labels("ARG")
    cation_list += get_atom_selection_labels("HIS")

    evaltcl('$LYS delete')
    evaltcl('$ARG delete')
    evaltcl('$HIS delete')

    return cation_list


def get_aromatic_atom_triplets(traj_frag_molid, frame_idx, chain_id):
    """
    Get list of aromatic atom triplets

    Returns
    -------
    aromatic_atom_triplet_list: list of tuples corresponding to three equally spaced points
    on the 6-membered rings of TYR, TRP, or PHE residues.
        [(A:PHE:72:CG:51049, A:PHE:72:CE1:51052, A:PHE:72:CE2:51058), ...]
    """
    aromatic_atom_list = []
    if chain_id is None:
        evaltcl("set PHE [atomselect %s \" (resname PHE) and (name CG CE1 CE2) \" frame %s]" %
                (traj_frag_molid, frame_idx))
        evaltcl("set TRP [atomselect %s \" (resname TRP) and (name CD2 CZ2 CZ3) \" frame %s]" %
                (traj_frag_molid, frame_idx))
        evaltcl("set TYR [atomselect %s \" (resname TYR) and (name CG CE1 CE2) \" frame %s]" %
                (traj_frag_molid, frame_idx))
    else:
        evaltcl("set PHE [atomselect %s \" (resname PHE) and (name CG CE1 CE2) and (chain %s)\" frame %s]" %
                (traj_frag_molid, frame_idx, chain_id))
        evaltcl("set TRP [atomselect %s \" (resname TRP) and (name CD2 CZ2 CZ3) and (chain %s)\" frame %s]" %
                (traj_frag_molid, frame_idx, chain_id))
        evaltcl("set TYR [atomselect %s \" (resname TYR) and (name CG CE1 CE2) and (chain %s)\" frame %s]" %
                (traj_frag_molid, frame_idx, chain_id))

    aromatic_atom_list += get_atom_selection_labels("PHE")
    aromatic_atom_list += get_atom_selection_labels("TRP")
    aromatic_atom_list += get_atom_selection_labels("TYR")

    evaltcl("$PHE delete")
    evaltcl("$TRP delete")
    evaltcl("$TYR delete")

    aromatic_atom_triplet_list = []

    # Generate triplets of the three equidistant atoms on an aromatic ring
    for i in range(0, len(aromatic_atom_list), 3):
        aromatic_atom_triplet_list.append(aromatic_atom_list[i:i+3])

    return aromatic_atom_triplet_list


def convert_to_single_atom_aromatic_string(aromatic_atom_label):
    """
    Replaces any aromatic ring atom with CG label

    Returns
    -------
    aromatic_CG_atom_label: The CG atom label for an aromatic ring (ie C:PHE:49:CG)
    """

    aromatic_CG_atom_label = ":".join(aromatic_atom_label.split(":")[0:3]) + ":CG:vmd_idx"
    return aromatic_CG_atom_label


def calc_water_to_residues_map(water_hbonds, solvent_resn):
    """
    Returns
    -------
    frame_idx: int
        Specify frame index with respect to the smaller trajectory fragment
    water_to_residues: dict mapping string to list of strings
        Map each water molecule to the list of residues it forms
        contacts with (ie {"W:TIP3:8719:OH2:29279" : ["A:PHE:159:N:52441", ...]})
    solvent_bridges: list
        List of hbond interactions between two water molecules
        [("W:TIP3:757:OH2:2312", "W:TIP3:8719:OH2:29279"), ...]
    """
    frame_idx = 0
    water_to_residues = {}
    _solvent_bridges = []
    for frame_idx, atom1_label, atom2_label, itype in water_hbonds:
        if solvent_resn in atom1_label and solvent_resn in atom2_label:
            _solvent_bridges.append((atom1_label, atom2_label))
            continue
        elif solvent_resn in atom1_label and solvent_resn not in atom2_label:
            water = atom1_label
            protein = atom2_label
        elif solvent_resn not in atom1_label and solvent_resn in atom2_label:
            water = atom2_label
            protein = atom1_label
        else:
            raise ValueError("Solvent residue name can't be resolved")

        if water not in water_to_residues:
            water_to_residues[water] = set()
        water_to_residues[water].add(protein)

    # Remove duplicate solvent bridges (w1--w2 and w2--w1 are the same)
    solvent_bridges = set()
    for water1, water2 in _solvent_bridges:
        key1 = (water1, water2)
        key2 = (water2, water1)
        if key1 not in solvent_bridges and key2 not in solvent_bridges:
            solvent_bridges.add(key1)
    solvent_bridges = sorted(list(solvent_bridges))

    return frame_idx, water_to_residues, solvent_bridges


def compute_distance(molid, frame_idx, atom1_label, atom2_label):
    """
    Compute distance between two atoms in a specified frame of simulation

    Parameters
    ----------
    molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    atom1_label: string
        Atom label (ie "A:GLU:323:OE2:55124")
    atom2_label: string
        Atom label (ie "A:ARG:239:NH1:53746")

    Returns
    -------
    distance: float
    """
    # atom_index1 = atom1_label.split(":")[-1]
    # atom_index2 = atom2_label.split(":")[-1]
    atom_index1 = atom1_label[atom1_label.rfind(":")+1:]
    atom_index2 = atom2_label[atom2_label.rfind(":")+1:]
    distance = float(evaltcl("measure bond {%s %s} molid %s frame %s" % (atom_index1, atom_index2, molid, frame_idx)))
    return distance


def compute_angle(molid, frame_idx, atom1, atom2, atom3):
    """
    Compute distance between two atoms in a specified frame of simulation

    Parameters
    ----------
    molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    atom1: string
        Atom label (ie "A:GLU:323:OE2:55124")
    atom2: string
        Atom label (ie "A:ARG:239:NH1:53746")
    atom3: string
        Atom label (ie "A:GLU:118:OE1:51792")

    Returns
    -------
    angle: float
        Expressed in degrees
    """
    atom_index1 = atom1.split(":")[-1]
    atom_index2 = atom2.split(":")[-1]
    atom_index3 = atom3.split(":")[-1]

    angle = float(evaltcl("measure angle {%s %s %s} molid %s frame %s" %
                          (atom_index1, atom_index2, atom_index3, molid, frame_idx)))
    return angle


def get_chain(traj_frag_molid, frame_idx, index):
    """
    Parse atom label and return element

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    index: string
        VMD atom index

    Returns
    -------
    chain: string (ie "A", "B")
    """
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    chain = evaltcl("$sel get chain")
    evaltcl("$sel delete")
    return chain


def get_resname(traj_frag_molid, frame_idx, index):
    """
    Parse atom label and return element

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    index: string
        VMD atom index

    Returns
    -------
    resname: string (ie "ASP", "GLU")
    """
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    resname = evaltcl("$sel get resname")
    evaltcl("$sel delete")
    return resname


def get_resid(traj_frag_molid, frame_idx, index):
    """
    Parse atom label and return element

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    index: string
        VMD atom index

    Returns
    -------
    resid: string (ie "115", "117")
    """
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    resid = evaltcl("$sel get resid")
    evaltcl("$sel delete")
    return resid


def get_name(traj_frag_molid, frame_idx, index):
    """
    Parse atom label and return element

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    index: string
        VMD atom index

    Returns
    -------
    name: string (ie "CA", "NZ", )
    """
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    name = evaltcl("$sel get name")
    evaltcl("$sel delete")
    return name


def get_element(traj_frag_molid, frame_idx, index):
    """
    Parse atom label and return element

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    index: string
        VMD atom index

    Returns
    -------
    element: string (ie "C", "H", "O", "N", "S")
    """
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    element = evaltcl("$sel get element")
    evaltcl("$sel delete")
    return element


def get_atom_label(traj_frag_molid, frame_idx, index):
    chain = get_chain(traj_frag_molid, frame_idx, index)
    resname = get_resname(traj_frag_molid, frame_idx, index)
    resid = get_resid(traj_frag_molid, frame_idx, index)
    name = get_name(traj_frag_molid, frame_idx, index)

    atom_label = "%s:%s:%s:%s:%s" % (chain, resname, resid, name, index)
    return atom_label


def parse_contacts(contact_string):
    """
    Parameters
    ----------
    contact_string: string
        Output from measure contacts function {indices} {indices}

    Returns
    -------
    contact_index_pairs: list of tuples
        List of index int pairs
    """
    contact_index_pairs = []

    # Handle case where only one pair of atoms form contacts
    if "} {" not in contact_string:
        atom1_index, atom2_index = map(int, contact_string.split(" "))
        contact_index_pairs.append((atom1_index, atom2_index))
    else:
        contacts_list = contact_string.split("} {")
        atom1_list_str = contacts_list[0].strip("{}")
        atom2_list_str = contacts_list[1].strip("{}")
        if atom1_list_str == "" or atom2_list_str == "":
            return []

        atom1_list = list(map(int, atom1_list_str.split(" ")))
        atom2_list = list(map(int, atom2_list_str.split(" ")))

        for idx in range(len(atom1_list)):
            atom1_index = atom1_list[idx]
            atom2_index = atom2_list[idx]
            contact_index_pairs.append((atom1_index, atom2_index))

    return contact_index_pairs


# Geometry Tools
def get_coord(traj_frag_molid, frame_idx, atom_label):
    """
    Get x, y, z coordinate of an atom specified by its label

    Parameters
    ----------
    traj_frag_molid: int
        Denotes trajectory id in VMD
    frame_idx: int
        Frame of simulation in trajectory fragment
    atom_label: string
        Atom label (ie "A:GLU:323:OE2:55124")

    Returns
    -------
    coord: np.array[x, y, z]
    """
    index = atom_label.split(":")[-1]
    evaltcl("set sel [atomselect %s \" index %s \" frame %s]" % (traj_frag_molid, index, frame_idx))
    x = float(evaltcl("$sel get x"))
    y = float(evaltcl("$sel get y"))
    z = float(evaltcl("$sel get z"))
    evaltcl("$sel delete")
    coord = np.array([x, y, z])
    return coord


def points_to_vector(point1, point2):
    """
    Return vector from point1 to point2
    """
    vector = point2 - point1
    return vector


def calc_vector_length(vector):
    """
    Compute length of vector
    """
    vector_length = math.sqrt(np.dot(vector, vector))
    return vector_length


def calc_angle_between_vectors(vector1, vector2):
    """
    Returns
    -------
    angle_between_vectors: float
        Degrees between two vectors
    """
    radians_between_vectors = math.acos(np.dot(vector1, vector2) /
                                        (calc_vector_length(vector1) * calc_vector_length(vector2)))
    angle_between_vectors = math.degrees(radians_between_vectors)
    return angle_between_vectors


def calc_geom_distance(point1, point2):
    """
    Compute distance between two points

    Returns
    -------
    distance: float
    """
    distance = np.linalg.norm(point1 - point2)
    return distance


def calc_geom_centroid(point1, point2, point3):
    """
    Compute centroid between three points

    Returns
    -------
    centroid: np.array[x, y, z]
    """
    centroid = (point1 + point2 + point3)/3
    return centroid


def calc_geom_normal_vector(point1, point2, point3):
    """
    Compute normal vector to the plane constructed by three points

    Returns
    -------
    normal_vector: np.array[x, y, z]

    """
    v1 = point3 - point1
    v2 = point2 - point1
    normal_vector = np.cross(v1, v2)
    return normal_vector


def calc_geom_psi_angle(center1, center2, normal_vector):
    """
    Parameters
    ----------
    center1: np.array of floats
        Coordinates of the center of aromatic plane 1
    center2: np.array of floats
        Coordinates of the center of aromatic plane 2
    normal_vector: np.array of floats
        Vector coordinate pointing from aromatic plane 1

    Returns
    -------
    psi_angle: float in degrees
        Angle between normal vector and vector(center2 - center1)
    """
    center_to_center_vector = points_to_vector(center2, center1)
    psi_angle = calc_angle_between_vectors(normal_vector, center_to_center_vector)
    psi_angle = min(math.fabs(psi_angle - 0), math.fabs(psi_angle - 180))
    return psi_angle
